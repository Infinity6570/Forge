---
name: Provider model availability
description: Local-first provider boundary and verifying model catalogs without silently changing selection.
---

The application must be portable to the user's PC and run with `python main.py` after export. Use personal provider keys from local configuration and standard provider clients, never Replit-managed AI proxies or AI credits.

**Why:** The user explicitly required 100% portability and repeated the instruction to stop relying on Replit AI Integrations.

**How to apply:** Keep provider calls independent of the hosting platform. Preserve masked key inputs and redacted configuration responses; never log credentials.

Check model IDs against the configured provider's live catalog and a minimal completion before claiming they work. Do not infer an API ID from a display name or assume an error's suggested replacement is available. Catalog maintenance must not silently switch the saved working model or an individual task's model.

**Why:** A requested replacement ID also returned HTTP 404; the user clarified the actually available Google models. The user requires explicit confirmation before task-level capability upgrades.

**How to apply:** Use exact API IDs returned by the provider, retain custom IDs for future releases, and use the explicit Apply Model action or task recommendation approval for selection changes.

The Google Gen AI adapter must use the native SDK and preserve Gemini candidate parts in chronological history. In particular, retain thought signatures on model function calls and pair each function response immediately with its call. Gemini Live models use the Live API session transport; image and speech models need their response modalities configured explicitly.

**Why:** Converting native turns through an OpenAI-shaped history serializer can drop signature fields or lose function-call/response pairing, while modality-specific models do not use ordinary text-generation defaults.

**How to apply:** Keep raw Gemini parts intact across tool rounds, use `generate_content_stream` for standard models and `live.connect` for Live models, and handle image/audio output separately from text.
