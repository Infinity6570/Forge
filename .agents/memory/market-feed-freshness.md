---
name: Market-feed freshness
description: Distinguish provider response latency from the freshness of energy market observations.
---

OilPriceAPI's latest endpoint can include source observation time and freshness metadata; a fast HTTP response does not prove that the underlying market data is current. Preserve its `as_of` and stale/fresh status, and disclose stale or unknown freshness instead of claiming real-time data.

**Why:** The provider documents that refresh cadence varies by source, market hours, dataset, and plan.

**How to apply:** Treat provider freshness metadata as authoritative. Label a quote real-time only when the provider explicitly marks it fresh, and keep delayed Yahoo fallbacks visibly flagged.
