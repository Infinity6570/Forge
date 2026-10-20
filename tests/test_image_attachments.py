from __future__ import annotations

import base64
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import main
from gemini_client import _make_contents
from llm_protocol import prepare_history
from model_client import _anthropic_messages


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-data"


class ImageAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.uploads = self.workspace / "uploads"
        self.uploads.mkdir()
        self.patches = [
            patch.object(main, "PROJECT_DIR", self.root.resolve()),
            patch.object(main, "BASE_DIR", self.workspace.resolve()),
            patch.object(main, "WORKSPACE", self.workspace),
            patch.object(main, "DATABASE", self.workspace / "assistant.db"),
            patch.object(main, "UPLOADS", self.uploads),
            patch.object(main, "NOTES", self.workspace / "notes"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        main.init_db()

    async def test_upload_accepts_valid_png_and_stores_detected_mime(self) -> None:
        uploaded = await main.upload_file(
            main.UploadFile(BytesIO(PNG_BYTES), filename="clinic.png")
        )
        self.assertEqual(uploaded["mimeType"], "image/png")
        self.assertEqual(uploaded["name"], "clinic.png")
        self.assertIn("Visual content", uploaded["extractedText"])
        row = main.db_one("SELECT disk_path,size_bytes FROM files WHERE id=?", (uploaded["id"],))
        self.assertEqual(Path(row["disk_path"]).read_bytes(), PNG_BYTES)
        self.assertEqual(row["size_bytes"], len(PNG_BYTES))

    async def test_image_extension_with_non_image_bytes_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as error:
            await main.upload_file(
                main.UploadFile(BytesIO(b"not an image"), filename="clinic.png")
            )
        self.assertEqual(error.exception.status_code, 415)
        self.assertIn("does not match", error.exception.detail)

    async def test_task_submit_returns_clear_unsupported_model_error_before_queueing(self) -> None:
        uploaded = await main.upload_file(
            main.UploadFile(BytesIO(PNG_BYTES), filename="clinic.png")
        )
        body = main.TaskInput(
            objective="Describe this image",
            provider="deepseek",
            model="deepseek-chat",
            fileIds=[uploaded["id"]],
        )
        with patch.object(main, "credential_for", return_value="test-provider-key"):
            with self.assertRaises(HTTPException) as error:
                await main.create_task(body, None)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("can't read image attachments", error.exception.detail)
        self.assertEqual(main.db_one("SELECT COUNT(*) AS count FROM tasks")["count"], 0)

    def test_unsupported_model_error_is_specific_and_actionable(self) -> None:
        path = self.uploads / "clinic.png"
        path.write_bytes(PNG_BYTES)
        with self.assertRaises(HTTPException) as error:
            main.validate_image_attachments("deepseek", "deepseek-chat", [{
                "name": "clinic.png",
                "mime_type": "image/png",
                "size_bytes": len(PNG_BYTES),
                "path": str(path),
            }])
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("deepseek-chat", error.exception.detail)
        self.assertIn("can't read image attachments", error.exception.detail)

    def test_provider_limits_are_checked_before_sending(self) -> None:
        path = self.uploads / "large.png"
        with path.open("wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
            handle.truncate(main.ANTHROPIC_IMAGE_MAX_BYTES + 1)
        with self.assertRaises(HTTPException) as error:
            main.validate_image_attachments("anthropic", "claude-sonnet-5-5", [{
                "name": "large.png",
                "mime_type": "image/png",
                "path": str(path),
            }])
        self.assertEqual(error.exception.status_code, 413)
        self.assertIn("up to 5 MB each", error.exception.detail)

    def test_anthropic_receives_native_base64_image_block(self) -> None:
        encoded = base64.b64encode(PNG_BYTES).decode("ascii")
        _, messages = _anthropic_messages([{
            "role": "user",
            "content": "Describe this image.",
            "images": [{"name": "clinic.png", "mime_type": "image/png", "data_base64": encoded}],
        }])
        blocks = messages[0]["content"]
        self.assertEqual(blocks[0], {"type": "text", "text": "Describe this image."})
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["source"], {
            "type": "base64",
            "media_type": "image/png",
            "data": encoded,
        })

    def test_gemini_receives_native_inline_image_part(self) -> None:
        encoded = base64.b64encode(PNG_BYTES).decode("ascii")
        contents, _ = _make_contents([{
            "role": "user",
            "content": "Describe this image.",
            "images": [{"mime_type": "image/png", "data_base64": encoded}],
        }])
        parts = contents[0].parts
        self.assertEqual(parts[0].text, "Describe this image.")
        image_part = parts[1].model_dump(mode="json", exclude_none=True, by_alias=True)
        self.assertEqual(image_part["inlineData"]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(image_part["inlineData"]["data"]), PNG_BYTES)

    def test_openai_compatible_vision_models_receive_image_url_parts(self) -> None:
        encoded = base64.b64encode(PNG_BYTES).decode("ascii")
        history = prepare_history([{
            "role": "user",
            "content": "Describe this image.",
            "images": [{"mime_type": "image/png", "data_base64": encoded}],
        }], "openai")
        self.assertEqual(history[0]["content"], [
            {"type": "text", "text": "Describe this image."},
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{encoded}",
            }},
        ])

    def test_image_hydration_does_not_accept_paths_outside_uploads(self) -> None:
        outside = self.root / "private.png"
        outside.write_bytes(PNG_BYTES)
        with self.assertRaises(HTTPException) as error:
            main.hydrate_image_attachments([{
                "role": "user",
                "content": "Read it",
                "images": [{
                    "name": "private.png",
                    "mime_type": "image/png",
                    "size_bytes": len(PNG_BYTES),
                    "path": str(outside),
                }],
            }], "gemini", "gemini-3.8-flash")
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("no longer available", error.exception.detail)


if __name__ == "__main__":
    unittest.main()
