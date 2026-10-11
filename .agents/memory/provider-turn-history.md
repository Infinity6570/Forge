---
name: Provider turn history
description: Preserve opaque thought metadata across function calls, streams, and approval resumes.
---

Treat provider assistant turns as opaque protocol data, not a list of fields to reconstruct. Replay all model function calls before their corresponding tool results, keeping call IDs, part ordering, and provider extensions intact. Never interleave parallel model calls with individual responses.

**Why:** The user repeatedly reported Gemini HTTP 400 errors caused by stripped thought signatures. Signatures carry model context; projecting a turn down to function name, arguments, and ID destroys required metadata.

**How to apply:** Apply the same preservation rule to streamed turns and paused approval history. Keep provider reasoning and cryptographic signatures internal rather than rendering them as chat text or diagnostic logs.

For Gemini only, use Google's documented `skip_thought_signature_validator` fallback when a function-call signature is absent. Never replace a valid signature with the fallback.

**Why:** The user explicitly requested the documented missing-signature failsafe. Preserving genuine signatures is preferable because the fallback skips validation but cannot recover lost model context.

**How to apply:** Repair missing signatures in older replayed histories as well as new turns; respect the transport's snake_case or camelCase representation and preserve the original function arguments.
