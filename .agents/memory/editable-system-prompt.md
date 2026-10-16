---
name: Editable system prompt boundary
description: The boundary between user-editable persona guidance and fixed agent execution instructions.
---

The Preferences editor should expose the active persona and collaboration guidance, but keep fixed safety, tool, and execution instructions outside the editable text. Saving an edit should update active task message histories and persist for future tasks without restarting the server.

**Why:** Users need to customize Forge's behavior, but replacing the entire runtime prompt could silently remove path, permission, or execution controls.

**How to apply:** When extending the prompt editor or prompt profiles, preserve the fixed instruction layer and keep the editable section clearly labeled as persona guidance.
