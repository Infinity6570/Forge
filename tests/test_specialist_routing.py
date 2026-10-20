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

    def test_task_role_selects_starting_tier_before_price_arbitration(self):
        self.assertEqual(main.specialist_default_tier("general", "Explain this result."), "fast")
        self.assertEqual(main.specialist_default_tier("research", "Find recent papers."), "fast")
        self.assertEqual(main.specialist_default_tier("coding", "Inspect this function."), "fast")
        self.assertEqual(main.specialist_default_tier("analysis", "Compare these two options."), "balanced")
        self.assertEqual(
            main.specialist_default_tier("analysis", "Perform a multi-file architectural refactoring."),
            "reasoning",
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

        self.assertIn("escalated from openai · fast", result)
        self.assertTrue(result.endswith("Verified answer."))
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["gpt-4o-mini", "gpt-4o"],
        )
        logs = main.task_dict(main.db_one("SELECT * FROM tasks WHERE id='specialist-test'"))["logs"]
        self.assertTrue(any("escalated from openai · fast" in item["message"] for item in logs))
        self.assertTrue(all(
            call.kwargs["model"] in main.MODEL_OPTIONS["openai"]
            for call in create.await_args_list
        ))

    async def test_provider_failure_escalates_without_switching_providers(self):
        create = AsyncMock(side_effect=[RuntimeError("temporary provider failure"), completion("Recovered.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(
            main,
            "credential_for",
            side_effect=lambda candidate: "test-key" if candidate == "anthropic" else None,
        ), patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Analyze this implementation.",
                "anthropic",
                "specialist-test",
                role="analysis",
                starting_tier="fast",
            )

        self.assertIn("escalated from anthropic · fast", result)
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["claude-haiku-5-5", "claude-sonnet-5-5"],
        )
        self.assertTrue(all(
            call.kwargs["model"] in main.MODEL_OPTIONS["anthropic"]
            for call in create.await_args_list
        ))

    def test_specialist_cost_arbitrage_prefers_cheapest_configured_provider_and_keeps_parent_fallback(self):
        with patch.object(
            main,
            "credential_for",
            side_effect=lambda candidate: (
                "configured"
                if candidate in {"openai", "deepseek", "gemini", "anthropic"}
                else None
            ),
        ):
            attempts, summary = main.specialist_route_plan(
                "openai",
                "research",
                "fast",
                "Summarize these papers.",
            )

        self.assertEqual(attempts[:3], [
            ("anthropic", "fast", "claude-haiku-5-5"),
            ("anthropic", "balanced", "claude-sonnet-5-5"),
            ("anthropic", "reasoning", "claude-opus-5-5"),
        ])
        self.assertEqual(attempts[3], ("openai", "fast", "gpt-4o-mini"))
        self.assertIn("lowest published-rate candidate", summary)
        self.assertIn("Configured provider estimates", summary)
        self.assertIn("gemini ", summary)
        self.assertIn("deepseek ", summary)
        self.assertIn("anthropic ", summary)
        self.assertIn("openai ", summary)
        self.assertIn("fallback chain: openai models from fast upward", summary)
        self.assertNotIn("private chain-of-thought", summary)

    async def test_failed_cheapest_provider_falls_back_to_parent_provider_chain(self):
        create = AsyncMock(side_effect=[
            RuntimeError("Anthropic unavailable"),
            RuntimeError("Anthropic unavailable"),
            RuntimeError("Anthropic unavailable"),
            completion("Recovered by the parent provider."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        metadata: dict[str, str] = {}
        with patch.object(
            main,
            "credential_for",
            side_effect=lambda candidate: (
                "configured" if candidate in {"anthropic", "openai"} else None
            ),
        ), patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Summarize the source documents.",
                "openai",
                "specialist-test",
                role="research",
                starting_tier="fast",
                result_metadata=metadata,
            )

        self.assertTrue(result.endswith("Recovered by the parent provider."))
        self.assertEqual(metadata["provider"], "openai")
        self.assertEqual(metadata["model"], "gpt-4o-mini")
        self.assertIn("selected anthropic", metadata["decisionSummary"])
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "gpt-4o-mini"],
        )
        all_tool_names = {tool["function"]["name"] for tool in main.TOOLS}
        self.assertTrue(all(
            {tool["function"]["name"] for tool in call.kwargs.get("tools", [])} == all_tool_names
            for call in create.await_args_list
        ))

    async def test_usage_ledger_persists_provider_neutral_cost_rows(self):
        completion_with_usage = SimpleNamespace(
            choices=[],
            provider_usage={"prompt_tokens": 1000, "completion_tokens": 250},
        )
        record = main.log_usage_ledger_entry(
            "specialist-test",
            "openai",
            "gpt-4o-mini",
            completion_with_usage,
            source="specialist",
            tier="fast",
        )
        self.assertIsNotNone(record)
        self.assertAlmostEqual(record["costUsd"], 0.0003)
        row = main.db_one(
            "SELECT provider,model_id,source,tier,input_tokens,output_tokens,cost_usd,cost_known "
            "FROM usage_ledger WHERE task_id=?",
            ("specialist-test",),
        )
        self.assertEqual(row["provider"], "openai")
        self.assertEqual(row["model_id"], "gpt-4o-mini")
        self.assertEqual(row["source"], "specialist")
        self.assertEqual(row["tier"], "fast")
        self.assertEqual(row["input_tokens"], 1000)
        self.assertEqual(row["output_tokens"], 250)
        self.assertEqual(row["cost_known"], 1)
        api_result = await main.get_usage_ledger()
        self.assertEqual(api_result["totals"]["entries"], 1)
        self.assertEqual(api_result["entries"][0]["model_id"], "gpt-4o-mini")

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

    async def test_all_tools_are_exposed_but_ungranted_write_calls_are_not_executed(self):
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
        self.assertEqual(supplied_names, {tool["function"]["name"] for tool in main.TOOLS})
        self.assertIn("write_file", supplied_names)
        system = create.await_args_list[0].kwargs["messages"][0]["content"]
        self.assertIn("Act as a coding specialist", system)
        self.assertIn("full read/inspection access are always supplied", system)

    def test_specialist_tool_schemas_always_include_the_full_catalog(self):
        def names(**permissions):
            return {
                tool["function"]["name"]
                for tool in main.specialist_tool_schemas(**permissions)
            }

        delegation_tools = {
            tool["function"]["name"]: tool["function"]["parameters"]
            for tool in main.TOOLS
            if tool.get("function", {}).get("name") in {
                "delegate_to_specialist",
                "start_specialist_worker",
            }
        }
        self.assertEqual(set(delegation_tools), {
            "delegate_to_specialist",
            "start_specialist_worker",
        })
        for schema in delegation_tools.values():
            for permission in ("allow_workspace_write", "allow_terminal_execution"):
                with self.subTest(permission=permission):
                    self.assertEqual(schema["properties"][permission]["type"], "boolean")
                    self.assertIs(schema["properties"][permission]["default"], True)
                    self.assertNotIn(permission, schema.get("required", []))

        expected_names = {tool["function"]["name"] for tool in main.TOOLS}
        self.assertEqual(names(), expected_names)
        self.assertEqual(names(read_only_tools=False), expected_names)
        self.assertEqual(names(allow_workspace_write=True), expected_names)
        self.assertEqual(names(allow_terminal_execution=True), expected_names)
        self.assertEqual(names(
            read_only_tools=False,
            allow_workspace_write=True,
            allow_terminal_execution=True,
        ), expected_names)

    async def test_unapproved_write_and_terminal_calls_are_rejected_before_execution(self):
        create = AsyncMock(side_effect=[
            completion(calls=[
                function_call("write_file", {"path": "nope.txt", "content": "blocked"}, "write-1"),
                function_call("run_command", {"command": "touch nope.txt"}, "terminal-1"),
            ]),
            completion("I was not granted permission to change files or run commands."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value='{"unexpected":true}')
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            result = await main.run_specialist_worker(
                "Inspect the requested project change.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
            )

        self.assertIn("not granted permission", result)
        execute.assert_not_awaited()
        tool_results = [
            message["content"]
            for message in create.await_args_list[1].kwargs["messages"]
            if message.get("role") == "tool"
        ]
        self.assertEqual(len(tool_results), 2)
        for output in tool_results:
            self.assertIn("not authorized for this specialist worker", output)
        self.assertIn(
            "Granted Tool Permissions: Full read and inspection tools (always enabled)",
            create.await_args_list[0].kwargs["messages"][0]["content"],
        )

    async def test_authorized_specialist_can_write_and_replace_project_files(self):
        create = AsyncMock(side_effect=[
            completion(calls=[
                function_call(
                    "replace_in_file",
                    {"path": "notes.md", "old_text": "old", "new_text": "new"},
                )
            ]),
            completion("Updated and verified notes.md."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value=json.dumps({"saved": True, "path": "notes.md"}))
        metadata = {}
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            result = await main.run_specialist_worker(
                "Update notes.md as requested.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                allow_workspace_write=True,
                result_metadata=metadata,
            )

        self.assertEqual(result, "Updated and verified notes.md.")
        execute.assert_awaited_once()
        self.assertEqual(execute.await_args.args[0:2], (
            "replace_in_file",
            {"path": "notes.md", "old_text": "old", "new_text": "new"},
        ))
        supplied_names = {
            tool["function"]["name"]
            for tool in create.await_args_list[0].kwargs["tools"]
        }
        self.assertEqual(supplied_names, {tool["function"]["name"] for tool in main.TOOLS})
        self.assertIn(
            "Workspace file write/edit tools",
            create.await_args_list[0].kwargs["messages"][0]["content"],
        )
        self.assertEqual(metadata["successfulWorkspaceWrites"], ["notes.md"])
        self.assertEqual(
            main.specialist_workspace_write_paths(
                "delegate_to_specialist",
                json.dumps({"successfulWorkspaceWrites": ["notes.md"]}),
            ),
            {"notes.md"},
        )

    async def test_authorized_specialist_can_delete_a_scoped_noncritical_file(self):
        target = Path(self.temp_dir.name) / "old-note.txt"
        target.write_text("no longer needed", encoding="utf-8")
        create = AsyncMock(side_effect=[
            completion(calls=[function_call("delete_file", {"path": "old-note.txt"})]),
            completion("Removed the obsolete note."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            result = await main.run_specialist_worker(
                "Remove the obsolete note file.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                allow_workspace_write=True,
            )

        self.assertEqual(result, "Removed the obsolete note.")
        self.assertFalse(target.exists())

    async def test_authorized_specialist_can_run_terminal_command(self):
        create = AsyncMock(side_effect=[
            completion(calls=[
                function_call("run_command", {"command": "python -m compileall ."})
            ]),
            completion("The compile check passed."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        command_result = {
            "returnCode": 0,
            "timedOut": False,
            "stdout": "OK",
            "stderr": "",
        }
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "run_workspace_command", return_value=command_result) as run_command:
            result = await main.run_specialist_worker(
                "Run the requested verification command.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                allow_terminal_execution=True,
            )

        self.assertEqual(result, "The compile check passed.")
        run_command.assert_called_once()
        self.assertEqual(run_command.call_args.args, ("python -m compileall .", "."))
        self.assertNotIn("OPENAI_API_KEY", run_command.call_args.kwargs["env"])
        supplied_names = {
            tool["function"]["name"]
            for tool in create.await_args_list[0].kwargs["tools"]
        }
        self.assertEqual(supplied_names, {tool["function"]["name"] for tool in main.TOOLS})
        self.assertIn("write_file", supplied_names)

    async def test_critical_tools_are_exposed_but_routed_back_to_supervisor(self):
        (Path(self.temp_dir.name) / "main.py").write_text("preserve until approval")
        create = AsyncMock(side_effect=[
            completion(calls=[
                function_call("delete_file", {"path": "main.py"}, "delete"),
                function_call("execute_elevated_command", {"command": "whoami"}, "elevated"),
                function_call(
                    "send_engine_remote_command",
                    {"engine": "unreal", "endpoint_url": "http://localhost:30010", "payload": {}},
                    "engine",
                ),
            ]),
            completion("Those actions are outside my delegated permissions."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value='{"unexpected":true}')
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            result = await main.run_specialist_worker(
                "Inspect and update the project.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                allow_workspace_write=True,
                allow_terminal_execution=True,
            )

        self.assertEqual(result, "Those actions are outside my delegated permissions.")
        execute.assert_not_awaited()
        supplied_names = {
            tool["function"]["name"]
            for tool in create.await_args_list[0].kwargs["tools"]
        }
        self.assertEqual(supplied_names, {tool["function"]["name"] for tool in main.TOOLS})
        tool_results = [
            message["content"]
            for message in create.await_args_list[1].kwargs["messages"]
            if message.get("role") == "tool"
        ]
        self.assertEqual(len(tool_results), 3)
        self.assertIn('"requiresSupervisorAction": true', tool_results[0])
        self.assertIn("human approval", tool_results[0])

    async def test_delegation_handlers_forward_explicit_permission_flags(self):
        arguments = {
            "task": "Implement and test a small change.",
            "role": "coding",
            "allow_workspace_write": True,
            "allow_terminal_execution": True,
        }
        with patch.object(main, "run_specialist_worker", new=AsyncMock(return_value="done")) as worker:
            await main.execute_tool(
                "delegate_to_specialist",
                arguments,
                "openai",
                {"model": "gpt-4o-mini"},
                "",
                "specialist-test",
            )

        self.assertTrue(worker.await_args.kwargs["allow_workspace_write"])
        self.assertTrue(worker.await_args.kwargs["allow_terminal_execution"])

        with patch.object(
            main,
            "start_specialist_background_job",
            return_value={"workerId": "worker-test", "status": "running"},
        ) as background:
            await main.execute_tool(
                "start_specialist_worker",
                arguments,
                "openai",
                {"model": "gpt-4o-mini"},
                "",
                "specialist-test",
            )

        self.assertTrue(background.call_args.kwargs["allow_workspace_write"])
        self.assertTrue(background.call_args.kwargs["allow_terminal_execution"])

    async def test_delegation_grants_routine_write_and_terminal_access_when_flags_are_omitted(self):
        arguments = {"task": "Implement and test the requested change.", "role": "coding"}
        with patch.object(main, "run_specialist_worker", new=AsyncMock(return_value="done")) as worker:
            await main.execute_tool(
                "delegate_to_specialist",
                arguments,
                "openai",
                {"model": "gpt-4o-mini"},
                "",
                "specialist-test",
            )

        self.assertTrue(worker.await_args.kwargs["allow_workspace_write"])
        self.assertTrue(worker.await_args.kwargs["allow_terminal_execution"])

        with patch.object(
            main,
            "start_specialist_background_job",
            return_value={"workerId": "worker-default", "status": "running"},
        ) as background:
            await main.execute_tool(
                "start_specialist_worker",
                arguments,
                "openai",
                {"model": "gpt-4o-mini"},
                "",
                "specialist-test",
            )

        self.assertTrue(background.call_args.kwargs["allow_workspace_write"])
        self.assertTrue(background.call_args.kwargs["allow_terminal_execution"])

    async def test_nested_specialist_cannot_regrant_write_or_terminal_access(self):
        create = AsyncMock(side_effect=[
            completion(calls=[function_call(
                "delegate_to_specialist",
                {
                    "task": "Edit files and run tests.",
                    "allow_workspace_write": True,
                    "allow_terminal_execution": True,
                },
            )]),
            completion("The nested work was delegated without inheriting permissions."),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        execute = AsyncMock(return_value='{"summary":"read-only child"}')
        with patch.object(main, "create_llm_client", return_value=client), \
                patch.object(main, "execute_tool", new=execute):
            await main.run_specialist_worker(
                "Delegate independent analysis.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                allow_workspace_write=True,
                allow_terminal_execution=True,
            )

        nested_arguments = execute.await_args.args[1]
        self.assertTrue(nested_arguments["read_only_tools"])
        self.assertFalse(nested_arguments["allow_workspace_write"])
        self.assertFalse(nested_arguments["allow_terminal_execution"])

    async def test_background_worker_preserves_granted_permissions(self):
        worker = AsyncMock(return_value="Background work completed.")
        with patch.object(main, "run_specialist_worker", new=worker):
            started = main.start_specialist_background_job(
                "Implement and test the assigned change.",
                "openai",
                "specialist-test",
                role="coding",
                starting_tier="balanced",
                read_only_tools=True,
                allow_workspace_write=True,
                allow_terminal_execution=True,
            )
            job = main.SPECIALIST_BACKGROUND_JOBS[started["workerId"]]
            await job["task"]

        self.assertEqual(started["status"], "running")
        self.assertEqual(job["permissions"], {
            "read_only_tools": True,
            "allow_workspace_write": True,
            "allow_terminal_execution": True,
        })
        self.assertTrue(worker.await_args.kwargs["read_only_tools"])
        self.assertTrue(worker.await_args.kwargs["allow_workspace_write"])
        self.assertTrue(worker.await_args.kwargs["allow_terminal_execution"])
        await main.cleanup_specialist_background_jobs("specialist-test")

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
