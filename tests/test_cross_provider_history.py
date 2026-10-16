from __future__ import annotations

import unittest

from gemini_client import _make_contents
from llm_protocol import prepare_history
from model_client import _anthropic_messages


class CrossProviderHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = [
            {"role": "system", "content": "Use tools when needed."},
            {"role": "user", "content": "Search for the latest update."},
            {
                "role": "assistant",
                "content": None,
                "parts": [{
                    "functionCall": {
                        "name": "web_search",
                        "args": {"query": "latest update"},
                    },
                    "thoughtSignature": "saved-google-signature",
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "gemini_call_0",
                "content": '{"summary":"Version 2 is current."}',
            },
            {"role": "assistant", "content": "Version 2 is current."},
        ]

    def test_switching_to_anthropic_rebuilds_function_use_and_tool_result_pair(self) -> None:
        history = prepare_history(self.history, "anthropic")
        system, messages = _anthropic_messages(history)

        self.assertEqual(system, "Use tools when needed.")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant", "user", "assistant"])
        call = messages[1]["content"][0]
        result = messages[2]["content"][0]
        self.assertEqual(call["type"], "tool_use")
        self.assertEqual(call["id"], "gemini_call_0")
        self.assertEqual(call["name"], "web_search")
        self.assertEqual(call["input"], {"query": "latest update"})
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool_use_id"], call["id"])

    def test_switching_to_gemini_uses_only_user_and_model_roles(self) -> None:
        history = prepare_history(self.history, "gemini")
        contents, system = _make_contents(history)

        self.assertEqual(system, "Use tools when needed.")
        self.assertEqual([content.role for content in contents], ["user", "model", "user", "model"])
        self.assertTrue(all(content.role in {"user", "model"} for content in contents))
        call = contents[1].parts[0].model_dump(mode="json", exclude_none=True, by_alias=True)
        result = contents[2].parts[0].model_dump(mode="json", exclude_none=True, by_alias=True)
        self.assertEqual(call["thoughtSignature"], "saved-google-signature")
        self.assertEqual(result["functionResponse"]["name"], "web_search")
        self.assertEqual(result["functionResponse"]["response"], {"summary": "Version 2 is current."})

    def test_switching_to_openai_keeps_matching_tool_call_ids_and_drops_native_extensions(self) -> None:
        history = prepare_history(self.history, "openai")

        self.assertEqual([message["role"] for message in history], [
            "system", "user", "assistant", "tool", "assistant",
        ])
        call = history[2]["tool_calls"][0]
        self.assertEqual(call["id"], "gemini_call_0")
        self.assertEqual(history[3]["tool_call_id"], call["id"])
        self.assertNotIn("parts", history[2])
        self.assertNotIn("extra_content", call)

    def test_legacy_tool_output_without_id_is_paired_by_tool_name(self) -> None:
        history = prepare_history([
            {"role": "assistant", "tool_calls": [{
                "id": "call-a",
                "type": "function",
                "function": {"name": "web_search", "arguments": "{}"},
            }]},
            {"role": "tool", "name": "web_search", "content": "result"},
        ], "openai")
        self.assertEqual(history[1]["tool_call_id"], "call-a")


if __name__ == "__main__":
    unittest.main()
