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


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ResponsiveConsoleBrowserTests(unittest.TestCase):
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
                raise RuntimeError("Vite exited before the browser test server became ready.")
            try:
                with urlopen(cls.base_url, timeout=1):
                    break
            except (OSError, URLError):
                time.sleep(0.25)
        else:
            cls.server.terminate()
            raise RuntimeError("Vite did not become ready for the browser test.")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def test_console_remains_usable_across_screen_sizes(self) -> None:
        executable = os.environ.get("CHROMIUM_EXECUTABLE_PATH") or shutil.which("chromium")
        if not executable:
            candidate = Path("/repl/tools/bin/chromium")
            executable = str(candidate) if candidate.is_file() else None
        self.assertIsNotNone(executable, "A Chromium executable is required for browser coverage.")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                for viewport in (
                    {"width": 390, "height": 844},
                    {"width": 1366, "height": 768},
                    {"width": 1920, "height": 1080},
                    {"width": 2560, "height": 1080},
                ):
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()

                        def mock_api(route) -> None:
                            path = route.request.url.split("?", 1)[0]
                            if path.endswith("/assistant/dashboard"):
                                body = {
                                    "activeTasks": 0,
                                    "completedTasks": 0,
                                    "activeTimers": 0,
                                    "notesCount": 0,
                                    "filesCount": 0,
                                    "recentTasks": [],
                                }
                            elif path.endswith("/assistant/settings"):
                                body = {
                                    "provider": "gemini",
                                    "modelId": "gemini-2.5-flash",
                                    "fallbackModelId": "",
                                    "ollamaBaseUrl": "",
                                    "localSetupAllowed": False,
                                    "providerSettingsAllowed": False,
                                    "hasOpenaiKey": False,
                                    "hasDeepseekKey": False,
                                    "hasGeminiKey": False,
                                    "hasOpenrouterKey": False,
                                    "codeRunnerEnabled": False,
                                    "appPreviewsEnabled": False,
                                }
                            elif path.endswith("/assistant/preview"):
                                body = {"staticAvailable": False, "apps": []}
                            else:
                                body = []
                            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

                        page.route("**/api/**", mock_api)
                        page_errors: list[str] = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.route(
                            "https://s3.tradingview.com/tv.js",
                            lambda route: route.fulfill(
                                status=200,
                                content_type="application/javascript",
                            body="window.__tvSymbols=[];window.__tvWidgets=0;window.__tvRemoved=0;window.TradingView={widget:function(options){window.__tvWidgets++;window.__tvSymbols.push(options.symbol);this.chart=function(){return {setSymbol:function(symbol){window.__tvSymbols.push(symbol);}}};this.onChartReady=function(callback){callback();};this.remove=function(){window.__tvRemoved++;};}};",
                            ),
                        )
                        page.goto(self.base_url, wait_until="domcontentloaded")

                        toggle = page.get_by_test_id("button-toggle-console")
                        toggle.wait_for(state="visible")
                        starts_open = viewport["width"] >= 1600
                        self.assertEqual(toggle.get_attribute("aria-expanded"), str(starts_open).lower())
                        self.assertEqual(page.get_by_test_id("right-inspector").count(), 1 if starts_open else 0)
                        toggle_box = toggle.bounding_box()
                        self.assertIsNotNone(toggle_box)
                        self.assertGreaterEqual(toggle_box["x"], 0)
                        self.assertLessEqual(toggle_box["x"] + toggle_box["width"], viewport["width"])

                        chat_before = page.locator(".center-pane").bounding_box()
                        self.assertIsNotNone(chat_before)
                        if not starts_open:
                            toggle.click()
                        inspector = page.get_by_test_id("right-inspector")
                        inspector.wait_for(state="visible")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
                        panel_box = inspector.bounding_box()
                        self.assertIsNotNone(panel_box)
                        self.assertGreater(panel_box["width"], 0)
                        self.assertLessEqual(panel_box["x"] + panel_box["width"], viewport["width"])
                        expected_position = "relative" if viewport["width"] >= 1500 else "fixed"
                        self.assertEqual(inspector.evaluate("(el) => getComputedStyle(el).position"), expected_position)

                        market_radar = page.get_by_test_id("section-market-radar")
                        market_radar.wait_for(state="visible")
                        self.assertEqual(page.get_by_test_id("text-market-symbol").inner_text(), "TVC:GOLD")
                        self.assertEqual(page.get_by_test_id("button-market-comex-gold").get_attribute("aria-pressed"), "true")
                        for button_id, expected_symbol in [
                            ("button-market-wti-crude", "TVC:USOIL"),
                            ("button-market-natural-gas", "TVC:NATGAS"),
                            ("button-market-mcx-gold-inr", "MCX:GOLD1!"),
                            ("button-market-nifty-50", "NSE:NIFTY"),
                        ]:
                            page.get_by_test_id(button_id).click()
                            self.assertEqual(page.get_by_test_id("text-market-symbol").inner_text(), expected_symbol)
                            self.assertEqual(page.get_by_test_id(button_id).get_attribute("aria-pressed"), "true")
                            self.assertEqual(
                                page.evaluate("window.__tvSymbols[window.__tvSymbols.length - 1]"),
                                expected_symbol,
                            )
                        self.assertEqual(page.evaluate("window.__tvWidgets"), 1)
                        self.assertEqual(page.evaluate("window.__tvRemoved"), 0)

                        live_preview_tab = page.get_by_test_id("tab-inspector-live-preview")
                        live_preview_tab.click()
                        self.assertEqual(live_preview_tab.get_attribute("aria-selected"), "true")
                        page.get_by_test_id("workspace-live-preview").wait_for(state="visible")

                        if viewport["width"] >= 1500:
                            maximize = page.get_by_test_id("button-toggle-preview-maximize")
                            normal_panel_box = inspector.bounding_box()
                            maximize.click()
                            self.assertTrue(page.locator(".app-frame").evaluate("(el) => el.classList.contains('preview-maximized')"))
                            self.assertIsNone(page.locator(".main-area").bounding_box())
                            expanded_panel_box = inspector.bounding_box()
                            self.assertIsNotNone(normal_panel_box)
                            self.assertIsNotNone(expanded_panel_box)
                            self.assertGreater(expanded_panel_box["width"], normal_panel_box["width"])
                            maximize.click()
                            self.assertFalse(page.locator(".app-frame").evaluate("(el) => el.classList.contains('preview-maximized')"))
                            self.assertIsNotNone(page.locator(".main-area").bounding_box())

                        workspace_tab = page.get_by_test_id("tab-workspace-inspector")
                        workspace_tab.click()
                        self.assertEqual(workspace_tab.get_attribute("aria-selected"), "true")
                        page.get_by_test_id("workspace-inspector").wait_for(state="visible")
                        tab_box = workspace_tab.bounding_box()
                        self.assertIsNotNone(tab_box)
                        self.assertGreaterEqual(tab_box["x"], panel_box["x"])
                        self.assertLessEqual(tab_box["x"] + tab_box["width"], panel_box["x"] + panel_box["width"])

                        toggle.click()
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        self.assertEqual(page.get_by_test_id("right-inspector").count(), 0)
                        page.wait_for_timeout(300)
                        chat_after = page.locator(".center-pane").bounding_box()
                        self.assertIsNotNone(chat_after)
                        self.assertAlmostEqual(chat_after["x"], chat_before["x"], delta=1)
                        if starts_open:
                            self.assertGreater(chat_after["width"], chat_before["width"])
                        else:
                            self.assertAlmostEqual(chat_after["width"], chat_before["width"], delta=1)
                        self.assertEqual(page_errors, [])
                        context.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
