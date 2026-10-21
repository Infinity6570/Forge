from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import elevated_runner


class ElevatedRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.audit_path = self.root / "logs" / "elevated_audit.log"
        self.path_patches = [
            patch.object(elevated_runner, "PROJECT_ROOT", self.root),
            patch.object(elevated_runner, "AUDIT_LOG_PATH", self.audit_path),
            patch.object(elevated_runner, "is_process_elevated", return_value=False),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

    def test_linux_uses_pkexec_and_audits_exact_command(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
        with (
            patch.object(elevated_runner.platform, "system", return_value="Linux"),
            patch.object(elevated_runner.shutil, "which", side_effect=lambda name: "/usr/bin/pkexec" if name == "pkexec" else None),
            patch.object(elevated_runner.subprocess, "run", return_value=completed) as run,
        ):
            result = elevated_runner.execute_elevated_command("id")

        self.assertEqual(result["returnCode"], 0)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pkexec", "/bin/sh", "-c", "id"])
        self.assertFalse(run.call_args.kwargs["shell"])
        records = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["event"] for record in records], ["started", "completed"])
        self.assertTrue(all(record["command"] == "id" for record in records))
        self.assertIn("timestamp", records[0])

    def test_windows_uses_encoded_powershell_uac_and_exact_command_file(self) -> None:
        command = "whoami /groups"
        captured: dict[str, Path] = {}

        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(argv[0], "powershell.exe")
            script = base64.b64decode(argv[-1]).decode("utf-16le")
            self.assertIn("Start-Process", script)
            self.assertIn("-Verb RunAs -Wait", script)
            encoded_path = re.search(r"FromBase64String\('([^']+)'\)", script)
            self.assertIsNotNone(encoded_path)
            command_file = Path(base64.b64decode(encoded_path.group(1)).decode("utf-8"))
            self.assertEqual(command_file.read_bytes(), (command + "\r\n").encode("utf-8"))
            captured["path"] = command_file
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with (
            patch.object(elevated_runner.platform, "system", return_value="Windows"),
            patch.object(elevated_runner.subprocess, "run", side_effect=fake_run),
        ):
            result = elevated_runner.execute_elevated_command(command)

        self.assertEqual(result["returnCode"], 0)
        self.assertFalse(captured["path"].exists())
        records = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[-1]["command"], command)

    def test_empty_multiline_and_oversized_commands_are_rejected(self) -> None:
        for command in ("", "first\nsecond", "x" * 4001):
            with self.subTest(command=repr(command[:20])), self.assertRaises(PermissionError):
                elevated_runner.validate_elevated_command(command)

    def test_destructive_or_chained_commands_are_blocked_even_before_approval(self) -> None:
        blocked = (
            "rmdir /s /q C:\\temp",
            "del /f /s /q C:\\temp\\*",
            "format C:",
            "diskpart",
            "reg delete HKLM\\Software\\Example",
            "powershell Remove-Item -Recurse C:\\temp",
            "shutdown /s",
            "rm -rf /tmp/example",
            "dd if=/dev/zero of=/dev/sda",
            "python -c \"print(1)\"",
            "whoami && id",
            "whoami > output.txt",
        )
        for command in blocked:
            with self.subTest(command=command), self.assertRaises(PermissionError):
                elevated_runner.validate_elevated_command(command)


if __name__ == "__main__":
    unittest.main()
