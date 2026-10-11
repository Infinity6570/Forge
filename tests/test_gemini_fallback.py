from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from openai import APIStatusError

import main


class GeminiFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"

        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "GEMINI_API_KEY": "test-gemini-provider-secret",
                "OPENROUTER_API_KEY": "",
                "GEMINI_FALLBACK_MODEL": "gemini-fallback-test",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.path_patches = [
            patch.object(main, "ROOT", root),
            patch.object(main, "ENV_FILE", root / ".env"),
            patch.object(main, "WORKSPACE", workspace),
            patch.object(main, "DATABASE", workspace / "assistant.db"),
            patch.object(main, "UPLOADS", workspace / "uploads"),
            patch.object(main, "NOTES", workspace / "notes"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

        main.init_db()

    def create_task(self, task_id: str, model: str = "gemini-primary-test") -> None:
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,"
            "file_ids_json,created_at,updated_at) VALUES(?,?,'queued','Queued','[]','gemini',?,'[]',?,?)",
            (task_id, "Complete the test task", model, now, now),
        )

    def status_error(self, status_code: int, message: str) -> APIStatusError:
        request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
        response = httpx.Response(status_code, request=request)
        return APIStatusError(message, response=response, body={"error": message})

    def task_history_json(self, task_id: str) -> str:
        row = main.db_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        assert row is not None
        return json.dumps(main.task_dict(row))

    async def test_overload_statuses_retry_once_and_record_fallback_model(self) -> None:
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Task result", tool_calls=None))]
        )
        for status_code in (429, 503):
            with self.subTest(status_code=status_code):
                task_id = f"overload-{status_code}"
                self.create_task(task_id)
                create = AsyncMock(
                    side_effect=[
                        self.status_error(status_code, "temporary overload"),
                        completion,
                    ]
                )
                client = SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=create))
                )

                with patch.object(main, "create_llm_client", return_value=client):
                    await main.run_agent_task(task_id, [])

                self.assertEqual(create.await_count, 2)
                self.assertEqual(
                    [call.kwargs["model"] for call in create.await_args_list],
                    ["gemini-primary-test", "gemini-fallback-test"],
                )
                row = main.db_one("SELECT status,model_id FROM tasks WHERE id=?", (task_id,))
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "completed")
                self.assertEqual(row["model_id"], "gemini-fallback-test")
                self.assertNotIn("test-gemini-provider-secret", self.task_history_json(task_id))

    async def test_authentication_and_invalid_model_errors_do_not_retry_or_change_history_model(
        self,
    ) -> None:
        for status_code, label in ((401, "authentication"), (404, "invalid-model")):
            with self.subTest(status_code=status_code):
                task_id = f"permanent-{label}"
                self.create_task(task_id)
                create = AsyncMock(
                    side_effect=[
                        self.status_error(
                            status_code,
                            f"provider rejected key test-gemini-provider-secret",
                        )
                    ]
                )
                client = SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=create))
                )

                with patch.object(main, "create_llm_client", return_value=client):
                    await main.run_agent_task(task_id, [])

                self.assertEqual(create.await_count, 1)
                row = main.db_one("SELECT status,model_id,error FROM tasks WHERE id=?", (task_id,))
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["model_id"], "gemini-primary-test")
                self.assertIn("[redacted]", row["error"])
                self.assertNotIn("test-gemini-provider-secret", self.task_history_json(task_id))


if __name__ == "__main__":
    unittest.main()
