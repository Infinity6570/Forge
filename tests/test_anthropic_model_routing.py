from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from model_client import AnthropicChatClient, _anthropic_messages, _anthropic_request, _chat_completion
from llm_protocol import collect_completion


class AnthropicProviderRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.env_patch = patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
                "CLAUDE_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "SESSION_SECRET": "test-session-secret",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.path_patches = [
            patch.object(main, "ROOT", root),
            patch.object(main, "ENV_FILE", root / ".env"),
            patch.object(main, "WORKSPACE", root / "workspace"),
            patch.object(main, "DATABASE", root / "workspace" / "assistant.db"),
            patch.object(main, "UPLOADS", root / "workspace" / "uploads"),
            patch.object(main, "NOTES", root / "workspace" / "notes"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)
        main.init_db()

    async def test_direct_client_uses_vault_key(self) -> None:
        main.save_vault_values({"ANTHROPIC_API_KEY": "  vault-anthropic-key  "})
        with patch.object(main, "AnthropicChatClient") as client:
            main.create_llm_client("anthropic")
        client.assert_called_once_with("vault-anthropic-key")

    async def test_direct_client_accepts_claude_environment_alias(self) -> None:
        os.environ["CLAUDE_API_KEY"] = "  env-claude-key  "
        with patch.object(main, "AnthropicChatClient") as client:
            main.create_llm_client("anthropic")
        client.assert_called_once_with("env-claude-key")

    async def test_openrouter_claude_uses_direct_provider_when_key_is_saved(self) -> None:
        main.save_vault_values({"ANTHROPIC_API_KEY": "vault-anthropic-key"})
        self.assertEqual(
            main.resolve_direct_anthropic_model(
                "openrouter", "anthropic/claude-opus-5.5"
            ),
            ("anthropic", "claude-opus-5-5"),
        )

    async def test_unmapped_openrouter_claude_ids_stay_on_openrouter(self) -> None:
        main.save_vault_values({"ANTHROPIC_API_KEY": "vault-anthropic-key"})
        self.assertEqual(
            main.resolve_direct_anthropic_model(
                "openrouter", "anthropic/claude-3.7-sonnet"
            ),
            ("openrouter", "anthropic/claude-3.7-sonnet"),
        )

    async def test_openrouter_model_stays_on_openrouter_without_direct_key(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "openrouter-key"
        self.assertEqual(
            main.resolve_direct_anthropic_model(
                "openrouter", "anthropic/claude-3.7-sonnet"
            ),
            ("openrouter", "anthropic/claude-3.7-sonnet"),
        )

    async def test_anthropic_messages_preserve_tool_call_and_pair_result(self) -> None:
        system, messages = _anthropic_messages([
            {"role": "system", "content": "Use tools carefully."},
            {"role": "user", "content": "Find the latest release."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-search",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query":"latest release"}',
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "call-search", "content": "Release is 2.0."},
        ])

        self.assertEqual(system, "Use tools carefully.")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant", "user"])
        result = messages[-1]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool_use_id"], "call-search")
        self.assertEqual(result["content"], "Release is 2.0.")

    async def test_anthropic_request_uses_official_message_shape(self) -> None:
        request = _anthropic_request({
            "model": "claude-sonnet-5-5",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Search."},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web.",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }],
            "tool_choice": "auto",
        })
        self.assertEqual(request["system"], "Be concise.")
        self.assertEqual(request["model"], "claude-sonnet-5-5")
        self.assertEqual(request["tools"][0]["name"], "web_search")
        self.assertEqual(request["max_tokens"], 4096)

    async def test_anthropic_tool_use_response_maps_to_chat_completion(self) -> None:
        response = SimpleNamespace(
            id="msg_123",
            model="claude-sonnet-5-5",
            stop_reason="tool_use",
            content=[
                SimpleNamespace(type="text", text="Searching."),
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_123",
                    name="web_search",
                    input={"query": "release"},
                ),
            ],
        )
        completion = _chat_completion(response)
        self.assertEqual(completion.choices[0].finish_reason, "tool_calls")
        self.assertEqual(completion.choices[0].message.content, "Searching.")
        self.assertEqual(completion.choices[0].message.tool_calls[0].function.name, "web_search")
        self.assertEqual(
            completion.choices[0].message.tool_calls[0].function.arguments,
            '{"query": "release"}',
        )

    async def test_client_uses_official_async_anthropic_sdk(self) -> None:
        with patch("model_client.anthropic.AsyncAnthropic") as sdk:
            client = AnthropicChatClient("  sk-ant-test  ")
        sdk.assert_called_once_with(
            api_key="sk-ant-test",
            timeout=90,
            max_retries=2,
        )
        client._sdk.close.assert_not_called()

    async def test_streaming_tool_use_flows_through_agent_completion_collector(self) -> None:
        events = [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_stream",
                    "name": "web_search",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"query":"latest"}'},
            },
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        ]

        class FakeEvents:
            def __aiter__(self):
                async def iterate():
                    for event in events:
                        yield event
                return iterate()

        class FakeStreamManager:
            async def __aenter__(self):
                return FakeEvents()

            async def __aexit__(self, *_args):
                return None

        sdk = SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **_kwargs: FakeStreamManager())
        )
        client = AnthropicChatClient("test-key", sdk_client=sdk)
        stream = await client.chat.completions.create(
            stream=True,
            model="claude-sonnet-5-5",
            messages=[{"role": "user", "content": "Search for the latest release."}],
        )
        completion = await collect_completion(stream)

        call = completion.choices[0].message.tool_calls[0]
        self.assertEqual(completion.choices[0].finish_reason, "tool_calls")
        self.assertEqual(call.id, "toolu_stream")
        self.assertEqual(call.function.name, "web_search")
        self.assertEqual(call.function.arguments, '{"query":"latest"}')
