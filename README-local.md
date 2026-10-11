# Run the assistant locally

The local app uses a Python/FastAPI server, a local SQLite database, and the
provider API key you configure. It does not use Replit AI Integrations.

## First-time setup

1. Install Python 3.10 or newer.
2. In this project folder, install the Python packages:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`. You can enter the key from the app's Settings
   screen after it starts. The `.env` file is private and excluded from Git.
4. Start the app:

   ```bash
   python main.py
   ```

5. Open <http://localhost:8000>. To build the frontend again after changing
   its source, run `pnpm install` and
   `pnpm --filter @workspace/meta-assistant run build`; the app serves the
   prebuilt frontend from `static/app`.

## Local data and API keys

- SQLite history and workspace files live in `workspace/`.
- Provider keys are saved only to the local `.env` file with owner-only file
  permissions. The Settings API accepts keys only from a loopback connection
  and never returns their values.
- OpenAI, Gemini, and OpenRouter use their standard provider APIs through an
  OpenAI-compatible client. You supply and pay for your own provider account.
- The Python runner is disabled by default. If enabled in local Settings, model
  generated code runs with your operating-system account's normal permissions
  and can access files beyond this project. Enable it only for work you trust;
  it is always disabled in Replit.

## Important

Do not publish this personal assistant as a public service. Its local settings
screen refuses remote key changes, but task history and workspace data are
designed for one local user rather than a multi-user deployment.
