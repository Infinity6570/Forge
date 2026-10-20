---
name: BenchLM ranking freshness
description: Keep cached benchmark scores visibly distinct from current live rankings.
---

Never return cached BenchLM scores as current when the key is missing or a refresh attempt fails. Preserve last-good rows only with an explicit stale flag and a plain-language reason; without cached rows, show an unscored catalog and explain that rankings are unavailable.

**Why:** Cached scores can otherwise look like live provider data after credentials are removed or the upstream service becomes unreachable.

**How to apply:** Keep API freshness metadata and the model picker/telemetry messages aligned whenever BenchLM caching, credential handling, or ranking displays change.
