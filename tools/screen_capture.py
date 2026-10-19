"""Read-only inspection of pages served from localhost."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tools.browser_runner import (
    BrowserError,
    USER_AGENT,
    browser_executable,
    clean_browser_env,
    chromium_available,
)

MAX_INSPECTION_TEXT_CHARS = 30_000
MAX_VISIBLE_CONTROLS = 200
MAX_CONSOLE_ERRORS = 40
INSPECTION_TIMEOUT_SECONDS = 40
INSPECTION_DIR = Path(__file__).resolve().parents[1] / "workspace" / "inspections"
_SLOTS = asyncio.Semaphore(2)


def validate_local_page_url(url: str) -> str:
    """Reject any URL that can address a non-loopback host."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2_048:
        raise ValueError("Provide an HTTP or HTTPS URL served from localhost.")
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise ValueError("The local page URL is invalid.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("Page inspection is restricted to HTTP(S) URLs on localhost.")
    return url.strip()


def _inspection_screenshot_path() -> Path:
    INSPECTION_DIR.mkdir(parents=True, exist_ok=True)
    if INSPECTION_DIR.is_symlink():
        raise BrowserError("The page-inspection screenshot directory cannot be a symbolic link.")
    return INSPECTION_DIR / f"page-{uuid.uuid4().hex}.png"


async def inspect_local_page(url: str) -> dict[str, Any]:
    """Inspect a rendered localhost page and save a screenshot in workspace/inspections/."""
    target = validate_local_page_url(url)
    if not chromium_available():
        raise BrowserError("Chromium is not installed. Run: python -m playwright install chromium")

    from playwright.async_api import async_playwright

    async def inspect() -> dict[str, Any]:
        async with async_playwright() as playwright:
            options: dict[str, Any] = {
                "headless": True,
                "timeout": 12_000,
                "env": clean_browser_env(),
                "args": [
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-dev-shm-usage",
                    "--no-proxy-server",
                ],
            }
            executable = browser_executable()
            if executable:
                options["executable_path"] = executable

            browser = await playwright.chromium.launch(**options)
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    accept_downloads=False,
                    service_workers="block",
                    viewport={"width": 1365, "height": 900},
                )

                async def guard(route: Any) -> None:
                    request = route.request
                    try:
                        validate_local_page_url(request.url)
                    except ValueError:
                        await route.abort()
                        return
                    if request.method not in {"GET", "HEAD"}:
                        await route.abort()
                        return
                    await route.continue_()

                await context.route("**/*", guard)
                await context.route_web_socket("**/*", lambda websocket: websocket.close())
                page = await context.new_page()
                console_errors: list[str] = []

                def record_console_error(message: Any) -> None:
                    if message.type == "error" and len(console_errors) < MAX_CONSOLE_ERRORS:
                        console_errors.append(message.text[:1_000])

                def record_page_error(error: Any) -> None:
                    if len(console_errors) < MAX_CONSOLE_ERRORS:
                        console_errors.append(str(error)[:1_000])

                page.on("console", record_console_error)
                page.on("pageerror", record_page_error)
                response = await page.goto(target, wait_until="domcontentloaded", timeout=20_000)
                if response and response.status >= 400:
                    raise BrowserError(f"The local page returned HTTP {response.status}.")
                validate_local_page_url(page.url)
                await page.wait_for_timeout(350)

                snapshot = await page.evaluate(
                    """({maxText, maxControls}) => {
                      const visible = (element) => {
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                          Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
                      };
                      const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                      const text = normalize(document.body?.innerText || '').slice(0, maxText);
                      const selector = [
                        'button', 'input', 'textarea', 'select',
                        '[role="button"]', '[role="checkbox"]', '[role="radio"]',
                        '[role="switch"]', '[role="combobox"]', '[role="tab"]',
                        '[role="textbox"]', '[contenteditable="true"]'
                      ].join(',');
                      const controls = [...document.querySelectorAll(selector)]
                        .filter(visible)
                        .slice(0, maxControls)
                        .map((element) => {
                          const tag = element.tagName.toLowerCase();
                          const type = (element.getAttribute('type') || '').toLowerCase();
                          const labels = element.labels ? [...element.labels].map(label => normalize(label.innerText)).join(' ') : '';
                          const label = normalize(
                            element.getAttribute('aria-label') || labels ||
                            element.getAttribute('title') || element.innerText
                          );
                          const isPassword = type === 'password';
                          const value = isPassword ? '[hidden]' :
                            (typeof element.value === 'string' ? element.value.slice(0, 500) :
                              (element.isContentEditable ? normalize(element.innerText).slice(0, 500) : undefined));
                          return {
                            tag,
                            type: type || undefined,
                            role: element.getAttribute('role') || undefined,
                            contenteditable: Boolean(element.isContentEditable),
                            label: label.slice(0, 300),
                            placeholder: (element.getAttribute('placeholder') || '').slice(0, 300) || undefined,
                            value,
                            disabled: Boolean(element.disabled),
                            checked: typeof element.checked === 'boolean' ? element.checked : undefined,
                            selected: tag === 'select' ? normalize(element.selectedOptions?.[0]?.innerText) : undefined
                          };
                        });
                      const composerState = controls.filter(control =>
                        control.tag === 'textarea' || control.role === 'textbox' ||
                        control.type === 'text' || control.type === 'search' ||
                        control.contenteditable
                      );
                      return {text, controls, composerState};
                    }""",
                    {"maxText": MAX_INSPECTION_TEXT_CHARS, "maxControls": MAX_VISIBLE_CONTROLS},
                )

                screenshot_path = _inspection_screenshot_path()
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=True, timeout=10_000)
                except Exception:
                    screenshot_path.unlink(missing_ok=True)
                    raise
                return {
                    "url": page.url,
                    "title": (await page.title())[:500],
                    "text": snapshot["text"],
                    "controls": snapshot["controls"],
                    "composerState": snapshot["composerState"],
                    "consoleErrors": console_errors,
                    "screenshotPath": screenshot_path.relative_to(INSPECTION_DIR.parents[1]).as_posix(),
                }
            finally:
                await browser.close()

    try:
        async with _SLOTS:
            return await asyncio.wait_for(inspect(), timeout=INSPECTION_TIMEOUT_SECONDS)
    except (BrowserError, ValueError):
        raise
    except asyncio.TimeoutError as error:
        raise BrowserError("Local page inspection exceeded its 40-second time limit.") from error
    except Exception as error:
        raise BrowserError(
            f"Chromium could not inspect this local page ({type(error).__name__})."
        ) from error
