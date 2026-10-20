from __future__ import annotations

import asyncio
import json
import os
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
            patch.object(main, "PROJECT_DIR", self.root.resolve()),
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

    def test_shell_runner_executes_commands_from_the_project_root(self) -> None:
        result = main.run_workspace_command(
            "mkdir -p generated/site && printf 'built' > generated/site/index.html && cat generated/site/index.html"
        )
        self.assertEqual(result["returnCode"], 0)
        self.assertEqual(result["stdout"], "built")
        self.assertEqual(
            (self.root / "generated/site/index.html").read_text(encoding="utf-8"),
            "built",
        )

    def test_critical_shell_commands_are_classified_for_human_approval(self) -> None:
        self.assertIsNone(main.workspace_action_requiring_approval(
            "run_command",
            {"command": "mkdir -p generated/site", "cwd": "."},
        ))
        self.assertIsNone(main.workspace_action_requiring_approval(
            "run_command",
            {"command": "rm generated/site/index.html", "cwd": "."},
        ))
        self.assertIsNone(main.workspace_action_requiring_approval(
            "run_command",
            {"command": "echo 'rm generated/site/index.html'", "cwd": "."},
        ))
        approval = main.workspace_action_requiring_approval(
            "run_command",
            {"command": "rm -rf generated/site", "cwd": "."},
        )
        self.assertIsNotNone(approval)
        self.assertEqual(approval[0], "critical_shell_command")
        self.assertIn("rm -rf generated/site", approval[1]["command"])
        protected = main.workspace_action_requiring_approval(
            "run_command",
            {"command": "rm main.py", "cwd": "."},
        )
        self.assertIsNotNone(protected)
        outside = main.workspace_action_requiring_approval(
            "run_command",
            {"command": "rm ../outside.txt", "cwd": "."},
        )
        self.assertIsNotNone(outside)

    async def test_scoped_delete_is_immediate_but_protected_changes_wait_for_approval(self) -> None:
        protected = self.root / "main.py"
        protected.write_text("original()", encoding="utf-8")
        important = self.root / "important.txt"
        important.write_text("keep me", encoding="utf-8")

        delete_result = json.loads(await main.execute_tool(
            "delete_file",
            {"path": "important.txt"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ))
        self.assertTrue(delete_result["deleted"])
        self.assertFalse(important.exists())

        critical_delete_result = json.loads(await main.execute_tool(
            "delete_file",
            {"path": "main.py"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ))
        self.assertTrue(critical_delete_result["approvalRequired"])
        self.assertTrue(protected.exists())

        write_result = json.loads(await main.execute_tool(
            "write_file",
            {"path": "main.py", "content": "updated()"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ))
        self.assertTrue(write_result["saved"])
        self.assertEqual(protected.read_text(encoding="utf-8"), "updated()")
        self.assertIsNone(main.workspace_action_requiring_approval(
            "write_file",
            {"path": "main.py", "content": "updated again()"},
        ))
        protected.write_text("original()", encoding="utf-8")

        delete_action, delete_payload, _ = main.workspace_action_requiring_approval(
            "delete_file",
            {"path": "main.py"},
        )
        self.assertTrue(protected.exists())
        protected.write_text("different content after delete approval", encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "changed while approval"):
            main.apply_approved_workspace_action(delete_action, delete_payload)
        protected.write_text("original()", encoding="utf-8")
        delete_action, delete_payload, _ = main.workspace_action_requiring_approval(
            "delete_file",
            {"path": "main.py"},
        )
        deleted = json.loads(main.apply_approved_workspace_action(delete_action, delete_payload))
        self.assertTrue(deleted["deleted"])
        self.assertFalse(protected.exists())

    async def test_routine_source_writes_are_immediate_but_bootstrap_config_is_gated(self) -> None:
        source_path = self.root / "main.py"
        source_path.write_text("before()", encoding="utf-8")
        result = json.loads(await main.execute_tool(
            "write_file",
            {"path": "main.py", "content": "after()"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ))
        self.assertTrue(result["saved"])
        self.assertEqual(source_path.read_text(encoding="utf-8"), "after()")

        runtime_config = self.root / ".replit"
        runtime_config.write_text("run = 'python main.py'\n", encoding="utf-8")
        pending = json.loads(await main.execute_tool(
            "write_file",
            {"path": ".replit", "content": "run = 'python other.py'\n"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ))
        self.assertTrue(pending["approvalRequired"])
        self.assertEqual(runtime_config.read_text(encoding="utf-8"), "run = 'python main.py'\n")

    def test_source_write_paths_are_not_misclassified_as_critical(self) -> None:
        for path in (
            "main.py",
            "tools/agent_tools.py",
            "artifacts/meta-assistant/src/App.tsx",
            "package.json",
            "requirements.txt",
        ):
            with self.subTest(path=path):
                self.assertIsNone(main.workspace_action_requiring_approval(
                    "write_file",
                    {"path": path, "content": "task scoped update"},
                ))
        self.assertIsNotNone(main.workspace_action_requiring_approval(
            "write_file",
            {"path": ".replit", "content": "run = 'python main.py'\n"},
        ))

    async def test_critical_recursive_shell_command_only_returns_approval_request(self) -> None:
        with patch.object(main, "run_workspace_command") as run_command:
            result = json.loads(await main.execute_tool(
                "run_command",
                {"command": "rm -rf sample.txt"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            ))
        self.assertTrue(result["approvalRequired"])
        self.assertEqual(result["action"], "critical_shell_command")
        run_command.assert_not_called()

    async def test_run_command_and_run_terminal_command_execute_without_approval_or_toggle(self) -> None:
        for tool_name in ("run_command", "run_terminal_command"):
            with self.subTest(tool=tool_name):
                raw = await main.execute_tool(
                    tool_name,
                    {"command": "python -c \"print('shell-enabled')\""},
                    "gemini",
                    {"model": "test-model"},
                    "",
                    "test-task",
                )
                result = json.loads(raw)
                self.assertEqual(result["returnCode"], 0)
                self.assertEqual(result["stdout"], "shell-enabled\n")
        self.assertIsNone(
            main.workspace_action_requiring_approval(
                "run_terminal_command",
                {"command": "mkdir -p created", "cwd": "."},
            )
        )

    async def test_project_file_and_shell_tool_results_redact_environment_secrets(self) -> None:
        secret = "test-session-secret-value"
        with patch.dict("os.environ", {"SESSION_SECRET": secret}):
            (self.root / ".env").write_text(f"SESSION_SECRET={secret}\n", encoding="utf-8")
            file_result = await main.execute_tool(
                "read_file",
                {"path": ".env"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            )
            shell_result = await main.execute_tool(
                "run_command",
                {"command": "python -c \"import os; print(os.environ['SESSION_SECRET'])\""},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            )
        self.assertNotIn(secret, file_result)
        self.assertNotIn(secret, shell_result)
        self.assertIn("[redacted]", file_result)
        self.assertIn("[redacted]", shell_result)

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

    async def test_project_file_tools_write_hidden_paths_append_and_delete_without_approval(self) -> None:
        created = main.write_project_file(
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
        self.assertEqual((self.root / "web/src/App.tsx").read_text(encoding="utf-8"), "replacement\n")
        hidden = await main.execute_tool(
            "create_file",
            {"path": ".forge-data/nested/config.json", "content": "{\"mode\":\"open\"}"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        appended = await main.execute_tool(
            "append_file",
            {"path": ".forge-data/nested/config.json", "content": "\n"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        self.assertTrue(main.parse_json(hidden, {})["saved"])
        self.assertEqual(main.parse_json(appended, {})["mode"], "append")
        self.assertEqual(
            (self.root / ".forge-data/nested/config.json").read_text(encoding="utf-8"),
            "{\"mode\":\"open\"}\n",
        )
        replaced = await main.execute_tool(
            "replace_in_file",
            {
                "path": ".forge-data/nested/config.json",
                "old_text": "{\"mode\":\"open\"}",
                "new_text": "{\"mode\":\"closed\"}",
            },
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        replaced_result = main.parse_json(replaced, {})
        self.assertTrue(replaced_result["saved"])
        self.assertEqual(replaced_result["replacements"], 1)
        self.assertEqual(
            main.successful_workspace_write_path("replace_in_file", replaced),
            ".forge-data/nested/config.json",
        )
        ambiguous = await main.execute_tool(
            "replace_in_file",
            {
                "path": ".forge-data/nested/config.json",
                "old_text": "absent",
                "new_text": "open",
            },
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        self.assertIn("not found", main.parse_json(ambiguous, {})["error"])
        self.assertEqual(
            (self.root / ".forge-data/nested/config.json").read_text(encoding="utf-8"),
            "{\"mode\":\"closed\"}\n",
        )
        read_back = await main.execute_tool(
            "read_file",
            {"path": ".forge-data/nested/config.json"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        )
        self.assertIn("closed", main.parse_json(read_back, {})["content"])
        deleted = main.parse_json(await main.execute_tool(
            "delete_file",
            {"path": ".forge-data/nested/config.json"},
            "gemini",
            {"model": "test-model"},
            "",
            "test-task",
        ), {})
        self.assertTrue(deleted["deleted"])
        self.assertFalse((self.root / ".forge-data/nested/config.json").exists())
        with self.assertRaises(PermissionError):
            main.project_path("../outside.py")
        self.assertEqual(main.list_workspace_directory(".")["path"], ".")

    async def test_project_root_self_management_tools_read_list_and_write_code_files(self) -> None:
        (self.root / "main.py").write_text("APP_VERSION = 'before'\n", encoding="utf-8")
        (self.root / "templates").mkdir()
        (self.root / "templates" / "index.html").write_text("<main>old</main>\n", encoding="utf-8")

        root_listing = main.parse_json(
            await main.execute_tool(
                "list_directory",
                {"path": "."},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            ),
            {},
        )
        self.assertIn("main.py", {entry["name"] for entry in root_listing["entries"]})
        self.assertIn("templates", {entry["name"] for entry in root_listing["entries"]})

        read_result = main.parse_json(
            await main.execute_tool(
                "read_file",
                {"path": "main.py"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            ),
            {},
        )
        self.assertEqual(read_result["content"], "APP_VERSION = 'before'\n")
        write_result = main.parse_json(
            await main.execute_tool(
                "write_file",
                {"path": "tools/agent_tools.py", "content": "# updated tool module\n"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            ),
            {},
        )
        self.assertTrue(write_result["saved"])
        self.assertEqual(
            (self.root / "tools" / "agent_tools.py").read_text(encoding="utf-8"),
            "# updated tool module\n",
        )
        (self.root / ".env").write_text(
            "GEMINI_API_KEY=test-only-secret\nAPP_MODE=local\n",
            encoding="utf-8",
        )
        env_read = main.parse_json(
            await main.execute_tool(
                "read_file",
                {"path": ".env"},
                "gemini",
                {"model": "test-model"},
                "",
                "test-task",
            ),
            {},
        )
        self.assertNotIn("test-only-secret", env_read["content"])
        self.assertIn("GEMINI_API_KEY=[redacted]", env_read["content"])
        self.assertIn("APP_MODE=local", env_read["content"])
        with self.assertRaises(PermissionError):
            main.project_path("../outside.py")

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

    async def test_nested_html_preview_entries_and_assets_are_served_safely(self) -> None:
        project = self.workspace / "dental-clinic"
        assets = project / "assets"
        assets.mkdir(parents=True)
        entry = project / "index.html"
        stylesheet = assets / "site.css"
        script = assets / "site.js"
        entry.write_text(
            '<link rel="stylesheet" href="assets/site.css"><h1>Nested preview</h1>'
            '<script type="module" src="assets/site.js"></script>',
            encoding="utf-8",
        )
        stylesheet.write_text("body { color: cyan; }\n", encoding="utf-8")
        script.write_text("document.documentElement.dataset.ready = 'yes';\n", encoding="utf-8")
        hidden_page = self.workspace / "dental-clinic" / "node_modules" / "private" / "index.html"
        hidden_page.parent.mkdir(parents=True)
        hidden_page.write_text("not served", encoding="utf-8")

        now_ns = __import__("time").time_ns()
        os.utime(self.preview_file, ns=(now_ns - 20_000_000_000, now_ns - 20_000_000_000))
        os.utime(entry, ns=(now_ns - 10_000_000_000, now_ns - 10_000_000_000))
        os.utime(stylesheet, ns=(now_ns, now_ns))
        manager = main.WorkspacePreviewManager(self.workspace)
        entries = main.list_workspace_html_entries(self.workspace)
        self.assertEqual([item["path"] for item in entries], ["dental-clinic/index.html", "sample.html"])
        self.assertTrue(entries[0]["previewUrl"].startswith("/workspace-preview/dental-clinic/index.html"))
        self.assertEqual(entries[0]["projectModifiedAt"], str(stylesheet.stat().st_mtime_ns))

        with patch.object(main, "PREVIEW_MANAGER", manager):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app),
                base_url="http://127.0.0.1",
            ) as client:
                entry_response = await client.get(
                    "/workspace-preview/dental-clinic?cache=preview",
                    follow_redirects=True,
                )
                relative_css_path = entry_response.url.path.rsplit("/", 1)[0] + "/assets/site.css"
                css_response = await client.get(relative_css_path)
                bare_directory_response = await client.get("/workspace-preview/dental-clinic")
                js_response = await client.get(
                    "/workspace-preview/dental-clinic/assets/site.js",
                    headers={"Origin": "null"},
                )
                clinic_root_alias = await client.get("/dental-clinic/")
                clinic_css_alias = await client.get("/dental-clinic/assets/site.css")
                workspace_clinic_js_alias = await client.get(
                    "/workspace/dental-clinic/assets/site.js",
                    headers={"Origin": "null"},
                )
                workspace_clinic_root_redirect = await client.get(
                    "/workspace/dental-clinic",
                )
                root_redirect_response = await client.get("/workspace-preview")
                entries_response = await client.get("/api/workspace/html-entries")
                status_response = await client.get("/api/workspace/preview")
                traversal_response = await client.get("/workspace-preview/%2E%2E%2Fsample.html")
        self.assertEqual(entry_response.status_code, 200, entry_response.text)
        self.assertEqual(entry_response.url.path, "/workspace-preview/dental-clinic/")
        self.assertEqual(entry_response.url.query, b"cache=preview")
        self.assertIn("Nested preview", entry_response.text)
        self.assertIn("sandbox", entry_response.headers["content-security-policy"])
        self.assertEqual(entry_response.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(bare_directory_response.status_code, 307)
        self.assertEqual(
            bare_directory_response.headers["location"],
            "/workspace-preview/dental-clinic/",
        )
        self.assertEqual(root_redirect_response.status_code, 307)
        self.assertEqual(root_redirect_response.headers["location"], "/workspace-preview/")
        self.assertEqual(clinic_root_alias.status_code, 200)
        self.assertIn("Nested preview", clinic_root_alias.text)
        self.assertEqual(clinic_css_alias.status_code, 200)
        self.assertIn("color: cyan", clinic_css_alias.text)
        self.assertEqual(workspace_clinic_js_alias.status_code, 200)
        self.assertEqual(
            workspace_clinic_js_alias.headers.get("access-control-allow-origin"),
            "null",
        )
        self.assertEqual(workspace_clinic_root_redirect.status_code, 307)
        self.assertEqual(
            workspace_clinic_root_redirect.headers["location"],
            "/workspace/dental-clinic/",
        )
        self.assertEqual(css_response.headers["content-type"].split(";")[0], "text/css")
        self.assertIn("color: cyan", css_response.text)
        self.assertIn("dataset.ready", js_response.text)
        self.assertEqual(js_response.headers.get("access-control-allow-origin"), "null")
        self.assertEqual(entries_response.json()[0]["path"], "dental-clinic/index.html")
        self.assertEqual(status_response.json()["staticEntryPath"], "dental-clinic/index.html")
        self.assertEqual(status_response.json()["htmlEntries"][0]["path"], "dental-clinic/index.html")
        self.assertIn(traversal_response.status_code, {403, 404})

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

    async def test_critical_shell_command_runs_only_after_explicit_approval(self) -> None:
        approval_id = "approval-critical-shell"
        task_id = await self._create_pending_task(
            approval_id,
            "critical_shell_command",
            {"command": "rm -rf sample.txt", "cwd": "."},
        )

        async def fake_worker(*_args: object) -> None:
            return None

        with (
            patch.object(main, "run_workspace_command", return_value={
                "returnCode": 0,
                "timedOut": False,
                "stdout": "",
                "stderr": "",
            }) as shell_runner,
            patch.object(main, "run_agent_task", new=fake_worker),
        ):
            response = await self._choose_approval(task_id, approval_id, True)
            self.assertEqual(response.status_code, 200, response.text)
            for _ in range(50):
                pending = main.db_one("SELECT status FROM pending_approvals WHERE id=?", (approval_id,))
                if pending["status"] != "processing":
                    break
                await asyncio.sleep(0.01)

        shell_runner.assert_called_once_with("rm -rf sample.txt", ".")
        self.assertEqual(pending["status"], "approved")
        self.assertTrue(self.sample.exists())

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
