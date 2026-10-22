"""Bound how much tool output re-enters the model context.

Two deterministic, cheap controls:
1. ``cap_tool_output`` shortens a single oversized result. The replacement stays
   valid JSON and states that it was truncated and how much was dropped.
2. ``elide_stale_tool_results`` replaces older tool results with a short stub
   before each model call. The conversation stored in the database is never changed;
   only the copy sent to the provider is trimmed.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_TOOL_OUTPUT_CHARS = 12_000
DEFAULT_KEEP_RECENT_TOOL_RESULTS = 4
ELISION_THRESHOLD_CHARS = 400
# Literature results are never truncated or elided: full abstracts are the evidence.
PRESERVED_TOOLS = frozenset({"academic_search", "pubmed_search"})
PRESERVED_ENGINES = frozenset({"academic-search", "pubmed-search"})


def _is_preserved_content(content: str) -> bool:
    if not content.lstrip().startswith("{"):
        return False
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("engine") in PRESERVED_ENGINES


def cap_tool_output(output: str, *, limit: int = DEFAULT_TOOL_OUTPUT_CHARS, tool_name: str = "") -> str:
    """Return ``output`` unchanged if small; otherwise a valid JSON preview with head and tail."""
    if not isinstance(output, str) or limit < 200 or len(output) <= limit:
        return output
    if tool_name in PRESERVED_TOOLS:
        return output
    head_size = (limit * 2) // 3
    tail_size = limit - head_size
    head = output[:head_size]
    tail = output[-tail_size:]
    payload = {
        "truncated": True,
        "tool": tool_name,
        "originalChars": len(output),
        "returnedChars": len(head) + len(tail),
        "head": head,
        "tail": tail,
        "note": (
            "Output was truncated to protect the context budget. Request a narrower range "
            "(a line offset, a search term, or a smaller file) if more is needed."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def elide_stale_tool_results(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = DEFAULT_KEEP_RECENT_TOOL_RESULTS,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with older large tool results replaced by stubs.

    The most recent ``keep_recent`` tool results are kept verbatim. The input list
    and its dictionaries are not modified.
    """
    tool_indexes = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "tool"]
    stale = set(tool_indexes[: max(0, len(tool_indexes) - max(0, keep_recent))])
    if not stale:
        return list(messages)
    result: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        content = message.get("content") if isinstance(message, dict) else None
        if (
            index in stale
            and isinstance(content, str)
            and len(content) > ELISION_THRESHOLD_CHARS
            and not _is_preserved_content(content)
        ):
            stub = json.dumps(
                {
                    "elided": True,
                    "originalChars": len(content),
                    "note": (
                        "An older tool result was removed from context to save tokens. "
                        "Re-run the tool if its content is still needed."
                    ),
                },
                ensure_ascii=False,
            )
            result.append({**message, "content": stub})
        else:
            result.append(message)
    return result
