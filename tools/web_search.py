"""Portable search routing: Gemini native grounding, personal APIs, or Chromium."""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Callable
from urllib.parse import urlparse
import httpx

from tools.browser_runner import BrowserRunner

SEARCH_KEY_NAMES = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY", "brave": "BRAVE_SEARCH_API_KEY"}


class SearchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        quota: bool = False,
        status_code: int | None = None,
        fallback_reason: str | None = None,
    ):
        super().__init__(message)
        self.quota = quota
        self.status_code = status_code
        self.fallback_reason = fallback_reason


class _GroundingThrottle:
    """Pace consecutive grounding calls made by the same agent task."""

    def __init__(self):
        self._states: dict[str, dict[str, Any]] = {}
        self._states_lock = asyncio.Lock()

    async def run(self, task_id: str, operation: Callable[[], Any]):
        async with self._states_lock:
            now = asyncio.get_running_loop().time()
            if len(self._states) >= 512:
                stale = [
                    key for key, entry in self._states.items()
                    if not entry["lock"].locked()
                    and entry["last_completed"] is not None
                    and now - entry["last_completed"] >= 60
                ]
                for key in stale:
                    self._states.pop(key, None)
                    if len(self._states) < 512:
                        break
            state = self._states.setdefault(task_id, {
                "lock": asyncio.Lock(), "last_completed": None, "consecutive": 0,
            })
        async with state["lock"]:
            now = asyncio.get_running_loop().time()
            previous = state["last_completed"]
            if previous is not None and now - previous < 60:
                state["consecutive"] = min(state["consecutive"] + 1, 5)
                delay = min(1.5 * (2 ** (state["consecutive"] - 2)), 12.0)
                await asyncio.sleep(delay * random.uniform(0.9, 1.1))
            else:
                state["consecutive"] = 1
            try:
                return await operation()
            finally:
                state["last_completed"] = asyncio.get_running_loop().time()


_grounding_throttle = _GroundingThrottle()


def search_settings() -> dict[str, Any]:
    mode = os.getenv("WEB_SEARCH_MODE", "native")
    engine = os.getenv("WEB_SEARCH_API_PROVIDER", "tavily")
    return {
        "searchMode": mode if mode in {"native", "api", "chromium"} else "native",
        "searchApiProvider": engine if engine in SEARCH_KEY_NAMES else "tavily",
        "searchChromiumFallback": os.getenv("WEB_SEARCH_CHROMIUM_FALLBACK", "false").lower() == "true",
        "hasTavilyKey": bool(os.getenv("TAVILY_API_KEY")),
        "hasSerperKey": bool(os.getenv("SERPER_API_KEY")),
        "hasBraveKey": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
    }


