---
name: Conversation display and replay boundary
description: Preserve provider context while keeping large-history UI loads lightweight.
---

Historical browser display may be paginated and shortened; signed provider replay history must remain complete and unchanged.

**Why:** Large tool/file payloads and repeated thinking logs caused the UI to freeze on load. UI performance changes must not break tool pairing, signatures, or follow-up context.

**How to apply:** Keep shortening at the display API boundary, never in stored provider turns. Open the newest conversation's bounded latest page on startup unless the user explicitly requests a fresh chat. Mount collapsed details only on expansion. Archiving hides conversations without deleting context or Task Activity.

Conversation activity ordering takes precedence over pin markers; reading older messages must not be interrupted by new output.

**Why:** The user wants the most recently active conversation first, latest messages visible on opening, and stable reading position when loading earlier history.

**How to apply:** Sort by updated time then creation time descending. Follow new output only while near the bottom; preserve scroll position during prepends and offer Jump to Latest beyond 200px from the bottom.

Do not discard layout-resize corrections during an initial bottom snap. Prefer a visible-card anchor when preserving position across older-page loads.

**Why:** Lazy-rendered content can acquire its real height after the first animation frame, invalidating both the initial scroll height and a simple prepend height difference.

**How to apply:** Keep the feed scrollable without shrinking its message children. Re-pin the bottom on late layout changes when following; maintain the visible card's offset during prepends until the user scrolls again.
