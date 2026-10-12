from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import quote, unquote

STATIC_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".webmanifest",
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
}
WRITABLE_SUFFIXES = STATIC_SUFFIXES
SOURCE_SUFFIXES = STATIC_SUFFIXES | {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".vue", ".svelte", ".astro", ".scss", ".sass", ".less", ".jsonc",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt", ".csv",
    ".xml", ".sql", ".graphql", ".gql",
}
BLOCKED_SOURCE_NAMES = {
    ".env", "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
BLOCKED_SOURCE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".db", ".sqlite"}
MAX_PREVIEW_FILE_BYTES = 2 * 1024 * 1024
MAX_RUNNING_APPS = 3
STARTUP_TIMEOUT_SECONDS = 30
MAX_PREVIEW_RUNTIME_SECONDS = 60 * 60
APP_URL_PREFIX = "/api/workspace/preview/server"


class WorkspacePreviewError(ValueError):
    pass


def local_app_previews_enabled() -> bool:
    in_replit = any(os.getenv(name) for name in ("REPL_ID", "REPLIT_DEV_DOMAIN", "REPLIT_DOMAINS"))
    return not in_replit and os.getenv("RUN_LOCAL_APP_PREVIEWS", "false").strip().lower() == "true"


def resolve_workspace_path(
    workspace: Path,
    relative_path: str | Path,
    *,
    allow_missing: bool = False,
) -> Path:
    raw = str(relative_path)
    root = workspace.resolve()
    windows_path = PureWindowsPath(raw)
    candidate = Path(raw)
    if (
        not raw
        or "\0" in raw
        or "\\" in raw
        or candidate.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part == ".." for part in PurePosixPath(raw).parts)
    ):
        raise PermissionError("Workspace operations require a safe workspace-relative path.")
    path = (root / candidate).resolve(strict=not allow_missing)
    if not path.is_relative_to(root):
        raise PermissionError("Workspace operations cannot access paths outside the workspace.")
    return path


def _safe_relative_parts(value: str) -> tuple[str, ...]:
    raw = unquote(value or "")
    if (
        not raw
        or len(raw) > 1000
        or raw.startswith(("/", "\\"))
        or "\\" in raw
        or "\0" in raw
        or PureWindowsPath(raw).is_absolute()
        or PureWindowsPath(raw).drive
    ):
        raise PermissionError("Workspace operations require a safe workspace-relative path.")
    parts = tuple(part for part in PurePosixPath(raw).parts if part not in {"", "."})
    if any(part == ".." for part in parts):
        raise PermissionError("Workspace operations cannot traverse to a parent directory.")
    if not parts or any(part.startswith(".") for part in parts):
        raise WorkspacePreviewError("Hidden files and parent-directory paths cannot be previewed.")
    if parts[0].lower() in {"uploads", "notes", "preview-runtime"}:
        raise WorkspacePreviewError("That workspace folder is private and cannot be previewed.")
    return parts


def resolve_workspace_asset(workspace: Path, relative_path: str, *, allow_missing: bool = False) -> Path:
    parts = _safe_relative_parts(relative_path)
    path = resolve_workspace_path(workspace, Path(*parts), allow_missing=allow_missing)
    root = workspace.resolve()
    resolved_parts = path.relative_to(root).parts
    if (
        not resolved_parts
        or resolved_parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in resolved_parts)
        or path.suffix.lower() not in STATIC_SUFFIXES
    ):
        raise WorkspacePreviewError("Only supported web assets inside the workspace can be previewed.")
    if not allow_missing and (not path.is_file() or path.stat().st_size > MAX_PREVIEW_FILE_BYTES):
        raise WorkspacePreviewError("The preview file is missing or larger than 2 MB.")
    return path


def resolve_workspace_script(workspace: Path, relative_path: str) -> Path:
    parts = _safe_relative_parts(relative_path)
    path = resolve_workspace_path(workspace, Path(*parts))
    root = workspace.resolve()
    resolved_parts = path.relative_to(root).parts
    if (
        not resolved_parts
        or resolved_parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in resolved_parts)
        or path.suffix.lower() != ".py"
        or not path.is_file()
    ):
        raise WorkspacePreviewError("Choose a Python script inside the workspace.")
    return path


