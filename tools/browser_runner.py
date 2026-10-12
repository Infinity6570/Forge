"""Ephemeral, bounded Chromium browsing. No saved profile, cookies or API keys."""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import os
from pathlib import Path
import shutil
from typing import Callable, Any
from urllib.parse import parse_qs, quote_plus, urlparse


class BrowserError(RuntimeError):
    pass


def browser_executable() -> str | None:
    explicit = os.getenv("CHROMIUM_EXECUTABLE_PATH")
    if explicit and Path(explicit).is_file():
        return explicit
    return next((path for name in ("chromium", "chromium-browser", "google-chrome", "msedge")
                 if (path := shutil.which(name))), None)


def chromium_available() -> bool:
    if not importlib.util.find_spec("playwright"):
        return False
    if browser_executable():
        return True
    roots = [
        Path.home() / ".cache/ms-playwright",
        Path.home() / "Library/Caches/ms-playwright",
        Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ms-playwright",
    ]
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
        roots.insert(0, Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    return any(any(root.glob(pattern)) for root in roots for pattern in
               ("chromium-*/chrome-linux*/chrome", "chromium-*/chrome-win*/chrome.exe",
                "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                "chromium_headless_shell-*/chrome-headless-shell-*/headless_shell*"))


def clean_browser_env() -> dict[str, str]:
    # Never propagate provider/search credentials into the browser process.
    allowed = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP",
               "SYSTEMROOT", "WINDIR", "LOCALAPPDATA", "APPDATA", "LD_LIBRARY_PATH",
               "FONTCONFIG_PATH", "FONTCONFIG_FILE", "XDG_RUNTIME_DIR")
    return {key: os.environ[key] for key in allowed if key in os.environ}


def unwrap_search_url(value: str) -> str:
    parsed = urlparse(value)
    args = parse_qs(parsed.query)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and args.get("uddg"):
        return args["uddg"][0]
    if parsed.hostname and parsed.hostname.endswith("bing.com") and args.get("u"):
        encoded = args["u"][0]
        if encoded.startswith("a1"):
            try:
                return base64.urlsafe_b64decode(encoded[2:] + "=" * (-len(encoded[2:]) % 4)).decode()
            except (ValueError, UnicodeError):
                pass
    return value


_SLOTS = asyncio.Semaphore(2)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"


class BrowserRunner:
    def __init__(self, validate_url: Callable[[str], str]):
        self.validate_url = validate_url

    async def _visit(self, url: str, search: bool) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._visit_impl(url, search), timeout=40)
        except asyncio.TimeoutError as exc:
            raise BrowserError("Chromium browsing exceeded its 40-second time limit.") from exc

    async def _visit_impl(self, url: str, search: bool) -> dict[str, Any]:
        await asyncio.to_thread(self.validate_url, url)
        if not chromium_available():
            raise BrowserError("Chromium is not installed. Run: python -m playwright install chromium")
        from playwright.async_api import async_playwright

        try:
            async with _SLOTS, async_playwright() as pw:
                options: dict[str, Any] = {
                    "headless": True, "timeout": 12_000, "env": clean_browser_env(),
                    "args": ["--disable-extensions", "--disable-background-networking",
                             "--disable-sync", "--disable-dev-shm-usage"],
                }
                executable = browser_executable()
                if executable:
                    options["executable_path"] = executable
                browser = await pw.chromium.launch(**options)
                try:
                    context = await browser.new_context(
                        user_agent=USER_AGENT, accept_downloads=False,
                        service_workers="block", viewport={"width": 1280, "height": 800},
                    )

                    async def guard(route: Any) -> None:
                        if route.request.resource_type in {"image", "media", "font"} or route.request.method not in {"GET", "HEAD"}:
                            await route.abort()
                            return
                        try:
                            await asyncio.to_thread(self.validate_url, route.request.url)
                        except (ValueError, OSError):
                            await route.abort()
                        else:
                            await route.continue_()

                    await context.route("**/*", guard)
                    await context.route_web_socket("**/*", lambda ws: ws.close())
                    page = await context.new_page()
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=18_000)
                    if response and response.status >= 400:
                        raise BrowserError(f"The public page returned HTTP {response.status}.")
                    try:
                        await page.wait_for_selector(
                            ".b_algo, .result, main, article" if search else "main, article, body",
                            timeout=2500,
                        )
                    except Exception:
                        pass  # DOM may be useful without a semantic main element.
                    if search:
                        items = await page.evaluate("""() => [...document.querySelectorAll('.b_algo, .result')].map(el => {
                          const a = el.querySelector('h2 a, .result__a');
                          const p = el.querySelector('.b_caption p, .result__snippet');
                          return {title: a?.innerText || '', url: a?.href || '', text: p?.innerText || ''};
                        }).filter(r => r.title && r.url).slice(0, 8)""")
                        results = []
                        for item in items:
                            destination = unwrap_search_url(item["url"])
                            try:
                                await asyncio.to_thread(self.validate_url, destination)
                            except (ValueError, OSError):
                                continue
                            results.append({"title": item["title"][:300], "url": destination,
                                            "text": item["text"][:1800]})
                        if not results:
                            raise BrowserError("Search returned no readable results (possibly a challenge page). Try a Search API; no empty result is treated as success.")
                        return {"engine": "chromium", "results": results}
                    text = await page.evaluate("""() => {
                      const root = (document.querySelector('main, article, [role="main"]') || document.body).cloneNode(true);
                      root.querySelectorAll('script, style, nav, footer, header, noscript, iframe, svg').forEach(el => el.remove());
                      return root.innerText || root.textContent || '';
                    }""")
                    text = " ".join(text.split())[:25_000]
                    if not text:
                        raise BrowserError("The browser page contains no readable text.")
                    return {"engine": "chromium", "url": page.url, "title": await page.title(), "text": text}
                finally:
                    await browser.close()
        except (BrowserError, ValueError):
            raise
        except TimeoutError as exc:
            raise BrowserError("Chromium browsing exceeded its 40-second time limit.") from exc
        except Exception as exc:
            # Don't reflect the browser process's environment/launch command in logs.
            raise BrowserError(f"Chromium could not load this page ({type(exc).__name__}). Check the browser installation or choose Search API.") from exc

    async def search(self, query: str) -> dict[str, Any]:
        return await self._visit("https://www.bing.com/search?q=" + quote_plus(query[:500]), True)

    async def fetch(self, url: str) -> dict[str, Any]:
        return await self._visit(url, False)
