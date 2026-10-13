from __future__ import annotations

import asyncio
import os
import json
import inspect
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import httpx
from websockets.asyncio.client import connect as websocket_connect

MAX_TERMINAL_COMMAND_LENGTH = 4_000
MAX_TERMINAL_OUTPUT_CHARS = 12_000
TERMINAL_TIMEOUT_SECONDS = 30
MAX_BLENDER_SCRIPT_BYTES = 64_000
BLENDER_TIMEOUT_SECONDS = 600
MAX_ENGINE_PAYLOAD_BYTES = 32_000
ENGINE_REQUEST_TIMEOUT_SECONDS = 12
MAX_ENGINE_RESPONSE_CHARS = 12_000
RENDER_SUFFIXES = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff"}
WEBSOCKET_CONNECT_SUPPORTS_PROXY = "proxy" in inspect.signature(websocket_connect).parameters
PRIVATE_ENGINE_PATHS = {
    ".agent-packages",
    "assistant.db",
    "logs",
    "notes",
    "preview-runtime",
    "uploads",
    "vault",
}

_BLOCKED_PATTERNS = (
    r"\brmdir\b",
    r"\bdel(?:ete)?\b",
    r"\berase\b",
    r"\bformat(?:\.com|\.exe)?\b",
    r"\bdiskpart(?:\.exe)?\b",
    r"\breg(?:\.exe)?\s+delete\b",
    r"\b(?:powershell|pwsh)(?:\.exe)?\b.*\bremove-item\b.*(?:-recurse|-r\b)",
    r"\bremove-item\b.*(?:-recurse|-r\b)",
    r"\bshutdown(?:\.exe)?\b",
    r"\brm\b.*(?:-r|-f)",
    r"\bshred\b",
    r"\b(?:sudo|su|runas|pkexec)\b",
    r"\b(?:mkfs|diskutil\s+erase|dd\s+if=)\b",
)
_SHELL_LAUNCHERS = {
    "bash", "cmd", "cmd.exe", "fish", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "sh", "zsh",
}
_INLINE_SCRIPT_FLAGS = {"-c", "-e", "--eval", "--execute"}


def validate_terminal_command(
    command: str,
    cwd: str = ".",
    *,
    windows: bool | None = None,
) -> list[str]:
    """Parse exactly one non-shell command for an explicit local approval."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_TERMINAL_COMMAND_LENGTH:
        raise PermissionError("Provide one terminal command, up to 4,000 characters.")
    if cwd != ".":
        raise PermissionError("Terminal commands must use the workspace root as their working directory.")
    normalized = command.casefold()
    if any(re.search(pattern, normalized) for pattern in _BLOCKED_PATTERNS):
        raise PermissionError("Known destructive or administrative commands are blocked.")
    if any(char in command for char in ";&|><`$\n\r"):
        raise PermissionError("Shell operators, substitutions, redirection, and command chaining are blocked.")
    use_windows = os.name == "nt" if windows is None else windows
    try:
        argv = shlex.split(command, posix=not use_windows)
        if use_windows:
            argv = [
                part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'} else part
                for part in argv
            ]
    except ValueError as error:
        raise PermissionError("The command quoting is invalid.") from error
    if not argv or len(argv) > 128 or any(len(part) > 1_000 for part in argv):
        raise PermissionError("The command has an invalid number or size of arguments.")

    executable = Path(argv[0].replace("\\", "/")).name.casefold()
    if executable in _SHELL_LAUNCHERS:
        raise PermissionError("Shell interpreters are not accepted; pass a script file to Python or Node instead.")
    if executable in {"python", "python3", "python.exe", "python3.exe", "py", "node", "node.exe"}:
        inline_prefixes = ("-c", "-e", "--eval=", "--execute=")
        if any(
            argument.casefold() in _INLINE_SCRIPT_FLAGS
            or argument.casefold().startswith(inline_prefixes)
            for argument in argv[1:3]
        ):
            raise PermissionError("Inline script execution is blocked; use a workspace script file.")
    return argv


def prepare_terminal_argv(argv: list[str], *, windows: bool | None = None) -> list[str]:
    """Avoid shell execution for Windows npm shims by invoking npm's JS CLI via node."""
    use_windows = os.name == "nt" if windows is None else windows
    if not use_windows:
        return argv
    executable = Path(argv[0].replace("\\", "/")).name.casefold()
    if executable not in {"npm", "npm.cmd", "npx", "npx.cmd"}:
        if executable.endswith((".cmd", ".bat")):
            raise PermissionError("Windows batch commands are not accepted; use a supported executable directly.")
        return argv

    node = shutil.which("node.exe") or shutil.which("node")
    npm_shim = shutil.which("npm.cmd") or shutil.which("npm")
    if not node or not npm_shim:
        raise PermissionError("Node.js and its npm CLI must be installed to run npm commands.")
    npm_root = Path(npm_shim).resolve().parent
    node_root = Path(node).resolve().parent
    cli_name = "npx-cli.js" if executable.startswith("npx") else "npm-cli.js"
    candidates = (
        node_root / "node_modules" / "npm" / "bin" / cli_name,
        npm_root / "node_modules" / "npm" / "bin" / cli_name,
        npm_root.parent / "node_modules" / "npm" / "bin" / cli_name,
        npm_root / "node_modules" / "npm" / "bin" / ("npx-cli.js" if cli_name == "npm-cli.js" else "npm-cli.js"),
    )
    cli = next((candidate for candidate in candidates if candidate.is_file()), None)
    if cli is None:
        raise PermissionError("Could not locate the npm JavaScript CLI; refusing to use a shell wrapper.")
    return [node, str(cli), *argv[1:]]


