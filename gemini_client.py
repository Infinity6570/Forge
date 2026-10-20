"""Native Google Gen AI adapter for Forge's OpenAI-shaped agent loop."""
from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from llm_protocol import collect_completion, to_wire

THOUGHT_SIGNATURE_FALLBACK = "skip_thought_signature_validator"
IMAGE_MODELS = {
    "gemini-nano-banana-2.1",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
    "gemini-3-pro-image",
}
TTS_MODELS = {"gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"}
LIVE_MODELS = {"gemini-3.8-live", "gemini-3.8-live-extended-thinking"}


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            segment.get("text", "")
            for segment in value
            if isinstance(segment, dict) and isinstance(segment.get("text"), str)
        )
    return ""


def _function_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _native_part(raw_part: dict[str, Any]) -> types.Part:
    part = deepcopy(raw_part)
    signature_key = (
        "thoughtSignature" if "thoughtSignature" in part
        else "thought_signature" if "thought_signature" in part
        else None
    )
    signature = part.pop(signature_key) if signature_key else None
    if isinstance(signature, str):
        try:
            return types.Part.model_validate({**part, signature_key: signature})
        except ValidationError:
            # The documented skip sentinel and older synthetic histories are
            # wire strings rather than base64-encoded signature bytes.
            native = types.Part.model_validate(part)
            native.thought_signature = signature
            return native
    native = types.Part.model_validate(part)
    if signature is not None:
        native.thought_signature = signature
    return native


def _make_contents(messages: list[dict[str, Any]]) -> tuple[list[types.Content], str]:
    contents: list[types.Content] = []
    system_parts: list[str] = []
    call_names: dict[str, str] = {}

    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                name = function.get("name")
                if isinstance(name, str) and name:
                    call_names[str(call.get("id") or "")] = name

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            text = _text_content(content)
            if text:
                system_parts.append(text)
            continue

        if role == "assistant":
            raw_parts = message.get("parts")
            if isinstance(raw_parts, list) and raw_parts:
                parts: list[types.Part] = []
                for raw_part in raw_parts:
                    if not isinstance(raw_part, dict):
                        continue
                    part = deepcopy(raw_part)
                    function_call = part.get("functionCall") or part.get("function_call")
                    if isinstance(function_call, dict) and not (
                        part.get("thoughtSignature") or part.get("thought_signature")
                    ):
                        part["thoughtSignature"] = THOUGHT_SIGNATURE_FALLBACK
                    parts.append(_native_part(part))
            else:
                parts = []
                text = _text_content(content)
                if text:
                    parts.append(types.Part.from_text(text=text))
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    metadata = call.get("extra_content") or {}
                    google_metadata = metadata.get("google") or {}
                    signature = (
                        google_metadata.get("thought_signature")
                        or google_metadata.get("thoughtSignature")
                        or call.get("thought_signature")
                        or call.get("thoughtSignature")
                        or THOUGHT_SIGNATURE_FALLBACK
                    )
                    parts.append(_native_part({
                        "function_call": {
                            "name": name,
                            "args": _function_args(function.get("arguments")),
                        },
                        "thought_signature": signature,
                    }))
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue

        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            name = call_names.get(tool_call_id, "tool_result")
            tool_text = _text_content(content)
            try:
                response = json.loads(tool_text)
                if not isinstance(response, dict):
                    response = {"result": response}
            except (json.JSONDecodeError, TypeError):
                response = {"result": tool_text}
            part = types.Part.from_function_response(name=name, response=response)
            # Gemini Content roles are limited to user/model. Function results
            # are user turns even though their parts are functionResponse.
            contents.append(types.Content(role="user", parts=[part]))
            continue

        if role == "user":
            text = _text_content(content)
            parts: list[types.Part] = []
            if text:
                parts.append(types.Part.from_text(text=text))
            for image in message.get("images") or []:
                if not isinstance(image, dict):
                    continue
                mime_type = str(image.get("mime_type") or "")
                encoded = image.get("data_base64")
                if mime_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
                    raise ValueError(f"Gemini does not support this image type: {mime_type or 'unknown'}.")
                if not isinstance(encoded, str) or not encoded:
                    raise ValueError("The image attachment could not be read. Re-upload it and try again.")
                try:
                    image_data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError) as error:
                    raise ValueError("The image attachment data is invalid. Re-upload it and try again.") from error
                parts.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))
            if parts:
                contents.append(types.Content(role="user", parts=parts))

    return contents, "\n\n".join(system_parts)


