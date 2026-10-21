---
name: Agent orchestration boundaries
description: Safety and control boundaries for dynamic micro-tools, DAG workers, and critic review.
---

Persistent micro-tools in `tools/dynamic/` are restricted data transformations, not arbitrary Python programs. Validate their schema and source, interpret only the supported AST subset in a short-lived child process, and cap inputs, outputs, loops, and runtime. Never switch this execution path to `exec` or expose filesystem, network, or shell access to a micro-tool.

DAG plans must be bounded and acyclic. Run only dependency-ready nodes concurrently, pass prerequisite artifacts as data, and grant each worker only the writes or terminal access selected by the supervisor. Existing critical-action approvals still apply.

The automated critic is read-only for project files, may run focused checks, and returns a structured pass/revise report to the primary agent. A revise verdict must be fed back before completion, with a small bounded correction budget; unresolved review findings must not be reported as a successful completion.

**Why:** Dynamic capability generation, parallel specialists, and automated review must not bypass the project's environment-integrity and human-approval boundaries.

**How to apply:** Preserve these boundaries when extending tool discovery, worker permissions, DAG scheduling, or completion verification.