def check_response(response: httpx.Response, engine: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchError(f"{engine} returned a non-JSON response (HTTP {response.status_code}).",
                          quota=response.status_code in {402, 429}, status_code=response.status_code) from exc
    if not isinstance(payload, dict):
        raise SearchError(f"{engine} returned an unexpected response shape.", status_code=response.status_code)
    if response.is_error or payload.get("error"):
        # Keep credentials and arbitrary provider bodies out of task logs.
        details = str(payload.get("error", payload.get("message", ""))).lower()
        quota = response.status_code in {402, 429} or (
            response.status_code in {200, 400, 403} and any(
                word in details for word in ("quota", "resource_exhausted", "not enough credits", "credits exhausted", "usage limit")
            )
        )
        raise SearchError(f"{engine} search failed (HTTP {response.status_code}). "
                          + ("Quota/rate limit exhausted." if quota else "Check the key, model support, and provider access."),
                          quota=quota, status_code=response.status_code)
    return payload


def normalized_results(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    results = []
    seen = set()
    for item in items[:64]:
        url = str(item.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or url in seen:
            continue
        seen.add(url)
        results.append({
            "title": str(item.get("title") or parsed.hostname)[:300],
            "url": url[:8192], "text": str(item.get("text", ""))[:2400],
        })
    return results


class GeminiGroundingAdapter:
    """Separate GenerateContent call: do not mix hosted and custom function tools.

    The agent's existing OpenAI-compatible history (including thought signatures)
    is untouched. The returned grounding metadata becomes a normal tool result.
    """
    async def search(self, query: str, model: str) -> dict[str, Any]:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise SearchError("Add a Gemini API key in Preferences before using native grounding.")
        model = model.removeprefix("models/")
        if not model.startswith("gemini-") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in model):
            raise SearchError("Native Google grounding requires a compatible Gemini model. Choose Search API or Chromium for Gemma/custom unsupported models.")
        async with httpx.AsyncClient(timeout=35, follow_redirects=False) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": "Search the public web for this query and answer with source citations: " + query}]}],
                    "tools": [{"google_search": {}}],
                    "generationConfig": {"maxOutputTokens": 4096},
                },
            )
        payload = check_response(response, "Google grounding")
        candidates = payload.get("candidates") or []
        if not candidates:
            raise SearchError("Google grounding returned no answer (possibly a safety block).")
        candidate = candidates[0]
        answer = "\n".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought"))
        metadata = candidate.get("groundingMetadata") or {}
        items = []
        for chunk in metadata.get("groundingChunks", []):
            web = chunk.get("web", {})
            if web.get("uri"):
                items.append({"title": web.get("title"), "url": web["uri"], "text": ""})
        if not answer.strip():
            raise SearchError("Google grounding returned no usable text.")
        result: dict[str, Any] = {
            "engine": "google-grounding", "model": model, "answer": answer,
            "results": normalized_results(items), "groundingMetadata": metadata,
            "grounded": bool(metadata.get("groundingChunks")),
        }
        if not result["grounded"]:
            result["warning"] = "Google did not return grounding sources; do not describe this answer as verified web evidence."
        return result


async def search_api(query: str, engine: str) -> dict[str, Any]:
    key = os.getenv(SEARCH_KEY_NAMES[engine])
    if not key:
        raise SearchError(f"No {engine.title()} search key is saved. Add it in API Keys Vault.")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        if engine == "tavily":
            response = await client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"},
                                         json={"query": query, "max_results": 6, "search_depth": "basic"})
        elif engine == "serper":
            response = await client.post("https://google.serper.dev/search", headers={"X-API-KEY": key},
                                         json={"q": query, "num": 6})
        else:
            response = await client.get("https://api.search.brave.com/res/v1/web/search",
                                        headers={"X-Subscription-Token": key, "Accept": "application/json"},
                                        params={"q": query, "count": 6})
    payload = check_response(response, engine.title())
    items = (
        [{"title": r.get("title"), "url": r.get("url"), "text": r.get("content")} for r in payload.get("results", [])]
        if engine == "tavily" else
        [{"title": r.get("title"), "url": r.get("link"), "text": r.get("snippet")} for r in payload.get("organic", [])]
        if engine == "serper" else
        [{"title": r.get("title"), "url": r.get("url"), "text": r.get("description")} for r in payload.get("web", {}).get("results", [])]
    )
    results = normalized_results(items)
    if not results:
        raise SearchError(f"{engine.title()} returned no readable results. Refine the query; no empty array is treated as success.")
    return {"engine": engine, "results": results}


def _google_failure_reason(error: Exception) -> str:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "Google Timeout"
    if isinstance(error, SearchError):
        if error.status_code == 429:
            return "Google 429 Throttled"
        message = str(error).lower()
        if "no answer" in message or "no usable text" in message or "empty result" in message:
            return "Google Empty Results"
        if error.status_code is not None:
            return f"Google HTTP {error.status_code}"
    return "Google Error"


