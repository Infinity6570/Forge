from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from history_display import (
    PROVIDER_SUMMARY_PREFIX,
    compact_log,
    retain_logs,
    select_display_logs,
)


def summary(n, body: str | None = None) -> dict:
    return {
        "id": f"s{n}",
        "kind": "agent",
        "message": PROVIDER_SUMMARY_PREFIX + (body if body is not None else f"summary number {n}"),
    }


def note(n, kind: str = "info", body: str | None = None) -> dict:
    return {"id": f"n{n}", "kind": kind, "message": body if body is not None else f"note {n}"}


class DisplayWindowTests(unittest.TestCase):
    def test_early_summaries_stay_visible_after_many_later_entries(self):
        logs = [summary(1)] + [note(i) for i in range(200)] + [summary(2)] + [note(i) for i in range(200, 260)]
        shown = select_display_logs(logs, 50)
        ids = [log["id"] for log in shown]
        self.assertIn("s1", ids)
        self.assertIn("s2", ids)
        # Ordinary entries still follow the recent-window rule.
        self.assertEqual(sum(1 for log in shown if log["kind"] == "info"), 50)
        self.assertEqual(len(shown), 52)
        self.assertEqual(ids[-1], "n259")
        self.assertNotIn("n0", ids)

    def test_original_order_is_preserved(self):
        logs = [note(0), summary(1), note(1), note(2), summary(2), note(3)]
        # Window of 2 = [s2, n3]; summaries s1 and s2 are always added, in original order.
        self.assertEqual([log["id"] for log in select_display_logs(logs, 2)], ["s1", "s2", "n3"])

    def test_long_summaries_are_not_shortened_but_ordinary_logs_still_are(self):
        long_body = "reasoning line. " * 1_500  # ~24k chars
        kept = compact_log(summary(1, long_body))
        self.assertEqual(kept["message"], PROVIDER_SUMMARY_PREFIX + long_body)
        shortened = compact_log(note(1, body="x" * 20_000))
        self.assertIn("Display shortened", shortened["message"])

    def test_only_agent_kind_with_the_prefix_is_protected(self):
        impostor = note(9, kind="info", body=PROVIDER_SUMMARY_PREFIX + "pretend")
        logs = [impostor] + [note(i) for i in range(100)]
        self.assertNotIn("n9", [log["id"] for log in select_display_logs(logs, 10)])


class StoredLogRetentionTests(unittest.TestCase):
    def test_ordinary_entries_are_trimmed_but_summaries_are_kept(self):
        logs = []
        for i in range(30):
            logs.append(summary(i))
            logs.extend(note(f"{i}-{j}") for j in range(20))
        trimmed = retain_logs(logs, limit=300)
        self.assertEqual(sum(1 for log in trimmed if log["kind"] == "agent"), 30)
        self.assertEqual(sum(1 for log in trimmed if log["kind"] == "info"), 300)
        self.assertEqual(trimmed[-1]["id"], "n29-19")

    def test_nothing_changes_when_under_the_cap(self):
        logs = [summary(1), note(1)]
        self.assertIs(retain_logs(logs), logs)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"
        workspace.mkdir()
        patchers = []
        for name, value in (
            ("ROOT", root),
            ("PROJECT_DIR", root.resolve()),
            ("BASE_DIR", workspace.resolve()),
            ("WORKSPACE", workspace),
            ("DATABASE", workspace / "assistant.db"),
            ("UPLOADS", workspace / "uploads"),
            ("NOTES", workspace / "notes"),
        ):
            patcher = patch.object(main, name, value)
            patcher.start()
            patchers.append(patcher)
        self.addCleanup(lambda: [p.stop() for p in reversed(patchers)])
        env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        main.init_db()
        now = main.utc_now()
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,logs_json,provider,model_id,"
            "file_ids_json,created_at,updated_at) VALUES(?,?,'running','Working','[]',?,?, '[]',?,?)",
            ("retention-test", "long task", "anthropic", "claude-sonnet-5-5", now, now),
        )

    def test_every_summary_reaches_the_browser_after_a_long_task(self):
        for round_number in range(25):
            main.log_task("retention-test", f"Reasoning step {round_number + 1} of 40", "info")
            main.log_task(
                "retention-test",
                f"{PROVIDER_SUMMARY_PREFIX}Thought for round {round_number}",
                "agent",
                update_step=False,
            )
            for extra in range(8):
                main.log_task(
                    "retention-test", f"usage/cache/tool entry {round_number}.{extra}", "info", update_step=False
                )

        row = main.db_one("SELECT * FROM tasks WHERE id='retention-test'")
        stored = main.task_dict(row)["logs"]
        self.assertEqual(sum(1 for log in stored if log["kind"] == "agent"), 25)

        shown = main.display_task(row, main.task_dict)["logs"]
        summaries = [log for log in shown if log["kind"] == "agent"]
        self.assertEqual(len(summaries), 25, "Every thinking summary must be sent to the UI")
        self.assertIn("Thought for round 0", summaries[0]["message"])
        self.assertIn("Thought for round 24", summaries[-1]["message"])

    def test_summaries_survive_the_stored_log_cap(self):
        for round_number in range(10):
            main.log_task(
                "retention-test",
                f"{PROVIDER_SUMMARY_PREFIX}early thought {round_number}",
                "agent",
                update_step=False,
            )
        for i in range(450):  # well past the 300-entry cap for ordinary logs
            main.log_task("retention-test", f"noise {i}", "info", update_step=False)

        stored = main.task_dict(main.db_one("SELECT * FROM tasks WHERE id='retention-test'"))["logs"]
        self.assertEqual(sum(1 for log in stored if log["kind"] == "agent"), 10)
        self.assertEqual(sum(1 for log in stored if log["kind"] == "info"), 300)
        self.assertEqual(stored[-1]["message"], "noise 449")


if __name__ == "__main__":
    unittest.main()
