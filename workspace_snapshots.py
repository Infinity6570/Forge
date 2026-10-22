"""Snapshot files before a write tool changes them, so a task can be rolled back.

Snapshots live in ``.forge/snapshots/<task_id>/`` with a manifest. Each file that
existed is copied; each file that did not exist is recorded so rollback can remove
it. Any failure to snapshot must stop the write (fail closed), which the caller enforces.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

SNAPSHOT_ROOT_PARTS = (".forge", "snapshots")
MAX_SNAPSHOT_FILE_BYTES = 5 * 1024 * 1024
MANIFEST_NAME = "manifest.json"
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,80}$")
_REFUSED_TOP_LEVEL = {".git", ".forge"}


def _safe_task_id(task_id: str) -> str:
    if not _TASK_ID_PATTERN.match(task_id or ""):
        raise ValueError("Snapshot task ID contains unsupported characters.")
    return task_id


def resolve_target(root: Path, relative_path: str) -> Path:
    """Resolve a project-relative write target and refuse anything outside ``root``."""
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("Write target path is missing.")
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("Write target is outside the project root.")
    relative = candidate.relative_to(root)
    if relative.parts and relative.parts[0] in _REFUSED_TOP_LEVEL:
        raise ValueError("Snapshots do not cover version-control or snapshot folders.")
    return candidate


def snapshot_write_targets(
    root: Path,
    task_id: str,
    relative_paths: list[str],
) -> Path:
    """Copy each target that exists and record those that do not, before a write runs."""
    root = root.resolve()
    task_dir = root.joinpath(*SNAPSHOT_ROOT_PARTS, _safe_task_id(task_id))
    files_dir = task_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = task_dir / MANIFEST_NAME
    manifest: dict[str, Any] = {"taskId": task_id, "entries": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = {entry["path"] for entry in manifest["entries"]}

    for relative in relative_paths:
        target = resolve_target(root, relative)
        rel_text = target.relative_to(root).as_posix()
        if rel_text in recorded:
            continue  # Keep the first, pre-task state if a file is written twice.
        if target.exists():
            if not target.is_file():
                raise ValueError(f"Snapshot target is not a regular file: {rel_text}")
            size = target.stat().st_size
            if size > MAX_SNAPSHOT_FILE_BYTES:
                raise ValueError(f"File is too large to snapshot safely: {rel_text}")
            backup = files_dir / rel_text
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            manifest["entries"].append({"path": rel_text, "existed": True})
        else:
            manifest["entries"].append({"path": rel_text, "existed": False})
        recorded.add(rel_text)

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return task_dir


def restore_snapshot(root: Path, task_id: str) -> list[str]:
    """Restore every file recorded for a task. Returns human-readable actions taken."""
    root = root.resolve()
    task_dir = root.joinpath(*SNAPSHOT_ROOT_PARTS, _safe_task_id(task_id))
    manifest_path = task_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"No snapshot exists for task {task_id}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actions: list[str] = []
    for entry in manifest["entries"]:
        target = resolve_target(root, entry["path"])
        if entry["existed"]:
            backup = task_dir / "files" / entry["path"]
            if not backup.is_file():
                raise FileNotFoundError(f"Snapshot copy is missing for {entry['path']}.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            actions.append(f"restored {entry['path']}")
        elif target.exists():
            target.unlink()
            actions.append(f"removed {entry['path']} (created during the task)")
    return actions


def list_snapshots(root: Path) -> list[str]:
    base = Path(root).resolve().joinpath(*SNAPSHOT_ROOT_PARTS)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / MANIFEST_NAME).is_file())


if __name__ == "__main__":  # pragma: no cover - manual rollback helper
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "restore":
        for line in restore_snapshot(Path(__file__).resolve().parent, sys.argv[2]):
            print(line)
    elif len(sys.argv) == 2 and sys.argv[1] == "list":
        print("\n".join(list_snapshots(Path(__file__).resolve().parent)) or "No snapshots.")
    else:
        print("Usage: python workspace_snapshots.py list | restore <task_id>")