def resolve_workspace_source_file(workspace: Path, relative_path: str, *, allow_missing: bool = False) -> Path:
    parts = _safe_relative_parts(relative_path)
    path = resolve_workspace_path(workspace, Path(*parts), allow_missing=allow_missing)
    resolved_parts = path.relative_to(workspace.resolve()).parts
    if (
        not resolved_parts
        or resolved_parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in resolved_parts)
        or path.name.casefold() in BLOCKED_SOURCE_NAMES
        or path.suffix.lower() in BLOCKED_SOURCE_SUFFIXES
        or path.suffix.lower() not in SOURCE_SUFFIXES
    ):
        raise WorkspacePreviewError("Only supported UTF-8 source and text files inside the workspace can be written.")
    if not allow_missing and (not path.is_file() or path.stat().st_size > MAX_PREVIEW_FILE_BYTES):
        raise WorkspacePreviewError("The workspace source file is missing or larger than 2 MB.")
    return path


def resolve_workspace_vite_project(workspace: Path, relative_path: str) -> Path:
    parts = _safe_relative_parts(relative_path)
    target = resolve_workspace_path(workspace, Path(*parts))
    root = workspace.resolve()
    if target.is_file() and target.name == "package.json":
        project = target.parent
    elif target.is_dir():
        project = target
    else:
        raise WorkspacePreviewError("Choose a project directory or its package.json for a Vite preview.")
    relative_project = project.relative_to(root)
    if (
        not relative_project.parts
        or relative_project.parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in relative_project.parts)
    ):
        raise WorkspacePreviewError("Vite projects must be inside a visible workspace folder.")
    package_file = project / "package.json"
    if not package_file.is_file() or package_file.stat().st_size > 1_000_000:
        raise WorkspacePreviewError("The Vite project needs a package.json no larger than 1 MB.")
    try:
        package = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkspacePreviewError("The Vite project's package.json is not valid JSON.") from error
    if not isinstance(package, dict) or not isinstance(package.get("scripts"), dict):
        raise WorkspacePreviewError("The Vite project needs a package.json with a dev script.")
    if not isinstance(package["scripts"].get("dev"), str):
        raise WorkspacePreviewError("The Vite project needs a package.json with a dev script.")
    vite_entry = project / "node_modules" / "vite" / "bin" / "vite.js"
    try:
        resolved_vite = resolve_workspace_path(
            workspace, vite_entry.relative_to(root).as_posix()
        )
    except (PermissionError, ValueError) as error:
        raise WorkspacePreviewError("Vite is not installed in this workspace project. Approve `npm install` first.") from error
    if not resolved_vite.is_file():
        raise WorkspacePreviewError("Vite is not installed in this workspace project. Approve `npm install` first.")
    return package_file


def static_preview_url(relative_path: str) -> str:
    parts = _safe_relative_parts(relative_path)
    return f"/api/workspace/preview/static/{quote('/'.join(parts), safe='/')}"


def write_workspace_asset(
    workspace: Path,
    relative_path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    payload = content.encode("utf-8")
    if len(payload) > MAX_PREVIEW_FILE_BYTES:
        raise WorkspacePreviewError("Generated app files must be 2 MB or smaller.")
    parts = _safe_relative_parts(relative_path)
    root = workspace.resolve()
    path = resolve_workspace_path(workspace, Path(*parts), allow_missing=True)
    resolved_parts = path.relative_to(root).parts
    if (
        not resolved_parts
        or resolved_parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in resolved_parts)
        or path.suffix.lower() not in WRITABLE_SUFFIXES
    ):
        raise WorkspacePreviewError("Only supported static web assets inside the workspace can be written.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.")
    if overwrite:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        try:
            with path.open("xb") as output:
                output.write(payload)
        except FileExistsError as exc:
            raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.") from exc
    return {
        "saved": True,
        "path": path.relative_to(workspace.resolve()).as_posix(),
        "sizeBytes": len(payload),
        "previewable": path.suffix.lower() in {".html", ".htm"},
    }


