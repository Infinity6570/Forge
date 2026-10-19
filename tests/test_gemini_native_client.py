from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gemini_client import GeminiChatClient, _call_config
import main


class FakeModels:
    def __init__(self, response=None, stream_chunks=None):
        self.response = response or {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "Gemini reply"}]},
            }],
        }
        self.stream_chunks = stream_chunks or [self.response]
        self.kwargs = None

    async def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.response

    async def generate_content_stream(self, **kwargs):
        self.kwargs = kwargs

        async def chunks():
            for chunk in self.stream_chunks:
                yield chunk

        return chunks()


class FakeLiveSession:
    def __init__(self, events):
        self.event_rounds = events
        self.sent_turns = []
        self.tool_responses = []
        self.closed = False

    async def send_client_content(self, **kwargs):
        self.sent_turns.append(kwargs)

    async def send_tool_response(self, **kwargs):
        self.tool_responses.append(kwargs)

    async def receive(self):
        events = self.event_rounds.pop(0) if self.event_rounds else []
        for event in events:
            yield event


class FakeLiveContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        self.session.closed = True


class FakeLive:
    def __init__(self, sessions):
        self.sessions = sessions
        self.calls = []

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        return FakeLiveContext(self.sessions[len(self.calls) - 1])


class GeminiNativeClientTests(unittest.IsolatedAsyncioTestCase):
    def sdk(self, models):
        return SimpleNamespace(aio=SimpleNamespace(models=models))

    async def test_gemini_model_ids_override_a_stale_non_google_provider(self):
        for model_id in (
            "gemini-4-argon",
            "gemini-3.8-live",
            "gemini-3.8-live-extended-thinking",
            "gemini-3.8-flash-tts",
            "gemini-3.8-flash-lite-tts",
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-nano-banana-2.1",
            "gemini-3.1-flash-image",
            "gemini-3.1-flash-lite-image",
            "gemini-3-pro-image",
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
        ):
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    main.resolve_model_provider("anthropic", model_id),
                    ("gemini", model_id),
                )

        self.assertEqual(
            main.resolve_model_provider("openrouter", "models/gemini-3.1-pro-preview"),
            ("gemini", "models/gemini-3.1-pro-preview"),
        )

    async def test_native_history_preserves_signed_calls_and_pairs_tool_response(self):
        models = FakeModels()
        client = GeminiChatClient("test-key", sdk_client=self.sdk(models))
        messages = [
            {"role": "system", "content": "System guidance"},
            {"role": "user", "content": "Search for weather"},
            {
                "role": "assistant",
                "content": None,
                "parts": [{
                    "functionCall": {"name": "web_search", "args": {"query": "weather"}},
                    "thoughtSignature": "opaque-google-signature",
                }],
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query":"weather"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": '{"summary":"sunny"}'},
        ]
        tools = [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }]

        completion = await client.chat.completions.create(
            model="gemini-3.8-flash",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
            max_tokens=400,
        )

        self.assertEqual(completion.choices[0].message.content, "Gemini reply")
        request_contents = models.kwargs["contents"]
        self.assertEqual([content.role for content in request_contents], ["user", "model", "user"])
        self.assertTrue(all(content.role in {"user", "model"} for content in request_contents))
        model_part = request_contents[1].parts[0].model_dump(
            mode="json", exclude_none=True, by_alias=True
        )
        self.assertEqual(model_part["thoughtSignature"], "opaque-google-signature")
        tool_part = request_contents[2].parts[0].model_dump(
            mode="json", exclude_none=True, by_alias=True
        )
        self.assertEqual(tool_part["functionResponse"]["name"], "web_search")
        self.assertEqual(tool_part["functionResponse"]["response"], {"summary": "sunny"})
        self.assertEqual(models.kwargs["config"].max_output_tokens, 400)
        self.assertEqual(models.kwargs["config"].tools[0].function_declarations[0].name, "web_search")

    async def test_streaming_uses_google_async_stream_and_collects_text(self):
        models = FakeModels(stream_chunks=[
            {"candidates": [{"content": {"parts": [{"text": "Live "}]}}]},
            {
                "candidates": [{"content": {"parts": [{"text": "text"}]}}],
                "usage_metadata": {"cached_content_token_count": 128},
            },
        ])
        client = GeminiChatClient("test-key", sdk_client=self.sdk(models))
        stream = await client.chat.completions.create(
            model="gemini-3.5-flash-lite",
            messages=[{"role": "user", "content": "Say hello"}],
            stream=True,
        )
        from llm_protocol import collect_completion

        completion = await collect_completion(stream)
        self.assertEqual(completion.choices[0].message.content, "Live text")
        self.assertEqual(completion.gemini_cached_tokens, 128)
        self.assertEqual(models.kwargs["model"], "gemini-3.5-flash-lite")

    async def test_non_streaming_cache_usage_metadata_is_preserved_for_telemetry(self):
        models = FakeModels(response={
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "Cached response"}]},
            }],
            "usageMetadata": {"cachedContentTokenCount": 64},
        })
        client = GeminiChatClient("test-key", sdk_client=self.sdk(models))

        completion = await client.chat.completions.create(
            model="gemini-3.8-flash",
            messages=[
                {"role": "system", "content": "Stable shared instructions"},
                {"role": "user", "content": "Hello"},
            ],
            stream=False,
        )

        self.assertEqual(completion.choices[0].message.content, "Cached response")
        self.assertEqual(completion.gemini_cached_tokens, 64)

    async def test_modality_models_receive_distinct_generation_configuration(self):
        _, _, tts_config = _call_config({
            "model": "gemini-3.8-flash-tts",
            "messages": [{"role": "user", "content": "Say hello"}],
            "tools": [{"type": "function", "function": {"name": "unused", "parameters": {}}}],
        })
        self.assertEqual(tts_config.response_modalities, ["AUDIO"])
        self.assertIsNotNone(tts_config.speech_config)
        self.assertIsNone(tts_config.tools)

        _, _, image_config = _call_config({
            "model": "gemini-3-pro-image",
            "messages": [{"role": "user", "content": "Draw a blue flower"}],
        })
        self.assertEqual(image_config.response_modalities, ["TEXT", "IMAGE"])

        _, _, thinking_config = _call_config({
            "model": "gemini-3.8-live-extended-thinking",
            "messages": [{"role": "user", "content": "Explain briefly"}],
        })
        self.assertTrue(thinking_config.thinking_config.include_thoughts)

    async def test_live_model_uses_live_sdk_session_and_sends_tool_results_back(self):
        live_session = FakeLiveSession([
            [{"tool_call": {"function_calls": [{
                "id": "live-call-1",
                "name": "web_search",
                "args": {"query": "weather"},
            }]}}],
            [{"server_content": {
                "model_turn": {"parts": [{"text": "The forecast is clear."}]},
                "turn_complete": True,
            }}],
        ])
        live = FakeLive([live_session])
        models = FakeModels()
        sdk = SimpleNamespace(aio=SimpleNamespace(models=models, live=live))
        client = GeminiChatClient("test-key", sdk_client=sdk)
        tools = [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }]

        first_stream = await client.chat.completions.create(
            model="gemini-3.8-live",
            messages=[{"role": "system", "content": "Be useful."}, {"role": "user", "content": "Check weather"}],
            tools=tools,
            stream=True,
        )
        from llm_protocol import collect_completion

        first = await collect_completion(first_stream)
        call = first.choices[0].message.tool_calls[0]
        followup_messages = [
            {"role": "system", "content": "Be useful."},
            {"role": "user", "content": "Check weather"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }],
            },
            {"role": "tool", "tool_call_id": call.id, "content": '{"weather":"clear"}'},
        ]
        second_stream = await client.chat.completions.create(
            model="gemini-3.8-live",
            messages=followup_messages,
            tools=tools,
            stream=True,
        )
        second = await collect_completion(second_stream)

        self.assertEqual(second.choices[0].message.content, "The forecast is clear.")
        self.assertEqual(len(live.calls), 1)
        self.assertEqual(live.calls[0]["model"], "gemini-3.8-live")
        self.assertEqual(live.calls[0]["config"].response_modalities, ["TEXT"])
        self.assertEqual(len(live_session.tool_responses), 1)
        self.assertEqual(
            live_session.tool_responses[0]["function_responses"][0].name,
            "web_search",
        )
        self.assertEqual(
            live_session.tool_responses[0]["function_responses"][0].id,
            "live-call-1",
        )
        self.assertTrue(live_session.closed)

    async def test_generated_image_is_saved_and_linked_in_the_completion(self):
        image = b"\x89PNG\r\n\x1a\nforged-test-image"
        encoded = base64.b64encode(image).decode("ascii")
        models = FakeModels(response={
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{
                    "inline_data": {"mime_type": "image/png", "data": encoded},
                }]},
            }],
        })
        with tempfile.TemporaryDirectory() as directory:
            client = GeminiChatClient(
                "test-key",
                sdk_client=self.sdk(models),
                media_output_dir=Path(directory),
            )
            completion = await client.chat.completions.create(
                model="gemini-3-pro-image",
                messages=[{"role": "user", "content": "Draw a blue flower"}],
                stream=False,
            )
            saved = list(Path(directory).glob("gemini-*.png"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].read_bytes(), image)
            self.assertIn(f"/workspace-preview/generated-media/{saved[0].name}", completion.choices[0].message.content)


if __name__ == "__main__":
    unittest.main()
