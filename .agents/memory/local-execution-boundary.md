---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Agent file tools operate across the project root, including hidden files and workspace/, with project-bound path resolution. Ordinary task-scoped source, UI, manifest, and test edits plus individual noncritical file deletions proceed without approval. Human approval is reserved for bootstrap/runtime configuration (`.replit`, `replit.nix`), database writes, protected/core or sensitive deletions, and broad/recursive removals. Secret files such as `.env` and Git metadata cannot be written through agent file tools. Shell tools run with `shell=True`, the project root as cwd (or a project-relative cwd), inherited environment, and the server process's ordinary OS permissions, with a 300-second timeout. They are not filesystem-sandboxed and can affect data outside the project; broad/recursive, protected-path, administrative, and system-level command patterns pause for human approval. Redact known API keys and sensitive environment values from tool output. Administrative elevation remains a separate explicit approval flow.

Generated Python and Vite app previews follow a separate explicit opt-in. They are always disabled in Replit Cloud; on a local exported copy, the user must enable “Enable Local App Previews (Unrestricted Workspace Execution)” in Preferences. This does not create a filesystem sandbox: children run with the local user's normal permissions, with `workspace/` as cwd and a cleaned environment that omits provider API keys. The UI must display the warning: “Running generated Python apps executes code with standard local user permissions.”

Local Blender and Unreal engine tools follow the same local-only opt-in boundary but require per-action approval. Show the exact Blender script or remote endpoint and payload before execution. Blender scripts run with ordinary local-user permissions, not in a filesystem sandbox; engine remote commands accept only loopback HTTP/WebSocket endpoints.

**Why:** The user states that preserving the Forge environment is the agents' highest operational priority because damage threatens project continuity. Treat this as careful stewardship of the user's project and data, not as an independent agent-survival objective. Normal shell and preview processes still use ordinary operating-system permissions, so they must not be described as sandboxed.

**How to apply:** Inspect existing state before changes; prefer the smallest reversible edit, preserve unrelated files, and verify outcomes. Keep path traversal checks and redaction. Let routine source/config edits, individual noncritical file removals, builds, tests, and ordinary shell commands proceed without user interruption. Route bootstrap/runtime configuration changes, database writes, sensitive/protected-file removals, broad/recursive deletion, and genuinely critical shell operations through the approval UI; verify targets have not changed while approval was pending. Never resist user control or put agent continuity above user intent. Keep static previews available everywhere; Python/Vite previews and Blender/Unreal integrations retain their separate local opt-ins. Preview children use a cleaned environment, loopback binding, runtime limits, and explicit stop lifecycle. For elevation and engine tools, show the exact command/script/endpoint and wait for approval; reject non-loopback remote-engine URLs.

New laptop layout breakpoints must not add automatic inspector closures; use an overlay or narrower layout while keeping an already-open preview mounted.

**Why:** Closing/unmounting the inspector stops preview processes. A layout-only resize should not introduce additional ways to terminate a running local app.

**How to apply:** Distinguish the initial inspector visibility on compact screens from lifecycle-changing closure of an existing inspector. Keep explicit close behavior and the existing mobile boundary intact.
