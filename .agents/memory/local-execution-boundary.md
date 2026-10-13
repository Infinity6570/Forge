---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Keep agent file operations limited to canonical workspace-relative paths. Read-only inspection remains allowlisted. Local terminal commands are separately gated, off by default, and available only in an exported localhost copy: show the exact one-line command in the task approval UI, require explicit approval, then run without elevation from workspace/ with a cleaned environment and a 30-second timeout. Block shell chaining/redirection, inline interpreter code, and known destructive or administrative commands. Refuse terminal access in Replit.

Generated Python and Vite app previews follow a separate explicit opt-in. They are always disabled in Replit Cloud; on a local exported copy, the user must enable “Enable Local App Previews (Unrestricted Workspace Execution)” in Preferences. This does not create a filesystem sandbox: children run with the local user's normal permissions, with `workspace/` as cwd and a cleaned environment that omits provider API keys. The UI must display the warning: “Running generated Python apps executes code with standard local user permissions.”

Local Blender and Unreal engine tools follow the same local-only opt-in boundary but require per-action approval. Show the exact Blender script or remote endpoint and payload before execution. Blender scripts run with ordinary local-user permissions, not in a filesystem sandbox; engine remote commands accept only loopback HTTP/WebSocket endpoints.

**Why:** The user explicitly chose local terminal commands after per-command approval, and local 3D-engine automation after reviewing its exact script or command. They also chose explicit, portable local opt-ins for generated apps and engine tools over kernel-specific sandbox dependencies. These processes can still access files available to the user's account, so approvals, warnings, and default-off toggles remain essential; none grants administrator permissions.

**How to apply:** Keep static previews available everywhere and Python/Vite and 3D-engine process tools disabled in Replit. Locally require their separate saved opt-ins. Use `workspace/` paths and cwd, pass only a cleaned environment, bind previews to loopback, enforce runtime limits, and terminate processes on explicit close. For 3D work, show the exact script or endpoint/payload and wait for explicit approval; reject non-loopback remote-engine URLs. Do not describe cwd or environment cleanup as filesystem confinement. Keep file tools workspace-confined, local terminal commands individually approved and non-elevated, and elevated commands separately gated, audited, and fail-closed.

New laptop layout breakpoints must not add automatic inspector closures; use an overlay or narrower layout while keeping an already-open preview mounted.

**Why:** Closing/unmounting the inspector stops preview processes. A layout-only resize should not introduce additional ways to terminate a running local app.

**How to apply:** Distinguish the initial inspector visibility on compact screens from lifecycle-changing closure of an existing inspector. Keep explicit close behavior and the existing mobile boundary intact.
