from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_LOG_PATH = PROJECT_ROOT / "logs" / "elevated_audit.log"
MAX_ELEVATED_COMMAND_LENGTH = 4000
_AUDIT_LOCK = threading.Lock()
_COMMAND_SEPARATORS = re.compile(r"[;&|<>]|\$\(|`")
_BLOCKED_COMMANDS = (
    re.compile(r"\b(?:rmdir|rd)\b[^\r\n]*(?:/s\b|-s\b)", re.IGNORECASE),
    re.compile(r"\bdel\b[^\r\n]*(?:/[fsq]\b)", re.IGNORECASE),
    re.compile(r"\bformat(?:\.com)?\b", re.IGNORECASE),
    re.compile(r"\bdiskpart(?:\.exe)?\b", re.IGNORECASE),
    re.compile(r"\breg(?:\.exe)?\s+delete\b", re.IGNORECASE),
    re.compile(
        r"\b(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*(?:\bremove-item\b[^\r\n]*(?:-recurse|-r\b)|-(?:enc|encodedcommand)\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\bshutdown(?:\.exe)?\b", re.IGNORECASE),
    re.compile(r"\brm\b[^\r\n]*(?:\s-[^\s]*r[^\s]*\b|\s--recursive\b)", re.IGNORECASE),
    re.compile(r"\b(?:mkfs(?:\.[\w-]+)?|wipefs|shred|reboot|poweroff|halt|fdisk|parted|userdel)\b", re.IGNORECASE),
    re.compile(r"\bdd\b[^\r\n]*\bof=/dev/", re.IGNORECASE),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)*)?|node|ruby|perl|php)\s+-(?:c|e)\b", re.IGNORECASE),
)


def is_replit_runtime() -> bool:
    return any(os.getenv(name) for name in ("REPL_ID", "REPLIT_DEV_DOMAIN", "REPLIT_DOMAINS"))


def is_process_elevated() -> bool:
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    return False


def validate_elevated_command(command: str) -> str:
    if not isinstance(command, str):
        raise PermissionError("An elevated command must be provided as text.")
    command = command.strip()
    if not command or len(command) > MAX_ELEVATED_COMMAND_LENGTH:
        raise PermissionError("Elevated commands must contain 1–4,000 characters.")
    if "\0" in command or "\n" in command or "\r" in command:
        raise PermissionError("Only one single-line elevated command can be requested.")
    if _COMMAND_SEPARATORS.search(command):
        raise PermissionError("Elevated requests must contain one command without shell chaining, redirection, or substitution.")
    if any(pattern.search(command) for pattern in _BLOCKED_COMMANDS):
        raise PermissionError("This destructive command or inline script is blocked, even with approval.")
    return command


def _append_audit(command: str, event: str, **details: Any) -> None:
    root = PROJECT_ROOT.resolve()
    log_path = AUDIT_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = log_path.parent.resolve()
    if not resolved_parent.is_relative_to(root):
        raise PermissionError("The elevation audit log must remain under the application directory.")
    resolved_log = log_path.resolve(strict=False)
    if not resolved_log.is_relative_to(root):
        raise PermissionError("The elevation audit log must remain under the application directory.")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "platform": platform.system(),
        "command": command,
        **details,
    }
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with _AUDIT_LOCK:
        descriptor = os.open(log_path, flags, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        if os.name != "nt":
            os.chmod(log_path, 0o600)


def _windows_elevation_argv(command: str) -> tuple[list[str], Path]:
    descriptor, temporary_name = tempfile.mkstemp(prefix="assistant-elevated-", suffix=".cmd")
    os.close(descriptor)
    command_file = Path(temporary_name)
    command_file.write_bytes((command + "\r\n").encode("utf-8"))
    encoded_path = base64.b64encode(str(command_file).encode("utf-8")).decode("ascii")
    powershell = (
        "$path=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + encoded_path
        + "'));"
        "$arguments='/d /c \"' + $path + '\"';"
        "try {$p=Start-Process -FilePath $env:ComSpec -ArgumentList $arguments "
        "-Verb RunAs -Wait -PassThru; exit $p.ExitCode} "
        "catch {[Console]::Error.WriteLine($_.Exception.Message); exit 1223}"
    )
    encoded_script = base64.b64encode(powershell.encode("utf-16le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded_script], command_file


def _elevation_argv(command: str) -> list[str]:
    system = platform.system()
    if system == "Windows":
        raise RuntimeError("Windows elevation requires a temporary command file.")
    if system not in {"Linux", "Darwin"}:
        raise RuntimeError(f"Administrative elevation is unsupported on {system or 'this platform'}.")
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec, "/bin/sh", "-c", command]
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo, "-n", "--", "/bin/sh", "-c", command]
    raise RuntimeError("Neither pkexec nor sudo is available for local elevation.")


def execute_elevated_command(command: str) -> dict[str, Any]:
    command = validate_elevated_command(command)
    if is_replit_runtime():
        _append_audit(command, "denied", reason="Replit-managed runtime is not eligible for local elevation.")
        raise PermissionError("Administrative execution is available only from a local exported copy.")
    if is_process_elevated():
        _append_audit(command, "denied", reason="The assistant server is already running with elevated privileges.")
        raise PermissionError("Run the assistant as a normal user; it must not start with elevated privileges.")

    _append_audit(command, "started")
    command_file: Path | None = None
    try:
        if platform.system() == "Windows":
            argv, command_file = _windows_elevation_argv(command)
        else:
            argv = _elevation_argv(command)
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        response = {
            "returnCode": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-4000:],
            "status": "completed" if result.returncode == 0 else "failed",
        }
        _append_audit(
            command,
            "completed" if result.returncode == 0 else "failed",
            returnCode=result.returncode,
        )
        return response
    except Exception as error:
        _append_audit(command, "failed", error=str(error)[:1000])
        raise
    finally:
        if command_file:
            command_file.unlink(missing_ok=True)
