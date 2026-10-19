---
name: Gemini prompt caching
description: Use Google-managed implicit context caching for repeated Gemini prompt prefixes and surface cache-hit usage.
---

For Gemini models supported by Google's API, prompt/context caching is implicit and provider-managed. Keep the stable system-instruction and tool prefix unchanged and at the start of requests; preserve all chronological native turns. Read cached-token usage metadata from completed responses and show it in task telemetry. Do not create explicit cached-content objects unless a model/usage case is verified to need them.

**Why:** Google's current Gemini API documentation says implicit caching is enabled automatically for supported 2.5+ models, while explicit caching has model-specific minimum token and lifecycle requirements. Forge's repeated system/tool prefix already enables provider-managed cache hits without modifying signed history.

**How to apply:** Keep system instructions and tools stable across tool rounds, preserve raw Gemini parts/signatures, and report `cached_content_token_count`/equivalent response metadata when present. Never claim a cache hit when the API returns no usage count.
