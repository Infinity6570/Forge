---
name: Specialist routing boundary
description: Provider-scoped model escalation and explicit read-only tool permissions for delegated specialists.
---

Specialists may use cost-ranked direct providers that are explicitly configured for the subtask, starting at the role-appropriate tier. On failure or empty output, escalate upward within that selected provider, then fall back to the parent task's provider tier chain. Unknown published rates are never treated as zero-cost.

Specialist tools are denied by default. The supervisor can grant read-only inspection, project-file writes, and terminal execution independently for each worker. Write and terminal grants must appear in that worker's advertised tool schemas and be rechecked immediately before execution. Delete, administrative elevation, and local 3D engine tools are never delegated.

**Why:** Subtasks can use a less expensive configured engine without changing the parent task's model or thread history; unknown costs must not win a price comparison by accident. The user has also authorized granular supervisor-issued write and terminal grants, while requiring safe defaults and independent execution checks.

**How to apply:** Keep candidate IDs in each provider's configured model set, base selection on published rates with an explicit token-mix estimate, record a concise user-facing decision summary and usage row, then apply the fallback chain if needed. Keep all specialist capabilities off unless the supervising agent explicitly grants that category for the individual delegation. Never pass credentials, supervisor history, or hidden reasoning to a specialist.
