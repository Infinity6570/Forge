from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import main
from tools.browser_runner import BrowserError, BrowserRunner, clean_browser_env, unwrap_search_url
from tools.web_search import GeminiGroundingAdapter, SearchError, routed_search, search_api


class SearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-gemini-only",
            "TAVILY_API_KEY": "test-tavily-only",
            "SERPER_API_KEY": "test-serper-only",
            "BRAVE_SEARCH_API_KEY": "test-brave-only",
            "WEB_SEARCH_MODE": "native",
            "WEB_SEARCH_API_PROVIDER": "tavily",
            "WEB_SEARCH_CHROMIUM_FALLBACK": "false",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def transport(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return patch("tools.web_search.httpx.AsyncClient", return_value=client)

    async def test_gemini_native_grounding_keeps_metadata_and_does_not_scrape(self):
        metadata = {
            "groundingChunks": [{"web": {"uri": "https://example.com/news", "title": "Example"}}],
            "groundingSupports": [{"segment": {"text": "Verified"}, "groundingChunkIndices": [0]}],
            "searchEntryPoint": {"renderedContent": "<div>Search suggestions</div>"},
            "webSearchQueries": ["current news"],
            "futureOpaqueField": {"value": "kept"},
        }
        def handler(request):
            self.assertTrue(request.url.path.endswith("/gemini-3.8-flash:generateContent"))
            self.assertEqual(request.headers["x-goog-api-key"], "test-gemini-only")
            body = json.loads(request.content)
            self.assertEqual(body["tools"], [{"google_search": {}}])
            return httpx.Response(200, json={"candidates": [{
                "content": {"parts": [{"text": "Verified"}]}, "groundingMetadata": metadata,
            }]})
        with self.transport(handler), patch.object(BrowserRunner, "search", new_callable=AsyncMock) as browser:
            output = await routed_search("current news", "gemini", "gemini-3.8-flash", lambda u: u)
        browser.assert_not_awaited()
        self.assertEqual(output["groundingMetadata"], metadata)
        self.assertEqual(output["results"][0]["title"], "Example")
        self.assertTrue(output["grounded"])

    async def test_resource_style_model_and_unverified_answer(self):
        def handler(request):
            self.assertIn("/gemini-2.5-flash:", request.url.path)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Unverified"}]}}]})
        with self.transport(handler):
            result = await GeminiGroundingAdapter().search("query", "models/gemini-2.5-flash")
        self.assertFalse(result["grounded"])
        self.assertIn("not return grounding", result["warning"])

    async def test_gemma_native_does_not_silently_change_model(self):
        with self.assertRaisesRegex(SearchError, "compatible Gemini"):
            await GeminiGroundingAdapter().search("query", "gemma-4-31b-it")

    async def test_three_search_apis_normalize_results(self):
        for engine, payload, header in [
            ("tavily", {"results": [{"title": "T", "url": "https://example.com", "content": "Tavily text"}]}, "authorization"),
            ("serper", {"organic": [{"title": "S", "link": "https://example.com", "snippet": "Serper text"}]}, "x-api-key"),
            ("brave", {"web": {"results": [{"title": "B", "url": "https://example.com", "description": "Brave text"}]}}, "x-subscription-token"),
        ]:
            def handler(request):
                self.assertIn(header, request.headers)
                return httpx.Response(200, json=payload)
            with self.transport(handler):
                result = await search_api("test query", engine)
            self.assertEqual(result["engine"], engine)
            self.assertEqual(set(result["results"][0]), {"title", "url", "text"})
            self.assertTrue(result["results"][0]["text"])

    async def test_api_mode_overrides_gemini_native(self):
        os.environ["WEB_SEARCH_MODE"] = "api"
        with patch("tools.web_search.search_api", new_callable=AsyncMock, return_value={"engine": "tavily", "results": [{"title": "T"}]}) as api:
            with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock) as native:
                await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        api.assert_awaited_once_with("query", "tavily")
        native.assert_not_awaited()

    async def test_quota_fallback_is_explicit_and_only_if_enabled(self):
        os.environ.update(WEB_SEARCH_MODE="api", WEB_SEARCH_CHROMIUM_FALLBACK="true")
        with patch("tools.web_search.search_api", new_callable=AsyncMock, side_effect=SearchError("quota", quota=True)):
            with patch.object(BrowserRunner, "search", new_callable=AsyncMock, return_value={"engine": "chromium", "results": [{"title": "B"}]}) as browser:
                result = await routed_search("query", "deepseek", "deepseek-chat", lambda u: u)
        browser.assert_awaited_once()
        self.assertEqual(result["fallbackFrom"], "tavily")
        os.environ["WEB_SEARCH_CHROMIUM_FALLBACK"] = "false"
        with patch("tools.web_search.search_api", new_callable=AsyncMock, side_effect=SearchError("quota", quota=True)):
            with patch.object(BrowserRunner, "search", new_callable=AsyncMock) as browser:
                with self.assertRaises(SearchError):
                    await routed_search("query", "deepseek", "deepseek-chat", lambda u: u)
                browser.assert_not_awaited()

    async def test_google_429_falls_back_in_tavily_serper_brave_order(self):
        calls = []

        async def fallback(query, engine):
            calls.append(engine)
            if engine == "tavily":
                raise SearchError("rate limited", quota=True, status_code=429)
            if engine == "serper":
                raise SearchError("bad saved key", status_code=401)
            return {"engine": engine, "results": [{"title": "Brave result"}]}

        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=SearchError("Google grounding 429", quota=True, status_code=429)) as google:
            with patch("tools.web_search.asyncio.sleep", new_callable=AsyncMock) as sleep:
                with patch("tools.web_search.random.uniform", return_value=1.0):
                    with patch("tools.web_search.search_api", new_callable=AsyncMock, side_effect=fallback):
                        result = await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)

        self.assertEqual(google.await_count, 2)
        sleep.assert_awaited_once_with(1.5)
        self.assertEqual(calls, ["tavily", "serper", "brave"])
        self.assertEqual(result["engine"], "brave")
        self.assertEqual(result["fallbackFrom"], "google-grounding")
        self.assertEqual(result["fallbackReason"], "Google 429 Throttled")
        self.assertEqual(result["fallbackAttempted"], calls)
        self.assertIn("Brave", result["warning"])

    async def test_google_429_retries_before_fallback_and_no_badge_if_retry_succeeds(self):
        success = {"engine": "google-grounding", "answer": "Found it", "results": []}
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=[SearchError("rate limited", quota=True, status_code=429), success]) as google:
            with patch("tools.web_search.asyncio.sleep", new_callable=AsyncMock) as sleep:
                with patch("tools.web_search.random.uniform", return_value=1.0):
                    with patch("tools.web_search.search_api", new_callable=AsyncMock) as api:
                        result = await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        self.assertEqual(result, success)
        self.assertNotIn("fallbackFrom", result)
        self.assertNotIn("fallbackReason", result)
        self.assertEqual(google.await_count, 2)
        sleep.assert_awaited_once_with(1.5)
        api.assert_not_awaited()

    async def test_google_429_retry_timeout_falls_back_with_specific_reason(self):
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=[
                              SearchError("rate limited", quota=True, status_code=429),
                              httpx.ReadTimeout("timed out"),
                          ]) as google:
            with patch("tools.web_search.asyncio.sleep", new_callable=AsyncMock):
                with patch("tools.web_search.random.uniform", return_value=1.0):
                    with patch("tools.web_search.search_api", new_callable=AsyncMock,
                               return_value={"engine": "tavily", "results": []}) as api:
                        result = await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        self.assertEqual(google.await_count, 2)
        api.assert_awaited_once_with("query", "tavily")
        self.assertEqual(result["fallbackReason"], "Google Timeout")

    async def test_google_429_retry_empty_answer_falls_back_as_empty_results(self):
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=[
                              SearchError("rate limited", quota=True, status_code=429),
                              SearchError("Google grounding returned no usable text."),
                          ]):
            with patch("tools.web_search.asyncio.sleep", new_callable=AsyncMock):
                with patch("tools.web_search.random.uniform", return_value=1.0):
                    with patch("tools.web_search.search_api", new_callable=AsyncMock,
                               return_value={"engine": "tavily", "results": []}):
                        result = await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        self.assertEqual(result["fallbackReason"], "Google Empty Results")

    async def test_google_chromium_fallback_includes_failure_reason(self):
        os.environ["WEB_SEARCH_CHROMIUM_FALLBACK"] = "true"
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=SearchError("quota", quota=True, status_code=403)):
            with patch.object(BrowserRunner, "search", new_callable=AsyncMock,
                              return_value={"engine": "chromium", "results": []}) as browser:
                result = await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        browser.assert_awaited_once()
        self.assertEqual(result["fallbackFrom"], "google-grounding")
        self.assertEqual(result["fallbackReason"], "Google HTTP 403")

    async def test_google_non_429_does_not_switch_search_providers(self):
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          side_effect=SearchError("Google unavailable", status_code=503)):
            with patch("tools.web_search.search_api", new_callable=AsyncMock) as api:
                with self.assertRaisesRegex(SearchError, "Google unavailable"):
                    await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        api.assert_not_awaited()

    async def test_consecutive_grounding_calls_back_off_exponentially_per_task(self):
        with patch.object(GeminiGroundingAdapter, "search", new_callable=AsyncMock,
                          return_value={"engine": "google-grounding"}):
            with patch("tools.web_search.asyncio.sleep", new_callable=AsyncMock) as sleep:
                with patch("tools.web_search.random.uniform", return_value=1.0):
                    for _ in range(3):
                        await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u,
                                            throttle_key="grounding-backoff-test")
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1.5, 3.0])

    async def test_bad_keys_and_server_errors_never_trigger_quota_fallback(self):
        os.environ.update(WEB_SEARCH_MODE="api", WEB_SEARCH_CHROMIUM_FALLBACK="true")
        for status in [401, 403, 503]:
            with self.transport(lambda r: httpx.Response(status, json={"error": "invalid key or server fault"})):
                with patch.object(BrowserRunner, "search", new_callable=AsyncMock) as browser:
                    with self.assertRaises(SearchError):
                        await routed_search("query", "openai", "gpt-4o", lambda u: u)
                    browser.assert_not_awaited()

    async def test_plain_text_429_and_credit_exhaustion_are_quota(self):
        for status, kwargs in [(429, {"text": "Too many requests"}), (403, {"json": {"error": "not enough credits"}})]:
            with self.transport(lambda r: httpx.Response(status, **kwargs)):
                with self.assertRaises(SearchError) as error:
                    await search_api("query", "tavily")
            self.assertTrue(error.exception.quota)

    async def test_empty_results_and_empty_query_are_not_success(self):
        with self.transport(lambda r: httpx.Response(200, json={"results": []})):
            with self.assertRaisesRegex(SearchError, "no readable"):
                await search_api("query", "tavily")
        with self.assertRaisesRegex(SearchError, "cannot be empty"):
            await routed_search(" ", "openai", "gpt-4o", lambda u: u)

    async def test_non_gemini_native_uses_selected_key_or_browser(self):
        with patch("tools.web_search.search_api", new_callable=AsyncMock, return_value={"engine": "tavily"}) as api:
            await routed_search("query", "deepseek", "deepseek-chat", lambda u: u)
        api.assert_awaited_once()
        os.environ["TAVILY_API_KEY"] = ""
        with patch.object(BrowserRunner, "search", new_callable=AsyncMock, return_value={"engine": "chromium"}) as browser:
            result = await routed_search("query", "deepseek", "deepseek-chat", lambda u: u)
        browser.assert_awaited_once()
        self.assertIn("no native", result["warning"])

    async def test_headless_mode_and_fetch_tool_route(self):
        os.environ["WEB_SEARCH_MODE"] = "chromium"
        with patch.object(BrowserRunner, "search", new_callable=AsyncMock, return_value={"engine": "chromium"}) as browser:
            await routed_search("query", "gemini", "gemini-3.8-flash", lambda u: u)
        browser.assert_awaited_once()
        with patch.object(BrowserRunner, "fetch", new_callable=AsyncMock, return_value={"text": "Browser page text"}):
            result = await main.execute_tool("fetch_webpage", {"url": "https://example.com"}, "openai", {"model": "gpt-4o"}, "", "test")
        self.assertEqual(json.loads(result)["text"], "Browser page text")

    async def test_agent_router_uses_task_model_not_global_default(self):
        os.environ.update(AGENT_PROVIDER="openai", AGENT_MODEL="gpt-4o")
        with patch("main.routed_search", new_callable=AsyncMock, return_value={"engine": "google-grounding"}) as routed:
            await main.execute_tool("web_search", {"query": "news"}, "gemini", {"model": "gemini-2.5-pro"}, "", "test")
        self.assertEqual(routed.await_args.args[1:3], ("gemini", "gemini-2.5-pro"))
        self.assertEqual(routed.await_args.kwargs["throttle_key"], "test")

    async def test_browser_refuses_private_urls_before_launch(self):
        with self.assertRaisesRegex(ValueError, "Local addresses"):
            await BrowserRunner(main.validate_public_url).fetch("https://localhost/")
        with self.assertRaises(ValueError):
            await BrowserRunner(main.validate_public_url).fetch("file:///etc/passwd")

    def test_browser_environment_does_not_inherit_keys(self):
        os.environ["PATH"] = "/test/bin"
        env = clean_browser_env()
        self.assertEqual(env["PATH"], "/test/bin")
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("TAVILY_API_KEY", env)

    def test_search_redirect_unwrap(self):
        self.assertEqual(unwrap_search_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com"), "https://example.com")


class SearchSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_file = Path(self.tmp.name) / ".env"
        p = patch.object(main, "ENV_FILE", self.env_file)
        p.start()
        self.addCleanup(p.stop)
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def test_keys_save_masked_status_and_preferences_persist_independently(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1") as client:
            keys = {"tavilyApiKey": "dummy-tavily", "serperApiKey": "dummy-serper", "braveApiKey": "dummy-brave"}
            response = await client.put("/api/assistant/settings/keys", json=keys)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["hasTavilyKey"])
            self.assertTrue(response.json()["hasSerperKey"])
            self.assertTrue(response.json()["hasBraveKey"])
            self.assertNotIn("dummy-", response.text)
            model_before = response.json()["modelId"]
            config = {"searchMode": "api", "searchApiProvider": "brave", "searchChromiumFallback": True}
            response = await client.patch("/api/assistant/settings/search", json=config)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["modelId"], model_before)
            refreshed = (await client.get("/api/assistant/settings")).json()
            for key, value in config.items():
                self.assertEqual(refreshed[key], value)
            response = await client.put("/api/assistant/settings/keys", json={"tavilyApiKey": ""})
            self.assertTrue(response.json()["hasTavilyKey"])
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)
        self.assertIn("WEB_SEARCH_MODE='api'", self.env_file.read_text())

    async def test_bad_mode_and_cross_origin_are_rejected(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1") as client:
            response = await client.patch("/api/assistant/settings/search", json={"searchMode": "bad", "searchApiProvider": "tavily"})
            self.assertEqual(response.status_code, 422)
            response = await client.patch("/api/assistant/settings/search", json={"searchMode": "api", "searchApiProvider": "tavily"}, headers={"origin": "https://attacker.example"})
            self.assertEqual(response.status_code, 403)
        self.assertFalse(self.env_file.exists())

    def test_search_credentials_are_redacted_from_errors(self):
        os.environ["TAVILY_API_KEY"] = "dummy-secret"
        self.assertEqual(main.redact_provider_keys("Failed: dummy-secret"), "Failed: [redacted]")
