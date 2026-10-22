"""On-demand health check for a local Forge install.

Reports runtime versions, database integrity, which provider keys are configured
(presence only, never values), snapshot status, pricing freshness, and catalog
reconciliation. Run it from the project root:  python forge_doctor.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROVIDER_KEY_NAMES = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)


def _configured_key_names(root: Path) -> set[str]:
    """Names of keys that are set in the environment or as a non-empty line in .env."""
    names = {name for name in PROVIDER_KEY_NAMES if os.environ.get(name, "").strip()}
    env_file = root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in PROVIDER_KEY_NAMES and value.strip().strip("\"'"):
                names.add(key.strip())
    return names


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def run_checks(
    root: Path,
    *,
    model_options: dict[str, set[str]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    today = today or date.today()
    checks: list[dict[str, str]] = []

    major, minor = sys.version_info[:2]
    checks.append(_check(
        "python",
        "ok" if (major, minor) >= (3, 11) else "fail",
        f"Python {major}.{minor} (3.11 or newer required)",
    ))

    node = shutil.which("node")
    checks.append(_check(
        "node",
        "ok" if node else "warn",
        "Node.js found on PATH" if node else "Node.js not found on PATH (needed for the frontend build)",
    ))

    db_path = root / "workspace" / "assistant.db"
    if db_path.is_file():
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                connection.close()
            checks.append(_check(
                "database", "ok" if result == "ok" else "fail", f"quick_check: {result}"
            ))
        except sqlite3.Error as error:
            checks.append(_check("database", "fail", f"Could not open database: {error}"))
    else:
        checks.append(_check("database", "warn", "workspace/assistant.db not found yet"))

    configured = _configured_key_names(root)
    missing = [name for name in PROVIDER_KEY_NAMES if name not in configured]
    checks.append(_check(
        "provider_keys",
        "ok" if configured else "warn",
        f"Configured: {', '.join(sorted(configured)) or 'none'}"
        + (f"; not set: {', '.join(missing)}" if missing else ""),
    ))

    snapshot_dir = root / ".forge" / "snapshots"
    snapshot_count = (
        sum(1 for p in snapshot_dir.iterdir() if p.is_dir()) if snapshot_dir.is_dir() else 0
    )
    checks.append(_check("snapshots", "ok", f"{snapshot_count} task snapshot(s) stored"))

    from usage_cost import PRICING_UPDATED_AT, RATE_TABLE

    if model_options is not None:
        from model_registry import reconcile

        report = reconcile(
            model_options,
            RATE_TABLE,
            pricing_updated_at=PRICING_UPDATED_AT,
            today=today,
        )
        if report["pricingStale"]:
            checks.append(_check(
                "pricing", "warn",
                f"Pricing last checked {report['pricingUpdatedAt']} "
                f"({report['pricingAgeDays']} days ago); refresh before relying on cost figures.",
            ))
        else:
            checks.append(_check("pricing", "ok", f"Pricing checked {report['pricingUpdatedAt']}"))
        if report["unpricedModels"]:
            checks.append(_check(
                "model_pricing", "warn",
                f"{len(report['unpricedModels'])} selectable model(s) have no rate: "
                + ", ".join(report["unpricedModels"][:12])
                + (" …" if len(report["unpricedModels"]) > 12 else ""),
            ))
        else:
            checks.append(_check("model_pricing", "ok", "Every selectable model has a rate"))
        if report["orphanedRates"]:
            checks.append(_check(
                "orphaned_rates", "warn",
                "Rates for models no longer selectable: " + ", ".join(report["orphanedRates"]),
            ))
    else:
        checks.append(_check(
            "pricing", "ok" if PRICING_UPDATED_AT else "warn",
            f"Pricing checked {PRICING_UPDATED_AT} (run through the app for full model reconciliation)",
        ))

    overall = "fail" if any(c["status"] == "fail" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks) else "ok"
    )
    return {"status": overall, "checks": checks}


def _print_report(report: dict[str, Any]) -> None:
    for check in report["checks"]:
        print(f"[{check['status'].upper():4}] {check['name']}: {check['detail']}")
    print(f"Overall: {report['status']}")


if __name__ == "__main__":
    report = run_checks(Path(__file__).resolve().parent)
    _print_report(report)
    raise SystemExit(1 if report["status"] == "fail" else 0)
