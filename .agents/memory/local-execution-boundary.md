---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Keep ordinary agent filesystem operations limited to canonical workspace-relative paths and expose only read-only, allowlisted workspace commands. Administrative commands are a separate, narrow exception: show one exact command in the task approval UI, block shell chaining/redirection/inline scripts and known destructive commands, and execute only after explicit approval in a local exported copy. Refuse elevation in Replit and when the server is already elevated.

Generated Python app previews follow a separate explicit opt-in. They are always disabled in Replit Cloud; on a local exported copy, the user must enable “Enable Local App Previews (Unrestricted Workspace Execution)” in Preferences. This does not create a filesystem sandbox: children run with the local user's normal permissions, with `workspace/` as cwd and a cleaned environment that omits provider API keys. The UI must display the warning: “Running generated Python apps executes code with standard local user permissions.”

**Why:** The user chose an explicit, portable local opt-in over kernel-specific sandbox dependencies. A child process can still read or modify anything available to the user's account, so the warning and default-off toggle are essential; this is distinct from the separate admin elevation approval gate.

**How to apply:** Keep static previews available everywhere and Python app processes disabled in Replit. On localhost, require the saved opt-in, use `workspace/` as cwd, pass only a cleaned environment, bind preview servers to loopback, enforce a runtime limit, and terminate children when the Live Preview panel closes. Do not describe cwd or environment cleanup as filesystem confinement. Keep ordinary file and command tools workspace-confined; keep elevated commands gated, audited, and fail-closed.
