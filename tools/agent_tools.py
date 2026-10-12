from __future__ import annotations

import os
import re
import shlex
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


def validate_terminal_command(command: str, cwd: str = ".") -> list[str]:
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
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as error:
        raise PermissionError("The command quoting is invalid.") from error
    if not argv or len(argv) > 128 or any(len(part) > 1_000 for part in argv):
        raise PermissionError("The command has an invalid number or size of arguments.")

    executable = Path(argv[0].replace("\\", "/")).name.casefold()
    if executable in _SHELL_LAUNCHERS:
        raise PermissionError("Shell interpreters are not accepted; pass a script file to Python or Node instead.")
    if executable in {"python", "python3", "python.exe", "python3.exe", "py", "node", "node.exe"}:
        if any(argument.casefold() in _INLINE_SCRIPT_FLAGS for argument in argv[1:3]):
            raise PermissionError("Inline script execution is blocked; use a workspace script file.")
    return argv


def run_approved_terminal_command(
    workspace: Path,
    command: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Run an already-approved command without a shell and with a scrubbed environment."""
    argv = validate_terminal_command(command, cwd)
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
        }
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        try:
            result = subprocess.run(
                argv,
                cwd=root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TERMINAL_TIMEOUT_SECONDS,
                env=child_env,
                check=False,
            )
            return {
                "returnCode": result.returncode,
                "timedOut": False,
                "stdout": (result.stdout or "")[-MAX_TERMINAL_OUTPUT_CHARS:],
                "stderr": (result.stderr or "")[-4_000:],
            }
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return {
                "returnCode": -1,
                "timedOut": True,
                "stdout": str(stdout)[-MAX_TERMINAL_OUTPUT_CHARS:],
                "stderr": str(stderr)[-4_000:],
            }

