---
name: Anthropic TLS trust store
description: System certificate trust requirements for direct Anthropic API calls in the hosted Linux runtime.
---

In the hosted Linux runtime, Python's bundled certifi roots may not include certificates trusted by the OS/runtime, causing Anthropic requests to fail with a generic connection error. Build a verified context with `ssl.create_default_context()` and pass it to the Anthropic HTTPX client. Do not disable certificate verification.

**Why:** A direct Anthropic request failed TLS verification with certifi while the runtime system trust store successfully verified the same endpoint.

**How to apply:** Keep direct-provider HTTP clients on validated system trust and include an offline unit test that asserts hostname and certificate verification remain enabled.
