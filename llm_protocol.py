"""Lossless OpenAI-compatible turns, including opaque Google thought metadata.

Provider signatures belong to conversation history, never to visible activity logs.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Awaitable, Callable

from openai.types.chat import ChatCompletion

TextCallback = Callable[[str | None], Awaitable[None]]
MISSING_SIGNATURE = "skip_thought_signature_validator"


def to_wire(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {key: to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: to_wire(item) for key, item in vars(value).items() if not key.startswith("_")}
    return deepcopy(value)


def _complete_native_parts(value: Any) -> None:
    if isinstance(value, dict):
        if "functionCall" in value or "function_call" in value:
            if not value.get("thought_signature") and not value.get("thoughtSignature"):
                field = "thoughtSignature" if "functionCall" in value else "thought_signature"
                value[field] = MISSING_SIGNATURE
            return  # Never modify the function's arguments.
        for part in value.values():
            _complete_native_parts(part)
    elif isinstance(value, list):
        for part in value:
            _complete_native_parts(part)


def assistant_turn(message: Any, provider: str = "") -> dict[str, Any]:
    """Replay the SDK message, not a projection of just name/arguments/id.

    This retains extra_content.google.thought_signature and native part metadata,
    including camelCase signatures, verbatim. Matching tool_call_id responses are
    translated into Google's functionResponse parts by its compatible endpoint.
    """
    turn = to_wire(message)
    if not isinstance(turn, dict):
        raise TypeError("The provider returned an invalid assistant message.")
    turn.setdefault("role", "assistant")
    turn.setdefault("content", None)
    if provider == "gemini":
        for call in turn.get("tool_calls") or []:
            if call.get("type", "function") != "function":
                continue
            if call.get("extra_content") is None:
                call["extra_content"] = {}
            if call["extra_content"].get("google") is None:
                call["extra_content"]["google"] = {}
            metadata = call["extra_content"]["google"]
            if not metadata.get("thought_signature"):
                metadata["thought_signature"] = (
                    metadata.get("thoughtSignature") or call.get("thought_signature")
                    or call.get("thoughtSignature") or MISSING_SIGNATURE
                )
        _complete_native_parts(turn)
    return turn


def prepare_history(messages: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Repair old/unsigned Google traces on replay without changing valid parts."""
    prepared = [
        assistant_turn(message, provider)
        if provider == "gemini" and message.get("role") in {"assistant", "model"}
        else to_wire(message)
        for message in messages
    ]
    # Native candidate parts are retained in stored history for lossless replay
    # and diagnostics, but the current Gemini client uses the OpenAI-compatible
    # endpoint, whose wire format is tool_calls + extra_content.google.
    if provider == "gemini":
        for message in prepared:
            message.pop("parts", None)
            # Thought text is retained with the stored turn for internal
            # diagnostics, but it is neither user-facing content nor part of
            # the OpenAI-compatible Gemini request history.
            message.pop("reasoning_content", None)
    # Raw stored turns stay lossless. Other providers do not accept Google's
    # opaque message extensions, so normalize only their outgoing wire copy.
    if provider in {"openai", "deepseek", "ollama"}:
        allowed = {"role", "content", "name", "tool_calls", "tool_call_id", "function_call", "refusal", "audio"}
        if provider == "deepseek":
            allowed.add("reasoning_content")
        for index, message in enumerate(prepared):
            prepared[index] = {key: value for key, value in message.items() if key in allowed}
            if message.get("tool_calls"):
                prepared[index]["tool_calls"] = [
                    {key: value for key, value in call.items() if key in {"id", "type", "function"}}
                    for call in message["tool_calls"]
                ]
    return prepared


def _merge_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_metadata(target[key], value)
        else:
            target[key] = deepcopy(value)


