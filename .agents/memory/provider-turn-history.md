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

Keep native Google grounding separate from the normal OpenAI-compatible function-calling conversation unless support for combining both tool types is verified for every supported model.

**Why:** Older Gemini models, including Gemini 2.5, do not support the same hosted/custom tool combinations as Gemini 3. A separate native grounding request avoids changing or corrupting the signed outer conversation history.

**How to apply:** Use the task's exact selected model for grounding; return the answer and untouched grounding metadata as the paired tool result. Do not silently substitute a grounding-capable model for unsupported Gemma selections.

Treat an assistant turn with no user-facing text and no tool calls as incomplete, not successful. After tool results—or an otherwise empty turn—make one bounded final synthesis request; only complete and persist the task when it returns non-whitespace text. Never store an empty-response placeholder as an assistant answer.

**Why:** Gemini can return function-call-only turns, and an empty final turn must not turn completed tool work into a false successful response or contaminate later chat context.

**How to apply:** Keep the synthesis instruction ephemeral, include the full paired tool history, and mark the task failed if the synthesis attempt is also empty. Filter legacy empty-response records from replay.
