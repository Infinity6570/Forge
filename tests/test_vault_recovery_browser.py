from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "meta-assistant"
LOCKED_SECRET = "previously-saved-vault-secret"
REPLACEMENT_SECRET = "replacement-browser-test-secret"


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class VaultRecoveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = available_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        env = os.environ.copy()
        env["PORT"] = str(cls.port)
        cls.server = subprocess.Popen(
            ["pnpm", "exec", "vite", "--config", "vite.config.ts", "--host", "127.0.0.1"],
            cwd=ARTIFACT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError("Vite exited before the vault recovery browser test server became ready.")
            try:
                with urlopen(cls.base_url, timeout=1):
                    break
            except (OSError, URLError):
                time.sleep(0.25)
        else:
            cls.server.terminate()
            raise RuntimeError("Vite did not become ready for the vault recovery browser test.")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def test_locked_vault_recovery_requires_confirmation_and_replacement_without_exposing_secrets(self) -> None:
        executable = os.environ.get("CHROMIUM_EXECUTABLE_PATH") or shutil.which("chromium")
        if not executable:
            candidate = Path("/repl/tools/bin/chromium")
            executable = str(candidate) if candidate.is_file() else None
        self.assertIsNotNone(executable, "A Chromium executable is required for browser coverage.")

        locked = {
            "vault_status": "locked",
            "openai_api_key": "not_set",
            "deepseek_api_key": "not_set",
            "gemini_api_key": "unavailable",
            "openrouter_api_key": "not_set",
            "tavily_api_key": "not_set",
            "serper_api_key": "not_set",
            "brave_search_api_key": "not_set",
            "kite_api_key": "not_set",
            "kite_api_secret": "not_set",
            "kite_access_token": "not_set",
            "alpha_vantage_api_key": "not_set",
            "finnhub_api_key": "not_set",
            "goldapi_io_key": "not_set",
            "oilpriceapi_key": "not_set",
            "commodity_api_key": "not_set",
        }
        saved_requests: list[dict[str, object]] = []
        vault_state = {"locked": True}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 900})

                def mock_api(route) -> None:
                    request = route.request
                    path = request.url.split("?", 1)[0]
                    if path.endswith("/assistant/settings"):
                        body = {
                            "provider": "gemini",
                            "modelId": "gemini-2.5-flash",
                            "fallbackModelId": "",
                            "ollamaBaseUrl": "",
                            "localSetupAllowed": True,
                            "providerSettingsAllowed": True,
                            "hasOpenaiKey": False,
                            "hasDeepseekKey": False,
                            "hasGeminiKey": False,
                            "hasOpenrouterKey": False,
                            "codeRunnerEnabled": False,
                            "appPreviewsEnabled": False,
                        }
                    elif path.endswith("/vault/keys") and request.method == "GET":
                        body = {**locked, "vault_status": "locked" if vault_state["locked"] else "ready"}
                        if not vault_state["locked"]:
                            body["gemini_api_key"] = "configured"
                    elif path.endswith("/vault/keys") and request.method == "POST":
                        saved_requests.append(json.loads(request.post_data or "{}"))
                        vault_state["locked"] = False
                        body = {**locked, "vault_status": "ready", "gemini_api_key": "configured"}
                    elif path.endswith("/assistant/timers"):
                        body = []
                    elif path.endswith("/assistant/system-prompt"):
                        body = {"systemPrompt": "", "isCustomized": False}
                    else:
                        body = []
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

                page.route("**/api/**", mock_api)
                page_errors: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(f"{self.base_url}/settings", wait_until="domcontentloaded")

                page.get_by_test_id("status-vault-locked").wait_for(state="visible")
                recovery_notice = page.get_by_test_id("status-vault-locked").inner_text()
                self.assertIn("Restore the original", recovery_notice)
                self.assertIn("VAULT_ENCRYPTION_KEY", recovery_notice)
                self.assertIn("re-enter the credentials", recovery_notice)
                self.assertIn("permanently removes the inaccessible encrypted entries", recovery_notice)
                self.assertIn("only the credentials you re-enter will be kept", recovery_notice)
                reset_confirmation = page.get_by_test_id("confirm-vault-reset-row").inner_text()
                self.assertIn("Reset inaccessible saved credentials", reset_confirmation)
                self.assertIn("permanently discarded", reset_confirmation)
                self.assertIn("at least one replacement credential", reset_confirmation)

                self.assertNotIn(LOCKED_SECRET, page.locator("body").inner_text())
                secret_fields = page.locator('[data-testid="settings-api-keys-vault"] input[type="password"]')
                for index in range(secret_fields.count()):
                    self.assertEqual(secret_fields.nth(index).input_value(), "")

                save_button = page.get_by_test_id("button-save-provider")
                self.assertTrue(save_button.is_disabled(), "Reset must be unavailable before confirmation.")

                page.get_by_test_id("checkbox-confirm-vault-reset").check()
                self.assertTrue(save_button.is_disabled(), "Confirmation alone must not enable reset.")

                replacement_field = page.get_by_test_id("input-geminiApiKey")
                replacement_field.fill(REPLACEMENT_SECRET)
                self.assertEqual(replacement_field.get_attribute("type"), "password")
                self.assertNotIn(REPLACEMENT_SECRET, page.locator("body").inner_text())
                self.assertFalse(save_button.is_disabled(), "Confirmation plus a replacement key should enable reset.")

                with page.expect_response(lambda response: response.url.endswith("/api/vault/keys") and response.request.method == "POST") as response_info:
                    save_button.click()
                self.assertEqual(response_info.value.status, 200)
                self.assertEqual(len(saved_requests), 1)
                self.assertTrue(saved_requests[0].get("recoverLockedVault"))
                self.assertEqual(saved_requests[0].get("geminiApiKey"), REPLACEMENT_SECRET)
                self.assertNotIn(LOCKED_SECRET, json.dumps(saved_requests))

                page.get_by_test_id("status-provider-saved").wait_for(state="visible")
                self.assertEqual(replacement_field.input_value(), "")
                self.assertNotIn(LOCKED_SECRET, page.locator("body").inner_text())
                self.assertNotIn(REPLACEMENT_SECRET, page.locator("body").inner_text())
                self.assertEqual(page_errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
