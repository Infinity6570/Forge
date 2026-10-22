"""Tests for the resilience, output-budget, spend-guard, snapshot, registry, and doctor modules."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forge_resilience import backoff_delay, call_with_transient_retry, is_transient_error  # noqa: E402
from model_registry import reconcile  # noqa: E402
from task_budget import context_growth_warnings, evaluate_budget  # noqa: E402
from tool_output_budget import cap_tool_output, elide_stale_tool_results  # noqa: E402
from workspace_snapshots import restore_snapshot, snapshot_write_targets  # noqa: E402
import forge_doctor  # noqa: E402


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    pass


class TransientClassificationTests(unittest.TestCase):
    def test_retries_rate_limits_overload_and_server_errors(self) -> None:
        for status in (429, 503, 529, 500):
            self.assertTrue(is_transient_error(StatusError(status)), status)

    def test_never_retries_client_errors(self) -> None:
        for status in (400, 401, 403, 404, 422):
            self.assertFalse(is_transient_error(StatusError(status)), status)

    def test_connection_and_timeout_errors_are_transient(self) -> None:
        self.assertTrue(is_transient_error(APIConnectionError("Connection error.")))
        self.assertTrue(is_transient_error(TimeoutError()))
        self.assertTrue(is_transient_error(ConnectionError()))

    def test_grpc_style_status_strings_are_mapped(self) -> None:
        class Grpc(Exception):
            code = "UNAVAILABLE"

        self.assertTrue(is_transient_error(Grpc()))

    def test_backoff_grows_and_respects_cap(self) -> None:
        low = backoff_delay(0, rng=lambda: 0.0)
        high = backoff_delay(10, rng=lambda: 0.999)
        self.assertAlmostEqual(low, 1.0)
        self.assertLessEqual(high, 30.0)
        self.assertGreater(backoff_delay(3, rng=lambda: 0.999), backoff_delay(1, rng=lambda: 0.999))


class RetryHelperTests(unittest.TestCase):
    def test_retries_transient_then_succeeds(self) -> None:
        calls = {"n": 0}
        messages: list[str] = []

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise StatusError(503)
            return "ok"

        async def no_sleep(_: float) -> None:
            return None

        result = asyncio.run(call_with_transient_retry(
            flaky, attempts=5, on_retry=messages.append, sleep=no_sleep,
        ))
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(messages), 2)

    def test_client_error_is_raised_immediately(self) -> None:
        calls = {"n": 0}

        async def bad() -> str:
            calls["n"] += 1
            raise StatusError(400)

        with self.assertRaises(StatusError):
            asyncio.run(call_with_transient_retry(bad, attempts=5))
        self.assertEqual(calls["n"], 1)

    def test_gives_up_after_attempts(self) -> None:
        calls = {"n": 0}

        async def down() -> str:
            calls["n"] += 1
            raise APIConnectionError("Connection error.")

        async def no_sleep(_: float) -> None:
            return None

        with self.assertRaises(APIConnectionError):
            asyncio.run(call_with_transient_retry(down, attempts=3, sleep=no_sleep))
        self.assertEqual(calls["n"], 3)


class ToolOutputBudgetTests(unittest.TestCase):
    def test_small_output_is_unchanged(self) -> None:
        self.assertEqual(cap_tool_output("hello", limit=100), "hello")

    def test_large_output_becomes_valid_json_with_metadata(self) -> None:
        big = "x" * 50_000
        capped = cap_tool_output(big, limit=12_000, tool_name="read_file")
        payload = json.loads(capped)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["originalChars"], 50_000)
        self.assertLessEqual(payload["returnedChars"], 12_000)
        self.assertEqual(payload["tool"], "read_file")

    def test_elides_only_old_large_tool_results(self) -> None:
        big = "y" * 2_000
        messages = [
            {"role": "user", "content": "task"},
            {"role": "tool", "tool_call_id": "1", "content": big},
            {"role": "tool", "tool_call_id": "2", "content": big},
            {"role": "tool", "tool_call_id": "3", "content": "small"},
            {"role": "tool", "tool_call_id": "4", "content": big},
        ]
        original_first = messages[1]["content"]
        trimmed = elide_stale_tool_results(messages, keep_recent=2)
        self.assertIn("elided", json.loads(trimmed[1]["content"]))
        self.assertIn("elided", json.loads(trimmed[2]["content"]))
        self.assertEqual(trimmed[3]["content"], "small")
        self.assertEqual(trimmed[4]["content"], big)
        # The caller's list is untouched.
        self.assertEqual(messages[1]["content"], original_first)


class PreservedLiteratureTests(unittest.TestCase):
    def test_academic_results_are_never_capped(self) -> None:
        big = json.dumps({"engine": "academic-search", "results": [{"abstract": "a" * 30_000}]})
        self.assertEqual(cap_tool_output(big, limit=12_000, tool_name="academic_search"), big)
        self.assertEqual(cap_tool_output(big, limit=12_000, tool_name="pubmed_search"), big)

    def test_academic_results_are_never_elided(self) -> None:
        big = json.dumps({"engine": "academic-search", "results": [{"abstract": "b" * 2_000}]})
        messages = [
            {"role": "tool", "tool_call_id": "1", "content": big},
            {"role": "tool", "tool_call_id": "2", "content": "x" * 2_000},
            {"role": "tool", "tool_call_id": "3", "content": "y" * 2_000},
        ]
        trimmed = elide_stale_tool_results(messages, keep_recent=1)
        self.assertEqual(trimmed[0]["content"], big)
        self.assertIn("elided", json.loads(trimmed[1]["content"]))


class SpendGuardTests(unittest.TestCase):
    def test_priced_spend_over_budget_is_flagged(self) -> None:
        rows = [{"cost_usd": 2.0, "cost_known": 1}, {"cost_usd": 4.0, "cost_known": 1}]
        status = evaluate_budget(rows, budget_usd=5.0, unpriced_token_ceiling=1_000)
        self.assertTrue(status.exceeded)
        self.assertIn("exceeded", status.reason)

    def test_spend_under_budget_passes(self) -> None:
        rows = [{"cost_usd": 0.5, "cost_known": 1}]
        self.assertFalse(evaluate_budget(rows, budget_usd=5.0, unpriced_token_ceiling=1_000).exceeded)

    def test_unpriced_tokens_have_their_own_ceiling(self) -> None:
        rows = [{"cost_known": 0, "input_tokens": 900_000, "cache_read_tokens": 200_000}]
        status = evaluate_budget(rows, budget_usd=5.0, unpriced_token_ceiling=1_000_000)
        self.assertTrue(status.exceeded)

    def test_zero_budget_disables_spend_limit(self) -> None:
        rows = [{"cost_usd": 999.0, "cost_known": 1}]
        self.assertFalse(evaluate_budget(rows, budget_usd=0, unpriced_token_ceiling=0).exceeded)

    def test_context_doubling_is_flagged(self) -> None:
        rows = [
            {"input_tokens": 60_000},
            {"input_tokens": 70_000},
            {"input_tokens": 200_000},
        ]
        warnings = context_growth_warnings(rows)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Model call 3", warnings[0])


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "workspace").mkdir()
        self.existing = self.root / "workspace" / "notes.txt"
        self.existing.write_text("original", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_restores_modified_and_removes_created_files(self) -> None:
        task = "11111111-aaaa-bbbb-cccc-000000000001"
        snapshot_write_targets(self.root, task, ["workspace/notes.txt", "workspace/new.txt"])
        self.existing.write_text("changed", encoding="utf-8")
        (self.root / "workspace" / "new.txt").write_text("created", encoding="utf-8")

        actions = restore_snapshot(self.root, task)

        self.assertEqual(self.existing.read_text(encoding="utf-8"), "original")
        self.assertFalse((self.root / "workspace" / "new.txt").exists())
        self.assertEqual(len(actions), 2)

    def test_second_write_keeps_the_first_snapshot(self) -> None:
        task = "11111111-aaaa-bbbb-cccc-000000000002"
        snapshot_write_targets(self.root, task, ["workspace/notes.txt"])
        self.existing.write_text("first edit", encoding="utf-8")
        snapshot_write_targets(self.root, task, ["workspace/notes.txt"])
        self.existing.write_text("second edit", encoding="utf-8")
        restore_snapshot(self.root, task)
        self.assertEqual(self.existing.read_text(encoding="utf-8"), "original")

    def test_refuses_paths_outside_the_project(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_write_targets(self.root, "11111111-aaaa-bbbb-cccc-000000000003", ["../escape.txt"])

    def test_refuses_version_control_and_snapshot_folders(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_write_targets(self.root, "11111111-aaaa-bbbb-cccc-000000000004", [".git/config"])

    def test_rejects_unsafe_task_ids(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_write_targets(self.root, "../../etc", ["workspace/notes.txt"])


class ModelRegistryTests(unittest.TestCase):
    def test_reports_unpriced_and_orphaned_models(self) -> None:
        report = reconcile(
            {"openai": {"gpt-4.1"}, "gemini": {"gemini-3.8-flash"}},
            {"gemini": {"gemini-3.8-flash": object(), "gemini-old": object()}},
            pricing_updated_at="2026-10-19",
            today=date(2026, 10, 20),
        )
        self.assertEqual(report["unpricedModels"], ["openai/gpt-4.1"])
        self.assertEqual(report["orphanedRates"], ["gemini/gemini-old"])
        self.assertFalse(report["ok"])

    def test_flags_stale_pricing(self) -> None:
        report = reconcile(
            {}, {}, pricing_updated_at="2026-01-01", today=date(2026, 10, 20),
        )
        self.assertTrue(report["pricingStale"])


class CriticReportTests(unittest.TestCase):
    def test_failed_specialist_is_reported_as_unavailable_not_a_blank_revise(self):
        import main

        failed = json.dumps({"error": "Specialist analysis could not complete the subtask: empty result."})
        report = main.parse_critic_report(failed)
        self.assertEqual(report["verdict"], "unavailable")
        self.assertEqual(report["findings"], [])
        self.assertIn("empty result", report["reason"])
        self.assertIn("not independently verified", main.critic_unavailable_note(report))

    def test_real_verdicts_are_unchanged(self):
        import main

        revise = main.parse_critic_report(json.dumps(
            {"verdict": "revise", "findings": ["bug"], "tests": [], "summary": "x"}
        ))
        self.assertEqual(revise["verdict"], "revise")
        self.assertEqual(revise["findings"], ["bug"])
        passed = main.parse_critic_report(json.dumps(
            {"verdict": "pass", "findings": [], "tests": ["ran"], "summary": "ok"}
        ))
        self.assertEqual(passed["verdict"], "pass")

    def test_revise_with_no_findings_is_inconclusive_not_actionable(self):
        import main

        empty = main.parse_critic_report(json.dumps(
            {"verdict": "revise", "findings": [], "tests": [], "summary": ""}
        ))
        self.assertEqual(empty["verdict"], "unavailable")
        self.assertIn("no findings", empty["reason"])
        missing_verdict = main.parse_critic_report(json.dumps({"findings": [], "tests": [], "summary": ""}))
        self.assertEqual(missing_verdict["verdict"], "unavailable")
        self.assertIn("not independently verified", main.critic_unavailable_note(empty))

    def test_revise_with_any_concrete_content_stays_actionable(self):
        import main

        for payload in (
            {"verdict": "revise", "findings": ["real bug"], "tests": [], "summary": ""},
            {"verdict": "revise", "findings": [], "tests": ["pytest failed"], "summary": ""},
            {"verdict": "revise", "findings": [], "tests": [], "summary": "Could not run the build."},
        ):
            self.assertEqual(main.parse_critic_report(json.dumps(payload))["verdict"], "revise", payload)

    def test_unparseable_text_still_requests_revision(self):
        import main

        self.assertEqual(main.parse_critic_report("not json at all")["verdict"], "revise")


class DoctorTests(unittest.TestCase):
    def test_report_never_contains_key_values(self) -> None:
        import os

        secret = "sk-test-SECRET-VALUE-123456"
        os.environ["ANTHROPIC_API_KEY"] = secret
        try:
            report = forge_doctor.run_checks(ROOT, today=date(2026, 10, 20))
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertNotIn(secret, json.dumps(report))
        self.assertIn(report["status"], {"ok", "warn", "fail"})
        names = {check["name"] for check in report["checks"]}
        self.assertTrue({"python", "database", "provider_keys", "snapshots"} <= names)


if __name__ == "__main__":
    unittest.main()
