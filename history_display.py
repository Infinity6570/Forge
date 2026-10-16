"""Bound browser display data without changing signed provider history on disk."""
import json
import re

DISPLAY_LIMIT = 10_240


def compact_text(value: str | None, limit: int = DISPLAY_LIMIT) -> str | None:
    if not value or len(value) <= limit:
        return value
    size = len(value.encode("utf-8")) / 1024
    return value[:limit] + f"\n[Display shortened: {size:.1f} KB; full content retained locally]"


def compact_log(log: dict) -> dict:
    text = log.get("message", "")
    if len(text) > DISPLAY_LIMIT and log.get("kind") == "tool":
        path = re.search(r'"(?:path|filename|file_path)"\s*:\s*"([^"]{1,240})"', text[:4096])
        filename = path.group(1) if path else "tool output"
        text = f"[File/tool payload: {filename} ({len(text.encode('utf-8')) / 1024:.1f} KB) — omitted from display; full log retained locally]"
    return {**log, "message": compact_text(text, 2000)}


def display_task(row, serialize_task, *, summary=False, log_limit=50):
    # Avoid parsing megabyte log arrays for sidebar/dashboard polling.
    values = dict(row)
    raw_logs = values.pop("logs_json", "[]")
    values["logs_json"] = "[]"
    result = serialize_task(values)
    if not summary:
        logs = json.loads(raw_logs or "[]")
        result["logs"] = [compact_log(log) for log in logs[-log_limit:] if isinstance(log, dict)]
    elif result.get("currentStep"):
        result["logs"] = [{"id": result["id"] + "-status", "kind": "info",
                           "message": compact_text(result["currentStep"], 500), "createdAt": result["updatedAt"]}]
    result["result"] = compact_text(result.get("result"), 2000 if summary else 65_536)
    result["objective"] = compact_text(result.get("objective"), 12_000)
    return result
