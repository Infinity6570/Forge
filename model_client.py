"""Anthropic Messages API adapter for Forge's OpenAI-shaped agent loop."""
from __future__ import annotations

import json
import re
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import anthropic
from openai.types.chat import ChatCompletion

from llm_protocol import to_wire

THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
ANTHROPIC_CACHE_TTL = "5m"  # Anthropic's wire value for the requested 300-second TTL.


def _anthropic_cache_control() -> dict[str, str]:
    return {"type": "ephemeral", "ttl": ANTHROPIC_CACHE_TTL}
THINKING_BLOCK_TYPES = {"thinking", "redacted_thinking"}


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

        preserved_blocks = message.get("anthropic_content_blocks")
        if isinstance(preserved_blocks, list) and preserved_blocks:
            # Anthropic requires the exact signed thinking block when continuing
            # a tool-use turn. Do not rebuild or normalize provider blocks.
            converted.append({
                "role": "assistant",
                "content": [to_wire(block) for block in preserved_blocks],
            })
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
    model = kwargs["model"]
    requested_max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 4096
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max(16384, int(requested_max_tokens)),
        "cache_control": _anthropic_cache_control(),
        "extra_headers": {"anthropic-beta": THINKING_BINDING_BETA},
    }
    if system:
        request["system"] = [{
            "type": "text",
            "text": system,
            "cache_control": _anthropic_cache_control(),
        }]
    tools = _anthropic_tools(kwargs.get("tools"))
    if tools:
        tools[-1]["cache_control"] = _anthropic_cache_control()
        request["tools"] = tools
        choice = kwargs.get("tool_choice")
        if choice == "required":
            request["tool_choice"] = {"type": "any"}
        elif isinstance(choice, dict):
            function = choice.get("function") or {}
            if function.get("name"):
                request["tool_choice"] = {"type": "tool", "name": function["name"]}
            # Keep tool schemas on every turn. A "none" preference must not
            # silently remove them from the protocol request.
        elif choice not in (None, "auto"):
            request["tool_choice"] = {"type": "auto"}

    version = re.search(r"claude-(?:opus|sonnet|haiku)-(\d+)[.-](\d+)", model.lower())
    thinking: dict[str, Any] | None = None
    if version:
        major, minor = int(version.group(1)), int(version.group(2))
        if major >= 5 or (major == 4 and minor >= 7):
            # Adaptive thinking is the supported mode for Claude 4.7+ and 5.x.
            thinking = {"type": "adaptive"}
            thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
            if major >= 5:
                # This is a provider-authored summary, not raw chain-of-thought.
                thinking["display"] = "summarized"
        elif major == 4 and minor >= 5:
            # Earlier Claude 4 models use a stable manual budget.
            thinking = {"type": "enabled", "budget_tokens": 4096}
    if thinking:
        request["thinking"] = thinking

    # Temperature/top_p are incompatible with extended/adaptive thinking.
    optional_parameters = ("stop",) if thinking else ("temperature", "top_p", "stop")
    for key in optional_parameters:
        if key in kwargs and kwargs[key] is not None:
            request[{"stop": "stop_sequences"}.get(key, key)] = kwargs[key]
    return request


def _chat_completion(response: Any, *, show_thinking_summary: bool = False) -> ChatCompletion:
    raw_response = to_wire(response)
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
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) or None,
        **({"tool_calls": tool_calls} if tool_calls else {}),
    }
    raw_content = raw_response.get("content") if isinstance(raw_response, dict) else None
    if isinstance(raw_content, list):
        message["anthropic_content_blocks"] = raw_content
    raw_usage = raw_response.get("usage") if isinstance(raw_response, dict) else None
    if isinstance(raw_usage, dict):
        message["anthropic_usage"] = raw_usage
    if show_thinking_summary:
        message["anthropic_thinking_summary"] = True
    return ChatCompletion(
        id=_get(response, "id") or f"chatcmpl_{uuid.uuid4().hex}",
        choices=[{
            "finish_reason": "tool_calls" if stop_reason == "tool_use" else "stop",
            "index": 0,
            "message": message,
        }],
        created=int(time.time()),
        model=_get(response, "model") or "",
        object="chat.completion",
    )


def _is_invalid_thinking_signature(error: Exception) -> bool:
    if getattr(error, "status_code", None) != 400:
        return False
    normalized = re.sub(r"[`'\".]", "", str(error).lower())
    return "invalid signature in thinking block" in normalized


def _without_historical_thinking(request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Strip thought blocks from an isolated retry copy; never mutate saved turns."""
    retry_request = deepcopy(request)
    clean_messages: list[dict[str, Any]] = []
    removed = False
    for message in retry_request.get("messages") or []:
        content = message.get("content")
        if not isinstance(content, list):
            clean_messages.append(message)
            continue
        filtered = [
            block for block in content
            if not (
                isinstance(block, dict)
                and block.get("type") in THINKING_BLOCK_TYPES
            )
        ]
        if len(filtered) != len(content):
            removed = True
        if filtered or message.get("role") != "assistant":
            message["content"] = filtered
            clean_messages.append(message)
        elif not filtered:
            removed = True
    retry_request["messages"] = clean_messages
    return retry_request, removed


class _AnthropicCompletions:
    def __init__(self, client: "AnthropicChatClient"):
        self._client = client

    async def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return self._stream(kwargs)
        return await self._complete(kwargs)

    async def _complete(self, kwargs: dict[str, Any]) -> ChatCompletion:
        request = _anthropic_request(kwargs)
        try:
            response = await self._client._sdk.messages.create(**request)
        except Exception as error:
            if not _is_invalid_thinking_signature(error):
                raise
            retry_request, stripped = _without_historical_thinking(request)
            if not stripped:
                raise
            response = await self._client._sdk.messages.create(**retry_request)
        show_summary = (request.get("thinking") or {}).get("display") == "summarized"
        return _chat_completion(response, show_thinking_summary=show_summary)

    async def _stream(self, kwargs: dict[str, Any]):
        request = _anthropic_request(kwargs)
        emitted = False
        try:
            async for chunk in self._stream_request(request):
                emitted = True
                yield chunk
        except Exception as error:
            # Do not replay a stream after text/tool deltas have escaped.
            if emitted or not _is_invalid_thinking_signature(error):
                raise
            retry_request, stripped = _without_historical_thinking(request)
            if not stripped:
                raise
            async for chunk in self._stream_request(retry_request):
                yield chunk

    async def _stream_request(self, request: dict[str, Any]):
        stream_id = f"chatcmpl_{uuid.uuid4().hex}"
        created = int(time.time())
        final_message: dict[str, Any] | None = None
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
            get_final_message = getattr(stream, "get_final_message", None)
            if callable(get_final_message):
                final = get_final_message()
                if hasattr(final, "__await__"):
                    final = await final
                serialized = to_wire(final)
                if isinstance(serialized, dict):
                    final_message = serialized

        if final_message:
            metadata: dict[str, Any] = {}
            blocks = final_message.get("content")
            usage = final_message.get("usage")
            if isinstance(blocks, list):
                metadata["anthropic_content_blocks"] = blocks
            if isinstance(usage, dict):
                metadata["anthropic_usage"] = usage
            if (request.get("thinking") or {}).get("display") == "summarized":
                metadata["anthropic_thinking_summary"] = True
            if metadata:
                yield {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request["model"],
                    "choices": [{"index": 0, "delta": metadata, "finish_reason": None}],
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
