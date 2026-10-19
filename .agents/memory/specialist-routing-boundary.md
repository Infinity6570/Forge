---
name: Specialist routing boundary
description: Full specialist tool visibility with per-worker write/terminal grants and supervisor-mediated critical approvals.
---

Specialists may use cost-ranked direct providers that are explicitly configured for the subtask, starting at the role-appropriate tier. On failure or empty output, escalate upward within that selected provider, then fall back to the parent task's provider tier chain. Unknown published rates are never treated as zero-cost.

Every specialist receives the full tool catalog and read/inspection access. Project and saved-state writes require a per-worker supervisor grant; shell commands and preview processes require a separate per-worker grant. Nested workers never inherit write or terminal grants. Deletions, protected Forge source/configuration edits, critical shell commands, administrative elevation, and local 3D engine commands route back to the supervisor and require human approval. Path boundaries and secret-handling restrictions remain enforced.

**Why:** Tool visibility should not be confused with permission to execute mutations. The user selected full tool visibility for workers, supervisor-issued write/terminal grants, and human review for critical actions so the project remains usable without removing its safety boundaries.

**How to apply:** Keep provider-scoped model selection and cost reporting unchanged. Expose all tool schemas to workers, then recheck workspace-write, saved-state-write, terminal, and preview permissions immediately before each call. Route critical requests back to the root supervisor; never pass credentials, supervisor history, or hidden reasoning to a specialist.
