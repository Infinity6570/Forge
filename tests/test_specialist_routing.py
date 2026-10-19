from __future__ import annotations

import asyncio
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


def function_call(name: str, arguments: dict[str, object], call_id: str = "call-1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class SpecialistRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"
        workspace.mkdir()
        self.patchers = []
        for name, value in (
            ("ROOT", root),
            ("PROJECT_DIR", root.resolve()),
            ("BASE_DIR", workspace.resolve()),
            ("WORKSPACE", workspace),
            ("DATABASE", workspace / "assistant.db"),
            ("UPLOADS", workspace / "uploads"),
            ("NOTES", workspace / "notes"),
        ):
            patcher = patch.object(main, name, value)
            patcher.start()
            self.patchers.append(patcher)
        self.addCleanup(self._stop_patchers)
        self.env_patch = patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        main.init_db()
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,"
            "file_ids_json,created_at,updated_at) VALUES(?,?,'running','Working','[]',?,?, '[]',?,?)",
            ("specialist-test", "test specialist", "openai", "gpt-4.1-mini", now, now),
        )

    def _stop_patchers(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_tier_chains_are_provider_scoped_and_only_include_configured_models(self):
        for provider in main.SPECIALIST_MODELS:
            with self.subTest(provider=provider):
                chain = main.specialist_model_chain(provider, "fast")
                self.assertTrue(chain)
                self.assertEqual(len({model for _, model in chain}), len(chain))
                for _, model in chain:
                    self.assertIn(model, main.MODEL_OPTIONS[provider])
                self.assertEqual(
                    chain,
                    main.specialist_model_chain(provider, "fast"),
                )

        self.assertEqual(
            main.specialist_model_chain("deepseek", "fast"),
            [("fast", "deepseek-chat"), ("balanced", "deepseek-reasoner")],
        )
        with self.assertRaisesRegex(ValueError, "specialist tier"):
            main.specialist_model_chain("openai", "premium")

    def test_incomplete_specialist_answers_are_marked_for_escalation(self):
        self.assertEqual(
            main.specialist_result_failure("I could not access the relevant source."),
            "reported incomplete or failed work",
        )

    async def test_empty_result_escalates_and_records_the_same_provider_decision(self):
        create = AsyncMock(side_effect=[completion("  "), completion("Verified answer.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Research the assigned question.",
                "openai",
                "specialist-test",
                role="research",
                starting_tier="fast",
            )

        self.assertIn("escalated from fast", result)
        self.assertTrue(result.endswith("Verified answer."))
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["gpt-4.1-mini", "gpt-4.1"],
        )
        logs = main.task_dict(main.db_one("SELECT * FROM tasks WHERE id='specialist-test'"))["logs"]
        self.assertTrue(any("escalated from fast" in item["message"] for item in logs))
        self.assertTrue(all(
            call.kwargs["model"] in main.MODEL_OPTIONS["openai"]
            for call in create.await_args_list
        ))

    async def test_provider_failure_escalates_without_switching_providers(self):
        create = AsyncMock(side_effect=[RuntimeError("temporary provider failure"), completion("Recovered.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Analyze this implementation.",
                "anthropic",
                "specialist-test",
                role="analysis",
                starting_tier="fast",
            )

        self.assertIn("escalated from fast", result)
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["claude-haiku-5-5", "claude-sonnet-5-5"],
        )
        self.assertTrue(all(
            call.kwargs["model"] in main.MODEL_OPTIONS["anthropic"]
            for call in create.await_args_list
        ))

    async def test_empty_reasoning_tier_returns_a_recorded_failure_without_downgrading(self):
        create = AsyncMock(return_value=completion(" "))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Prove the result.",
                "openai",
                "specialist-test",
                role="analysis",
                starting_tier="reasoning",
            )

        self.assertIn("could not complete", result)
        self.assertEqual([call.kwargs["model"] for call in create.await_args_list], ["o3-mini"])
        logs = main.task_dict(main.db_one("SELECT * FROM tasks WHERE id='specialist-test'"))["logs"]
        self.assertTrue(any("could not complete the subtask" in item["message"] for item in logs))
        self.assertFalse(any("escalated" in item["message"] for item in logs))

    async def test_read_only_tools_are_allowlisted_and_write_calls_are_never_executed(self):
        create = AsyncMock(side_effect=[
            completion(calls=[function_call("write_file", {"path": "nope.txt", "content": "blocked"})]),
            completion("I could not write the file."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value='{"saved":true}')
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            result = await main.run_specialist_worker(
                "Inspect the requested project change.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                read_only_tools=True,
            )

        self.assertEqual(result, "I could not write the file.")
        execute.assert_not_awaited()
        supplied_tools = create.await_args_list[0].kwargs["tools"]
        supplied_names = {tool["function"]["name"] for tool in supplied_tools}
        self.assertTrue(supplied_names)
        self.assertLessEqual(supplied_names, main.SPECIALIST_READ_ONLY_TOOLS)
        self.assertNotIn("write_file", supplied_names)
        system = create.await_args_list[0].kwargs["messages"][0]["content"]
        self.assertIn("Act as a coding specialist", system)

    async def test_requested_safe_read_tool_can_run(self):
        create = AsyncMock(side_effect=[
            completion(calls=[function_call("read_file", {"path": "notes.md"})]),
            completion("The note says: verified."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value="verified note text")
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            result = await main.run_specialist_worker(
                "Read the note and report its finding.",
                "openai",
                "specialist-test",
                role="research",
                starting_tier="balanced",
                read_only_tools=True,
            )

        self.assertEqual(result, "The note says: verified.")
        execute.assert_awaited_once()
        self.assertEqual(execute.await_args.args[:3], (
            "read_file",
            {"path": "notes.md"},
            "openai",
        ))

    async def test_background_specialists_run_concurrently_and_return_structured_reports(self):
        release_workers = asyncio.Event()

        async def specialist_result(
            task: str,
            provider: str,
            task_id: str,
            *,
            result_metadata=None,
            **kwargs,
        ):
            await release_workers.wait()
            if result_metadata is not None:
                result_metadata.update({"provider": provider, "model": "gpt-4.1", "tier": "balanced"})
            return f"Report for {task}"

        with patch.object(main, "run_specialist_worker", new=AsyncMock(side_effect=specialist_result)):
            first = main.start_specialist_background_job(
                "Compare recent studies",
                "openai",
                "specialist-test",
                role="research",
                starting_tier="balanced",
                read_only_tools=True,
            )
            second = main.start_specialist_background_job(
                "Check the implementation",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                read_only_tools=True,
            )
            await asyncio.sleep(0)

            self.assertEqual(first["status"], "running")
            self.assertEqual(second["status"], "running")
            self.assertEqual(
                sum(
                    job["status"] == "running"
                    for job in main.SPECIALIST_BACKGROUND_JOBS.values()
                    if job["task_id"] == "specialist-test"
                ),
                2,
            )
            release_workers.set()
            reports = await main.collect_pending_specialist_artifacts("specialist-test")

        self.assertEqual(len(reports), 2)
        self.assertEqual({report["status"] for report in reports}, {"completed"})
        self.assertTrue(all(report["artifacts"][0]["type"] == "specialist-report" for report in reports))
        self.assertEqual({report["model"] for report in reports}, {"gpt-4.1"})
        await main.cleanup_specialist_background_jobs("specialist-test")


if __name__ == "__main__":
    unittest.main()