def write_workspace_app_script(
    workspace: Path,
    relative_path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    payload = content.encode("utf-8")
    if len(payload) > MAX_PREVIEW_FILE_BYTES:
        raise WorkspacePreviewError("Generated Python files must be 2 MB or smaller.")
    parts = _safe_relative_parts(relative_path)
    root = workspace.resolve()
    path = resolve_workspace_path(workspace, Path(*parts), allow_missing=True)
    resolved_parts = path.relative_to(root).parts
    if (
        not resolved_parts
        or resolved_parts[0].lower() in {"uploads", "notes", "preview-runtime"}
        or any(part.startswith(".") for part in resolved_parts)
        or path.suffix.lower() != ".py"
    ):
        raise WorkspacePreviewError("Only Python source files inside the workspace can be written.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.")
    if overwrite:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        try:
            with path.open("xb") as output:
                output.write(payload)
        except FileExistsError as exc:
            raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.") from exc
    return {
        "saved": True,
        "path": path.relative_to(root).as_posix(),
        "sizeBytes": len(payload),
        "previewable": False,
    }


def write_workspace_source_file(
    workspace: Path,
    relative_path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    payload = content.encode("utf-8")
    if len(payload) > MAX_PREVIEW_FILE_BYTES:
        raise WorkspacePreviewError("Generated source files must be 2 MB or smaller.")
    path = resolve_workspace_source_file(workspace, relative_path, allow_missing=True)
    root = workspace.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.")
    if overwrite:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        try:
            with path.open("xb") as output:
                output.write(payload)
        except FileExistsError as error:
            raise WorkspacePreviewError("That workspace file already exists. Ask before replacing it.") from error
    return {
        "saved": True,
        "path": path.relative_to(root).as_posix(),
        "sizeBytes": len(payload),
        "previewable": path.suffix.lower() in {".html", ".htm"},
    }


@dataclass
class PreviewProcess:
    app_id: str
    framework: str
    entry_path: str
    port: int
    local_url: str
    preview_url: str
    started_at: str
    process: subprocess.Popen[str]
    wrapper_path: Path | None = None
    runtime_path: Path | None = None
    runtime_timer: threading.Timer | None = None
    output_lines: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    output_lock: threading.Lock = field(default_factory=threading.Lock)
    reader_thread: threading.Thread | None = None


class WorkspacePreviewManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self._apps: dict[str, PreviewProcess] = {}
        self._lock = threading.RLock()

    def _read_output(self, app: PreviewProcess) -> None:
        stream = app.process.stdout
        if stream is None:
            return
        for line in stream:
            with app.output_lock:
                app.output_lines.append(line.rstrip()[:2000])

    def _log_tail(self, app: PreviewProcess) -> str:
        with app.output_lock:
            return "\n".join(list(app.output_lines)[-8:])[-3000:]

    def _purge_exited(self) -> None:
        with self._lock:
            for app_id, app in list(self._apps.items()):
                if app.process.poll() is not None:
                    self._cleanup(app_id, app, terminate=False)

    def _choose_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _child_environment(self, port: int, prefix: str) -> dict[str, str]:
        app_id = prefix.rsplit("/", 1)[-1]
        runtime_dir = resolve_workspace_path(
            self.workspace, Path("preview-runtime") / app_id, allow_missing=True
        )
        home_dir = runtime_dir / "home"
        temp_dir = runtime_dir / "tmp"
        home_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        python_paths = [str(self.workspace)]
        python_paths.extend(
            value
            for value in sys.path
            if value
            and Path(value).is_dir()
            and ("site-packages" in value or "dist-packages" in value)
        )
        child_env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home_dir),
            "USERPROFILE": str(home_dir),
            "TMP": str(temp_dir),
            "TEMP": str(temp_dir),
            "TMPDIR": str(temp_dir),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join(dict.fromkeys(python_paths)),
            "PORT": str(port),
            "HOST": "127.0.0.1",
            "BIND_HOST": "127.0.0.1",
            "WORKSPACE_PREVIEW_BASE_PATH": prefix,
            "NODE_ENV": "development",
            "BROWSER": "none",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        }
        for name in ("SYSTEMROOT", "WINDIR"):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        return child_env

    def _command(
        self,
        framework: str,
        script: Path,
        app_id: str,
        port: int,
        runtime_dir: Path,
    ) -> tuple[list[str], Path | None]:
        prefix = f"{APP_URL_PREFIX}/{app_id}"
        if framework == "streamlit":
            command = [
                sys.executable, "-m", "streamlit", "run", str(script),
                "--server.address=127.0.0.1",
                f"--server.port={port}",
                f"--server.baseUrlPath={prefix.lstrip('/')}",
                "--server.headless=true",
                "--server.enableCORS=false",
                "--browser.gatherUsageStats=false",
            ]
            return command, None
        if framework == "flask":
            runtime_dir.mkdir(parents=True, exist_ok=True)
            wrapper_path = runtime_dir / "workspace-preview-flask.py"
            wrapper_path.write_text(
                "import importlib.util, sys\n"
                "from pathlib import Path\n"
                "script = Path(sys.argv[1]).resolve()\n"
                "prefix = sys.argv[2]\n"
                "port = int(sys.argv[3])\n"
                "sys.path.insert(0, str(script.parent))\n"
                "sys.path.insert(0, str(script.parent.parent))\n"
                "spec = importlib.util.spec_from_file_location('workspace_preview_app', script)\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "app = getattr(module, 'app', None) or getattr(module, 'application', None)\n"
                "if app is None and callable(getattr(module, 'create_app', None)):\n"
                "    app = module.create_app()\n"
                "if not callable(app):\n"
                "    raise RuntimeError('Flask script must export app, application, or create_app().')\n"
                "from werkzeug.middleware.dispatcher import DispatcherMiddleware\n"
                "from werkzeug.serving import run_simple\n"
                "from werkzeug.wrappers import Response\n"
                "mounted = DispatcherMiddleware(Response('Not found', status=404), {prefix: app})\n"
                "run_simple('127.0.0.1', port, mounted, threaded=True, use_reloader=False)\n",
                encoding="utf-8",
            )
            return [sys.executable, str(wrapper_path), str(script), prefix, str(port)], wrapper_path
        if framework == "fastapi":
            runtime_dir.mkdir(parents=True, exist_ok=True)
            wrapper_path = runtime_dir / "workspace-preview-fastapi.py"
            wrapper_path.write_text(
                "import importlib.util, sys\n"
                "from pathlib import Path\n"
                "script = Path(sys.argv[1]).resolve()\n"
                "port = int(sys.argv[2])\n"
                "prefix = sys.argv[3]\n"
                "sys.path.insert(0, str(script.parent))\n"
                "spec = importlib.util.spec_from_file_location('workspace_preview_app', script)\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "app = getattr(module, 'app', None) or getattr(module, 'application', None)\n"
                "if app is None and callable(getattr(module, 'create_app', None)):\n"
                "    app = module.create_app()\n"
                "if app is None:\n"
                "    raise RuntimeError('FastAPI script must export app, application, or create_app().')\n"
                "import uvicorn\n"
                "class PreviewPrefix:\n"
                "    def __init__(self, child, mount):\n"
                "        self.child, self.mount = child, mount\n"
                "    async def __call__(self, scope, receive, send):\n"
                "        if scope.get('type') in {'http', 'websocket'}:\n"
                "            path = scope.get('path', '')\n"
                "            if path == self.mount or path.startswith(self.mount + '/'):\n"
                "                scope = dict(scope)\n"
                "                scope['path'] = path[len(self.mount):] or '/'\n"
                "                scope['root_path'] = self.mount\n"
                "                scope['raw_path'] = scope['path'].encode('utf-8')\n"
                "        await self.child(scope, receive, send)\n"
                "uvicorn.run(PreviewPrefix(app, prefix), host='127.0.0.1', port=port, "
                "proxy_headers=False, access_log=False)\n",
                encoding="utf-8",
            )
            return [sys.executable, str(wrapper_path), str(script), str(port), prefix], wrapper_path
        if framework == "vite":
            node = shutil.which("node")
            if not node:
                raise WorkspacePreviewError("Node.js is required to launch a Vite preview.")
            project = script.parent
            vite_entry = project / "node_modules" / "vite" / "bin" / "vite.js"
            project_root = project.relative_to(self.workspace).as_posix()
            return [
                node,
                str(vite_entry),
                project_root,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
                "--base",
                f"{prefix}/",
            ], None
        raise WorkspacePreviewError("Choose static, Flask, Streamlit, FastAPI, or Vite preview mode.")

    async def _wait_for_listening(self, app: PreviewProcess) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if app.process.poll() is not None:
                break
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", app.port),
                    timeout=0.4,
                )
                writer.close()
                await writer.wait_closed()
                return
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.25)
        logs = self._log_tail(app)
        self.stop(app.app_id)
        detail = f" App output: {logs}" if logs else ""
        raise WorkspacePreviewError(f"The {app.framework} app did not start listening within 30 seconds.{detail}")

    async def launch(self, framework: str, entry_path: str) -> dict[str, Any]:
        framework = framework.lower().strip()
        if framework == "static":
            asset = resolve_workspace_asset(self.workspace, entry_path)
            if asset.suffix.lower() not in {".html", ".htm"}:
                raise WorkspacePreviewError("Static preview entry points must be HTML files.")
            relative = asset.relative_to(self.workspace).as_posix()
            preview_url = static_preview_url(relative)
            main_port = int(os.getenv("PORT", "8000"))
            return {
                "started": True,
                "framework": "static",
                "entryPath": relative,
                "port": main_port,
                "localUrl": f"http://127.0.0.1:{main_port}{preview_url}",
                "previewUrl": preview_url,
                "status": "ready",
            }
        if framework not in {"flask", "streamlit", "fastapi", "vite"}:
            raise WorkspacePreviewError("Choose static, Flask, Streamlit, FastAPI, or Vite preview mode.")
        if not local_app_previews_enabled():
            raise PermissionError(
                "Local app previews are disabled. Enable “Enable Local App Previews "
                "(Unrestricted Workspace Execution)” in Preferences on a local copy. They are always "
                "disabled in Replit Cloud."
            )
        script = (
            resolve_workspace_vite_project(self.workspace, entry_path)
            if framework == "vite"
            else resolve_workspace_script(self.workspace, entry_path)
        )
        with self._lock:
            self._purge_exited()
            if len(self._apps) >= MAX_RUNNING_APPS:
                raise WorkspacePreviewError(f"Stop a running preview before starting another (limit {MAX_RUNNING_APPS}).")
        app_id = str(uuid.uuid4())
        port = self._choose_port()
        prefix = f"{APP_URL_PREFIX}/{app_id}"
        runtime_path = resolve_workspace_path(
            self.workspace, Path("preview-runtime") / app_id, allow_missing=True
        )
        runtime_path.mkdir(parents=True, exist_ok=True)
        command, wrapper_path = self._command(framework, script, app_id, port, runtime_path)
        child_env = self._child_environment(port, prefix)
        process_options: dict[str, Any] = {
            "cwd": str(self.workspace),
            "env": child_env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        if os.name == "nt":
            process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_options["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **process_options)
        except (OSError, subprocess.SubprocessError):
            shutil.rmtree(runtime_path, ignore_errors=True)
            raise
        started_at = datetime.now(timezone.utc).isoformat()
        app = PreviewProcess(
            app_id=app_id,
            framework=framework,
            entry_path=script.relative_to(self.workspace).as_posix(),
            port=port,
            local_url=f"http://127.0.0.1:{port}{prefix}",
            preview_url=prefix,
            started_at=started_at,
            process=process,
            wrapper_path=wrapper_path,
            runtime_path=runtime_path,
        )
        with self._lock:
            self._apps[app_id] = app
            app.runtime_timer = threading.Timer(
                MAX_PREVIEW_RUNTIME_SECONDS, self.stop, args=(app_id,)
            )
            app.runtime_timer.daemon = True
            app.runtime_timer.start()
        app.reader_thread = threading.Thread(target=self._read_output, args=(app,), daemon=True)
        app.reader_thread.start()
        await self._wait_for_listening(app)
        return {"started": True, **self._public_app(app)}

    def _public_app(self, app: PreviewProcess) -> dict[str, Any]:
        return {
            "id": app.app_id,
            "framework": app.framework,
            "entryPath": app.entry_path,
            "port": app.port,
            "localUrl": app.local_url,
            "previewUrl": app.preview_url,
            "status": "running",
            "startedAt": app.started_at,
        }

    def get_status(self) -> dict[str, Any]:
        self._purge_exited()
        entry_path = "index.html"
        try:
            entry = resolve_workspace_asset(self.workspace, entry_path)
            if entry.suffix.lower() not in {".html", ".htm"}:
                entry = None
        except (WorkspacePreviewError, OSError):
            entry = None
        with self._lock:
            apps = [self._public_app(app) for app in self._apps.values()]
        return {
            "staticAvailable": entry is not None,
            "staticEntryPath": entry_path if entry is not None else None,
            "staticPreviewUrl": static_preview_url(entry_path) if entry is not None else None,
            "pythonPreviewsEnabled": local_app_previews_enabled(),
            "localAppPreviewsEnabled": local_app_previews_enabled(),
            "pythonPreviewRuntimeLimitSeconds": MAX_PREVIEW_RUNTIME_SECONDS,
            "apps": apps,
        }

    def list_apps(self) -> list[dict[str, Any]]:
        self._purge_exited()
        with self._lock:
            return [self._public_app(app) for app in self._apps.values()]

    def get_app(self, app_id: str) -> PreviewProcess | None:
        try:
            app_id = str(uuid.UUID(app_id))
        except (ValueError, AttributeError):
            return None
        self._purge_exited()
        with self._lock:
            return self._apps.get(app_id)

    def _cleanup(self, app_id: str, app: PreviewProcess, *, terminate: bool) -> None:
        self._apps.pop(app_id, None)
        if app.runtime_timer and threading.current_thread() is not app.runtime_timer:
            app.runtime_timer.cancel()
        if terminate and app.process.poll() is None:
            try:
                if os.name == "nt":
                    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
                    taskkill = Path(system_root) / "System32" / "taskkill.exe"
                    subprocess.run(
                        [str(taskkill), "/PID", str(app.process.pid), "/T", "/F"],
                        cwd=str(self.workspace),
                        env={"SYSTEMROOT": system_root, "WINDIR": system_root},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                    app.process.wait(timeout=2)
                else:
                    os.killpg(app.process.pid, signal.SIGTERM)
                app.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "nt":
                        app.process.kill()
                    else:
                        os.killpg(app.process.pid, signal.SIGKILL)
                    app.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if app.runtime_path:
            shutil.rmtree(app.runtime_path, ignore_errors=True)
        elif app.wrapper_path:
            app.wrapper_path.unlink(missing_ok=True)
        if app.reader_thread and app.reader_thread is not threading.current_thread():
            app.reader_thread.join(timeout=0.2)
        if app.process.stdout:
            app.process.stdout.close()

    def stop(self, app_id: str) -> bool:
        try:
            app_id = str(uuid.UUID(app_id))
        except (ValueError, AttributeError):
            return False
        with self._lock:
            app = self._apps.get(app_id)
            if not app:
                return False
            self._cleanup(app_id, app, terminate=True)
            return True

    def stop_all(self) -> int:
        with self._lock:
            stopped = 0
            for app_id in list(self._apps):
                app = self._apps.get(app_id)
                if app:
                    self._cleanup(app_id, app, terminate=True)
                    stopped += 1
            return stopped

