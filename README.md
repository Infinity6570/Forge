# Forge

Forge is a local-first assistant with a Python/FastAPI backend, a React/Vite
frontend, a local SQLite database, and an optional Electron desktop window.
Provider API keys are supplied by you and stored locally; Forge does not require
Replit AI services.

## Prerequisites

Start with a fresh project export or checkout, extract it, and open a terminal
in the project root (the directory containing `main.py`, `package.json`, and
`requirements.txt`).

Install Python 3.11, Node.js 24, and npm using the commands for your operating
system. Reopen the terminal after installation so the new commands are on
`PATH`.

### Install the runtimes on Windows

In PowerShell, install [winget](https://learn.microsoft.com/windows/package-manager/winget/)
if it is not already available, then run:

```powershell
winget install --exact --id Python.Python.3.11
winget install --exact --id OpenJS.NodeJS.LTS
```

Close and reopen PowerShell. Verify:

```powershell
py -3.11 --version
node --version
npm --version
```

### Install the runtimes on Ubuntu or Debian Linux

These commands install the distribution's Python 3 and Node.js 24:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl ca-certificates
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt install -y nodejs
```

Verify:

```bash
python3 --version
node --version
npm --version
```

The Python version must be 3.11 or newer (Ubuntu 24.04 and Debian 12 or newer
provide a suitable system Python). On older distributions, install a newer
Python from that distribution's supported repository first.

For other Linux distributions, install Python 3.11 or newer with `venv` support
and Node.js 24 from that distribution's package manager or official installers.
On Ubuntu or Debian, install Electron's desktop libraries if you plan to use the
native window:

```bash
sudo apt install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libpangocairo-1.0-0
if apt-cache show libasound2t64 >/dev/null 2>&1; then
  sudo apt install -y libasound2t64
else
  sudo apt install -y libasound2
fi
```

On Fedora, the runtime setup is:

```bash
sudo dnf install -y python3.11 python3.11-pip curl ca-certificates
curl -fsSL https://rpm.nodesource.com/setup_24.x | sudo bash -
sudo dnf install -y nodejs
```

### Install the runtimes on macOS

Install [Homebrew](https://brew.sh/) if needed. Its official install command is:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install Python and Node.js:

```bash
brew install python@3.11 node@24
echo 'export PATH="$(brew --prefix node@24)/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Verify:

```bash
python3.11 --version
node --version
npm --version
```

### Install pnpm

Forge uses pnpm for the JavaScript workspace. With Node.js 24 installed, enable
the included Corepack shim and activate pnpm 10:

**Windows PowerShell** (use an Administrator PowerShell window if Corepack
cannot write its shims):

```powershell
corepack enable
corepack prepare pnpm@10 --activate
pnpm --version
```

**Linux** (Corepack may need permission to create the system shim):

```bash
sudo corepack enable
corepack prepare pnpm@10 --activate
pnpm --version
```

**macOS**

```bash
corepack enable
corepack prepare pnpm@10 --activate
pnpm --version
```

If `corepack` is not installed with Node.js, install pnpm directly:

**Windows PowerShell**

```powershell
npm install --global pnpm@10
pnpm --version
```

**macOS**

```bash
npm install --global pnpm@10
pnpm --version
```

**Linux**

```bash
sudo npm install --global pnpm@10
pnpm --version
```

Run the remaining commands from the project root. Setup creates a Python virtual
environment in `.venv`, installs every Python and JavaScript dependency from the
lockfiles/manifests, creates `.env` if needed, and builds the frontend. Forge
creates its local SQLite database automatically on first launch; no separate
database installation is needed.

## Windows (PowerShell)

```powershell
# Create and populate the Python virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Install the complete JavaScript workspace (pnpm was enabled above)
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
# Create and populate the Python virtual environment (Python must be >= 3.11)
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

# Install the complete JavaScript workspace (pnpm was enabled above)
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

# Install the complete JavaScript workspace (pnpm was enabled above)
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
