---
name: Specialist routing boundary
description: Full specialist tool visibility with per-worker write/terminal grants and supervisor-mediated critical approvals.
---

Specialists may use cost-ranked direct providers that are explicitly configured for the subtask, starting at the role-appropriate tier. On failure or empty output, escalate upward within that selected provider, then fall back to the parent task's provider tier chain. Unknown published rates are never treated as zero-cost.

Every specialist receives the full tool catalog and read/inspection access. Delegating a task grants routine task-scoped writes and ordinary terminal/preview execution by default; the supervisor can explicitly set either permission false for a read-only worker. Nested workers never inherit write or terminal grants. A granted worker can perform task-scoped edits and individual noncritical deletions without user interruption. Bootstrap/runtime configuration and database writes, protected or broad/recursive deletions, critical shell commands, administrative elevation, and local 3D engine commands route back to the supervisor and require human approval. Path boundaries and secret-handling restrictions remain enforced.

**Why:** The user wants agents to make routine implementation decisions and execute task-scoped work without repeatedly asking for permission; human approval is reserved for genuinely critical operations while preserving the Forge environment.

**How to apply:** Keep provider-scoped model selection and cost reporting unchanged. Expose all tool schemas to workers, apply default task-scoped write/terminal grants at delegation unless the supervisor deliberately limits them, and recheck permissions immediately before each call. Prefer minimal, reversible, non-overlapping edits and verify results, but do not interrupt the user for routine scoped actions. Route only critical requests back to the root supervisor; never pass credentials, supervisor history, or hidden reasoning to a specialist.
