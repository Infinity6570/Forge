from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from dotenv import dotenv_values

import main


APP_SOURCE = Path(__file__).resolve().parents[1] / "artifacts/meta-assistant/src/App.tsx"


class ProviderSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"

        self.env_file = root / ".env"
        self.database = workspace / "assistant.db"
        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "GEMINI_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
                "RUN_LOCAL_CODE": "false",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.path_patches = [
            patch.object(main, "ROOT", root),
            patch.object(main, "ENV_FILE", self.env_file),
            patch.object(main, "WORKSPACE", workspace),
            patch.object(main, "DATABASE", self.database),
            patch.object(main, "UPLOADS", workspace / "uploads"),
            patch.object(main, "NOTES", workspace / "notes"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

        main.init_db()
        self.assertTrue(self.database.is_file())

    async def put_settings(
        self,
        *,
        base_url: str,
        origin: str | None = None,
        provider: str = "gemini",
        model_id: str = "gemini-2.5-flash",
        **extra: str,
    ) -> httpx.Response:
        headers = {"Origin": origin} if origin else {}
        payload = {
            "provider": provider,
            "modelId": model_id,
            "codeRunnerEnabled": False,
            **extra,
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url=base_url,
        ) as client:
            return await client.put("/api/assistant/settings", json=payload, headers=headers)

    async def get_settings(self, *, base_url: str = "http://127.0.0.1") -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url=base_url,
        ) as client:
            return await client.get("/api/assistant/settings")

    async def test_local_settings_write_keys_to_temporary_env(self) -> None:
        response = await self.put_settings(
            base_url="http://127.0.0.1",
            provider="openai",
            model_id="gpt-4.1-mini",
            openaiApiKey="local-test-openai-key",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(dotenv_values(self.env_file)["OPENAI_API_KEY"], "local-test-openai-key")
        self.assertEqual(os.environ["OPENAI_API_KEY"], "local-test-openai-key")
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)

    async def test_same_origin_preview_can_write_provider_settings(self) -> None:
        preview_origin = "https://assistant.replit.dev"
        os.environ.update(
            {
                "REPL_ID": "test-repl",
                "REPLIT_DEV_DOMAIN": "assistant.replit.dev",
            }
        )

        response = await self.put_settings(
            base_url=preview_origin,
            origin=preview_origin,
            geminiApiKey="preview-test-gemini-key",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(dotenv_values(self.env_file)["GEMINI_API_KEY"], "preview-test-gemini-key")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "preview-test-gemini-key")

    async def test_untrusted_preview_origin_cannot_write_settings(self) -> None:
        os.environ.update(
            {
                "REPL_ID": "test-repl",
                "REPLIT_DEV_DOMAIN": "assistant.replit.dev",
            }
        )

        response = await self.put_settings(
            base_url="https://assistant.replit.dev",
            origin="https://attacker.example",
            geminiApiKey="must-not-be-saved",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.env_file.exists())
        self.assertEqual(os.environ["GEMINI_API_KEY"], "")

    async def test_provider_keys_are_redacted_from_settings_responses(self) -> None:
        test_keys = {
            "openaiApiKey": "test-openai-secret",
            "geminiApiKey": "test-gemini-secret",
            "openrouterApiKey": "test-openrouter-secret",
        }
        update_response = await self.put_settings(
            base_url="http://127.0.0.1",
            **test_keys,
        )
        read_response = await self.get_settings()

        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(read_response.status_code, 200, read_response.text)
        for secret in test_keys.values():
            self.assertNotIn(secret, update_response.text)
            self.assertNotIn(secret, read_response.text)
        self.assertTrue(read_response.json()["hasOpenaiKey"])
        self.assertTrue(read_response.json()["hasGeminiKey"])
        self.assertTrue(read_response.json()["hasOpenrouterKey"])
        self.assertEqual(
            main.redact_provider_keys("provider error: test-gemini-secret"),
            "provider error: [redacted]",
        )

    async def test_saved_provider_keys_survive_provider_and_model_updates(self) -> None:
        test_keys = {
            "openaiApiKey": "saved-openai-secret",
            "deepseekApiKey": "saved-deepseek-secret",
            "geminiApiKey": "saved-gemini-secret",
            "openrouterApiKey": "saved-openrouter-secret",
        }
        first_save = await self.put_settings(
            base_url="http://127.0.0.1",
            provider="openai",
            model_id="gpt-4.1-mini",
            **test_keys,
        )
        provider_change = await self.put_settings(
            base_url="http://127.0.0.1",
            provider="gemini",
            model_id="gemini-2.5-pro",
        )
        model_change = await self.put_settings(
            base_url="http://127.0.0.1",
            provider="gemini",
            model_id="gemini-2.5-flash",
        )
        read_response = await self.get_settings()

        for response in (first_save, provider_change, model_change, read_response):
            self.assertEqual(response.status_code, 200, response.text)
            for secret in test_keys.values():
                self.assertNotIn(secret, response.text)

        saved_env = dotenv_values(self.env_file)
        self.assertEqual(saved_env["AGENT_PROVIDER"], "gemini")
        self.assertEqual(saved_env["AGENT_MODEL"], "gemini-2.5-flash")
        for field, secret in test_keys.items():
            env_key = {
                "openaiApiKey": "OPENAI_API_KEY",
                "deepseekApiKey": "DEEPSEEK_API_KEY",
                "geminiApiKey": "GEMINI_API_KEY",
                "openrouterApiKey": "OPENROUTER_API_KEY",
            }[field]
            with self.subTest(env_key=env_key):
                self.assertEqual(saved_env[env_key], secret)
                self.assertEqual(os.environ[env_key], secret)

        settings = read_response.json()
        self.assertTrue(settings["hasOpenaiKey"])
        self.assertTrue(settings["hasDeepseekKey"])
        self.assertTrue(settings["hasGeminiKey"])
        self.assertTrue(settings["hasOpenrouterKey"])

    async def test_every_listed_gemini_model_and_custom_id_can_be_saved(self) -> None:
        source = APP_SOURCE.read_text()
        ui_gemini_models = re.search(
            r"gemini:\s*\[(.*?)\n\s*\],\s*openrouter:",
            source,
            flags=re.DOTALL,
        )
        ui_known_models = re.search(
            r"const GEMINI_MODEL_IDS = new Set\(\[(.*?)\]\);",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(ui_gemini_models, "Could not find Gemini model choices in the settings UI.")
        self.assertIsNotNone(ui_known_models, "Could not find the UI's known Gemini model IDs.")
        displayed_ids = set(re.findall(r"id:\s*'([^']+)'", ui_gemini_models.group(1)))
        known_ids = set(re.findall(r"'([^']+)'", ui_known_models.group(1)))
        self.assertEqual(displayed_ids, main.MODEL_OPTIONS["gemini"])
        self.assertEqual(known_ids, displayed_ids)

        for model_id in sorted(displayed_ids):
            with self.subTest(model_id=model_id):
                response = await self.put_settings(
                    base_url="http://127.0.0.1",
                    model_id=model_id,
                    geminiApiKey="test-gemini-key",
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["modelId"], model_id)

        custom_id = "models/gemini-3.1-pro-preview"
        custom_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id=custom_id,
            geminiApiKey="test-gemini-key",
        )
        self.assertEqual(custom_response.status_code, 200, custom_response.text)
        self.assertEqual(custom_response.json()["modelId"], custom_id)
        self.assertEqual(dotenv_values(self.env_file)["AGENT_MODEL"], custom_id)

    async def test_malformed_gemini_model_does_not_replace_saved_settings(self) -> None:
        saved_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id="gemini-2.5-flash",
            fallbackModelId="gemini-2.5-flash-lite",
            geminiApiKey="saved-gemini-key",
        )
        self.assertEqual(saved_response.status_code, 200, saved_response.text)
        saved_env = self.env_file.read_text()

        invalid_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id="gemini-2.5-flash?invalid",
            fallbackModelId="gemini-2.5-pro",
            geminiApiKey="replacement-gemini-key",
        )

        self.assertEqual(invalid_response.status_code, 422, invalid_response.text)
        self.assertEqual(self.env_file.read_text(), saved_env)
        self.assertEqual(os.environ["AGENT_MODEL"], "gemini-2.5-flash")
        self.assertEqual(os.environ["GEMINI_FALLBACK_MODEL"], "gemini-2.5-flash-lite")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "saved-gemini-key")

        wrong_provider_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id="gpt-4.1-mini",
            fallbackModelId="gemini-2.5-pro",
            geminiApiKey="replacement-gemini-key",
        )

        self.assertEqual(wrong_provider_response.status_code, 422, wrong_provider_response.text)
        self.assertIn("Gemini model ID", wrong_provider_response.json()["detail"])
        self.assertEqual(self.env_file.read_text(), saved_env)
        self.assertEqual(os.environ["AGENT_MODEL"], "gemini-2.5-flash")
        self.assertEqual(os.environ["GEMINI_FALLBACK_MODEL"], "gemini-2.5-flash-lite")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "saved-gemini-key")
    async def test_non_gemini_fallback_does_not_replace_saved_settings(self) -> None:
        saved_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id="gemini-2.5-flash",
            fallbackModelId="gemini-2.5-flash-lite",
            geminiApiKey="saved-gemini-key",
        )
        self.assertEqual(saved_response.status_code, 200, saved_response.text)
        saved_env = self.env_file.read_text()

        invalid_response = await self.put_settings(
            base_url="http://127.0.0.1",
            model_id="gemini-2.5-pro",
            fallbackModelId="gpt-4.1-mini",
            geminiApiKey="replacement-gemini-key",
        )

        self.assertEqual(invalid_response.status_code, 422, invalid_response.text)
        self.assertIn("Gemini fallback", invalid_response.json()["detail"])
        self.assertEqual(self.env_file.read_text(), saved_env)
        self.assertEqual(os.environ["AGENT_MODEL"], "gemini-2.5-flash")
        self.assertEqual(os.environ["GEMINI_FALLBACK_MODEL"], "gemini-2.5-flash-lite")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "saved-gemini-key")

    async def test_invalid_saved_gemini_fallback_is_not_returned(self) -> None:
        os.environ["GEMINI_FALLBACK_MODEL"] = "gpt-4.1-mini"

        response = await self.get_settings()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["fallbackModelId"], "")


if __name__ == "__main__":
    unittest.main()
