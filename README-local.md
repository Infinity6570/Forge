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
- Provider keys are saved in the `.env` file for the environment running the
  app. Local changes require a loopback connection; Replit preview changes
  require a same-origin request. The API never returns key values, and the file
  is excluded from Git.
- OpenAI, Gemini, and OpenRouter use their standard provider APIs through an
  OpenAI-compatible client. You supply and pay for your own provider account.
- The Python runner is disabled by default. If enabled in local Settings, model
  generated code runs with your operating-system account's normal permissions
  and can access files beyond this project. Enable it only for work you trust;
  it is always disabled in Replit.

## Important

Do not publish or share this personal assistant as a public service. The Replit
preview settings modal writes keys into that Replit workspace's `.env` file;
task history and workspace data are designed for one user, not a multi-user
deployment.
