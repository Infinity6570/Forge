from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main


class GeminiToolHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        workspace = root / "workspace"
        workspace.mkdir()
        for name, value in {
            "ROOT": root, "PROJECT_DIR": root.resolve(), "BASE_DIR": workspace.resolve(), "WORKSPACE": workspace, "DATABASE": workspace / "assistant.db",
            "UPLOADS": workspace / "uploads", "NOTES": workspace / "notes", "ENV_FILE": root / ".env",
        }.items():
            change = patch.object(main, name, value)
            change.start()
            self.addCleanup(change.stop)
        environment = patch.dict(main.os.environ, {"GEMINI_API_KEY": "test-only-key", "GEMINI_FALLBACK_MODEL": ""}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        main.init_db()
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,file_ids_json,created_at,updated_at) "
            "VALUES('signed','Test signed tools','queued','Queued','[]','gemini','gemini-3.5-flash-lite','[]',?,?)",
            (now, now),
        )

    def signed_stream(self, name="web_search", arguments=None):
        async def chunks():
            yield {
                "id": "turn", "created": 1, "model": "gemini-3.5-flash-lite",
                "choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "call_one", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments or {"query": "weather"})},
                    "extra_content": {"google": {"thought_signature": "opaque-regression-signature"}},
                }]}, "finish_reason": "tool_calls"}],
            }
        return chunks()

    def text_stream(self, *, fail=False):
        async def chunks():
            for text in ["Hello", " world"]:
                yield {
                    "id": "answer", "created": 1, "model": "gemini-3.5-flash-lite",
                    "choices": [{"index": 0, "delta": {"content": text}}],
                }
                if fail:
                    raise ValueError("Provider interrupted")
                await asyncio.sleep(0.16)
        return chunks()

    async def test_streamed_tool_history_keeps_signature_and_pairs_tool_response(self):
        create = AsyncMock(side_effect=[self.signed_stream(), self.text_stream()])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client), patch.object(main, "execute_tool", new=AsyncMock(return_value='{"weather":"clear"}')):
            await main.run_agent_task("signed", [])
        history = create.call_args.kwargs["messages"]
        call = next(turn for turn in history if turn["role"] == "assistant")["tool_calls"][0]
        tool_result = next(turn for turn in history if turn["role"] == "tool")
        self.assertEqual(call["extra_content"]["google"]["thought_signature"], "opaque-regression-signature")
        self.assertEqual(call["id"], tool_result["tool_call_id"])
        self.assertTrue(create.call_args.kwargs["stream"])
        task = main.db_one("SELECT * FROM tasks WHERE id='signed'")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "Hello world")
        self.assertNotIn("opaque-regression-signature", task["logs_json"])

    async def test_native_candidate_text_completes_simple_no_tool_prompt(self):
        response = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "Hi! How can I help?"}]},
            }],
        }
        create = AsyncMock(return_value=response)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("signed", [])

        task = main.db_one("SELECT status,result FROM tasks WHERE id='signed'")
        self.assertEqual(create.await_count, 1)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "Hi! How can I help?")
        self.assertNotIn("All actions have completed", str(create.call_args.kwargs["messages"]))

    async def test_academic_abstracts_are_not_truncated_in_tool_followup(self):
        output = json.dumps({"engine": "academic-search", "results": [
            {"title": "Clinical trial", "abstract": "Full abstract text. " * 1200}
        ]})
        create = AsyncMock(side_effect=[
            self.signed_stream(name="academic_search", arguments={"query": "dental trial"}),
            self.text_stream(),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client), patch.object(
            main, "execute_tool", new=AsyncMock(return_value=output)
        ):
            await main.run_agent_task("signed", [])
        history = create.call_args.kwargs["messages"]
        tool_result = next(turn for turn in history if turn["role"] == "tool")
        self.assertGreater(len(output), 16_000)
        self.assertEqual(tool_result["content"], output)

    async def test_native_tool_result_is_sent_back_for_final_candidate_text(self):
        tool_response = {
            "candidates": [{
                "finishReason": "FUNCTION_CALL",
                "content": {"parts": [
                    {"text": "Searching the web.", "thought": True},
                    {"functionCall": {"name": "web_search", "args": {"query": "weather"}},
                     "thoughtSignature": "native-signature"},
                ]},
            }],
        }
        final_response = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "The forecast is clear."}]},
            }],
        }
        create = AsyncMock(side_effect=[tool_response, final_response])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        checkpointed = []

        def capture_checkpoint(task_id, messages, history_start):
            checkpointed[:] = messages

        with patch.object(main, "create_llm_client", return_value=client), patch.object(
            main, "execute_tool", new=AsyncMock(return_value='{"forecast":"clear"}')
        ) as execute, patch.object(main.THREADS, "checkpoint", side_effect=capture_checkpoint):
            await main.run_agent_task("signed", [])

        self.assertEqual(create.await_count, 2)
        execute.assert_awaited_once()
        follow_up = create.call_args_list[1].kwargs["messages"]
        self.assertTrue(any(turn["role"] == "tool" and "clear" in turn["content"] for turn in follow_up))
        task = main.db_one("SELECT status,result FROM tasks WHERE id='signed'")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "The forecast is clear.")
        stored_assistant = next(
            turn for turn in checkpointed
            if turn.get("role") == "assistant" and turn.get("tool_calls")
        )
        self.assertEqual(stored_assistant["reasoning_content"], "Searching the web.")
        self.assertEqual(
            stored_assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"],
            "native-signature",
        )

    async def test_empty_final_turn_retries_with_tool_results_and_synthesis_instruction(self):
        create = AsyncMock(side_effect=[
            self.signed_stream(),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                role="assistant", content=None, tool_calls=None
            ))]),
            self.text_stream(),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client), patch.object(
            main, "execute_tool", new=AsyncMock(return_value='{"weather":"clear"}')
        ) as execute:
            await main.run_agent_task("signed", [])

        self.assertEqual(create.await_count, 3)
        execute.assert_awaited_once()
        synthesis = create.call_args.kwargs
        self.assertNotIn("tools", synthesis)
        sent = synthesis["messages"]
        self.assertTrue(any(turn["role"] == "tool" and "clear" in turn["content"] for turn in sent))
        self.assertIn("All actions have completed", sent[-1]["content"])
        task = main.db_one("SELECT * FROM tasks WHERE id='signed'")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "Hello world")
        self.assertNotIn("The model returned no final text.", task["logs_json"])

    async def test_configured_tool_round_limit_is_followed_by_synthesis_before_completion(self):
        create = AsyncMock(
            side_effect=[
                self.signed_stream() for _ in range(main.MAX_TOOL_ROUNDS)
            ] + [self.text_stream()]
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client), patch.object(
            main, "execute_tool", new=AsyncMock(return_value='{"step":"done"}')
        ) as execute:
            await main.run_agent_task("signed", [])

        self.assertEqual(create.await_count, main.MAX_TOOL_ROUNDS + 1)
        self.assertEqual(execute.await_count, main.MAX_TOOL_ROUNDS)
        final_request = create.call_args.kwargs
        self.assertNotIn("tools", final_request)
        self.assertIn("All actions have completed", final_request["messages"][-1]["content"])
        self.assertEqual(main.db_one("SELECT status FROM tasks WHERE id='signed'")["status"], "completed")

    async def test_empty_synthesis_fails_without_persisting_a_fake_assistant_answer(self):
        empty = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            role="assistant", content=None, tool_calls=None
        ))])
        create = AsyncMock(side_effect=[empty, empty])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("signed", [])

        task = main.db_one("SELECT * FROM tasks WHERE id='signed'")
        self.assertEqual(create.await_count, 2)
        self.assertEqual(task["status"], "failed")
        self.assertIsNone(task["result"])
        self.assertIn("no user-facing text", task["error"])
        self.assertNotIn("The model returned no final text.", task["messages_json"])

    async def test_workspace_update_runs_immediately_and_keeps_signed_tool_history(self):
        target = main.WORKSPACE / "index.html"
        target.write_text("old", encoding="utf-8")
        create = AsyncMock(side_effect=[
            self.signed_stream("write_workspace_preview_file", {"path": "index.html", "content": "new"}),
            self.text_stream(),
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("signed", [])
        task = main.db_one("SELECT * FROM tasks WHERE id='signed'")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        history = create.call_args.kwargs["messages"]
        assistant = next(turn for turn in history if turn["role"] == "assistant")
        response = next(turn for turn in history if turn["role"] == "tool")
        self.assertEqual(assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "opaque-regression-signature")
        self.assertEqual(response["tool_call_id"], assistant["tool_calls"][0]["id"])
        self.assertEqual(task["result"], "Hello world")

    async def test_interrupted_stream_does_not_leave_partial_text_as_final_answer(self):
        create = AsyncMock(return_value=self.text_stream(fail=True))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            await main.run_agent_task("signed", [])
        task = main.db_one("SELECT * FROM tasks WHERE id='signed'")
        self.assertEqual(task["status"], "failed")
        self.assertIsNone(task["result"])
        self.assertIn("Provider interrupted", task["error"])
