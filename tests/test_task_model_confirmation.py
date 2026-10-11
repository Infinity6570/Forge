from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import main


class TaskModelConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"

        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "DEEPSEEK_API_KEY": "test-deepseek-provider-secret",
                "GEMINI_API_KEY": "",
                "OPENROUTER_API_KEY": "",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.path_patches = [
            patch.object(main, "ROOT", root),
            patch.object(main, "ENV_FILE", root / ".env"),
            patch.object(main, "WORKSPACE", workspace),
            patch.object(main, "DATABASE", workspace / "assistant.db"),
            patch.object(main, "UPLOADS", workspace / "uploads"),
            patch.object(main, "NOTES", workspace / "notes"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

        main.ACTIVE_TASKS.clear()
        main.init_db()
        self.worker_started = asyncio.Event()
        self.release_worker = asyncio.Event()
        self.worker_calls: list[tuple[str, str, str, list[str]]] = []
        self.worker_patch = patch.object(main, "run_agent_task", new=self.fake_worker)
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    async def asyncTearDown(self) -> None:
        self.release_worker.set()
        tasks = list(main.ACTIVE_TASKS.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        main.ACTIVE_TASKS.clear()

    async def fake_worker(self, task_id: str, file_ids: list[str]) -> None:
        row = main.db_one("SELECT provider,model_id FROM tasks WHERE id=?", (task_id,))
        assert row is not None
        self.worker_calls.append((task_id, row["provider"], row["model_id"], file_ids))
        self.worker_started.set()
        await self.release_worker.wait()

    async def post(self, path: str, payload: dict[str, object]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.post(path, json=payload)

    async def create_task(self, objective: str) -> dict[str, object]:
        response = await self.post(
            "/api/assistant/tasks",
            {
                "objective": objective,
                "provider": "deepseek",
                "modelId": "deepseek-chat",
                "fileIds": [],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def wait_for_worker(self) -> None:
        await asyncio.wait_for(self.worker_started.wait(), timeout=1)

    async def finish_worker(self, task_id: str) -> None:
        task = main.ACTIVE_TASKS.get(task_id)
        self.release_worker.set()
        if task:
            await task

    async def test_simple_task_starts_immediately_on_selected_budget_model(self) -> None:
        task = await self.create_task("Summarize this short note.")

        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["modelId"], "deepseek-chat")
        self.assertFalse(task["requiresModelConfirmation"])
        await self.wait_for_worker()
        self.assertEqual(
            self.worker_calls,
            [(task["id"], "deepseek", "deepseek-chat", [])],
        )
        await self.finish_worker(task["id"])

    async def test_complex_task_waits_without_starting_worker_until_choice(self) -> None:
        task = await self.create_task("Refactor the architecture across multiple files.")

        self.assertEqual(task["status"], "awaiting_confirmation")
        self.assertTrue(task["requiresModelConfirmation"])
        self.assertEqual(task["modelId"], "deepseek-chat")
        self.assertEqual(self.worker_calls, [])
        self.assertNotIn(task["id"], main.ACTIVE_TASKS)

    async def test_recommended_model_choice_starts_once_with_recommendation(self) -> None:
        task = await self.create_task("Refactor the architecture across multiple files.")
        choice = await self.post(
            f"/api/assistant/tasks/{task['id']}/model-choice",
            {"switchToRecommendation": True},
        )

        self.assertEqual(choice.status_code, 200, choice.text)
        self.assertEqual(choice.json()["status"], "queued")
        self.assertEqual(choice.json()["modelId"], "deepseek-reasoner")
        await self.wait_for_worker()
        self.assertEqual(
            self.worker_calls,
            [(task["id"], "deepseek", "deepseek-reasoner", [])],
        )
        await self.finish_worker(task["id"])

    async def test_stay_on_current_model_choice_starts_once_with_selected_model(self) -> None:
        task = await self.create_task("Refactor the architecture across multiple files.")
        choice = await self.post(
            f"/api/assistant/tasks/{task['id']}/model-choice",
            {"switchToRecommendation": False},
        )

        self.assertEqual(choice.status_code, 200, choice.text)
        self.assertEqual(choice.json()["status"], "queued")
        self.assertEqual(choice.json()["modelId"], "deepseek-chat")
        await self.wait_for_worker()
        self.assertEqual(
            self.worker_calls,
            [(task["id"], "deepseek", "deepseek-chat", [])],
        )
        await self.finish_worker(task["id"])

    async def test_repeated_model_choice_cannot_start_a_second_worker(self) -> None:
        task = await self.create_task("Refactor the architecture across multiple files.")
        path = f"/api/assistant/tasks/{task['id']}/model-choice"

        first = await self.post(path, {"switchToRecommendation": True})
        second = await self.post(path, {"switchToRecommendation": True})

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        await self.wait_for_worker()
        self.assertEqual(len(self.worker_calls), 1)
        self.assertEqual(self.worker_calls[0][2], "deepseek-reasoner")
        await self.finish_worker(task["id"])


if __name__ == "__main__":
    unittest.main()
