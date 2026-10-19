"""Published provider token rates and a cross-provider usage-cost ledger.

Rates are USD per million tokens from the providers' public API pricing pages
checked on 2026-10-19. Costs are calculated from reported token counts and
published rates; they are not a provider invoice and exclude account credits,
free-tier allowances, taxes, request-based tool fees, and Gemini cache storage.
Unknown model IDs are deliberately left unpriced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PRICING_UPDATED_AT = "2026-10-19"

PRICING_SOURCES = {
    "anthropic": "https://www.anthropic.com/pricing",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing/",
    "openai": "https://developers.openai.com/api/docs/pricing",
    "ollama": "https://ollama.com/",
}


@dataclass(frozen=True)
class TokenRates:
    input: float
    output: float
    cache_write: float
    cache_read: float


# USD per million tokens. Cache-write rates equal normal input rates for
# providers whose public price tables do not charge a separate write premium.
RATE_TABLE: dict[str, dict[str, TokenRates]] = {
    "anthropic": {
        "claude-opus-5-5": TokenRates(4.00, 20.00, 5.00, 0.20),
        "claude-sonnet-5-5": TokenRates(2.00, 10.00, 2.50, 0.10),
        "claude-haiku-5-5": TokenRates(0.10, 0.50, 0.125, 0.01),
    },
    "gemini": {
        "gemini-3.1-pro-preview": TokenRates(2.00, 12.00, 2.00, 0.20),
        "gemini-3.8-flash": TokenRates(0.75, 3.75, 0.75, 0.075),
        "gemini-3.5-flash-lite": TokenRates(0.30, 2.50, 0.30, 0.03),
        "gemini-2.5-flash-lite": TokenRates(0.10, 0.40, 0.10, 0.01),
        # Sourced from BenchLM's pricing table (price checked 2026-10-19).
        "gemini-3.6-flash": TokenRates(0.75, 3.75, 0.75, 0.07),
        "gemini-3.1-flash-lite": TokenRates(0.25, 1.50, 0.25, 0.03),
        "gemini-3-flash-preview": TokenRates(0.50, 3.00, 0.50, 0.05),
        "gemini-4-argon": TokenRates(2.00, 10.00, 2.00, 0.10),
    },
    # These legacy model IDs use their published V3/R1 API rates. DeepSeek's
    # newer V4 IDs have different rates and should be added as separate IDs.
    "deepseek": {
        "deepseek-chat": TokenRates(0.27, 1.10, 0.27, 0.07),
        "deepseek-reasoner": TokenRates(0.55, 2.19, 0.55, 0.14),
    },
    "openai": {
        "gpt-4o": TokenRates(2.50, 10.00, 2.50, 1.25),
        "gpt-4o-mini": TokenRates(0.15, 0.60, 0.15, 0.075),
        "o3-mini": TokenRates(1.10, 4.40, 1.10, 0.55),
    },
    # Local inference has no hosted token charge. Hardware, electricity, and
    # any separately hosted Ollama endpoint are outside this estimate.
    "ollama": {
        "qwen2.5-coder": TokenRates(0.0, 0.0, 0.0, 0.0),
        "llama3.3": TokenRates(0.0, 0.0, 0.0, 0.0),
        "deepseek-r1": TokenRates(0.0, 0.0, 0.0, 0.0),
    },
}

_LONG_CONTEXT_RATES: dict[tuple[str, str], tuple[int, TokenRates]] = {
    ("anthropic", "claude-haiku-5-5"): (
        100_000,
        TokenRates(0.50, 2.50, 0.625, 0.05),
    ),
    ("gemini", "gemini-3.1-pro-preview"): (
        200_000,
        TokenRates(4.00, 18.00, 4.00, 0.40),
    ),
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump(exclude_none=True)
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}
    return {}


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _first_int(source: dict[str, Any], *names: str) -> int:
    for name in names:
        value = source.get(name)
        if value is not None:
            return _int(value)
    return 0


def _reported_usage(usage: Any) -> dict[str, Any]:
    normalized = _mapping(usage)
    # OpenAI-compatible SDKs return Pydantic usage objects; some provider
    # adapters attach their native meter in a nested field.
    for key in ("usage", "usage_metadata", "usageMetadata", "provider_usage"):
        nested = _mapping(normalized.get(key))
        if nested:
            normalized = {**normalized, **nested}
    return normalized


def _token_counts(provider: str, usage: Any) -> dict[str, int]:
    raw = _reported_usage(usage)
    prompt_details = _mapping(raw.get("prompt_tokens_details") or raw.get("input_tokens_details"))
    input_tokens = _first_int(
        raw,
        "input_tokens",
        "prompt_tokens",
        "promptTokenCount",
        "inputTokenCount",
    )
    output_tokens = _first_int(
        raw,
        "output_tokens",
        "completion_tokens",
        "candidatesTokenCount",
        "outputTokenCount",
    )
    cache_read = _first_int(
        raw,
        "cache_read_input_tokens",
        "cached_tokens",
        "prompt_cache_hit_tokens",
        "cachedContentTokenCount",
        "cached_content_token_count",
        "total_cached_tokens",
        "totalCachedTokens",
    )
    if not cache_read:
        cache_read = _first_int(
            prompt_details,
            "cached_tokens",
            "cachedTokens",
            "cache_read_input_tokens",
        )
    cache_write = _first_int(
        raw,
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
        "cache_write_tokens",
        "cacheCreationTokenCount",
    )
    if provider == "gemini":
        # Gemini exposes thought tokens separately on some response types.
        # They are billable output, so include them if the candidate count
        # omitted them; totalTokenCount is a provider-reported cross-check.
        thoughts = _first_int(raw, "thoughtsTokenCount", "thoughts_token_count")
        total_tokens = _first_int(raw, "totalTokenCount", "total_tokens")
        if thoughts:
            output_tokens = max(output_tokens, output_tokens + thoughts)
        if total_tokens and input_tokens and not output_tokens:
            output_tokens = max(0, total_tokens - input_tokens)
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheWriteTokens": cache_write,
        "cacheReadTokens": cache_read,
    }


def _rates_for(provider: str, model: str, input_tokens: int) -> TokenRates | None:
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model or "").strip().lower()
    rates = RATE_TABLE.get(normalized_provider, {}).get(normalized_model)
    long_context = _LONG_CONTEXT_RATES.get((normalized_provider, normalized_model))
    if long_context and input_tokens > long_context[0]:
        return long_context[1]
    return rates


def calculate_usage_cost(provider: str, model: str, usage: dict[str, Any]) -> dict[str, Any]:
    """Return normalized token counts, published-rate USD cost, and a summary.

    Anthropic reports uncached input separately from its cache read/write
    counters. OpenAI-compatible and Gemini usage usually report cached input as
    a subset of prompt/input tokens, so that subset is removed before applying
    the normal input rate.
    """
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model or "").strip().lower()
    counts = _token_counts(normalized_provider, usage)
    rates = _rates_for(normalized_provider, normalized_model, counts["inputTokens"])
    if normalized_provider == "anthropic":
        regular_input = counts["inputTokens"]
    else:
        regular_input = max(
            0,
            counts["inputTokens"] - counts["cacheWriteTokens"] - counts["cacheReadTokens"],
        )

    cost: float | None = None
    if rates is not None:
        cost = (
            regular_input * rates.input
            + counts["outputTokens"] * rates.output
            + counts["cacheWriteTokens"] * rates.cache_write
            + counts["cacheReadTokens"] * rates.cache_read
        ) / 1_000_000

    formatted_cost = (
        "unknown (no published rate configured)"
        if cost is None
        else f"${cost:.6f}"
    )
    model_label = normalized_model or "unknown model"
    provider_label = normalized_provider or "unknown provider"
    summary = (
        f"{provider_label} · {model_label} · "
        f"{counts['inputTokens']:,} input / {counts['outputTokens']:,} output tokens · "
        f"published-rate estimate {formatted_cost}"
    )
    if normalized_provider == "ollama" and cost == 0:
        summary += " (hosted API token charge; local compute excluded)"
    return {
        "provider": normalized_provider,
        "model": normalized_model,
        **counts,
        "costUsd": cost,
        "costKnown": cost is not None,
        "summary": summary,
        "pricingUpdatedAt": PRICING_UPDATED_AT,
        "pricingSource": PRICING_SOURCES.get(normalized_provider),
        "ratesPerMillion": (
            {
                "input": rates.input,
                "output": rates.output,
                "cacheWrite": rates.cache_write,
                "cacheRead": rates.cache_read,
            }
            if rates is not None
            else None
        ),
        "billingBasis": (
            "published token-rate estimate; excludes account credits, free-tier allowances, taxes, "
            "request-based tool fees, and Gemini cache storage"
        ),
    }


def estimate_model_cost(
    provider: str,
    model: str,
    input_tokens: int = 4_000,
    output_tokens: int = 1_000,
) -> float | None:
    """Return a small request-size cost proxy used only for specialist ranking."""
    rates = _rates_for(provider, model, max(0, input_tokens))
    if rates is None:
        return None
    return (max(0, input_tokens) * rates.input + max(0, output_tokens) * rates.output) / 1_000_000


def anthropic_usage_summary(model: str, usage: dict[str, Any]) -> str:
    """Backward-compatible Anthropic usage line for existing integrations."""
    result = calculate_usage_cost("anthropic", model, usage)
    cost_text = (
        f"${result['costUsd']:.4f}"
        if result["costUsd"] is not None
        else "unknown (no rate configured)"
    )
    return (
        "Anthropic usage · "
        f"input_tokens={result['inputTokens']} · "
        f"output_tokens={result['outputTokens']} · "
        f"cache_read_input_tokens={result['cacheReadTokens']} · "
        f"cache_creation_input_tokens={result['cacheWriteTokens']} · "
        f"est_cost_usd={cost_text}"
    )
