import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from llm_protocol import collect_completion
from model_client import (
    AnthropicChatClient,
    _anthropic_messages,
    _anthropic_request,
)
from openai.types.chat import ChatCompletion


class AnthropicPromptCacheTests(unittest.IsolatedAsyncioTestCase):
    def test_requests_cache_stable_prefix_and_keep_tools_on_each_turn(self):
        request = _anthropic_request({
            "model": "claude-sonnet-5-5",
            "max_tokens": 6000,
            "temperature": 0.2,
            "system": None,
            "messages": [
                {"role": "system", "content": "Stable assistant instructions"},
                {"role": "user", "content": "Build a small page"},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write a workspace file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a workspace file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ],
            "tool_choice": {"type": "none"},
        })

        self.assertEqual(request["cache_control"], {"type": "ephemeral"})
        self.assertEqual(
            request["extra_headers"],
            {"anthropic-beta": "thinking-binding-controls-2026-08-01"},
        )
        self.assertEqual(request["system"], [{
            "type": "text",
            "text": "Stable assistant instructions",
            "cache_control": {"type": "ephemeral"},
        }])
        self.assertEqual(request["tools"][-1]["name"], "read_file")
        self.assertEqual(request["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(len(request["tools"]), 2)
        self.assertEqual(request["thinking"], {
            "type": "adaptive",
            "display": "summarized",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"},
        })
        self.assertNotIn("temperature", request)
        self.assertEqual(request["max_tokens"], 16384)

    def test_legacy_supported_model_uses_stable_manual_budget(self):
        request = _anthropic_request({
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Reason carefully"}],
        })
        self.assertEqual(
            request["thinking"],
            {"type": "enabled", "budget_tokens": 4096},
        )

    def test_signed_thinking_blocks_are_replayed_without_reconstruction(self):
        blocks = [
            {"type": "thinking", "thinking": "private provider data", "signature": "signed-value"},
            {"type": "text", "text": "Visible answer"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.txt"}},
        ]
        _, messages = _anthropic_messages([
            {"role": "user", "content": "Inspect a file"},
            {
                "role": "assistant",
                "content": "Visible answer",
                "tool_calls": [{
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                }],
                "anthropic_content_blocks": blocks,
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": "file text"},
        ])
        self.assertEqual(messages[1]["content"], blocks)
        self.assertEqual(messages[2]["content"], [{
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "file text",
        }])

    async def test_stream_keeps_provider_blocks_and_usage_private_from_text_callback(self):
        blocks = [
            {"type": "thinking", "thinking": "private provider data", "signature": "signed-value"},
            {"type": "text", "text": "Done"},
        ]
        usage = {
            "input_tokens": 14,
            "output_tokens": 5,
            "cache_read_input_tokens": 9,
            "cache_creation_input_tokens": 3,
        }

        class FakeStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def __aiter__(self):
                async def events():
                    yield {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "thinking_delta", "thinking": "private provider data"},
                    }
                    yield {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "text_delta", "text": "Done"},
                    }
                    yield {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                    }
                return events()

            async def get_final_message(self):
                return {
                    "id": "msg_test",
                    "model": "claude-sonnet-5-5",
                    "content": blocks,
                    "usage": usage,
                }

        class FakeMessages:
            def stream(self, **kwargs):
                self.request = kwargs
                return FakeStream()

        class FakeSdk:
            def __init__(self):
                self.messages = FakeMessages()

        sdk = FakeSdk()
        client = AnthropicChatClient("test-key", sdk_client=sdk)
        visible_text = []
        completion = await collect_completion(
            await client.chat.completions.create(
                model="claude-sonnet-5-5",
                messages=[{"role": "user", "content": "Do the work"}],
                tools=[],
                stream=True,
            ),
            lambda text: _append_visible(visible_text, text),
        )

        message = completion.choices[0].message
        self.assertEqual(message.content, "Done")
        self.assertEqual(message.anthropic_content_blocks, blocks)
        self.assertEqual(message.anthropic_usage, usage)
        self.assertNotIn("private provider data", "".join(text or "" for text in visible_text))
        self.assertEqual(sdk.messages.request["cache_control"], {"type": "ephemeral"})

    async def test_cache_usage_is_written_to_the_task_telemetry_feed(self):
        response = ChatCompletion.model_validate({
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "created": 1,
            "model": "claude-sonnet-5-5",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Done",
                    "anthropic_usage": {
                        "cache_read_input_tokens": 42,
                        "cache_creation_input_tokens": 11,
                    },
                },
            }],
        })

        class FakeCompletions:
            async def create(self, **_kwargs):
                return response

        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        with patch.object(main, "log_task") as log_task:
            await main.create_completion_with_fallback(
                client,
                {"model": "claude-sonnet-5-5", "messages": []},
                "anthropic",
                {"model": "claude-sonnet-5-5"},
                "",
                "task-test",
            )

        self.assertEqual(log_task.call_args.args[0], "task-test")
        self.assertIn("cache_read_input_tokens=42", log_task.call_args.args[1])
        self.assertIn("cache_creation_input_tokens=11", log_task.call_args.args[1])
        self.assertFalse(log_task.call_args.kwargs["update_step"])

    async def test_signature_mismatch_retries_with_a_copy_without_thinking_blocks(self):
        historical_blocks = [
            {"type": "thinking", "thinking": "summary", "signature": "bad-signature"},
            {"type": "text", "text": "Searching"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}},
            {"type": "redacted_thinking", "data": "opaque"},
        ]
        original_messages = [
            {"role": "system", "content": "Stable system instructions"},
            {"role": "user", "content": "Inspect a file"},
            {
                "role": "assistant",
                "content": "Searching",
                "anthropic_content_blocks": historical_blocks,
                "tool_calls": [{
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": "file text"},
        ]

        class SignatureMismatch(Exception):
            status_code = 400

        class FakeMessages:
            def __init__(self):
                self.requests = []

            async def create(self, **request):
                self.requests.append(request)
                if len(self.requests) == 1:
                    raise SignatureMismatch(
                        "400 Invalid signature in thinking block: prefix mismatch"
                    )
                return {
                    "id": "msg_retry",
                    "model": "claude-sonnet-5-5",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {},
                }

        class FakeSdk:
            def __init__(self):
                self.messages = FakeMessages()

        sdk = FakeSdk()
        client = AnthropicChatClient("test-key", sdk_client=sdk)
        result = await client.chat.completions.create(
            model="claude-sonnet-5-5",
            messages=original_messages,
            tools=[],
        )

        self.assertEqual(result.choices[0].message.content, "Done")
        self.assertEqual(len(sdk.messages.requests), 2)
        first_blocks = sdk.messages.requests[0]["messages"][1]["content"]
        retry_blocks = sdk.messages.requests[1]["messages"][1]["content"]
        self.assertEqual(first_blocks, historical_blocks)
        self.assertEqual(
            [block["type"] for block in retry_blocks],
            ["text", "tool_use"],
        )
        self.assertEqual(original_messages[2]["anthropic_content_blocks"], historical_blocks)
        self.assertEqual(
            sdk.messages.requests[1]["system"],
            sdk.messages.requests[0]["system"],
        )
        self.assertEqual(
            sdk.messages.requests[1]["extra_headers"],
            {"anthropic-beta": "thinking-binding-controls-2026-08-01"},
        )

    async def test_stream_signature_mismatch_retries_before_any_delta(self):
        class SignatureMismatch(Exception):
            status_code = 400

        class Stream:
            def __init__(self, fail=False):
                self.fail = fail

            async def __aenter__(self):
                if self.fail:
                    raise SignatureMismatch(
                        "400 Invalid signature in thinking block: prefix mismatch"
                    )
                return self

            async def __aexit__(self, *_):
                return None

            def __aiter__(self):
                async def events():
                    yield {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "recovered"},
                    }
                    yield {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
                return events()

            async def get_final_message(self):
                return {
                    "id": "msg_retry",
                    "model": "claude-sonnet-5-5",
                    "content": [{"type": "text", "text": "recovered"}],
                    "usage": {},
                }

        class FakeMessages:
            def __init__(self):
                self.requests = []

            def stream(self, **request):
                self.requests.append(request)
                return Stream(fail=len(self.requests) == 1)

        class FakeSdk:
            def __init__(self):
                self.messages = FakeMessages()

        original_messages = [
            {"role": "system", "content": "Stable system instructions"},
            {"role": "user", "content": "Continue"},
            {
                "role": "assistant",
                "content": "old",
                "anthropic_content_blocks": [
                    {"type": "thinking", "thinking": "summary", "signature": "bad"},
                    {"type": "text", "text": "old"},
                ],
            },
        ]
        sdk = FakeSdk()
        client = AnthropicChatClient("test-key", sdk_client=sdk)
        visible = []
        result = await collect_completion(
            await client.chat.completions.create(
                model="claude-sonnet-5-5",
                messages=original_messages,
                tools=[],
                stream=True,
            ),
            lambda text: _append_visible(visible, text),
        )

        self.assertEqual(result.choices[0].message.content, "recovered")
        self.assertEqual(visible, ["recovered"])
        self.assertEqual(len(sdk.messages.requests), 2)
        self.assertEqual(
            [block["type"] for block in sdk.messages.requests[1]["messages"][1]["content"]],
            ["text"],
        )
        self.assertEqual(
            original_messages[2]["anthropic_content_blocks"][0]["type"],
            "thinking",
        )

    async def test_provider_summarized_thinking_is_logged_as_visible_activity(self):
        response = ChatCompletion.model_validate({
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "created": 1,
            "model": "claude-opus-5-5",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Final answer",
                    "anthropic_thinking_summary": True,
                    "anthropic_content_blocks": [
                        {"type": "thinking", "thinking": "I will check the source first.", "signature": "sig"},
                        {"type": "text", "text": "Final answer"},
                    ],
                },
            }],
        })

        class FakeCompletions:
            async def create(self, **_kwargs):
                return response

        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        with patch.object(main, "log_task") as log_task:
            await main.create_completion_with_fallback(
                client,
                {"model": "claude-opus-5-5", "messages": []},
                "anthropic",
                {"model": "claude-opus-5-5"},
                "",
                "task-summary",
            )

        self.assertEqual(log_task.call_args.args[0], "task-summary")
        self.assertIn("Claude thinking summary:", log_task.call_args.args[1])
        self.assertIn("I will check the source first.", log_task.call_args.args[1])
        self.assertEqual(log_task.call_args.args[2], "agent")
        self.assertFalse(log_task.call_args.kwargs["update_step"])


async def _append_visible(output, text):
    if text:
        output.append(text)


if __name__ == "__main__":
    unittest.main()