def run_approved_terminal_command(
    workspace: Path,
    command: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Run an already-approved command without a shell and with a scrubbed environment."""
    argv = validate_terminal_command(command, cwd)
    argv = prepare_terminal_argv(argv)
    root = workspace.resolve()
    if not root.is_dir():
        raise PermissionError("The workspace directory is unavailable.")

    with tempfile.TemporaryDirectory(prefix="forge-command-") as temporary:
        temporary_home = Path(temporary)
        package_target = root / ".agent-packages"
        child_env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(temporary_home),
            "USERPROFILE": str(temporary_home),
            "TMP": str(temporary_home),
            "TEMP": str(temporary_home),
            "TMPDIR": str(temporary_home),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(package_target),
            "PIP_TARGET": str(package_target),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_CACHE_DIR": "1",
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "NPM_CONFIG_CACHE": str(temporary_home / "npm-cache"),
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
            "APPDATA": str(temporary_home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(temporary_home / "AppData" / "Local"),
        }
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_options["start_new_session"] = True
        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = subprocess.Popen(
                    argv,
                    cwd=root,
                    shell=False,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=child_env,
                    **process_options,
                )
                timed_out = False
                try:
                    process.wait(timeout=TERMINAL_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    if os.name == "nt":
                        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
                        if taskkill:
                            try:
                                subprocess.run(
                                    [taskkill, "/F", "/T", "/PID", str(process.pid)],
                                    shell=False,
                                    capture_output=True,
                                    timeout=5,
                                    env=child_env,
                                    check=False,
                                )
                            except (OSError, subprocess.SubprocessError):
                                process.kill()
                        else:
                            process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                stdout_file.seek(0, os.SEEK_END)
                stdout_size = stdout_file.tell()
                stdout_file.seek(max(0, stdout_size - MAX_TERMINAL_OUTPUT_CHARS))
                stderr_file.seek(0, os.SEEK_END)
                stderr_size = stderr_file.tell()
                stderr_file.seek(max(0, stderr_size - 4_000))
                stdout = stdout_file.read().decode("utf-8", errors="replace")
                stderr = stderr_file.read().decode("utf-8", errors="replace")
            return {
                "returnCode": -1 if timed_out else int(process.returncode or 0),
                "timedOut": timed_out,
                "stdout": stdout,
                "stderr": stderr,
            }
        except OSError as error:
            return {
                "returnCode": -1,
                "timedOut": False,
                "stdout": "",
                "stderr": str(error)[-4_000:],
            }


def _workspace_relative_path(
    workspace: Path,
    relative_path: str,
    *,
    allow_missing: bool,
) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip() or "\x00" in relative_path:
        raise PermissionError("Provide a workspace-relative path.")
    normalized = relative_path.replace("\\", "/")
    segments = normalized.split("/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or any(
        segment in {"", ".", ".."} for segment in segments
    ):
        raise PermissionError("Absolute paths, traversal, and empty path segments are blocked.")
    if any(segment.startswith(".") or segment.casefold() in PRIVATE_ENGINE_PATHS for segment in segments):
        raise PermissionError("Hidden or private assistant paths are not available to engine tools.")

    root = workspace.resolve()
    candidate = root.joinpath(*segments)
    current = root
    for segment in segments:
        current = current / segment
        if current.is_symlink():
            raise PermissionError("Symbolic links are not available to engine tools.")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise PermissionError("Engine paths must stay inside workspace/.")
    if not allow_missing and not resolved.is_file():
        raise PermissionError("The selected Blender project must be an existing workspace file.")
    return resolved


def validate_blender_request(
    workspace: Path,
    script_content: str,
    blend_filepath: str | None = None,
    render_output_path: str | None = None,
) -> dict[str, str | None]:
    if not isinstance(script_content, str) or not script_content.strip():
        raise PermissionError("Provide a non-empty Blender Python script.")
    if len(script_content.encode("utf-8")) > MAX_BLENDER_SCRIPT_BYTES:
        raise PermissionError("Blender scripts are limited to 64 KB.")

    blend_path: Path | None = None
    blend_relative: str | None = None
    if blend_filepath:
        blend_path = _workspace_relative_path(workspace, blend_filepath, allow_missing=False)
        if blend_path.suffix.casefold() != ".blend":
            raise PermissionError("The Blender project path must end in .blend.")
        blend_relative = blend_path.relative_to(workspace.resolve()).as_posix()

    render_path: Path | None = None
    render_relative: str | None = None
    if render_output_path:
        render_path = _workspace_relative_path(workspace, render_output_path, allow_missing=True)
        if render_path.suffix.casefold() not in RENDER_SUFFIXES:
            raise PermissionError("Choose a PNG, JPG, EXR, TIF, or TIFF render output path.")
        if render_path.exists() or (
            render_path.parent.is_dir()
            and any(
                item.is_file() and item.name.casefold().startswith(render_path.stem.casefold())
                for item in render_path.parent.iterdir()
            )
        ):
            raise PermissionError("That render output already exists. Choose a new path to avoid overwriting it.")
        render_relative = render_path.relative_to(workspace.resolve()).as_posix()

    return {"blend_filepath": blend_relative, "render_output_path": render_relative}


def _engine_child_environment(temporary_home: Path) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(temporary_home),
        "USERPROFILE": str(temporary_home),
        "TMP": str(temporary_home),
        "TEMP": str(temporary_home),
        "TMPDIR": str(temporary_home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "BLENDER_USER_CONFIG": str(temporary_home / "blender-config"),
        "BLENDER_USER_SCRIPTS": str(temporary_home / "blender-scripts"),
        "BLENDER_USER_DATAFILES": str(temporary_home / "blender-data"),
    }
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
    return environment


def run_blender_automation(
    script_content: str,
    blend_filepath: str | None = None,
    render_output_path: str | None = None,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Run an explicitly approved Blender script from a local workspace."""
    workspace = workspace or Path(__file__).resolve().parents[1] / "workspace"
    validated = validate_blender_request(
        workspace, script_content, blend_filepath, render_output_path
    )
    root = workspace.resolve()
    blender = shutil.which("blender")
    if not blender:
        return {
            "ok": False,
            "returnCode": -1,
            "timedOut": False,
            "error": "Blender CLI was not found on PATH. Install Blender locally before enabling this tool.",
            "stdout": "",
            "stderr": "",
            "renderedOutputPaths": [],
        }

    blend = validated["blend_filepath"]
    render = validated["render_output_path"]
    blend_path = _workspace_relative_path(root, blend, allow_missing=False) if blend else None
    render_path = _workspace_relative_path(root, render, allow_missing=True) if render else None
    if render_path:
        render_path.parent.mkdir(parents=True, exist_ok=True)
        validate_blender_request(
            root,
            script_content,
            validated["blend_filepath"],
            validated["render_output_path"],
        )

    with tempfile.TemporaryDirectory(prefix="forge-blender-") as temporary:
        temporary_root = Path(temporary)
        script_path = temporary_root / "temp_blender_task.py"
        script_path.write_text(script_content, encoding="utf-8")
        argv = [blender]
        if blend_path:
            argv.append(str(blend_path))
        argv.extend(["--background", "--disable-autoexec", "--python-exit-code", "1"])
        if render_path:
            argv.extend(["--render-output", str(render_path)])
        argv.extend(["--python", str(script_path)])
        environment = _engine_child_environment(temporary_root / "home")
        Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_options["start_new_session"] = True
        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = subprocess.Popen(
                    argv,
                    cwd=root,
                    shell=False,
                    env=environment,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    **process_options,
                )
                timed_out = False
                try:
                    process.wait(timeout=BLENDER_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    if os.name == "nt":
                        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
                        if taskkill:
                            try:
                                subprocess.run(
                                    [taskkill, "/F", "/T", "/PID", str(process.pid)],
                                    shell=False,
                                    capture_output=True,
                                    timeout=5,
                                    env=environment,
                                    check=False,
                                )
                            except (OSError, subprocess.SubprocessError):
                                process.kill()
                        else:
                            process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                def tail_text(file_obj, limit: int) -> str:
                    file_obj.seek(0, os.SEEK_END)
                    size = file_obj.tell()
                    file_obj.seek(max(0, size - limit))
                    return file_obj.read().decode("utf-8", errors="replace")

                stdout = tail_text(stdout_file, MAX_TERMINAL_OUTPUT_CHARS)
                stderr = tail_text(stderr_file, 4_000)

        except OSError as error:
            return {
                "ok": False,
                "returnCode": -1,
                "timedOut": False,
                "error": str(error)[-1_000:],
                "stdout": "",
                "stderr": "",
                "renderedOutputPaths": [],
            }

    rendered_paths: list[str] = []
    if render_path:
        if render_path.is_file():
            rendered_paths.append(render_path.relative_to(root).as_posix())
        elif render_path.parent.is_dir():
            prefix = render_path.stem.casefold()
            rendered_paths.extend(
                item.relative_to(root).as_posix()
                for item in sorted(render_path.parent.iterdir(), key=lambda entry: entry.name.casefold())
                if item.is_file() and item.name.casefold().startswith(prefix)
            )
    return {
        "ok": not timed_out and process.returncode == 0,
        "returnCode": -1 if timed_out else int(process.returncode or 0),
        "timedOut": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "errorTrace": stderr if process.returncode != 0 or timed_out else "",
        "renderOutputPath": render,
        "renderedOutputPaths": rendered_paths,
    }


def validate_engine_endpoint(endpoint_url: str) -> str:
    if not isinstance(endpoint_url, str) or len(endpoint_url) > 2_000:
        raise PermissionError("Provide a valid local engine listener URL.")
    try:
        parsed = urlsplit(endpoint_url.strip())
        port = parsed.port
    except ValueError as error:
        raise PermissionError("The engine listener URL has an invalid port.") from error
    if (
        parsed.scheme not in {"http", "ws"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise PermissionError("Engine commands may only target an HTTP or WebSocket listener on localhost.")
    return endpoint_url.strip()


def validate_engine_remote_request(
    engine: str,
    endpoint_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if engine not in {"unreal", "blender"}:
        raise PermissionError("Choose either the unreal or blender engine.")
    url = validate_engine_endpoint(endpoint_url)
    if not isinstance(payload, dict):
        raise PermissionError("Engine command payload must be a JSON object.")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PermissionError("Engine command payload must contain valid JSON values.") from error
    if len(encoded.encode("utf-8")) > MAX_ENGINE_PAYLOAD_BYTES:
        raise PermissionError("Engine command payloads are limited to 32 KB.")
    return {"engine": engine, "endpoint_url": url, "payload": payload}


async def send_engine_remote_command(
    engine: str,
    endpoint_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send one approved JSON command to a local Unreal/Blender engine listener."""
    request = validate_engine_remote_request(engine, endpoint_url, payload)
    url = str(request["endpoint_url"])
    encoded = json.dumps(request["payload"], ensure_ascii=False, allow_nan=False)

    if url.startswith("ws://"):
        try:
            connect_options: dict[str, Any] = {
                "open_timeout": 4,
                "close_timeout": 2,
                "max_size": MAX_ENGINE_RESPONSE_CHARS * 4,
            }
            if WEBSOCKET_CONNECT_SUPPORTS_PROXY:
                connect_options["proxy"] = None
            async with websocket_connect(url, **connect_options) as connection:
                await connection.send(encoded)
                reply = await asyncio.wait_for(connection.recv(), timeout=ENGINE_REQUEST_TIMEOUT_SECONDS)
        except Exception as error:
            return {"ok": False, "engine": engine, "transport": "websocket", "error": str(error)[:1_000]}
        content = reply if isinstance(reply, str) else reply.decode("utf-8", errors="replace")
        if len(content) > MAX_ENGINE_RESPONSE_CHARS:
            return {
                "ok": True,
                "engine": engine,
                "transport": "websocket",
                "response": {
                    "truncated": True,
                    "preview": content[:MAX_ENGINE_RESPONSE_CHARS],
                },
            }
        try:
            response: Any = json.loads(content)
        except json.JSONDecodeError:
            response = content[:MAX_ENGINE_RESPONSE_CHARS]
        return {"ok": True, "engine": engine, "transport": "websocket", "response": response}

    try:
        async with httpx.AsyncClient(
            timeout=ENGINE_REQUEST_TIMEOUT_SECONDS,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Accept": "application/json"},
            ) as response:
                status_code = response.status_code
                is_success = response.is_success
                body_bytes = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = MAX_ENGINE_RESPONSE_CHARS - len(body_bytes)
                    body_bytes.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break
        body_text = bytes(body_bytes).decode("utf-8", errors="replace")
        if truncated:
            body: Any = {"truncated": True, "preview": body_text}
        else:
            try:
                body = json.loads(body_text)
            except json.JSONDecodeError:
                body = body_text
        return {
            "ok": is_success,
            "engine": engine,
            "transport": "http",
            "statusCode": status_code,
            "response": body,
            **({"error": "The local engine returned an HTTP error."} if not is_success else {}),
        }
    except httpx.HTTPError as error:
        return {"ok": False, "engine": engine, "transport": "http", "error": str(error)[:1_000]}

