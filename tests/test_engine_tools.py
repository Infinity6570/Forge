from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from tools.agent_tools import (
    run_blender_automation,
    send_engine_remote_command,
    validate_blender_request,
    validate_engine_endpoint,
    validate_engine_remote_request,
)


class EngineToolValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def test_blender_files_are_confined_and_existing_render_is_never_overwritten(self) -> None:
        project = self.workspace / "scene.blend"
        project.write_bytes(b"blend")
        result = validate_blender_request(
            self.workspace,
            "import bpy\n",
            "scene.blend",
            "renders/final.png",
        )
        self.assertEqual(result, {
            "blend_filepath": "scene.blend",
            "render_output_path": "renders/final.png",
        })
        for path in ("../outside.blend", "/etc/passwd", r"C:\Users\private\scene.blend"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                validate_blender_request(self.workspace, "import bpy\n", path)

        (self.workspace / "existing.png").write_bytes(b"keep")
        with self.assertRaisesRegex(PermissionError, "already exists"):
            validate_blender_request(
                self.workspace,
                "import bpy\n",
                render_output_path="existing.png",
            )
        self.assertEqual((self.workspace / "existing.png").read_bytes(), b"keep")
        frame_dir = self.workspace / "frames"
        frame_dir.mkdir()
        (frame_dir / "render0001.png").write_bytes(b"existing frame")
        with self.assertRaisesRegex(PermissionError, "already exists"):
            validate_blender_request(
                self.workspace,
                "import bpy\n",
                render_output_path="frames/render.png",
            )

    def test_symlinked_blender_paths_are_rejected(self) -> None:
        outside = self.root / "outside.blend"
        outside.write_bytes(b"blend")
        (self.workspace / "linked.blend").symlink_to(outside)
        with self.assertRaisesRegex(PermissionError, "Symbolic links"):
            validate_blender_request(self.workspace, "import bpy\n", "linked.blend")

    def test_engine_endpoint_must_be_local_http_or_websocket_without_credentials(self) -> None:
        for url in (
            "http://localhost:30010/remote/object/call",
            "http://127.0.0.1:30010/action",
            "ws://[::1]:8765",
        ):
            self.assertEqual(validate_engine_endpoint(url), url)
        for url in (
            "https://localhost:30010/action",
            "wss://localhost:30010/action",
            "http://example.com:30010/action",
            "http://user:pass@localhost:30010/action",
            "http://localhost:30010/action?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(PermissionError):
                validate_engine_endpoint(url)

    def test_engine_payload_validation_rejects_non_json_and_oversized_payloads(self) -> None:
        with self.assertRaises(PermissionError):
            validate_engine_remote_request("unreal", "http://localhost:30010", {"bad": object()})
        with self.assertRaises(PermissionError):
            validate_engine_remote_request("blender", "http://localhost:8765", {"data": "x" * 33_000})

    def test_blender_runner_uses_clean_environment_workspace_and_reports_output(self) -> None:
        script = "import bpy\nprint('rendering scene')\n"
        render_path = "renders/frame.png"
        observed: dict[str, object] = {}

        class FakeProcess:
            returncode = 0

            def wait(self, timeout: int) -> int:
                observed["timeout"] = timeout
                return 0

        def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
            observed["argv"] = argv
            observed["cwd"] = kwargs["cwd"]
            observed["shell"] = kwargs["shell"]
            env = kwargs["env"]
            observed["env"] = env
            script_path = Path(argv[-1])
            self.assertEqual(script_path.name, "temp_blender_task.py")
            self.assertEqual(script_path.read_text(encoding="utf-8"), script)
            kwargs["stdout"].write(b"Blender render complete\n")
            kwargs["stderr"].write(b"")
            output = self.workspace / render_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"image")
            return FakeProcess()

        with (
            patch("tools.agent_tools.shutil.which", return_value="/usr/bin/blender"),
            patch("tools.agent_tools.subprocess.Popen", side_effect=fake_popen),
            patch.dict(os.environ, {"PATH": "/safe/bin", "OPENAI_API_KEY": "must-not-leak"}, clear=True),
        ):
            result = run_blender_automation(
                script,
                render_output_path=render_path,
                workspace=self.workspace,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "Blender render complete\n")
        self.assertEqual(result["renderedOutputPaths"], [render_path])
        self.assertEqual(observed["cwd"], self.workspace.resolve())
        self.assertIs(observed["shell"], False)
        self.assertEqual(observed["timeout"], 600)
        self.assertNotIn("OPENAI_API_KEY", observed["env"])
        self.assertNotIn("PYTHONPATH", observed["env"])
        argv = observed["argv"]
        self.assertIn("--background", argv)
        self.assertIn("--disable-autoexec", argv)
        self.assertIn("--python-exit-code", argv)
        self.assertIn("--render-output", argv)

    def test_missing_blender_fails_explicitly(self) -> None:
        with patch("tools.agent_tools.shutil.which", return_value=None):
            result = run_blender_automation("import bpy\n", workspace=self.workspace)
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def test_local_http_bridge_posts_json_without_proxy_or_redirects(self) -> None:
        original_client = httpx.AsyncClient
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            return httpx.Response(200, json={"ok": True})

        def create_client(**kwargs: object) -> httpx.AsyncClient:
            seen["clientOptions"] = kwargs.copy()
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        with patch("tools.agent_tools.httpx.AsyncClient", side_effect=create_client):
            result = asyncio.run(send_engine_remote_command(
                "unreal",
                "http://localhost:30010/remote/object/call",
                {"objectPath": "/Game/Scene"},
            ))
        request = seen["request"]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "http://localhost:30010/remote/object/call")
        self.assertEqual(request.read(), b'{"objectPath":"/Game/Scene"}')
        self.assertFalse(seen["clientOptions"]["trust_env"])
        self.assertFalse(seen["clientOptions"]["follow_redirects"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["response"], {"ok": True})

    def test_local_websocket_bridge_sends_and_receives_json(self) -> None:
        observed: dict[str, object] = {}

        class FakeConnection:
            async def __aenter__(self) -> "FakeConnection":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def send(self, message: str) -> None:
                observed["message"] = message

            async def recv(self) -> str:
                return '{"executed":true}'

        def fake_connect(url: str, **kwargs: object) -> FakeConnection:
            observed["url"] = url
            observed["options"] = kwargs
            return FakeConnection()

        with patch("tools.agent_tools.websocket_connect", side_effect=fake_connect):
            result = asyncio.run(send_engine_remote_command(
                "blender",
                "ws://127.0.0.1:8765",
                {"command": "render"},
            ))
        self.assertEqual(observed["url"], "ws://127.0.0.1:8765")
        self.assertEqual(observed["message"], '{"command": "render"}')
        self.assertTrue(result["ok"])
        self.assertEqual(result["response"], {"executed": True})


if __name__ == "__main__":
    unittest.main()
