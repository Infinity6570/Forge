"""Reconcile Forge's model catalog with the pricing table so they cannot drift apart.

``reconcile`` compares the selectable model IDs (``MODEL_OPTIONS`` in main.py) with
``usage_cost.RATE_TABLE``. It reports selectable models with no published rate,
priced models that are no longer selectable, and pricing data that is out of date.
Image capability checks remain in main.py (``supports_image_input``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

DEFAULT_MAX_PRICING_AGE_DAYS = 30


def reconcile(
    model_options: dict[str, set[str]],
    rate_table: dict[str, dict[str, Any]],
    *,
    pricing_updated_at: str,
    today: date,
    max_pricing_age_days: int = DEFAULT_MAX_PRICING_AGE_DAYS,
) -> dict[str, Any]:
    unpriced: list[str] = []
    orphaned: list[str] = []
    for provider in sorted(set(model_options) | set(rate_table)):
        selectable = set(model_options.get(provider, set()))
        priced = set(rate_table.get(provider, {}))
        for model in sorted(selectable - priced):
            unpriced.append(f"{provider}/{model}")
        for model in sorted(priced - selectable):
            orphaned.append(f"{provider}/{model}")

    age_days: int | None
    try:
        age_days = (today - date.fromisoformat(pricing_updated_at)).days
    except (TypeError, ValueError):
        age_days = None
    stale = age_days is None or age_days > max_pricing_age_days

    return {
        "unpricedModels": unpriced,
        "orphanedRates": orphaned,
        "pricingUpdatedAt": pricing_updated_at,
        "pricingAgeDays": age_days,
        "pricingStale": stale,
        "ok": not unpriced and not orphaned and not stale,
    }
