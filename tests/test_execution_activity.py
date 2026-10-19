from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import main


class ExecutionActivityTests(unittest.TestCase):
    def test_task_response_exposes_stored_log_timestamp_as_created_at(self) -> None:
        timestamp = "2026-10-12T10:20:15Z"
        row = {
            "id": "task",
            "thread_id": "thread",
            "objective": "Run a task",
            "status": "completed",
            "current_step": "Done",
            "result": "ok",
            "error": None,
            "logs_json": json.dumps([{"id": "log", "kind": "info", "message": "Started", "timestamp": timestamp}]),
            "provider": "gemini",
            "model_id": "gemini-3.5-flash-lite",
            "recommendation_kind": None,
            "recommendation_reason": None,
            "recommended_provider": None,
            "recommended_model_id": None,
            "retry_prompt": None,
            "pending_approval_id": None,
            "pending_approval_kind": None,
            "approval_summary": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

        task = main.task_dict(row)

        self.assertEqual(task["logs"][0]["createdAt"], timestamp)
        self.assertEqual(task["logs"][0]["timestamp"], timestamp)

    def test_summaries_identify_real_actions(self) -> None:
        self.assertEqual(main.tool_activity_summary("run_command", {"command": "ls assets"}, finished=True), "Ran command: ls assets")
        self.assertEqual(main.tool_activity_summary("write_workspace_preview_file", {"path": "index.html"}, finished=True), "Edited: index.html")
        self.assertEqual(main.tool_activity_summary("web_search", {"query": "weather"}), "Web search: weather")
        self.assertTrue(main.tool_activity_summary("run_command", {"command": "invalid"}, failed=True).startswith("Failed action"))

    def test_tool_completion_updates_one_stable_log_and_redacts_secrets(self) -> None:
        logs = [{"id": "stable", "kind": "tool", "message": "Running command: ls", "timestamp": "2026-10-11T00:00:00Z"}]
        with patch.dict(main.os.environ, {"GEMINI_API_KEY": "synthetic-key-only"}), \
                patch.object(main, "db_one", return_value={"logs_json": json.dumps(logs)}), \
                patch.object(main, "db_run") as write:
            main.finish_tool_activity("task", "stable", "run_command", {"command": "ls"}, "synthetic-key-only stdout", False)
        saved = json.loads(write.call_args.args[1][0])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], "stable")
        self.assertEqual(saved[0]["timestamp"], logs[0]["timestamp"])
        self.assertIn("Ran command: ls", saved[0]["message"])
        self.assertIn("Inputs:", saved[0]["message"])
        self.assertIn("Output:", saved[0]["message"])
        self.assertNotIn("synthetic-key-only", saved[0]["message"])

    def test_agent_logs_allow_reasonable_reasoning_summaries(self) -> None:
        with patch.object(main, "db_one", return_value={"logs_json": "[]"}), \
                patch.object(main, "db_run") as write:
            main.log_task("task", "R" * (main.MAX_AGENT_LOG_CHARS + 100), "agent")

        saved = json.loads(write.call_args.args[1][0])
        self.assertEqual(len(saved[0]["message"]), main.MAX_AGENT_LOG_CHARS)

    def test_tool_input_and_output_logs_keep_up_to_sixteen_thousand_characters_each(self) -> None:
        logs = [{"id": "stable", "kind": "tool", "message": "Running command", "timestamp": "now"}]
        with patch.object(main, "db_one", return_value={"logs_json": json.dumps(logs)}), \
                patch.object(main, "db_run") as write:
            main.finish_tool_activity(
                "task",
                "stable",
                "run_command",
                {"payload": "I" * (main.MAX_TOOL_LOG_SECTION_CHARS + 20)},
                "O" * (main.MAX_TOOL_LOG_SECTION_CHARS + 20),
                False,
            )

        saved = json.loads(write.call_args.args[1][0])[0]["message"]
        self.assertIn("I" * main.MAX_TOOL_LOG_SECTION_CHARS, saved)
        self.assertNotIn("I" * (main.MAX_TOOL_LOG_SECTION_CHARS + 1), saved)
        self.assertIn("O" * main.MAX_TOOL_LOG_SECTION_CHARS, saved)
        self.assertNotIn("O" * (main.MAX_TOOL_LOG_SECTION_CHARS + 1), saved)
        self.assertIn("… [truncated]", saved)

    def test_failed_tool_does_not_claim_success(self) -> None:
        logs = [{"id": "stable", "kind": "tool", "message": "Editing file", "timestamp": "2026-10-11T00:00:00Z"}]
        with patch.object(main, "db_one", return_value={"logs_json": json.dumps(logs)}), patch.object(main, "db_run") as write:
            main.finish_tool_activity("task", "stable", "write_workspace_app_script", {"path": "../blocked.py"}, '{"error":"PermissionError"}', True)
        saved = json.loads(write.call_args.args[1][0])[0]
        self.assertEqual(saved["kind"], "error")
        self.assertIn("Failed action", saved["message"])
        self.assertNotIn("Edited:", saved["message"])
