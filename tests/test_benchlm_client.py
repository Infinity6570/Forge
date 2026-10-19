from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

import benchlm_client


class StubAsyncClient:
    def __init__(self, result):
        self.result = result
        self.request_url = None
        self.request_headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, url, *, headers):
        self.request_url = url
        self.request_headers = headers
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class BenchLMClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        benchlm_client.clear_benchlm_cache()

    def tearDown(self) -> None:
        benchlm_client.clear_benchlm_cache()

    async def test_unconfigured_key_returns_catalog_without_invented_scores(self) -> None:
        result = await benchlm_client.fetch_benchlm_rankings(
            surface="coding",
            api_key=None,
            model_catalog=[{"modelId": "gpt-4o", "provider": "openai"}],
        )

        self.assertEqual(result["source"], "catalog-fallback")
        self.assertEqual(result["models"][0]["modelId"], "gpt-4o")
        self.assertIsNone(result["models"][0]["rating"])
        self.assertIsNone(result["models"][0]["codingScore"])

    async def test_success_normalizes_provider_score_and_caches_for_six_hours(self) -> None:
        response = httpx.Response(
            200,
            json={"rankings": [{"model_id": "gpt-4o", "provider": "openai", "score": 91.25, "rank": 2}]},
            request=httpx.Request("GET", "https://data.benchlm.ai/v1/rankings/current"),
        )
        client = StubAsyncClient(response)
        with patch("benchlm_client.httpx.AsyncClient", return_value=client) as client_factory:
            first = await benchlm_client.fetch_benchlm_rankings(
                surface="coding",
                api_key="test-benchlm-key",
                model_catalog=[{"modelId": "gpt-4o", "provider": "openai", "name": "GPT-4o"}],
            )
            second = await benchlm_client.fetch_benchlm_rankings(surface="coding", api_key="test-benchlm-key")

        self.assertEqual(client_factory.call_count, 1)
        self.assertEqual(client.request_headers["Authorization"], "Bearer test-benchlm-key")
        self.assertIn("surface=coding", client.request_url)
        self.assertEqual(first["source"], "benchlm")
        self.assertEqual(first["models"][0]["codingScore"], 91.25)
        self.assertEqual(first["models"][0]["provider"], "openai")
        self.assertEqual(second["models"], first["models"])

    def test_normalization_keeps_real_cost_latency_and_omits_non_finite_values(self) -> None:
        rows = benchlm_client.normalize_rankings(
            [
                {
                    "modelId": "gpt-4o",
                    "codingScore": 92,
                    "costIndex": "1.25",
                    "latency_ms": "450",
                },
                {
                    "modelId": "claude-sonnet-5-5",
                    "codingScore": float("nan"),
                    "costIndex": float("inf"),
                    "latencyMs": None,
                },
            ],
            surface="coding",
        )

        self.assertEqual(rows[0]["costIndex"], 1.25)
        self.assertEqual(rows[0]["latencyMs"], 450)
        self.assertIsNone(rows[1]["codingScore"])
        self.assertIsNone(rows[1]["costIndex"])
        self.assertIsNone(rows[1]["latencyMs"])

    async def test_refresh_failure_serves_last_good_rankings_as_stale(self) -> None:
        success = httpx.Response(
            200,
            json={"results": [{"id": "claude-sonnet-5-5", "provider": "anthropic", "coding_score": 88, "rank": 3}]},
            request=httpx.Request("GET", "https://data.benchlm.ai/v1/rankings/current"),
        )
        clients = [StubAsyncClient(success), StubAsyncClient(httpx.ConnectError("offline"))]
        with (
            patch("benchlm_client.httpx.AsyncClient", side_effect=clients),
            patch("benchlm_client.time.monotonic", side_effect=[10.0, 21611.0]),
        ):
            first = await benchlm_client.fetch_benchlm_rankings(
                surface="coding",
                api_key="test-benchlm-key",
            )
            stale = await benchlm_client.fetch_benchlm_rankings(
                surface="coding",
                api_key="test-benchlm-key",
            )

        self.assertFalse(first["stale"])
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["models"][0]["codingScore"], 88.0)
        self.assertIn("last successful", stale["message"])

    async def test_rejects_unknown_surface(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported BenchLM"):
            await benchlm_client.fetch_benchlm_rankings(
                surface="reasoning",
                api_key=None,
            )


if __name__ == "__main__":
    unittest.main()
