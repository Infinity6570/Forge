---
name: Local execution boundary
description: Security constraints for workspace file tools and generated previews.
---

Keep agent filesystem operations limited to canonical workspace-relative paths and expose only read-only, allowlisted workspace commands. Do not run generated Python web apps in portable mode without an OS sandbox.

**Why:** The user requires portable local execution with strict workspace boundaries. A standard Python subprocess inherits the local account's filesystem permissions and cannot enforce this boundary consistently across supported operating systems.

**How to apply:** Keep static previews available. Re-enable Python app launches or arbitrary scripts only after adding a real platform-specific OS sandbox and verifying that it blocks access outside the workspace.
