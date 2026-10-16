# Forge

Forge is a local-first assistant with a Python/FastAPI backend, a React/Vite
frontend, a local SQLite database, and an optional Electron desktop window.
Provider API keys are supplied by you and stored locally; Forge does not require
Replit AI services.

## Prerequisites

Install these before following the setup commands:

- Python 3.11 or newer
- Node.js 24 or newer, including npm
- pnpm 10 (the commands below install/activate it through Corepack)

Run all commands from the repository root. The commands create a Python virtual
environment in `.venv`, install Python and JavaScript dependencies, create a
local `.env` from the example if needed, and build the frontend.

## Windows (PowerShell)

```powershell
# Create and populate the Python virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Enable pnpm and install the complete JavaScript workspace
corepack enable
corepack prepare pnpm@10 --activate
pnpm install --frozen-lockfile

# Create local configuration (keep .env private)
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# Build the frontend that the Python server serves
pnpm --filter @workspace/meta-assistant run build
```

Start Forge in PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
```

Open <http://localhost:8000>. To open the native Electron window, leave the
server running and use a second PowerShell window:

```powershell
pnpm run desktop
```

## Linux

```bash
# Create and populate the Python virtual environment
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

# Enable pnpm and install the complete JavaScript workspace
corepack enable
corepack prepare pnpm@10 --activate
pnpm install --frozen-lockfile

# Create local configuration (keep .env private)
test -f .env || cp .env.example .env

# Build the frontend that the Python server serves
pnpm --filter @workspace/meta-assistant run build
```

Start Forge:

```bash
./.venv/bin/python main.py
```

Open <http://localhost:8000>. To open the native Electron window, leave the
server running and use a second terminal:

```bash
pnpm run desktop
```

## macOS

```bash
# Create and populate the Python virtual environment
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

# Enable pnpm and install the complete JavaScript workspace
corepack enable
corepack prepare pnpm@10 --activate
pnpm install --frozen-lockfile

# Create local configuration (keep .env private)
test -f .env || cp .env.example .env

# Build the frontend that the Python server serves
pnpm --filter @workspace/meta-assistant run build
```

Start Forge:

```bash
./.venv/bin/python main.py
```

Open <http://localhost:8000>. To open the native Electron window, leave the
server running and use a second terminal:

```bash
pnpm run desktop
```

## Configure API keys

The app starts without a provider key. Add your own provider key in **Preferences
→ API Keys Vault**, or edit `.env` directly. Never commit or share `.env`; it is
ignored by Git. Available variable names are listed in `.env.example`.

## Optional: Chromium for rendered web search

Forge can use Playwright Chromium for rendered public web pages. Install the
browser after installing Python requirements:

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

**Linux and macOS**

```bash
./.venv/bin/python -m playwright install chromium
```

## Optional: develop the frontend with hot reload

For frontend hot reload, start the backend in one terminal using the
platform-specific command above. In a second terminal, run:

```bash
pnpm --filter @workspace/meta-assistant run dev
```

The Electron command opens an already-running local server; it does not create a
packaged installer. Local app previews can execute generated code with normal
local-user permissions. Enable them only for code you trust.

## Local data

Conversation history, SQLite data, and workspace files are kept under
`workspace/`. See [README-local.md](README-local.md) for additional details about
local previews, web search, and security limits.
