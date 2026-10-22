"""Bound browser display data without changing signed provider history on disk."""
import json
import re

DISPLAY_LIMIT = 10_240
# Provider thinking summaries are the user's record of how the agent reasoned. They are
# never dropped from the display window and are shown (almost) in full.
PROVIDER_SUMMARY_PREFIX = "Claude thinking summary:\n"
PROVIDER_SUMMARY_DISPLAY_LIMIT = 30_000
MAX_DISPLAYED_SUMMARIES = 500
MAX_STORED_LOGS = 300
MAX_STORED_SUMMARIES = 1_000


def is_provider_summary(log: object) -> bool:
    return (
        isinstance(log, dict)
        and log.get("kind") == "agent"
        and isinstance(log.get("message"), str)
        and log["message"].startswith(PROVIDER_SUMMARY_PREFIX)
    )


def retain_logs(logs: list, limit: int = MAX_STORED_LOGS, summary_limit: int = MAX_STORED_SUMMARIES) -> list:
    """Trim stored logs by dropping the oldest ordinary entries first.

    Provider thinking summaries do not count against ``limit``; only the oldest ones beyond
    ``summary_limit`` (far above the tool-round cap) could ever be removed.
    """
    summary_positions = [i for i, log in enumerate(logs) if is_provider_summary(log)]
    ordinary_positions = [i for i, log in enumerate(logs) if not is_provider_summary(log)]
    if len(ordinary_positions) <= limit and len(summary_positions) <= summary_limit:
        return logs
    keep = set(ordinary_positions[-limit:] if limit > 0 else [])
    keep.update(summary_positions[-summary_limit:] if summary_limit > 0 else [])
    return [log for i, log in enumerate(logs) if i in keep]


def select_display_logs(logs: list, log_limit: int) -> list:
    """Latest ``log_limit`` entries plus every provider summary, in original order."""
    dict_logs = [log for log in logs if isinstance(log, dict)]
    recent_start = max(0, len(dict_logs) - log_limit)
    summary_positions = [i for i, log in enumerate(dict_logs) if is_provider_summary(log)]
    keep = set(range(recent_start, len(dict_logs)))
    keep.update(summary_positions[-MAX_DISPLAYED_SUMMARIES:])
    return [log for i, log in enumerate(dict_logs) if i in keep]


def compact_text(value: str | None, limit: int = DISPLAY_LIMIT) -> str | None:
    if not value or len(value) <= limit:
        return value
    size = len(value.encode("utf-8")) / 1024
    return value[:limit] + f"\n[Display shortened: {size:.1f} KB; full content retained locally]"


def compact_log(log: dict) -> dict:
    text = log.get("message", "")
    if is_provider_summary(log):
        return {**log, "message": compact_text(text, PROVIDER_SUMMARY_DISPLAY_LIMIT)}
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
        result["logs"] = [compact_log(log) for log in select_display_logs(logs, log_limit)]
    elif result.get("currentStep"):
        result["logs"] = [{"id": result["id"] + "-status", "kind": "info",
                           "message": compact_text(result["currentStep"], 500), "createdAt": result["updatedAt"]}]
    result["result"] = compact_text(result.get("result"), 2000 if summary else 65_536)
    result["objective"] = compact_text(result.get("objective"), 12_000)
    return result
