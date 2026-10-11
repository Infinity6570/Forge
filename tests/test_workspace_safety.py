from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import main


class WorkspaceSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.path_patches = [
            patch.object(main, "BASE_DIR", self.workspace.resolve()),
            patch.object(main, "WORKSPACE", self.workspace),
            patch.object(main, "DATABASE", self.workspace / "assistant.db"),
            patch.object(main, "UPLOADS", self.workspace / "uploads"),
            patch.object(main, "NOTES", self.workspace / "notes"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)
        main.init_db()
        self.sample = self.workspace / "sample.txt"
        self.preview_file = self.workspace / "sample.html"
        self.preview_file.write_text("<h1>original</h1>\n", encoding="utf-8")
        self.sample.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    async def asyncTearDown(self) -> None:
        tasks = list(main.ACTIVE_TASKS.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        main.ACTIVE_TASKS.clear()

    def test_resolver_accepts_workspace_paths_and_rejects_traversal(self) -> None:
        self.assertEqual(
            main.safe_workspace_path("sample.txt"),
            self.sample.resolve(),
        )
        for path in (
            "../outside.txt",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
            "C:/Windows/win.ini",
        ):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                main.safe_workspace_path(path)

    def test_symlink_cannot_escape_workspace(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        (self.workspace / "outside-link.txt").symlink_to(outside)
        with self.assertRaises(PermissionError):
            main.safe_workspace_path("outside-link.txt")
        self.assertNotIn("outside-link.txt", main.list_workspace_paths())

    def test_workspace_command_runner_is_read_only_and_confined(self) -> None:
        result = main.run_workspace_command("cat sample.txt")
        self.assertEqual(result["returnCode"], 0)
        self.assertEqual(result["stdout"], "alpha\nbeta\ngamma\n")
        self.assertEqual(
            main.parse_workspace_command("head -n 2 sample.txt"),
            ("head", "sample.txt", 2),
        )
        blocked = (
            "rmdir /s /q workspace",
            "del /f /s /q *",
            "format C:",
            "diskpart",
            "reg delete HKLM",
            "powershell Remove-Item -Recurse workspace",
            "shutdown /s",
            "cat ../outside.txt",
            "cat sample.txt && pwd",
            "python -c print(1)",
        )
        for command in blocked:
            with self.subTest(command=command), self.assertRaises(PermissionError):
                main.parse_workspace_command(command)

    async def test_static_preview_is_available_but_python_processes_are_blocked(self) -> None:
        manager = main.WorkspacePreviewManager(self.workspace)
        preview = await manager.launch("static", "sample.html")
        self.assertTrue(preview["started"])
        self.assertEqual(preview["framework"], "static")
        with self.assertRaises(PermissionError):
            await manager.launch("flask", "app.py")

    async def _create_pending_task(self, approval_id: str, action: str, payload: dict[str, str]) -> str:
        task_id = f"task-{approval_id}"
        now = main.utc_now()
        messages = [
            {
                "role": "tool",
                "tool_call_id": f"call-{approval_id}",
                "content": json.dumps({"approvalPending": True}),
            }
        ]
        main.db_run(
            "INSERT INTO tasks(id,objective,status,current_step,provider,model_id,file_ids_json,"
            "messages_json,pending_approval_id,approval_summary,created_at,updated_at) "
            "VALUES(?,?,'awaiting_approval','Waiting for your approval','deepseek','deepseek-chat',"
            "'[]',?,?,?, ?,?)",
            (
                task_id,
                "Update a workspace file",
                json.dumps(messages),
                approval_id,
                f"Approve {action}?",
                now,
                now,
            ),
        )
        main.db_run(
            "INSERT INTO pending_approvals(id,task_id,tool_call_id,action,payload_json,status,created_at) "
            "VALUES(?,?,?,?,?,'pending',?)",
            (
                approval_id,
                task_id,
                f"call-{approval_id}",
                action,
                json.dumps(payload),
                now,
            ),
        )
        return task_id

    async def _choose_approval(self, task_id: str, approval_id: str, approve: bool) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.post(
                f"/api/assistant/tasks/{task_id}/approval-choice",
                json={"approvalId": approval_id, "approve": approve},
            )

    async def test_overwrite_waits_for_explicit_approval(self) -> None:
        original = self.preview_file.read_text(encoding="utf-8")
        approval_id = "approval-overwrite"
        task_id = await self._create_pending_task(
            approval_id,
            "write",
            {"path": "sample.html", "content": "<h1>replacement</h1>"},
        )
        self.assertEqual(self.preview_file.read_text(encoding="utf-8"), original)

        async def fake_worker(*_args: object) -> None:
            return None

        with patch.object(main, "run_agent_task", new=fake_worker):
            response = await self._choose_approval(task_id, approval_id, True)
            await asyncio.sleep(0)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.preview_file.read_text(encoding="utf-8"), "<h1>replacement</h1>")
        self.assertEqual(response.json()["status"], "queued")
        self.assertFalse(response.json()["requiresApproval"])

    async def test_rejected_delete_leaves_file_unchanged(self) -> None:
        approval_id = "approval-delete"
        task_id = await self._create_pending_task(
            approval_id,
            "delete",
            {"path": "sample.txt"},
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with patch.object(main, "run_agent_task", new=fake_worker):
            response = await self._choose_approval(task_id, approval_id, False)
            await asyncio.sleep(0)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.sample.is_file())
        self.assertEqual(
            self.sample.read_text(encoding="utf-8"),
            "alpha\nbeta\ngamma\n",
        )
        pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
        self.assertEqual(pending["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
