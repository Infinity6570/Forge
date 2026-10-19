from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import main


class WorkspaceCanvasTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.patch = patch.object(main, "WORKSPACE", self.workspace)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_lists_renderable_files_without_exposing_dotfiles(self):
        (self.workspace / "index.html").write_text("<h1>Preview</h1>", encoding="utf-8")
        docs = self.workspace / "docs"
        docs.mkdir()
        (docs / "guide.md").write_text("# Guide", encoding="utf-8")
        (self.workspace / ".env").write_text("OPENAI_API_KEY=do-not-show", encoding="utf-8")
        (self.workspace / "api-token.txt").write_text("do-not-show", encoding="utf-8")

        files = await main.list_workspace_canvas_files()

        paths = {entry["path"] for entry in files}
        self.assertEqual(paths, {"index.html", "docs/guide.md"})
        html = next(entry for entry in files if entry["path"] == "index.html")
        self.assertEqual(html["kind"], "html")
        self.assertEqual(html["previewUrl"], "/workspace-preview/index.html")
        markdown = next(entry for entry in files if entry["path"] == "docs/guide.md")
        self.assertEqual(markdown["kind"], "markdown")

    async def test_returns_text_file_content_for_read_only_canvas(self):
        docs = self.workspace / "docs"
        docs.mkdir()
        path = docs / "guide.md"
        path.write_text("# Guide\n\n## Findings", encoding="utf-8")

        result = await main.get_workspace_canvas_file("docs/guide.md")

        self.assertEqual(result["path"], "docs/guide.md")
        self.assertEqual(result["content"], "# Guide\n\n## Findings")
        self.assertFalse(result["truncated"])

    async def test_rejects_traversal_and_non_text_content(self):
        outside = Path(self.temp_dir.name) / "outside.md"
        outside.write_text("private", encoding="utf-8")
        (self.workspace / "diagram.pdf").write_bytes(b"%PDF")

        with self.assertRaises(HTTPException) as traversal:
            await main.get_workspace_canvas_file("../outside.md")
        self.assertEqual(traversal.exception.status_code, 404)

        with self.assertRaises(HTTPException) as binary:
            await main.get_workspace_canvas_file("diagram.pdf")
        self.assertEqual(binary.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