def _function_tools(tools: Any) -> list[types.Tool]:
    declarations: list[types.FunctionDeclaration] = []
    for entry in tools or []:
        function = entry.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        declarations.append(types.FunctionDeclaration(
            name=name,
            description=function.get("description") or "",
            parameters_json_schema=function.get("parameters") or {
                "type": "object",
                "properties": {},
            },
        ))
    return [types.Tool(function_declarations=declarations)] if declarations else []


def _call_config(kwargs: dict[str, Any]) -> tuple[str, list[types.Content], types.GenerateContentConfig]:
    model = str(kwargs.get("model") or "")
    model = model.removeprefix("models/")
    # Keep system instructions and tool declarations stable, and preserve
    # chronological conversation order. Google's implicit context caching uses
    # repeated prefixes on supported Gemini models; do not reorder signed turns.
    contents, system_instruction = _make_contents(kwargs.get("messages") or [])
    config: dict[str, Any] = {
        "system_instruction": system_instruction or None,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    max_tokens = kwargs.get("max_output_tokens") or kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
    if max_tokens is not None:
        config["max_output_tokens"] = int(max_tokens)
    for key in ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"):
        if kwargs.get(key) is not None:
            config[key] = kwargs[key]
    if kwargs.get("stop"):
        config["stop_sequences"] = kwargs["stop"]

    lower_model = model.lower()
    supports_tools = model not in IMAGE_MODELS and model not in TTS_MODELS
    tools = _function_tools(kwargs.get("tools")) if supports_tools else []
    choice = kwargs.get("tool_choice", "auto")
    if tools and choice != "none":
        config["tools"] = tools
        mode = "ANY" if choice == "required" or isinstance(choice, dict) else "AUTO"
        function_config: dict[str, Any] = {"mode": mode}
        if isinstance(choice, dict):
            selected_name = ((choice.get("function") or {}).get("name"))
            if selected_name:
                function_config["allowed_function_names"] = [selected_name]
        config["tool_config"] = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(**function_config),
        )

    if model in IMAGE_MODELS:
        config["response_modalities"] = ["TEXT", "IMAGE"]
    elif model in TTS_MODELS:
        config["response_modalities"] = ["AUDIO"]
        config["speech_config"] = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede"),
            ),
        )
    if lower_model.endswith("-extended-thinking"):
        config["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
    return model, contents, types.GenerateContentConfig(**config)


class _GeminiCompletions:
    def __init__(self, client: "GeminiChatClient"):
        self._client = client

    async def create(self, **kwargs: Any) -> Any:
        selected_model = str(kwargs.get("model") or "").removeprefix("models/")
        if selected_model in LIVE_MODELS:
            stream = self._stream_live(selected_model, kwargs)
            if kwargs.get("stream"):
                return stream
            return await collect_completion(stream)

        model, contents, config = _call_config(kwargs)
        if kwargs.get("stream"):
            return self._stream(model, contents, config)
        response = await self._client._sdk.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        normalized = self._client._replace_media_parts(to_wire(response))
        return await collect_completion(normalized)

    async def _stream(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ):
        stream = await self._client._sdk.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )
        media_fragments: dict[str, list[str]] = {}
        async for chunk in stream:
            raw = to_wire(chunk)
            self._client._collect_media_fragments(raw, media_fragments)
            yield self._client._remove_media_parts(raw)
        links = self._client._save_media_fragments(media_fragments)
        if links:
            yield {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "\n\n".join(links)}]},
                }],
            }

    async def _stream_live(self, model: str, kwargs: dict[str, Any]):
        contents, system_instruction = _make_contents(kwargs.get("messages") or [])
        tools = _function_tools(kwargs.get("tools"))
        config: dict[str, Any] = {
            "response_modalities": ["TEXT"],
            "system_instruction": system_instruction or None,
            "tools": tools or None,
        }
        max_tokens = kwargs.get("max_output_tokens") or kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
        if max_tokens is not None:
            config["max_output_tokens"] = int(max_tokens)
        for key in ("temperature", "top_p", "top_k"):
            if kwargs.get(key) is not None:
                config[key] = kwargs[key]
        if model.endswith("-extended-thinking"):
            config["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
        live_config = types.LiveConnectConfig(**config)

        session = await self._client._get_live_session(model, live_config)
        tool_messages = [
            message for message in (kwargs.get("messages") or [])
            if message.get("role") == "tool"
        ]
        if self._client._live_pending_calls:
            new_tool_messages = tool_messages[self._client._live_tool_count:]
            if new_tool_messages:
                responses = []
                for index, message in enumerate(new_tool_messages):
                    pending = (
                        self._client._live_pending_calls[index]
                        if index < len(self._client._live_pending_calls)
                        else {}
                    )
                    text = _text_content(message.get("content"))
                    try:
                        response = json.loads(text)
                        if not isinstance(response, dict):
                            response = {"result": response}
                    except (json.JSONDecodeError, TypeError):
                        response = {"result": text}
                    response_data: dict[str, Any] = {
                        "name": pending.get("name") or "tool_result",
                        "response": response,
                    }
                    if pending.get("id"):
                        response_data["id"] = pending["id"]
                    responses.append(types.FunctionResponse(**response_data))
                try:
                    await session.send_tool_response(function_responses=responses)
                except BaseException:
                    await self._client._close_live_session()
                    raise
                self._client._live_tool_count = len(tool_messages)
                self._client._live_pending_calls = []
        else:
            # Live sessions keep their own context between tool rounds. On a
            # fresh session, replay the thread as user/model turns, with tool
            # results represented as model-visible function responses.
            live_turns = []
            for content in contents:
                turn = content.model_dump(mode="json", exclude_none=True, by_alias=True)
                if turn.get("role") == "tool":
                    turn["role"] = "user"
                live_turns.append(turn)
            if live_turns:
                try:
                    await session.send_client_content(turns=live_turns, turn_complete=True)
                except BaseException:
                    await self._client._close_live_session()
                    raise
            self._client._live_tool_count = len(tool_messages)

        preserve_session = False
        try:
            async for event in session.receive():
                raw = to_wire(event)
                if not isinstance(raw, dict):
                    continue
                server_content = raw.get("server_content") or raw.get("serverContent") or {}
                model_turn = server_content.get("model_turn") or server_content.get("modelTurn") or {}
                parts = list(model_turn.get("parts") or [])
                tool_call = raw.get("tool_call") or raw.get("toolCall") or {}
                functions = tool_call.get("function_calls") or tool_call.get("functionCalls") or []
                live_call_info = []
                for function in functions:
                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    call_id = function.get("id")
                    live_call_info.append({"id": call_id, "name": name})
                    parts.append({
                        "function_call": {
                            "name": name,
                            "args": function.get("args") or {},
                            **({"id": call_id} if call_id else {}),
                        },
                        "thought_signature": THOUGHT_SIGNATURE_FALLBACK,
                    })
                if not parts:
                    transcription = (
                        (server_content.get("output_transcription") or {}).get("text")
                        or (server_content.get("outputTranscription") or {}).get("text")
                    )
                    if transcription:
                        parts.append({"text": transcription})
                if parts:
                    candidate: dict[str, Any] = {
                        "content": {"role": "model", "parts": parts},
                    }
                    if live_call_info:
                        candidate["finishReason"] = "FUNCTION_CALL"
                        self._client._live_pending_calls = live_call_info
                        preserve_session = True
                    yield {"candidates": [candidate]}
                if live_call_info:
                    break
                if server_content.get("turn_complete") or server_content.get("turnComplete"):
                    break
            if not preserve_session:
                await self._client._close_live_session()
        except BaseException:
            await self._client._close_live_session()
            raise


class GeminiChatClient:
    """Expose Google's native async Gen AI SDK through Forge's chat loop."""

    def __init__(
        self,
        api_key: str,
        *,
        sdk_client: Any | None = None,
        media_output_dir: Path | None = None,
    ):
        key = api_key.strip()
        if not key:
            raise ValueError("A Gemini API key is required.")
        self._sdk = sdk_client or genai.Client(api_key=key)
        self._media_output_dir = media_output_dir
        self.chat = SimpleNamespace(completions=_GeminiCompletions(self))
        self._live_context: Any | None = None
        self._live_session: Any | None = None
        self._live_model: str | None = None
        self._live_tool_count = 0
        self._live_pending_calls: list[dict[str, Any]] = []

    async def _get_live_session(self, model: str, config: types.LiveConnectConfig) -> Any:
        if self._live_session is not None and self._live_model == model:
            return self._live_session
        await self._close_live_session()
        self._live_context = self._sdk.aio.live.connect(model=model, config=config)
        try:
            self._live_session = await self._live_context.__aenter__()
        except BaseException:
            await self._close_live_session()
            raise
        self._live_model = model
        return self._live_session

    async def _close_live_session(self) -> None:
        context, self._live_context = self._live_context, None
        self._live_session = None
        self._live_model = None
        self._live_tool_count = 0
        self._live_pending_calls = []
        if context is not None:
            await context.__aexit__(None, None, None)

    def _collect_media_fragments(
        self,
        response: Any,
        collected: dict[str, list[str]],
    ) -> None:
        if not isinstance(response, dict):
            return
        for candidate in response.get("candidates") or []:
            for part in ((candidate.get("content") or {}).get("parts") or []):
                inline = part.get("inline_data") or part.get("inlineData")
                if not isinstance(inline, dict):
                    continue
                data = inline.get("data")
                mime_type = str(inline.get("mime_type") or inline.get("mimeType") or "application/octet-stream")
                if isinstance(data, bytes):
                    collected.setdefault(mime_type, []).append(base64.b64encode(data).decode("ascii"))
                elif isinstance(data, str) and data:
                    collected.setdefault(mime_type, []).append(data)

    def _remove_media_parts(self, response: Any) -> Any:
        if not isinstance(response, dict):
            return response
        cleaned = deepcopy(response)
        for candidate in cleaned.get("candidates") or []:
            content = candidate.get("content") or {}
            content["parts"] = [
                part for part in content.get("parts") or []
                if not isinstance(part, dict)
                or not (part.get("inline_data") or part.get("inlineData"))
            ]
        return cleaned

    def _replace_media_parts(self, response: Any) -> Any:
        fragments: dict[str, list[str]] = {}
        self._collect_media_fragments(response, fragments)
        cleaned = self._remove_media_parts(response)
        links = self._save_media_fragments(fragments)
        if links and isinstance(cleaned, dict) and cleaned.get("candidates"):
            candidate = cleaned["candidates"][0]
            content = candidate.setdefault("content", {})
            content.setdefault("parts", []).append({"text": "\n\n".join(links)})
        return cleaned

    def _save_media_fragments(self, fragments: dict[str, list[str]]) -> list[str]:
        if not self._media_output_dir:
            return []
        self._media_output_dir.mkdir(parents=True, exist_ok=True)
        links: list[str] = []
        for mime_type, encoded_parts in fragments.items():
            try:
                data = base64.b64decode("".join(encoded_parts), validate=False)
            except (ValueError, TypeError):
                continue
            if not data:
                continue
            normalized_mime = mime_type.split(";", 1)[0].strip().lower()
            extension = mimetypes.guess_extension(normalized_mime) or ".bin"
            if extension == ".jpe":
                extension = ".jpg"
            name = f"gemini-{uuid.uuid4().hex}{extension}"
            path = self._media_output_dir / name
            path.write_bytes(data)
            url = f"/workspace-preview/generated-media/{name}"
            if normalized_mime.startswith("image/"):
                links.append(f"![Generated image]({url})")
            elif normalized_mime.startswith("audio/"):
                links.append(f"[Open generated audio]({url})")
            else:
                links.append(f"[Open generated file]({url})")
        return links

    async def close(self) -> None:
        await self._close_live_session()
        aio = getattr(self._sdk, "aio", None)
        close = getattr(aio, "aclose", None)
        if callable(close):
            await close()
