---
name: Conversation display and replay boundary
description: Preserve provider context while keeping large-history UI loads lightweight.
---

Historical browser display may be paginated and shortened; signed provider replay history must remain complete and unchanged.

**Why:** Large tool/file payloads and repeated thinking logs caused the UI to freeze on load. UI performance changes must not break tool pairing, signatures, or follow-up context.

**How to apply:** Keep shortening at the display API boundary, never in stored provider turns. Start with a clean view instead of automatically opening old history, and mount collapsed details only on expansion. Archiving hides conversations without deleting context or Task Activity.