async def _grounding_search_with_retry(adapter: GeminiGroundingAdapter, query: str, model: str) -> dict[str, Any]:
    try:
        return await adapter.search(query, model)
    except SearchError as first_error:
        if first_error.status_code != 429:
            raise

    # Retry once before consuming an alternate provider's quota.
    await asyncio.sleep(1.5 * random.uniform(0.9, 1.1))
    try:
        return await adapter.search(query, model)
    except (SearchError, httpx.TimeoutException, httpx.RequestError) as retry_error:
        reason = _google_failure_reason(retry_error)
        raise SearchError(
            "Google grounding retry failed after the initial HTTP 429.",
            quota=getattr(retry_error, "quota", False),
            status_code=getattr(retry_error, "status_code", None),
            fallback_reason=reason,
        ) from retry_error


async def _fallback_from_google_failure(
    query: str,
    validate_url: Callable[[str], str],
    settings: dict[str, Any],
    failure_reason: str,
    google_error: SearchError,
) -> dict[str, Any]:
    attempted: list[str] = []
    failures: list[str] = []
    for engine in ("tavily", "serper", "brave"):
        if not os.getenv(SEARCH_KEY_NAMES[engine]):
            continue
        attempted.append(engine)
        try:
            result = await search_api(query, engine)
            result.update(
                fallbackFrom="google-grounding",
                fallbackReason=failure_reason,
                fallbackAttempted=attempted,
                warning=f"{failure_reason}; search results came from {engine.title()} instead.",
            )
            return result
        except SearchError:
            # A saved key may itself be rate-limited, invalid, or out of credits.
            # Continue in the configured fallback order without exposing provider details.
            failures.append(engine)

    if settings["searchChromiumFallback"]:
        result = await BrowserRunner(validate_url).search(query)
        result.update(
            fallbackFrom="google-grounding",
            fallbackReason=failure_reason,
            fallbackAttempted=attempted,
            warning=f"{failure_reason}; saved API fallbacks were unavailable, so Chromium was used.",
        )
        return result

    if not attempted:
        reason = "No Tavily, Serper, or Brave API key is saved in the API Keys Vault."
    else:
        reason = f"Configured search fallbacks were unavailable ({', '.join(failures)})."
    raise SearchError(
        f"{failure_reason}. {reason} Save a search API key or enable Chromium fallback.",
        quota=google_error.quota,
        status_code=google_error.status_code,
    )


async def routed_search(
    query: str,
    provider: str,
    model: str,
    validate_url: Callable[[str], str],
    throttle_key: str | None = None,
) -> dict[str, Any]:
    query = query.strip()[:500]
    if not query:
        raise SearchError("Search query cannot be empty.")
    settings = search_settings()
    mode, engine = settings["searchMode"], settings["searchApiProvider"]
    browser = BrowserRunner(validate_url)
    if mode == "chromium":
        return await browser.search(query)
    route = "google-grounding" if mode == "native" and provider == "gemini" else engine
    if mode == "native" and provider != "gemini" and not os.getenv(SEARCH_KEY_NAMES[engine]):
        result = await browser.search(query)
        result["warning"] = "This provider has no native search or saved selected search API key; Chromium was used."
        return result
    try:
        if route == "google-grounding":
            adapter = GeminiGroundingAdapter()
            operation = lambda: _grounding_search_with_retry(adapter, query, model)
            return await _grounding_throttle.run(throttle_key, operation) if throttle_key else await operation()
        return await search_api(query, engine)
    except SearchError as exc:
        if route == "google-grounding" and exc.fallback_reason:
            return await _fallback_from_google_failure(query, validate_url, settings, exc.fallback_reason, exc)
        if not exc.quota or not settings["searchChromiumFallback"]:
            raise
        result = await browser.search(query)
        if route == "google-grounding":
            failure_reason = _google_failure_reason(exc)
            result.update(
                fallbackFrom=route,
                fallbackReason=failure_reason,
                warning=f"{failure_reason}; used the enabled Chromium fallback.",
            )
        else:
            result.update(fallbackFrom=route, warning=f"{route} quota/rate limit exhausted; used the enabled Chromium fallback.")
        return result
