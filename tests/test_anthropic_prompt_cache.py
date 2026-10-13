import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from llm_protocol import collect_completion
from model_client import AnthropicChatClient, _anthropic_messages, _anthropic_request
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
        self.assertEqual(request["system"], [{
            "type": "text",
            "text": "Stable assistant instructions",
            "cache_control": {"type": "ephemeral"},
        }])
        self.assertEqual(request["tools"][-1]["name"], "read_file")
        self.assertEqual(request["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(len(request["tools"]), 2)
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertNotIn("temperature", request)
        self.assertEqual(request["max_tokens"], 8192)

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


async def _append_visible(output, text):
    if text:
        output.append(text)


if __name__ == "__main__":
    unittest.main()
