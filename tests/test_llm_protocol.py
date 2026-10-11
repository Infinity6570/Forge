from __future__ import annotations

import unittest
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

from llm_protocol import MISSING_SIGNATURE, assistant_turn, collect_completion, prepare_history


class FakeStream:
    def __init__(self, deltas: list[dict]):
        self.deltas = deltas
        self.closed = False

    def __aiter__(self):
        async def chunks():
            for delta in self.deltas:
                yield {
                    "id": "completion",
                    "created": 1,
                    "model": "gemini-3.5-flash-lite",
                    "choices": [{"index": 0, "delta": delta}],
                }
        return chunks()

    async def close(self):
        self.closed = True


class LLMProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_missing_signature_uses_documented_failsafe_only_when_missing(self):
        unsigned = {"role": "assistant", "tool_calls": [{
            "id": "call_one", "type": "function", "function": {"name": "web_search", "arguments": "{}"},
        }]}
        repaired = assistant_turn(unsigned, "gemini")
        self.assertEqual(repaired["tool_calls"][0]["extra_content"]["google"]["thought_signature"], MISSING_SIGNATURE)
        self.assertNotIn("extra_content", unsigned["tool_calls"][0])
        nullable = {"role": "assistant", "tool_calls": [{
            "id": "call_null", "type": "function", "function": {"name": "web_search", "arguments": "{}"},
            "extra_content": {"google": None},
        }]}
        self.assertEqual(assistant_turn(nullable, "gemini")["tool_calls"][0]["extra_content"]["google"]["thought_signature"], MISSING_SIGNATURE)
        signed = {"role": "assistant", "tool_calls": [{
            "id": "call_one", "type": "function", "function": {"name": "web_search", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": "real-signature", "other_field": {"opaque": "keep"}}},
        }]}
        self.assertEqual(assistant_turn(signed, "gemini")["tool_calls"], signed["tool_calls"])
        self.assertEqual(assistant_turn(unsigned, "deepseek")["tool_calls"], unsigned["tool_calls"])

    async def test_native_part_failsafe_honors_wire_casing_and_keeps_arguments_exact(self):
        raw = {"role": "model", "parts": [
            {"functionCall": {"name": "web_search", "args": {"query": "weather"}}, "thoughtSignature": "real"},
            {"functionCall": {"name": "read_workspace_file", "args": {"path": "index.html"}}},
            {"function_call": {"name": "read_workspace_file", "args": {"path": "site.css"}}},
        ]}
        parts = assistant_turn(raw, "gemini")["parts"]
        self.assertEqual(parts[0], raw["parts"][0])
        self.assertEqual(parts[1]["functionCall"], raw["parts"][1]["functionCall"])
        self.assertEqual(parts[1]["thoughtSignature"], MISSING_SIGNATURE)
        self.assertEqual(parts[2]["thought_signature"], MISSING_SIGNATURE)

    async def test_old_history_is_repaired_without_interleaving_calls_and_responses(self):
        calls = [{"id": "one", "type": "function", "function": {"name": "web_search", "arguments": "{}"}},
                 {"id": "two", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]
        history = [{"role": "user", "content": "Search"}, {"role": "assistant", "tool_calls": calls},
                   {"role": "tool", "tool_call_id": "one", "content": "A"},
                   {"role": "tool", "tool_call_id": "two", "content": "B"}]
        repaired = prepare_history(history, "gemini")
        self.assertEqual([turn["role"] for turn in repaired], ["user", "assistant", "tool", "tool"])
        for call in repaired[1]["tool_calls"]:
            self.assertEqual(call["extra_content"]["google"]["thought_signature"], MISSING_SIGNATURE)
        self.assertEqual(repaired[2:], history[2:])

    async def test_full_assistant_message_preserves_opaque_metadata(self):
        raw = {
            "role": "assistant",
            "tool_calls": [{
                "id": "call_one", "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"weather"}'},
                "extra_content": {"google": {"thought_signature": "opaque-signature"}},
            }],
            "extra_content": {"google": {"parts": [
                {"functionCall": {"name": "web_search", "args": {"query": "weather"}}, "thoughtSignature": "camel-signature"},
            ]}},
        }
        message = ChatCompletion.model_validate({
            "id": "completion", "model": "gemini-3.5-flash-lite", "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "message": raw, "finish_reason": "tool_calls"}],
        }).choices[0].message
        replayed = assistant_turn(message)
        self.assertEqual(replayed["tool_calls"], raw["tool_calls"])
        self.assertEqual(replayed["extra_content"], raw["extra_content"])

    async def test_streaming_parallel_calls_keep_per_call_signatures_and_arguments(self):
        stream = FakeStream([
            {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_one", "type": "function", "function": {"name": "web_search", "arguments": '{"query":'}}]},
            {"tool_calls": [{"index": 1, "id": "call_two", "type": "function", "function": {"name": "read_workspace_file", "arguments": '{"path":"index.html"}'}, "extra_content": {"google": {"thoughtSignature": "second"}}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": '"weather"}'}, "extra_content": {"google": {"thought_signature": "first"}}}]},
        ])
        completion = await collect_completion(stream)
        replayed = assistant_turn(completion.choices[0].message)
        self.assertEqual(replayed["tool_calls"][0]["function"]["arguments"], '{"query":"weather"}')
        self.assertEqual(replayed["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "first")
        self.assertEqual(replayed["tool_calls"][1]["extra_content"]["google"]["thoughtSignature"], "second")
        self.assertTrue(stream.closed)

    async def test_user_facing_text_streams_without_private_reasoning(self):
        stream = FakeStream([{"reasoning_content": "PRIVATE"}, {"content": "Hello"}, {"content": " world."}])
        updates = []
        async def publish(text):
            updates.append(text)
        result = await collect_completion(stream, publish)
        self.assertEqual(updates, ["Hello", "Hello world."])
        self.assertEqual(result.choices[0].message.content, "Hello world.")
        self.assertNotIn("PRIVATE", str(updates))

    async def test_tool_turn_removes_partial_answer_but_retains_signature(self):
        stream = FakeStream([
            {"content": "Checking."},
            {"tool_calls": [{"index": 0, "id": "call_one", "type": "function", "function": {"name": "web_search", "arguments": "{}"}, "extra_content": {"google": {"thought_signature": "opaque"}}}]},
        ])
        updates = []
        async def publish(text):
            updates.append(text)
        await collect_completion(stream, publish)
        self.assertEqual(updates, ["Checking.", None])

    async def test_non_streaming_compatibility_and_empty_stream_failure(self):
        response = SimpleNamespace(choices=[])
        self.assertIs(await collect_completion(response), response)
        with self.assertRaisesRegex(ValueError, "empty"):
            await collect_completion(FakeStream([]))
