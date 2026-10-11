---
name: Conversation isolation
description: Persistent chat context, run ordering, deletion semantics, and safe restart behavior.
---

Keep each chat's conversation context and visible execution stream separate from the global Task Activity list. Workspace files remain shared.

**Why:** The user requested clean, isolated new chats while preserving the existing workspace and task-monitoring behavior.

**How to apply:** Follow-ups use the selected chat's chronological turns, not a collection of recent tasks from unrelated chats.

Permit only one unfinished run per chat; other chats can run independently.

**Why:** Interleaved runs can separate signed function calls from their matching results and create inconsistent conversational context.

**How to apply:** Enforce this at the backend, including paused approval/model-confirmation states, not only by disabling the send button.

Deleting a chat removes its conversation context but retains Task Activity records, including objectives, results, and logs. State this clearly before confirmation.

**Why:** Monitoring must remain backward-compatible; chat deletion must not be presented as complete erasure of task data.

**How to apply:** Preserve task records and make active-chat deletion fail explicitly.

Do not automatically retry interrupted runs after server restart. Pending approval requests remain paused.

**Why:** A command may have changed files before the interruption; replaying it silently can duplicate side effects or bypass user approval.

**How to apply:** Mark interrupted work clearly and let the user submit a follow-up or resolve the pending approval.
