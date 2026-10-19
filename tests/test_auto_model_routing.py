from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import main


class AutoModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"
        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "GEMINI_API_KEY": "test-gemini-key",
                "ANTHROPIC_API_KEY": "test-anthropic-key",
                "CLAUDE_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        for name, value in (
            ("ROOT", root),
            ("ENV_FILE", root / ".env"),
            ("WORKSPACE", workspace),
            ("DATABASE", workspace / "assistant.db"),
            ("UPLOADS", workspace / "uploads"),
            ("NOTES", workspace / "notes"),
        ):
            patcher = patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        main.ACTIVE_TASKS.clear()
        main.init_db()
        self.worker_tasks: list[asyncio.Task] = []
        self.worker_patch = patch.object(main, "run_agent_task", new=self.fake_worker)
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    async def asyncTearDown(self) -> None:
        await asyncio.sleep(0)
        tasks = list(main.ACTIVE_TASKS.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        main.ACTIVE_TASKS.clear()

    async def fake_worker(self, task_id: str, file_ids: list[str]) -> None:
        return None

    async def post_task(self, payload: dict[str, object]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.post("/api/assistant/tasks", json=payload)

    def test_scoped_modes_never_cross_provider_boundaries(self) -> None:
        cases = (
            ("auto-gemini", "gemini", "gemini-3.1-pro-preview"),
            ("auto-claude", "anthropic", "claude-opus-5-5"),
            ("auto-openai", "openai", "o3-mini"),
        )
        prompt = "Refactor the multi-file architecture and prove the migration is safe"
        for mode, expected_provider, expected_model in cases:
            with self.subTest(mode=mode):
                decision = main.route_task(
                    prompt,
                    mode,
                    available_providers={"gemini", "anthropic", "openai"},
                )
                self.assertEqual(decision["provider"], expected_provider)
                self.assertEqual(decision["model"], expected_model)

    def test_global_selection_is_intent_and_credential_scoped(self) -> None:
        fast = main.route_task(
            "Hi, can you help?",
            "auto-global",
            available_providers={"gemini", "anthropic", "openai"},
        )
        academic = main.route_task(
            "Run a deep academic literature search for clinical trials",
            "auto-global",
            available_providers={"gemini", "anthropic"},
        )
        self.assertEqual((fast["provider"], fast["model"]), ("gemini", "gemini-3.5-flash-lite"))
        self.assertEqual((academic["provider"], academic["model"]), ("gemini", "gemini-3.8-flash"))

    def test_benchlm_scores_improve_auto_routing_without_crossing_provider_scope(self) -> None:
        rankings = [
            {
                "modelId": "gemini-3.8-flash",
                "provider": "gemini",
                "codingScore": 87.5,
                "rank": 4,
            },
            {
                "modelId": "claude-sonnet-5-5",
                "provider": "anthropic",
                "codingScore": 94.0,
                "rank": 1,
            },
        ]
        global_decision = main.route_task(
            "Refactor the codebase architecture",
            "auto-global",
            available_providers={"gemini", "anthropic"},
            benchmark_rankings=rankings,
        )
        scoped_decision = main.route_task(
            "Refactor the codebase architecture",
            "auto-gemini",
            available_providers={"gemini", "anthropic"},
            benchmark_rankings=rankings,
        )

        self.assertEqual((global_decision["provider"], global_decision["model"]), ("anthropic", "claude-sonnet-5-5"))
        self.assertIn("BenchLM coding score 94", global_decision["reason"])
        self.assertEqual((scoped_decision["provider"], scoped_decision["model"]), ("gemini", "gemini-3.8-flash"))

    def test_scoped_mode_without_provider_key_fails_clearly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "configured Gemini API key"):
            main.route_task("hello", "auto-gemini", available_providers={"openai"})

    async def test_auto_route_is_resolved_and_persisted_on_task_and_thread(self) -> None:
        response = await self.post_task({
            "objective": "Refactor the multi-file application architecture",
            "autoRouteMode": "auto-gemini",
            "provider": "gemini",
        })
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task["provider"], "gemini")
        self.assertEqual(task["modelId"], "gemini-3.1-pro-preview")
        self.assertEqual(task["routingMode"], "auto-gemini")
        self.assertEqual(task["routingIntent"], "code_refactoring")
        self.assertIn("multi-file architectural refactoring", task["routingReason"])
        with main.THREADS.transaction() as connection:
            thread = main.THREADS.describe(
                connection,
                main.THREADS.require(connection, task["threadId"]),
            )
        self.assertEqual(thread["provider"], "gemini")
        self.assertEqual(thread["modelId"], "gemini-3.1-pro-preview")

    async def test_global_auto_fails_when_no_supported_key_is_available(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            response = await self.post_task({
                "objective": "Summarize the question",
                "autoRouteMode": "auto-global",
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("needs an API key", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
