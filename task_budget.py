"""Per-task spend guard and runaway-context detection.

Inputs are rows from the existing ``usage_ledger`` table, so no schema change is needed.
The guard reads the ledger before each model round and halts the task when the
spend ceiling is exceeded. Unpriced models are limited by a raw token ceiling, so a
model with unknown rates cannot run unbounded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TASK_BUDGET_USD = 5.00
DEFAULT_UNPRICED_TOKEN_CEILING = 5_000_000
GROWTH_WARNING_FACTOR = 2.0
GROWTH_WARNING_MIN_CONTEXT = 50_000


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def configured_task_budget_usd() -> float:
    """USD ceiling per task. Set FORGE_TASK_BUDGET_USD=0 to disable the spend limit."""
    return _env_float("FORGE_TASK_BUDGET_USD", DEFAULT_TASK_BUDGET_USD)


def configured_unpriced_token_ceiling() -> int:
    return int(_env_float("FORGE_UNPRICED_TASK_TOKEN_CEILING", DEFAULT_UNPRICED_TOKEN_CEILING))


@dataclass
class BudgetStatus:
    spend_usd: float
    unpriced_tokens: int
    exceeded: bool
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def evaluate_budget(
    rows: list[dict[str, Any]],
    *,
    budget_usd: float,
    unpriced_token_ceiling: int,
) -> BudgetStatus:
    """Judge a task from its ledger rows (dicts with the usage_ledger column names)."""
    spend = 0.0
    unpriced = 0
    for row in rows:
        if int(row.get("cost_known") or 0):
            spend += float(row.get("cost_usd") or 0.0)
        else:
            unpriced += sum(
                int(row.get(key) or 0)
                for key in ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")
            )
    reason = None
    if budget_usd > 0 and spend > budget_usd:
        reason = f"Task spend ${spend:.4f} exceeded the ${budget_usd:.2f} per-task budget."
    elif unpriced_token_ceiling > 0 and unpriced > unpriced_token_ceiling:
        reason = (
            f"Unpriced-model usage of {unpriced:,} tokens exceeded the "
            f"{unpriced_token_ceiling:,}-token ceiling."
        )
    return BudgetStatus(
        spend_usd=round(spend, 6),
        unpriced_tokens=unpriced,
        exceeded=reason is not None,
        reason=reason,
        warnings=context_growth_warnings(rows),
    )


def context_growth_warnings(rows: list[dict[str, Any]]) -> list[str]:
    """Flag rounds whose context roughly doubled, which usually signals a runaway loop."""
    warnings: list[str] = []
    previous = 0
    for index, row in enumerate(rows, start=1):
        context = (
            int(row.get("input_tokens") or 0)
            + int(row.get("cache_read_tokens") or 0)
            + int(row.get("cache_write_tokens") or 0)
        )
        if (
            previous > 0
            and context >= GROWTH_WARNING_MIN_CONTEXT
            and context >= GROWTH_WARNING_FACTOR * previous
        ):
            warnings.append(
                f"Model call {index} sent {context:,} context tokens, up from {previous:,} "
                "on the previous call. Check whether a tool output is growing each round."
            )
        previous = context
    return warnings

