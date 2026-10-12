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
    latest prebuilt frontend from `artifacts/meta-assistant/dist/public`,
    falling back to `static/app` when that build is absent. Include the latest
    build directory in your local export so Python serves the updated UI.

## Local data and API keys

- SQLite history and workspace files live in `workspace/`.
- Provider keys are saved in the `.env` file for the environment running the
  app. Local changes require a loopback connection; Replit preview changes
  require a same-origin request. The API never returns key values, and the file
  is excluded from Git.
- OpenAI, Gemini, and OpenRouter use their standard provider APIs through an
  OpenAI-compatible client. You supply and pay for your own provider account.
- Local app previews are disabled by default. Enable **Enable Local App Previews
  (Unrestricted Workspace Execution)** in Preferences to let the assistant start
  Flask, Streamlit, or FastAPI apps from `workspace/`. They bind to localhost,
  use a cleaned environment without provider API keys, and are stopped when the
  Live Preview panel closes or after one hour. They are always disabled in
  Replit Cloud.
- **Running generated Python apps executes code with standard local user
  permissions.** Setting `cwd=workspace/` does not confine file access: generated
  code can read or modify files your local account can access. Enable previews
  only for code you trust.

## Important

Do not publish or share this personal assistant as a public service. The Replit
preview Preferences page writes keys into that Replit workspace's `.env` file;
task history and workspace data are designed for one user, not a multi-user
deployment.

## Web search and rendered pages

Preferences has a **Web Search Engine Configuration** panel. Its saved modes are:

- **Native / provider default:** Gemini searches use Google's native
  `generateContent` API with the Google Search tool, not a scraper. This is a
  dedicated grounding request inside the normal `web_search` tool so existing
  function-call history and thought signatures stay intact. The task's selected
  model is used unchanged. Gemma does not support native grounding; choose an
  external search mode instead. Other providers use the selected search API
  if its key is saved, otherwise Chromium.
- **Search API:** Tavily (recommended), Serper, or Brave, using your personal key.
  Add `TAVILY_API_KEY`, `SERPER_API_KEY`, or `BRAVE_SEARCH_API_KEY` via the same
  **Save Keys** button as model-provider credentials. Blank fields retain keys.
- **Headless Chromium:** Searches and `fetch_webpage` use an ephemeral browser
  to render public HTTPS pages. To install a browser on your PC:
  `python -m playwright install chromium`. An installed Chromium/Chrome is also
  detected, or set `CHROMIUM_EXECUTABLE_PATH` to its executable.

Search preferences persist as `WEB_SEARCH_MODE` (`native`, `api`, `chromium`),
`WEB_SEARCH_API_PROVIDER` (`tavily`, `serper`, `brave`), and
`WEB_SEARCH_CHROMIUM_FALLBACK` (`true`/`false`). The optional Chromium fallback
is used only for quota/rate-limit exhaustion, not invalid keys or generic errors.
It defaults off. Empty or blocked search results are explicit errors, not `[]`.

Browser runs have a 40-second budget, at most two concurrent sessions, no saved
profile/cookies, and no provider/search keys in the browser environment. Local,
private, non-HTTPS and credential-bearing page requests, downloads, WebSockets,
and service workers are blocked. These safeguards are not an OS-level sandbox;
browse trusted public sites. Each session closes its browser on completion,
failure, or cancellation. Chromium may still encounter CAPTCHAs; the app does not
bypass them. Search APIs are the more reliable choice for unattended research.

Grounding answers, source links, search suggestions, and raw metadata are stored
with tool messages in the current chat and remain visible under Thinking and the
answer's Sources section after reloads. No Replit AI credits or proxy is used.
