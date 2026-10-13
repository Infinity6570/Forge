"""Anthropic Messages API adapter for Forge's OpenAI-shaped agent loop."""
from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from typing import Any

import anthropic
from openai.types.chat import ChatCompletion


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, list):
        return "".join(
            _get(part, "text", "")
            for part in value
            if _get(part, "type") == "text" and isinstance(_get(part, "text"), str)
        )
    return json.dumps(value, ensure_ascii=False)


def _parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"_raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    def append_user_block(block: dict[str, Any]) -> None:
        if converted and converted[-1]["role"] == "user":
            current = converted[-1]["content"]
            if not isinstance(current, list):
                converted[-1]["content"] = [{"type": "text", "text": _text(current)}]
            converted[-1]["content"].append(block)
        else:
            converted.append({"role": "user", "content": [block]})

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            if content:
                system_parts.append(_text(content))
            continue
        if role == "tool":
            append_user_block({
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": _text(content),
            })
            continue
        if role == "user":
            text = _text(content)
            if converted and converted[-1]["role"] == "user":
                existing = converted[-1]["content"]
                if isinstance(existing, list):
                    existing.append({"type": "text", "text": text})
                else:
                    converted[-1]["content"] = f"{existing}\n{text}"
            else:
                converted.append({"role": "user", "content": text})
            continue
        if role != "assistant":
            continue

        blocks: list[dict[str, Any]] = []
        text = _text(content)
        if text:
            blocks.append({"type": "text", "text": text})
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            blocks.append({
                "type": "tool_use",
                "id": str(tool_call.get("id") or f"toolu_{uuid.uuid4().hex}"),
                "name": name,
                "input": _parse_tool_arguments(function.get("arguments")),
            })
        if blocks:
            converted.append({"role": "assistant", "content": blocks})

    # Anthropic requires each turn to begin with a user message.
    if converted and converted[0]["role"] == "assistant":
        converted.insert(0, {"role": "user", "content": "Continue from the prior conversation."})
    return "\n\n".join(part for part in system_parts if part), converted


def _anthropic_tools(tools: Any) -> list[dict[str, Any]]:
    converted = []
    for tool in tools or []:
        function = tool.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        converted.append({
            "name": name,
            "description": function.get("description") or "",
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return converted


def _anthropic_request(kwargs: dict[str, Any]) -> dict[str, Any]:
    system, messages = _anthropic_messages(kwargs.get("messages") or [])
    request: dict[str, Any] = {
        "model": kwargs["model"],
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 4096,
    }
    if system:
        request["system"] = system
    tools = _anthropic_tools(kwargs.get("tools"))
    if tools:
        request["tools"] = tools
        choice = kwargs.get("tool_choice")
        if choice == "required":
            request["tool_choice"] = {"type": "any"}
        elif isinstance(choice, dict):
            function = choice.get("function") or {}
            if function.get("name"):
                request["tool_choice"] = {"type": "tool", "name": function["name"]}
            elif choice.get("type") == "none":
                request.pop("tools", None)
        elif choice not in (None, "auto"):
            request["tool_choice"] = {"type": "auto"}
    for key in ("temperature", "top_p", "stop"):
        if key in kwargs and kwargs[key] is not None:
            request[{"stop": "stop_sequences"}.get(key, key)] = kwargs[key]
    return request


def _chat_completion(response: Any) -> ChatCompletion:
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in _get(response, "content", []) or []:
        block_type = _get(block, "type")
        if block_type == "text":
            value = _get(block, "text")
            if isinstance(value, str):
                content_parts.append(value)
        elif block_type == "tool_use":
            tool_calls.append({
                "id": _get(block, "id") or f"toolu_{uuid.uuid4().hex}",
                "type": "function",
                "function": {
                    "name": _get(block, "name") or "",
                    "arguments": json.dumps(_get(block, "input") or {}, ensure_ascii=False),
                },
            })
    stop_reason = _get(response, "stop_reason")
    return ChatCompletion(
        id=_get(response, "id") or f"chatcmpl_{uuid.uuid4().hex}",
        choices=[{
            "finish_reason": "tool_calls" if stop_reason == "tool_use" else "stop",
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            },
        }],
        created=int(time.time()),
        model=_get(response, "model") or "",
        object="chat.completion",
    )


class _AnthropicCompletions:
    def __init__(self, client: "AnthropicChatClient"):
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return self._stream(kwargs)
        return self._complete(kwargs)

    async def _complete(self, kwargs: dict[str, Any]) -> ChatCompletion:
        response = await self._client._sdk.messages.create(**_anthropic_request(kwargs))
        return _chat_completion(response)

    async def _stream(self, kwargs: dict[str, Any]):
        request = _anthropic_request(kwargs)
        stream_id = f"chatcmpl_{uuid.uuid4().hex}"
        created = int(time.time())
        async with self._client._sdk.messages.stream(**request) as stream:
            async for event in stream:
                event_type = _get(event, "type")
                choices: list[dict[str, Any]] = []
                if event_type == "content_block_start":
                    block = _get(event, "content_block")
                    if _get(block, "type") == "tool_use":
                        input_value = _get(block, "input") or {}
                        initial_arguments = (
                            json.dumps(input_value, ensure_ascii=False) if input_value else ""
                        )
                        choices.append({
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": _get(event, "index", 0),
                                    "id": _get(block, "id"),
                                    "type": "function",
                                    "function": {
                                        "name": _get(block, "name", ""),
                                        "arguments": initial_arguments,
                                    },
                                }],
                            },
                            "finish_reason": None,
                        })
                elif event_type == "content_block_delta":
                    delta = _get(event, "delta")
                    delta_type = _get(delta, "type")
                    if delta_type == "text_delta":
                        choices.append({
                            "index": 0,
                            "delta": {"content": _get(delta, "text", "")},
                            "finish_reason": None,
                        })
                    elif delta_type == "input_json_delta":
                        choices.append({
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": _get(event, "index", 0),
                                    "function": {"arguments": _get(delta, "partial_json", "")},
                                }],
                            },
                            "finish_reason": None,
                        })
                    elif delta_type in {"thinking_delta", "signature_delta"}:
                        reasoning = _get(delta, "thinking") or _get(delta, "signature")
                        if reasoning:
                            choices.append({
                                "index": 0,
                                "delta": {"reasoning_content": reasoning},
                                "finish_reason": None,
                            })
                elif event_type == "message_delta":
                    delta = _get(event, "delta")
                    stop_reason = _get(delta, "stop_reason")
                    choices.append({
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls" if stop_reason == "tool_use" else "stop",
                    })
                for choice in choices:
                    yield {
                        "id": stream_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": request["model"],
                        "choices": [choice],
                    }


class AnthropicChatClient:
    """Expose Anthropic's official async Messages API through the agent loop interface."""

    def __init__(self, api_key: str, *, sdk_client: Any | None = None):
        resolved_key = api_key.strip()
        if not resolved_key:
            raise ValueError("An Anthropic API key is required.")
        self._sdk = sdk_client or anthropic.AsyncAnthropic(
            api_key=resolved_key,
            timeout=90,
            max_retries=2,
        )
        self.chat = SimpleNamespace(completions=_AnthropicCompletions(self))

    async def close(self) -> None:
        await self._sdk.close()
