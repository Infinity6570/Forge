# Universal Meta-Agent Assistant

Personal assistant dashboard for local AI tasks, reminders, workspace files, and notes.

## Run and validate

- Replit API preview: `pnpm --filter @workspace/api-server run dev`
- Local app: install `requirements.txt`, then run `python main.py` and open `http://localhost:8000`
- Validate: `pnpm run typecheck`
- Rebuild API client and schemas: `pnpm --filter @workspace/api-spec run codegen`
- Build portable frontend assets: `pnpm --filter @workspace/meta-assistant run build`, then copy `artifacts/meta-assistant/dist/public` to `static/app`

## Stack and source of truth

- Frontend: React, Vite, TypeScript in `artifacts/meta-assistant/`
- Portable backend: FastAPI in root `main.py`
- Local persistence: SQLite and workspace files under `workspace/`
- API contract: `lib/api-spec/openapi.yaml`
- Python dependencies: `requirements.txt`
- UI assets served by the portable backend: `static/app/`

## Product and architecture rules

- The exported app must run locally with `python main.py`.
- Do not use Replit-managed AI integrations or credits. Use only standard local provider variables: `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `OPENROUTER_API_KEY`.
- Provider keys belong in the local `.env` file, not in SQLite. The settings write endpoint must remain limited to loopback requests and must never return key values.
- Keep the `.env` file out of source control, static serving, and workspace exports.
- The optional Python runner is disabled by default, requires explicit local opt-in, and must remain disabled in Replit.
- This is a single-user local app; do not publish it as a public service without adding authentication and per-user storage.
