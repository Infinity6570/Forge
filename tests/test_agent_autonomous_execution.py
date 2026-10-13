from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main


def completion(text: str | None = None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        role="assistant", content=text, tool_calls=calls
    ))])


class AutonomousExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        workspace = root / "workspace"
        workspace.mkdir()
        for name, value in {
            "ROOT": root,
            "BASE_DIR": workspace.resolve(),
            "WORKSPACE": workspace,
            "DATABASE": workspace / "assistant.db",
            "UPLOADS": workspace / "uploads",
            "NOTES": workspace / "notes",
            "ENV_FILE": root / ".env",
        }.items():
            change = patch.object(main, name, value)
            change.start()
            self.addCleanup(change.stop)
        environment = patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "test-anthropic-key", "GEMINI_FALLBACK_MODEL": ""},
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)
        main.init_db()

    def create_task(self, task_id: str, objective: str, provider: str = "anthropic"):
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,"
            "file_ids_json,created_at,updated_at) VALUES(?,?, 'queued','Queued','[]',?,?,'[]',?,?)",
            (task_id, objective, provider, "claude-sonnet-5-5", now, now),
        )

    async def test_anthropic_build_plan_is_intercepted_then_files_are_written(self):
        self.create_task("build-write", "Build a Python app at autonomous_app.py")
        write_call = SimpleNamespace(
            id="call-write",
            type="function",
            function=SimpleNamespace(
                name="write_file",
                arguments=json.dumps({
                    "path": "autonomous_app.py",
                    "content": "print('built')\n",
                }),
            ),
        )
        create = AsyncMock(side_effect=[
            completion("I will create a plan for the application."),
            completion(None, [write_call]),
            completion("The Python app was created and verified."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("build-write", [])

        self.assertEqual(create.await_count, 3)
        self.assertIn("Proceed immediately to create these files using write_file now.", create.await_args_list[1].kwargs["messages"][-1]["content"])
        for request in create.await_args_list:
            tools = request.kwargs["tools"]
            write_schema = next(
                tool["function"] for tool in tools
                if tool["function"]["name"] == "write_file"
            )
            self.assertEqual(write_schema["parameters"]["required"], ["path", "content"])
        self.assertTrue(all("tools" in request.kwargs for request in create.await_args_list))
        self.assertEqual(
            (main.WORKSPACE / "autonomous_app.py").read_text(encoding="utf-8"),
            "print('built')\n",
        )
        task = main.db_one("SELECT status,result FROM tasks WHERE id='build-write'")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "The Python app was created and verified.")

    async def test_build_cannot_complete_if_no_workspace_write_succeeds(self):
        self.create_task("build-no-write", "Create a website for a local bakery")
        create = AsyncMock(side_effect=[
            completion(None),
            *[completion("Here is the plan for the website.") for _ in range(9)],
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("build-no-write", [])

        task = main.db_one("SELECT status,result,error FROM tasks WHERE id='build-no-write'")
        self.assertEqual(create.await_count, 10)
        self.assertEqual(task["status"], "failed")
        self.assertIsNone(task["result"])
        self.assertIn("did not write any files", task["error"])
        self.assertIn("Proceed immediately to create these files using write_file now.", create.await_args.kwargs["messages"][-1]["content"])

    def test_build_intent_detection_avoids_non_code_create_requests(self):
        self.assertTrue(main.build_request_requires_workspace_write("Create a React app"))
        self.assertTrue(main.build_request_requires_workspace_write("Redesign the website"))
        self.assertTrue(main.build_request_requires_workspace_write("Update the homepage"))
        self.assertFalse(main.build_request_requires_workspace_write("Create a reminder for tomorrow"))
        self.assertFalse(main.build_request_requires_workspace_write("Build a 5-day travel itinerary"))


if __name__ == "__main__":
    unittest.main()