async def collect_completion(response: Any, on_text: TextCallback | None = None) -> Any:
    """Accumulate streaming deltas without discarding provider extensions.

    Only ordinary user-facing content is sent to on_text. Reasoning fields and
    signatures are retained for protocol replay but are never rendered in the UI.
    """
    if not hasattr(response, "__aiter__"):
        raw_response = to_wire(response)
        if not isinstance(raw_response, dict) or not raw_response.get("candidates") or raw_response.get("choices"):
            if on_text:
                choices = raw_response.get("choices", []) if isinstance(raw_response, dict) else []
                if choices:
                    content = (choices[0].get("message") or {}).get("content")
                    await on_text(content if isinstance(content, str) else None)
            return response

        async def single_native_response():
            yield raw_response

        response = single_native_response()
    message: dict[str, Any] = {"role": "assistant"}
    calls: dict[int, dict[str, Any]] = {}
    response_id, model, created = "", "", 0
    finish_reason = None
    seen_choice = False
    last_text: str | None = None
    native_parts: list[dict[str, Any]] = []
    try:
        async for chunk in response:
            raw = to_wire(chunk)
            response_id = raw.get("id", response_id)
            model = raw.get("model", model)
            created = raw.get("created", created)
            choices = raw.get("choices", [])
            candidates = raw.get("candidates", [])
            if not choices and candidates:
                candidate = candidates[0]
                seen_choice = True
                content = candidate.get("content") or {}
                for part_index, part in enumerate(content.get("parts") or []):
                    native_parts.append(deepcopy(part))
                    text = part.get("text")
                    is_thought = bool(
                        part.get("thought")
                        or part.get("reasoning")
                        or part.get("isThought")
                    )
                    if isinstance(text, str):
                        if is_thought:
                            message["reasoning_content"] = (
                                message.get("reasoning_content", "") + text
                            )
                        else:
                            message["content"] = message.get("content", "") + text
                    function_call = part.get("functionCall") or part.get("function_call")
                    if isinstance(function_call, dict):
                        call = calls.setdefault(part_index, {})
                        call.setdefault("id", f"gemini_call_{part_index}")
                        call["type"] = "function"
                        function = call.setdefault("function", {})
                        function["name"] = function_call.get("name", "")
                        arguments = function_call.get("args", function_call.get("arguments", {}))
                        function["arguments"] = (
                            arguments if isinstance(arguments, str)
                            else json.dumps(arguments, ensure_ascii=False)
                        )
                        signature = part.get("thoughtSignature") or part.get("thought_signature")
                        if signature:
                            call.setdefault("extra_content", {}).setdefault("google", {})[
                                "thought_signature"
                            ] = signature
                reason = candidate.get("finishReason") or candidate.get("finish_reason")
                if reason:
                    finish_reason = (
                        "tool_calls" if reason in {"FUNCTION_CALL", "MALFORMED_FUNCTION_CALL"}
                        else "length" if reason == "MAX_TOKENS"
                        else "stop"
                    )
                visible_text = None if calls else message.get("content")
                if on_text and visible_text != last_text:
                    await on_text(visible_text)
                    last_text = visible_text
                continue
            for choice in choices:
                if choice.get("index", 0) != 0:
                    continue
                seen_choice = True
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta", {})
                for key, value in delta.items():
                    if value is None:
                        continue
                    if key == "tool_calls":
                        for part in value:
                            index = part.get("index", 0)
                            call = calls.setdefault(index, {})
                            for field, item in part.items():
                                if field == "index":
                                    continue
                                if field == "function":
                                    function = call.setdefault("function", {})
                                    for name, fragment in item.items():
                                        if name in {"arguments", "name"} and isinstance(fragment, str):
                                            function[name] = function.get(name, "") + fragment
                                        else:
                                            function[name] = deepcopy(fragment)
                                elif isinstance(item, dict):
                                    _merge_metadata(call.setdefault(field, {}), item)
                                else:
                                    call[field] = deepcopy(item)
                    elif key in {"content", "reasoning_content"} and isinstance(value, str):
                        message[key] = message.get(key, "") + value
                    elif isinstance(value, dict):
                        _merge_metadata(message.setdefault(key, {}), value)
                    else:
                        message[key] = deepcopy(value)
                # Text emitted before a function-call delta isn't a final answer.
                visible_text = None if calls else message.get("content")
                if on_text and visible_text != last_text:
                    await on_text(visible_text)
                    last_text = visible_text
    finally:
        if hasattr(response, "close"):
            await response.close()
    if not seen_choice:
        raise ValueError("The provider returned an empty completion stream.")
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
    if native_parts:
        message["parts"] = native_parts
    message.setdefault("content", None)
    return ChatCompletion.model_validate({
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason or ("tool_calls" if calls else "stop"),
            "message": message,
        }],
    })
