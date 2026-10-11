---
name: Conversation UI boundary
description: Inline provider configuration and manual-only task diagnostics.
---

Keep API key management and working-model selection directly in Preferences, not in a provider-configuration modal. Submitting a task must stay in the main conversational feed and must not automatically open Task Details.

**Why:** The user explicitly requested direct provider controls and a conversational flow without intrusive task popups.

**How to apply:** Keep intermediate activity behind a compact Thinking accordion, make full task diagnostics an explicit View Details action, and retain inline approval cards. This is not a ban on model-picker popovers, which the user explicitly requested.
