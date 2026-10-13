from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main


class DeepSeekModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"

        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "DEEPSEEK_API_KEY": "test-deepseek-key",
                "GEMINI_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "GEMINI_FALLBACK_MODEL": "",
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

    def create_task(self, task_id: str, model: str) -> None:
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,"
            "file_ids_json,created_at,updated_at) VALUES(?,?,'queued','Queued','[]','deepseek',?,'[]',?,?)",
            (task_id, "Complete the test task", model, now, now),
        )

    async def test_client_uses_deepseek_key_and_api_base_url(self) -> None:
        with patch.object(main, "AsyncOpenAI") as openai_client:
            main.create_llm_client("deepseek")

        openai_client.assert_called_once_with(
            api_key="test-deepseek-key",
            base_url="https://api.deepseek.com",
            timeout=90,
            max_retries=2,
        )

    async def test_openrouter_client_prefers_vault_key_and_sets_auth_headers(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "environment-openrouter-key"
        main.save_vault_values({"OPENROUTER_API_KEY": "vault-openrouter-key"})

        with patch.object(main, "AsyncOpenAI") as openai_client:
            main.create_llm_client("openrouter")

        openai_client.assert_called_once_with(
            api_key="vault-openrouter-key",
            base_url="https://openrouter.ai/api/v1",
            timeout=90,
            max_retries=2,
            default_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "Forge"},
        )

    async def test_openrouter_client_falls_back_to_environment_key(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = " environment-openrouter-key "

        with patch.object(main, "AsyncOpenAI") as openai_client:
            main.create_llm_client("openrouter")

        self.assertEqual(openai_client.call_args.kwargs["api_key"], "environment-openrouter-key")

    async def test_openrouter_missing_key_fails_before_client_creation(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "   "
        expected = (
            "Please configure your OpenRouter API key in Preferences/Vault before selecting this model."
        )
        with patch.object(main, "AsyncOpenAI") as openai_client:
            with self.assertRaisesRegex(RuntimeError, expected.replace("/", r"\/")):
                main.create_llm_client("openrouter")

        openai_client.assert_not_called()

    async def test_supervisor_and_delegated_specialist_keep_selected_model(self) -> None:
        model_ids = ("deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash")

        for model_id in model_ids:
            with self.subTest(model_id=model_id):
                task_id = f"deepseek-{model_id}"
                self.create_task(task_id, model_id)

                supervisor_tool_call = SimpleNamespace(
                    id="call_delegate",
                    function=SimpleNamespace(
                        name="delegate_to_specialist",
                        arguments=json.dumps({"task": "Research the assigned question."}),
                    ),
                )
                tool_call_completion = SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None, tool_calls=[supervisor_tool_call])
                        )
                    ]
                )
                specialist_completion = SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="Specialist result", tool_calls=None)
                        )
                    ]
                )
                final_completion = SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="Supervisor result", tool_calls=None)
                        )
                    ]
                )
                create = AsyncMock(
                    side_effect=[
                        tool_call_completion,
                        specialist_completion,
                        final_completion,
                    ]
                )
                client = SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=create))
                )

                with patch.object(main, "create_llm_client", return_value=client):
                    await main.run_agent_task(task_id, [])

                self.assertEqual(create.await_count, 3)
                self.assertEqual(
                    [call.kwargs["model"] for call in create.await_args_list],
                    [model_id, model_id, model_id],
                )
                self.assertIn("tools", create.await_args_list[0].kwargs)
                self.assertEqual(
                    create.await_args_list[1].kwargs["messages"][-1]["content"],
                    "Research the assigned question.",
                )
                row = main.db_one("SELECT status,result,model_id FROM tasks WHERE id=?", (task_id,))
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "completed")
                self.assertEqual(row["result"], "Supervisor result")
                self.assertEqual(row["model_id"], model_id)


if __name__ == "__main__":
    unittest.main()
