from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from tools.browser_runner import BrowserError
from tools.screen_capture import inspect_local_page, validate_local_page_url


class LocalPageUrlTests(unittest.TestCase):
    def test_accepts_loopback_http_urls(self) -> None:
        for url in (
            "http://localhost:5173/",
            "https://127.0.0.1:8443/settings",
            "http://[::1]:3000/",
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_local_page_url(url), url)

    def test_rejects_non_local_urls_and_invalid_schemes(self) -> None:
        for url in (
            "https://example.com/",
            "http://localhost.evil.test/",
            "http://127.0.0.2/",
            "file:///etc/passwd",
            "ftp://localhost/",
            "http://user:pass@localhost/",
            "http://localhost:99999/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_local_page_url(url)


class LocalPageInspectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_inspection_rejects_external_url_before_browser_launch(self) -> None:
        with patch("tools.screen_capture.chromium_available") as browser_available:
            with self.assertRaisesRegex(ValueError, "localhost"):
                await inspect_local_page("https://example.com/")
        browser_available.assert_not_called()

    async def test_inspection_returns_page_state_and_always_closes_browser(self) -> None:
        observed: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as temporary:
            screenshot_dir = Path(temporary) / "workspace" / "inspections"

            class FakeRequest:
                def __init__(self, url: str, method: str = "GET") -> None:
                    self.url = url
                    self.method = method

            class FakeRoute:
                def __init__(self, url: str, method: str = "GET") -> None:
                    self.request = FakeRequest(url, method)
                    self.aborted = False
                    self.continued = False

                async def abort(self) -> None:
                    self.aborted = True

                async def continue_(self) -> None:
                    self.continued = True

            class FakePage:
                url = "http://localhost:5173/"

                def on(self, event: str, handler: object) -> None:
                    observed[f"handler:{event}"] = handler

                async def goto(self, url: str, **_kwargs: object) -> SimpleNamespace:
                    observed["navigated"] = url
                    return SimpleNamespace(status=200)

                async def wait_for_timeout(self, _milliseconds: int) -> None:
                    return None

                async def evaluate(self, _script: str, _args: object) -> dict[str, object]:
                    return {
                        "text": "Forge local page",
                        "controls": [{"tag": "textarea", "placeholder": "Message Forge", "value": ""}],
                        "composerState": [{"tag": "textarea", "placeholder": "Message Forge", "value": ""}],
                    }

                async def title(self) -> str:
                    return "Forge"

                async def screenshot(self, *, path: str, **_kwargs: object) -> None:
                    Path(path).write_bytes(b"test screenshot")

            page = FakePage()

            class FakeContext:
                async def route(self, _pattern: str, handler: object) -> None:
                    observed["route_handler"] = handler

                async def route_web_socket(self, _pattern: str, _handler: object) -> None:
                    return None

                async def new_page(self) -> FakePage:
                    return page

            context = FakeContext()

            class FakeBrowser:
                async def new_context(self, **_kwargs: object) -> FakeContext:
                    return context

                async def close(self) -> None:
                    observed["browser_closed"] = True

            browser = FakeBrowser()

            class FakeChromium:
                async def launch(self, **_kwargs: object) -> FakeBrowser:
                    return browser

            class FakePlaywright:
                chromium = FakeChromium()

            class FakePlaywrightManager:
                async def __aenter__(self) -> FakePlaywright:
                    return FakePlaywright()

                async def __aexit__(self, *_args: object) -> None:
                    observed["playwright_closed"] = True

            with (
                patch("tools.screen_capture.chromium_available", return_value=True),
                patch("tools.screen_capture.browser_executable", return_value=None),
                patch("tools.screen_capture.INSPECTION_DIR", screenshot_dir),
                patch("playwright.async_api.async_playwright", return_value=FakePlaywrightManager()),
            ):
                result = await inspect_local_page("http://localhost:5173/")

            self.assertEqual(result["text"], "Forge local page")
            self.assertEqual(result["controls"][0]["tag"], "textarea")
            self.assertEqual(result["composerState"][0]["placeholder"], "Message Forge")
            self.assertEqual(result["consoleErrors"], [])
            self.assertEqual(result["title"], "Forge")
            screenshot_path = Path(temporary) / result["screenshotPath"]
            self.assertTrue(screenshot_path.is_file())
            self.assertTrue(observed["browser_closed"])
            self.assertTrue(observed["playwright_closed"])

            handler = observed["route_handler"]
            external_route = FakeRoute("https://example.com/image.png")
            await handler(external_route)
            self.assertTrue(external_route.aborted)
            post_route = FakeRoute("http://localhost:5173/save", "POST")
            await handler(post_route)
            self.assertTrue(post_route.aborted)

    async def test_browser_is_closed_if_navigation_fails(self) -> None:
        observed: dict[str, bool] = {}

        class FakeContext:
            async def route(self, *_args: object) -> None:
                return None

            async def route_web_socket(self, *_args: object) -> None:
                return None

            async def new_page(self) -> object:
                class Page:
                    def on(self, *_args: object) -> None:
                        return None

                    async def goto(self, *_args: object, **_kwargs: object) -> None:
                        raise OSError("local server stopped")

                return Page()

        class FakeBrowser:
            async def new_context(self, **_kwargs: object) -> FakeContext:
                return FakeContext()

            async def close(self) -> None:
                observed["closed"] = True

        browser = FakeBrowser()

        class FakeChromium:
            async def launch(self, **_kwargs: object) -> FakeBrowser:
                return browser

        class FakePlaywrightManager:
            async def __aenter__(self) -> SimpleNamespace:
                return SimpleNamespace(chromium=FakeChromium())

            async def __aexit__(self, *_args: object) -> None:
                observed["playwright_closed"] = True

        with (
            patch("tools.screen_capture.chromium_available", return_value=True),
            patch("tools.screen_capture.browser_executable", return_value=None),
            patch("playwright.async_api.async_playwright", return_value=FakePlaywrightManager()),
        ):
            with self.assertRaises(BrowserError):
                await inspect_local_page("http://localhost:5173/")
        self.assertTrue(observed["closed"])
        self.assertTrue(observed["playwright_closed"])

    async def test_main_dispatch_and_tool_schema_expose_inspection(self) -> None:
        payload = {
            "url": "http://localhost:5173/",
            "text": "page",
            "controls": [],
            "composerState": [],
            "consoleErrors": [],
            "screenshotPath": "workspace/inspections/page-test.png",
        }
        with patch("main.inspect_local_page", new_callable=AsyncMock, return_value=payload):
            result = await main.execute_tool(
                "inspect_local_page", {"url": "http://localhost:5173/"},
                "openai", {"model": "gpt-4o"}, "", "test",
            )
        self.assertEqual(json.loads(result), payload)
        tool = next(tool for tool in main.TOOLS if tool["function"]["name"] == "inspect_local_page")
        self.assertIn("localhost", tool["function"]["description"])


if __name__ == "__main__":
    unittest.main()
