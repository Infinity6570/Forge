from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MAX_TERMINAL_COMMAND_LENGTH = 4_000
MAX_TERMINAL_OUTPUT_CHARS = 12_000
TERMINAL_TIMEOUT_SECONDS = 30

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

