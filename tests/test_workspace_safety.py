from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

import main
from tools.agent_tools import prepare_terminal_argv


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
            ("head", "sample.txt", 2, ""),
        )
        self.assertEqual(
            main.parse_workspace_command('grep -n "beta" sample.txt'),
            ("grep-n", "sample.txt", 20, "beta"),
        )
        matches = main.run_workspace_command('grep -n "a" sample.txt')
        self.assertEqual(matches["returnCode"], 0)
        self.assertEqual(matches["stdout"], "1:alpha\n2:beta\n3:gamma")
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

    async def test_read_only_workspace_commands_do_not_require_local_terminal_toggle(self) -> None:
        with patch.object(main, "local_code_runner_available", return_value=False):
            raw = await main.execute_tool(
                "run_command",
                {"command": "grep beta sample.txt"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            )
        self.assertEqual(json.loads(raw)["stdout"], "beta")

    def test_local_terminal_commands_require_exact_local_approval(self) -> None:
        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_code_runner_available", return_value=True),
        ):
            staged = main.workspace_action_requiring_approval(
                "run_terminal_command",
                {"command": "python -m pytest", "cwd": "."},
            )
        self.assertEqual(
            staged,
            (
                "terminal_command",
                {"command": "python -m pytest", "cwd": "."},
                "Run local terminal command: python -m pytest",
            ),
        )
        for command in (
            "python -m pytest && echo bypass",
            "python -c print(1)",
            "rmdir /s /q workspace",
            "sudo python main.py",
        ):
            with self.subTest(command=command), self.assertRaises(PermissionError):
                main.validate_terminal_command(command)
        with patch.object(main, "is_replit_runtime", return_value=True):
            with self.assertRaises(PermissionError):
                main.workspace_action_requiring_approval(
                    "run_terminal_command",
                    {"command": "python -m pytest", "cwd": "."},
                )
        self.assertEqual(
            main.validate_terminal_command('npm install --prefix "web app"', windows=True),
            ["npm", "install", "--prefix", "web app"],
        )
        self.assertEqual(
            main.validate_terminal_command(r'python "C:\Users\me\app.py"', windows=True),
            ["python", r"C:\Users\me\app.py"],
        )

    def test_engine_actions_are_local_opt_in_and_stage_exact_review_details(self) -> None:
        script = "import bpy\nbpy.context.scene.frame_end = 48\n"
        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_engine_tools_available", return_value=True),
        ):
            staged = main.workspace_action_requiring_approval(
                "run_blender_automation",
                {"script_content": script, "render_output_path": "renders/scene.png"},
            )
            remote = main.workspace_action_requiring_approval(
                "send_engine_remote_command",
                {
                    "engine": "unreal",
                    "endpoint_url": "http://localhost:30010/remote/object/call",
                    "payload": {"objectPath": "/Game/Scene", "functionName": "CreateActor"},
                },
            )
        self.assertEqual(staged[0], "blender_automation")
        self.assertEqual(staged[1]["script_content"], script)
        self.assertIn("renders/scene.png", staged[2])
        self.assertEqual(main.workspace_approval_details("run_blender_automation", staged[1]), script)
        self.assertEqual(remote[0], "engine_remote_command")
        self.assertIn("localhost:30010", remote[2])
        self.assertIn('"functionName": "CreateActor"', main.workspace_approval_details(
            "send_engine_remote_command", remote[1]
        ))
        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_engine_tools_available", return_value=False),
            self.assertRaises(PermissionError),
        ):
            main.workspace_action_requiring_approval(
                "run_blender_automation",
                {"script_content": script},
            )
        with (
            patch.object(main, "is_replit_runtime", return_value=True),
            patch.object(main, "local_engine_tools_available", return_value=True),
            self.assertRaises(PermissionError),
        ):
            main.workspace_action_requiring_approval(
                "send_engine_remote_command",
                {"engine": "unreal", "endpoint_url": "http://localhost:30010", "payload": {}},
            )

    def test_windows_npm_batch_shim_is_replaced_with_node_cli(self) -> None:
        node = self.root / "node.exe"
        npm = self.root / "npm.cmd"
        cli = self.root / "node_modules" / "npm" / "bin" / "npm-cli.js"
        node.touch()
        npm.touch()
        cli.parent.mkdir(parents=True)
        cli.touch()
        with patch(
            "tools.agent_tools.shutil.which",
            side_effect=lambda name: str(node) if name in {"node.exe", "node"}
            else str(npm) if name in {"npm.cmd", "npm"}
            else None,
        ):
            prepared = prepare_terminal_argv(
                ["npm", "install", "--prefix", "web app"],
                windows=True,
            )
        self.assertEqual(prepared, [str(node), str(cli), "install", "--prefix", "web app"])

    def test_approved_terminal_runner_uses_workspace_and_scrubs_secrets(self) -> None:
        script = self.workspace / "runner_probe.py"
        script.write_text(
            "import os\n"
            "print(os.getcwd())\n"
            "print(os.getenv('OPENAI_API_KEY', 'missing'))\n",
            encoding="utf-8",
        )
        with patch.dict(
            "os.environ",
            {"PATH": __import__("os").environ.get("PATH", ""), "OPENAI_API_KEY": "test-only-secret"},
            clear=True,
        ):
            result = main.run_approved_terminal_command(self.workspace, "python runner_probe.py")
        self.assertEqual(result["returnCode"], 0, result["stderr"])
        self.assertEqual(result["stdout"].splitlines(), [str(self.workspace.resolve()), "missing"])

    async def test_write_file_supports_immediate_workspace_updates(self) -> None:
        created = main.write_workspace_source_file(
            self.workspace,
            "web/src/App.tsx",
            "export default function App() { return <main />; }\n",
        )
        self.assertEqual(created["path"], "web/src/App.tsx")
        required = main.workspace_action_requiring_approval(
            "write_file",
            {"path": "web/src/App.tsx", "content": "replacement\n"},
        )
        self.assertIsNone(required)
        raw = await main.execute_tool(
            "write_file",
            {"path": "web/src/App.tsx", "content": "replacement\n"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        result = main.parse_json(raw, {})
        self.assertTrue(result["saved"])
        self.assertEqual((self.workspace / "web/src/App.tsx").read_text(encoding="utf-8"), "replacement\n")
        with self.assertRaises((PermissionError, main.WorkspacePreviewError)):
            main.write_workspace_source_file(self.workspace, "../outside.py", "blocked\n")
        self.assertEqual(main.list_workspace_directory(".")["path"], ".")

    async def test_static_preview_is_available_and_python_previews_are_disabled_by_default(self) -> None:
        manager = main.WorkspacePreviewManager(self.workspace)
        preview = await manager.launch("static", "sample.html")
        self.assertTrue(preview["started"])
        self.assertEqual(preview["framework"], "static")
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "false",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
        ):
            with self.assertRaises(PermissionError):
                await manager.launch("flask", "app.py")

    async def test_replit_cloud_disables_python_previews_even_if_env_flag_is_true(self) -> None:
        manager = main.WorkspacePreviewManager(self.workspace)
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "true",
                "REPL_ID": "test-repl",
                "REPLIT_DEV_DOMAIN": "assistant.replit.dev",
                "REPLIT_DOMAINS": "",
            },
        ):
            self.assertFalse(manager.get_status()["pythonPreviewsEnabled"])
            with self.assertRaises(PermissionError):
                await manager.launch("flask", "app.py")

    async def test_python_preview_files_remain_confined_and_can_be_updated_directly(self) -> None:
        created = main.write_workspace_app_script(
            self.workspace,
            "preview_app.py",
            "app = None\n",
        )
        self.assertEqual(created["path"], "preview_app.py")
        with self.assertRaises(PermissionError):
            main.write_workspace_app_script(self.workspace, "../outside.py", "app = None\n")

        required = main.workspace_action_requiring_approval(
            "write_workspace_app_script",
            {"path": "preview_app.py", "content": "app = 'replacement'\n"},
        )
        self.assertIsNone(required)
        raw = await main.execute_tool(
            "write_workspace_app_script",
            {"path": "preview_app.py", "content": "app = 'replacement'\n"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        result = main.parse_json(raw, {})
        self.assertTrue(result["saved"])
        self.assertEqual(
            (self.workspace / "preview_app.py").read_text(encoding="utf-8"),
            "app = 'replacement'\n",
        )

    async def test_static_preview_assets_can_be_updated_directly(self) -> None:
        required = main.workspace_action_requiring_approval(
            "write_workspace_preview_file",
            {"path": "sample.html", "content": "<h1>updated</h1>"},
        )
        self.assertIsNone(required)
        raw = await main.execute_tool(
            "write_workspace_preview_file",
            {"path": "sample.html", "content": "<h1>updated</h1>"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        self.assertTrue(main.parse_json(raw, {})["saved"])
        self.assertEqual(self.preview_file.read_text(encoding="utf-8"), "<h1>updated</h1>")

    async def test_local_flask_preview_uses_workspace_cwd_scrubbed_env_and_stops(self) -> None:
        app_script = self.workspace / "preview_app.py"
        app_script.write_text(
            "import os\n"
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.get('/')\n"
            "def index():\n"
            "    return os.getcwd() + '|' + os.getenv('OPENAI_API_KEY', 'missing')\n",
            encoding="utf-8",
        )
        manager = main.WorkspacePreviewManager(self.workspace)
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "true",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
                "OPENAI_API_KEY": "parent-process-key-must-not-be-inherited",
            },
        ):
            try:
                launched = await manager.launch("flask", "preview_app.py")
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(launched["localUrl"] + "/")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.text,
                    f"{self.workspace.resolve()}|missing",
                )
                with patch.object(main, "PREVIEW_MANAGER", manager):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=main.app),
                        base_url="http://127.0.0.1",
                    ) as client:
                        stopped = await client.post("/api/workspace/preview/stop-all")
                self.assertEqual(stopped.status_code, 200, stopped.text)
                self.assertEqual(stopped.json()["stopped"], 1)
                self.assertEqual(manager.list_apps(), [])
            finally:
                manager.stop_all()

    async def test_local_streamlit_preview_serves_under_its_preview_prefix(self) -> None:
        app_script = self.workspace / "streamlit_app.py"
        app_script.write_text(
            "import streamlit as st\n"
            "st.title('Preview smoke test')\n",
            encoding="utf-8",
        )
        manager = main.WorkspacePreviewManager(self.workspace)
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "true",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
        ):
            try:
                launched = await manager.launch("streamlit", "streamlit_app.py")
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(launched["localUrl"] + "/")
                    health = await client.get(launched["localUrl"] + "/_stcore/health")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('id="root"', response.text)
                self.assertEqual(health.status_code, 200, health.text)
            finally:
                manager.stop_all()

    async def test_local_fastapi_preview_starts_on_loopback_and_stops_on_close(self) -> None:
        app_script = self.workspace / "fastapi_app.py"
        app_script.write_text(
            "import os\n"
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "@app.get('/')\n"
            "def index():\n"
            "    return {'cwd': os.getcwd()}\n",
            encoding="utf-8",
        )
        manager = main.WorkspacePreviewManager(self.workspace)
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "true",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
        ):
            try:
                launched = await manager.launch("fastapi", "fastapi_app.py")
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(launched["localUrl"] + "/")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["cwd"], str(self.workspace.resolve()))
                self.assertEqual(manager.stop_all(), 1)
                self.assertEqual(manager.list_apps(), [])
            finally:
                manager.stop_all()

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    async def test_local_vite_preview_uses_registered_loopback_port_and_stops(self) -> None:
        project = self.workspace / "site"
        vite_entry = project / "node_modules" / "vite" / "bin" / "vite.js"
        vite_entry.parent.mkdir(parents=True)
        (project / "package.json").write_text(
            json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "*"}}),
            encoding="utf-8",
        )
        vite_entry.write_text(
            "const http=require('http');\n"
            "const args=process.argv.slice(2);\n"
            "const port=Number(args[args.indexOf('--port')+1]);\n"
            "const base=args[args.indexOf('--base')+1];\n"
            "http.createServer((req,res)=>{res.writeHead(200,{'content-type':'text/plain'});res.end('vite:'+base);})"
            ".listen(port,'127.0.0.1');\n",
            encoding="utf-8",
        )
        manager = main.WorkspacePreviewManager(self.workspace)
        with patch.dict(
            "os.environ",
            {
                "RUN_LOCAL_APP_PREVIEWS": "true",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
        ):
            try:
                launched = await manager.launch("vite", "site")
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(launched["localUrl"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(launched["previewUrl"], response.text)
                self.assertEqual(manager.stop_all(), 1)
                self.assertEqual(manager.list_apps(), [])
            finally:
                manager.stop_all()

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
            "messages_json,pending_approval_id,pending_approval_kind,approval_summary,created_at,updated_at) "
            "VALUES(?,?,'awaiting_approval','Waiting for your approval','deepseek','deepseek-chat',"
            "'[]',?,?,?,?,?,?)",
            (
                task_id,
                "Update a workspace file",
                json.dumps(messages),
                approval_id,
                action,
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

    async def test_elevated_request_is_only_staged_for_approval(self) -> None:
        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "is_process_elevated", return_value=False),
        ):
            staged = main.workspace_action_requiring_approval(
                "execute_elevated_command",
                {"command": "ipconfig /flushdns"},
            )

        self.assertEqual(
            staged,
            (
                "elevated_command",
                {"command": "ipconfig /flushdns"},
                "ipconfig /flushdns",
            ),
        )
        with self.assertRaises(PermissionError):
            main.validate_elevated_command("first\nsecond")

    async def test_elevated_command_runs_only_after_approval(self) -> None:
        approval_id = "approval-elevation"
        task_id = await self._create_pending_task(
            approval_id,
            "elevated_command",
            {"command": "whoami"},
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(
                main,
                "execute_elevated_command",
                return_value={"returnCode": 0, "stdout": "local-user", "stderr": "", "status": "completed"},
            ) as elevated_runner,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            self.assertEqual(elevated_runner.call_count, 0)
            response = await self._choose_approval(task_id, approval_id, True)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["requiresApproval"])

            for _ in range(50):
                pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
                if pending["status"] != "processing":
                    break
                await asyncio.sleep(0.01)

        elevated_runner.assert_called_once_with("whoami")
        self.assertEqual(pending["status"], "approved")
        task = main.db_one("SELECT status,pending_approval_kind FROM tasks WHERE id=?", (task_id,))
        self.assertEqual(task["status"], "queued")
        self.assertIsNone(task["pending_approval_kind"])

    async def test_local_terminal_command_runs_only_after_approval(self) -> None:
        approval_id = "approval-terminal"
        task_id = await self._create_pending_task(
            approval_id,
            "terminal_command",
            {"command": "python -m pytest", "cwd": "."},
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_code_runner_available", return_value=True),
            patch.object(
                main,
                "run_approved_terminal_command",
                return_value={
                    "returnCode": 0,
                    "timedOut": False,
                    "stdout": "2 tests passed",
                    "stderr": "",
                },
            ) as terminal_runner,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            response = await self._choose_approval(task_id, approval_id, True)
            self.assertEqual(response.status_code, 200, response.text)
            for _ in range(50):
                pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
                if pending["status"] != "processing":
                    break
                await asyncio.sleep(0.01)
        terminal_runner.assert_called_once_with(self.workspace, "python -m pytest", ".")
        self.assertEqual(pending["status"], "approved")
        task = main.db_one("SELECT status,pending_approval_kind,messages_json FROM tasks WHERE id=?", (task_id,))
        self.assertEqual(task["status"], "queued")
        self.assertIsNone(task["pending_approval_kind"])

    async def test_blender_script_runs_only_after_explicit_approval(self) -> None:
        approval_id = "approval-blender"
        script = "import bpy\nbpy.context.scene.frame_end = 24\n"
        task_id = await self._create_pending_task(
            approval_id,
            "blender_automation",
            {
                "script_content": script,
                "blend_filepath": None,
                "render_output_path": None,
            },
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_engine_tools_available", return_value=True),
            patch.object(main, "run_blender_automation", return_value={
                "ok": True, "returnCode": 0, "stdout": "done", "stderr": "", "renderedOutputPaths": []
            }) as blender_runner,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            blender_runner.assert_not_called()
            response = await self._choose_approval(task_id, approval_id, True)
            self.assertEqual(response.status_code, 200, response.text)
            for _ in range(50):
                pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
                if pending["status"] != "processing":
                    break
                await asyncio.sleep(0.01)

        blender_runner.assert_called_once_with(
            script,
            None,
            None,
            workspace=self.workspace,
        )
        self.assertEqual(pending["status"], "approved")
        task = main.db_one(
            "SELECT status,pending_approval_kind,pending_approval_details,messages_json FROM tasks WHERE id=?",
            (task_id,),
        )
        self.assertEqual(task["status"], "queued")
        self.assertIsNone(task["pending_approval_kind"])
        self.assertIsNone(task["pending_approval_details"])
        self.assertIn("done", task["messages_json"])

    async def test_engine_remote_command_is_sent_only_after_explicit_approval(self) -> None:
        approval_id = "approval-engine-remote"
        task_id = await self._create_pending_task(
            approval_id,
            "engine_remote_command",
            {
                "engine": "unreal",
                "endpoint_url": "http://localhost:30010/remote/object/call",
                "payload": {"objectPath": "/Game/Scene", "functionName": "CreateActor"},
            },
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(main, "is_replit_runtime", return_value=False),
            patch.object(main, "local_engine_tools_available", return_value=True),
            patch.object(
                main,
                "send_engine_remote_command",
                new=AsyncMock(return_value={"ok": True, "transport": "http", "statusCode": 200, "response": {"success": True}}),
            ) as engine_sender,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            engine_sender.assert_not_awaited()
            response = await self._choose_approval(task_id, approval_id, True)
            self.assertEqual(response.status_code, 200, response.text)
            for _ in range(50):
                pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
                if pending["status"] != "processing":
                    break
                await asyncio.sleep(0.01)

        engine_sender.assert_awaited_once_with(
            engine="unreal",
            endpoint_url="http://localhost:30010/remote/object/call",
            payload={"objectPath": "/Game/Scene", "functionName": "CreateActor"},
        )
        self.assertEqual(pending["status"], "approved")

    async def test_rejected_local_terminal_command_never_runs(self) -> None:
        approval_id = "approval-terminal-reject"
        task_id = await self._create_pending_task(
            approval_id,
            "terminal_command",
            {"command": "python -m pytest", "cwd": "."},
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(main, "run_approved_terminal_command") as terminal_runner,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            response = await self._choose_approval(task_id, approval_id, False)
            await asyncio.sleep(0)
        self.assertEqual(response.status_code, 200, response.text)
        terminal_runner.assert_not_called()
        pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
        self.assertEqual(pending["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
