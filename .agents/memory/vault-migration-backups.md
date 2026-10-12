---
name: Vault migration backups
description: Design rule for moving Forge's encrypted local credential vault between app copies.
---

Migration backups must protect the local vault encryption key and encrypted entries together under a separate user-chosen backup password. Keep the bundled key encrypted at rest in the backup and never return it in plaintext to the browser. Validate that the bundled key decrypts every entry before replacing the destination vault, and leave unrelated app data unchanged.

**Why:** Moving SQLite vault rows without their matching encryption key makes saved credentials unreadable; returning the key to the browser would weaken the existing local-secret boundary.

**How to apply:** Any future vault export, import, or migration flow should preserve the encrypted package boundary, verify before mutation, and replace only vault records unless the user explicitly requests a broader app restore.
