---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Keep agent file operations limited to canonical workspace-relative paths. Read-only inspection remains allowlisted. Local terminal commands are separately gated, off by default, and available only in an exported localhost copy: show the exact one-line command in the task approval UI, require explicit approval, then run without elevation from workspace/ with a cleaned environment and a 30-second timeout. Block shell chaining/redirection, inline interpreter code, and known destructive or administrative commands. Refuse terminal access in Replit.

Generated Python and Vite app previews follow a separate explicit opt-in. They are always disabled in Replit Cloud; on a local exported copy, the user must enable “Enable Local App Previews (Unrestricted Workspace Execution)” in Preferences. This does not create a filesystem sandbox: children run with the local user's normal permissions, with `workspace/` as cwd and a cleaned environment that omits provider API keys. The UI must display the warning: “Running generated Python apps executes code with standard local user permissions.”

**Why:** The user explicitly chose local terminal commands after per-command approval. They also chose an explicit, portable local opt-in for app previews over kernel-specific sandbox dependencies. Child processes can still read or modify anything available to the user's account, so each terminal command needs exact approval and the preview warning/default-off toggle remain essential; neither feature grants administrator permissions.

**How to apply:** Keep static previews available everywhere and Python/Vite app processes disabled in Replit. On localhost, require the saved opt-in, use `workspace/` as cwd, pass only a cleaned environment, bind preview servers to loopback, enforce a runtime limit, and terminate children when the Live Preview panel closes. Do not describe cwd or environment cleanup as filesystem confinement. Keep file tools workspace-confined, local terminal commands individually approved and non-elevated, and elevated commands separately gated, audited, and fail-closed.

New laptop layout breakpoints must not add automatic inspector closures; use an overlay or narrower layout while keeping an already-open preview mounted.

**Why:** Closing/unmounting the inspector stops preview processes. A layout-only resize should not introduce additional ways to terminate a running local app.

**How to apply:** Distinguish the initial inspector visibility on compact screens from lifecycle-changing closure of an existing inspector. Keep explicit close behavior and the existing mobile boundary intact.
