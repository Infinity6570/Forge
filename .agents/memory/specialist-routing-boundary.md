---
name: Specialist routing boundary
description: Provider-scoped model escalation and explicit read-only tool permissions for delegated specialists.
---

Specialist model escalation must stay within the provider selected for the parent task and move only upward from the requested tier. Read-only specialist access is opt-in and must use a fixed allowlist; specialists do not inherit write or command tools.

**Why:** A specialist is a subordinate worker, not permission to silently change the task's provider or expand workspace access. A failed or empty response should get a controlled stronger attempt without changing those boundaries.

**How to apply:** Keep tier model IDs in the provider's configured model set, record each escalation decision, and check the read-only allowlist both when advertising tools and immediately before execution.
