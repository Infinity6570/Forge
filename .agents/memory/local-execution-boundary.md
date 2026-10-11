---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Keep ordinary agent filesystem operations limited to canonical workspace-relative paths and expose only read-only, allowlisted workspace commands. Administrative commands are a separate, narrow exception: show one exact command in the task approval UI, block shell chaining/redirection/inline scripts and known destructive commands, and execute only after explicit approval in a local exported copy. Refuse elevation in Replit and when the server is already elevated. Do not run generated Python web apps in portable mode without an OS sandbox.

**Why:** The user requires portable local execution with strict workspace boundaries. A standard Python subprocess inherits local account permissions; elevated execution can affect the whole machine, so it needs its own visible approval, audit trail, platform elevation helper, and destructive-command denylist.

**How to apply:** Keep static previews available. Ordinary file and command tools remain workspace-confined. Elevated execution must stay separate from agent tools until the user approves the exact command, and it must fail closed when the local OS elevation helper is unavailable. Re-enable Python app launches or arbitrary scripts only after adding a real platform-specific OS sandbox and verifying that it blocks access outside the workspace.
