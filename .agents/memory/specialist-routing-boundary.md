---
name: Specialist routing boundary
description: Provider-scoped model escalation and explicit read-only tool permissions for delegated specialists.
---

Specialists may use cost-ranked direct providers that are explicitly configured for the subtask, starting at the role-appropriate tier. On failure or empty output, escalate upward within that selected provider, then fall back to the parent task's provider tier chain. Unknown published rates are never treated as zero-cost.

**Why:** Subtasks can use a less expensive configured engine without changing the parent task's model or thread history; unknown costs must not win a price comparison by accident.

**How to apply:** Keep candidate IDs in each provider's configured model set, base selection on published rates with an explicit token-mix estimate, record a concise user-facing decision summary and usage row, then apply the fallback chain if needed. Read-only access stays opt-in and must pass the fixed specialist allowlist both when advertising tools and immediately before execution; never pass write or terminal tools, credentials, supervisor history, or hidden reasoning to a specialist.
