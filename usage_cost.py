"""Estimated USD cost for Anthropic Messages API usage.

Rates are USD per million tokens, from claude.com/pricing as checked on the
pricing page. Only models with confirmed rates are priced; anything else is
reported as unknown instead of guessed.
"""

from __future__ import annotations

from typing import Any

# model id -> (input, output, cache_write, cache_read) USD per million tokens
ANTHROPIC_RATES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def anthropic_usage_summary(model: str, usage: dict[str, Any]) -> str:
    """Return one log line with token counts and an estimated cost."""
    input_tokens = _int(usage.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))
    cache_read = _int(usage.get("cache_read_input_tokens"))
    cache_created = _int(usage.get("cache_creation_input_tokens"))

    rates = ANTHROPIC_RATES.get((model or "").strip().lower())
    if rates:
        in_rate, out_rate, write_rate, read_rate = rates
        cost = (
            input_tokens * in_rate
            + output_tokens * out_rate
            + cache_created * write_rate
            + cache_read * read_rate
        ) / 1_000_000
        cost_text = f"${cost:.4f}"
    else:
        cost_text = "unknown (no rate configured)"

    return (
        "Anthropic usage · "
        f"input_tokens={input_tokens} · "
        f"output_tokens={output_tokens} · "
        f"cache_read_input_tokens={cache_read} · "
        f"cache_creation_input_tokens={cache_created} · "
        f"est_cost_usd={cost_text}"
    )
