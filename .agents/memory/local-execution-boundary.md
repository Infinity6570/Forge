---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Agent file tools operate across the project root, including hidden files and workspace/, and may read, create, overwrite, append, or delete immediately without confirmation. Project file paths stay inside the project root; relative paths that already exist in workspace/ continue to resolve there for compatibility. Shell tools execute arbitrary commands immediately with `shell=True`, the project root as cwd (or a project-relative cwd), inherited environment, and the server process's ordinary OS permissions; there is no command allowlist, local toggle, or per-command approval, with a 300-second timeout. Shell commands are not sandboxed and can access data outside the project and environment secrets. Redact known API keys and sensitive environment values from tool output. Administrative elevation remains a separate explicit approval flow.

Generated Python and Vite app previews follow a separate explicit opt-in. They are always disabled in Replit Cloud; on a local exported copy, the user must enable “Enable Local App Previews (Unrestricted Workspace Execution)” in Preferences. This does not create a filesystem sandbox: children run with the local user's normal permissions, with `workspace/` as cwd and a cleaned environment that omits provider API keys. The UI must display the warning: “Running generated Python apps executes code with standard local user permissions.”

Local Blender and Unreal engine tools follow the same local-only opt-in boundary but require per-action approval. Show the exact Blender script or remote endpoint and payload before execution. Blender scripts run with ordinary local-user permissions, not in a filesystem sandbox; engine remote commands accept only loopback HTTP/WebSocket endpoints.

**Why:** The user explicitly confirmed unrestricted project file and shell access after reviewing that commands can modify/delete any data reachable by the server process, including outside the project and environment secrets. They separately chose explicit approval for administrator elevation, local 3D-engine automation, and local generated-app previews.

**How to apply:** Keep static previews available everywhere; Python/Vite previews and Blender/Unreal integrations retain their separate local opt-ins. Preview child processes still use a cleaned environment, loopback binding, runtime limits, and explicit stop lifecycle. Shell execution is intentionally broader and must not be described as sandboxed; keep it at ordinary server-user privileges and redact sensitive values from returned output. For administrator elevation, show the exact command and wait for explicit UI approval. For engine tools, show the script or endpoint/payload and wait for approval; reject non-loopback remote-engine URLs.

New laptop layout breakpoints must not add automatic inspector closures; use an overlay or narrower layout while keeping an already-open preview mounted.

**Why:** Closing/unmounting the inspector stops preview processes. A layout-only resize should not introduce additional ways to terminate a running local app.

**How to apply:** Distinguish the initial inspector visibility on compact screens from lifecycle-changing closure of an existing inspector. Keep explicit close behavior and the existing mobile boundary intact.
