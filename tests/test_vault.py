from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from dotenv import dotenv_values

import main


class LocalVaultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        workspace = root / "workspace"
        self.env_file = root / ".env"
        self.env_patch = patch.dict(
            os.environ,
            {
                "VAULT_ENCRYPTION_KEY": "",
                "OPENAI_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "GEMINI_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "TAVILY_API_KEY": "",
                "SERPER_API_KEY": "",
                "BRAVE_SEARCH_API_KEY": "",
                "KITE_API_KEY": "",
                "KITE_API_SECRET": "",
                "KITE_ACCESS_TOKEN": "",
                "ALPHA_VANTAGE_API_KEY": "",
                "FINNHUB_API_KEY": "",
                "REPL_ID": "",
                "REPLIT_DEV_DOMAIN": "",
                "REPLIT_DOMAINS": "",
            },
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        for name, value in {
            "ROOT": root,
            "ENV_FILE": self.env_file,
            "WORKSPACE": workspace,
            "DATABASE": workspace / "assistant.db",
            "UPLOADS": workspace / "uploads",
            "NOTES": workspace / "notes",
        }.items():
            patcher = patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        main.init_db()

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def test_vault_saves_encrypted_values_and_returns_status_only(self) -> None:
        secrets = {
            "geminiApiKey": "vault-test-gemini-secret",
            "tavilyApiKey": "vault-test-tavily-secret",
            "kiteApiSecret": "vault-test-kite-secret",
            "alphaVantageApiKey": "vault-test-market-secret",
        }
        response = await self.request("POST", "/api/vault/keys", json=secrets)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["gemini_api_key"], "configured")
        self.assertEqual(response.json()["tavily_api_key"], "configured")
        self.assertEqual(response.json()["kite_api_secret"], "configured")
        self.assertEqual(response.json()["alpha_vantage_api_key"], "configured")
        for secret in secrets.values():
            self.assertNotIn(secret, response.text)

        row = main.db_one(
            "SELECT key_value FROM vault_secrets WHERE key_name='GEMINI_API_KEY'"
        )
        self.assertIsNotNone(row)
        self.assertNotIn(secrets["geminiApiKey"], row["key_value"])
        self.assertEqual(main.get_vault_secret("GEMINI_API_KEY"), secrets["geminiApiKey"])
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)
        saved_env = dotenv_values(self.env_file)
        self.assertIn("VAULT_ENCRYPTION_KEY", saved_env)
        self.assertNotIn("GEMINI_API_KEY", saved_env)

    async def test_database_value_takes_precedence_and_environment_is_fallback(self) -> None:
        os.environ["GEMINI_API_KEY"] = "fallback-gemini-key"
        self.assertEqual(main.get_vault_secret("GEMINI_API_KEY"), "fallback-gemini-key")
        main.save_vault_values({"GEMINI_API_KEY": "encrypted-database-key"})
        os.environ["GEMINI_API_KEY"] = "newer-env-key"
        self.assertEqual(main.get_vault_secret("GEMINI_API_KEY"), "encrypted-database-key")

    async def test_inactive_database_record_falls_back_to_environment(self) -> None:
        main.save_vault_values({"TAVILY_API_KEY": "database-search-key"})
        os.environ["TAVILY_API_KEY"] = "env-search-key"
        main.db_run("UPDATE vault_secrets SET is_active=0 WHERE key_name='TAVILY_API_KEY'")
        self.assertEqual(main.get_vault_secret("TAVILY_API_KEY"), "env-search-key")

    async def test_get_statuses_include_env_fallback_without_exposing_values(self) -> None:
        os.environ["OPENAI_API_KEY"] = "env-openai-test-secret"
        response = await self.request("GET", "/api/vault/keys")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["openai_api_key"], "configured")
        self.assertEqual(response.json()["kite_api_key"], "not_set")
        self.assertNotIn("env-openai-test-secret", response.text)

    async def test_market_quote_tool_normalizes_quote_fields_without_network(self) -> None:
        ticker = unittest.mock.Mock()
        ticker.fast_info = {
            "lastPrice": 105.0,
            "previousClose": 100.0,
            "currency": "USD",
        }
        with patch("yfinance.Ticker", return_value=ticker):
            result = await main.get_market_quote("gc=f")

        self.assertEqual(
            result,
            '{"symbol": "GC=F", "current_price": 105.0, "previous_close": 100.0, "day_change_percent": 5.0, "currency": "USD", "data_source": "Yahoo Finance (may be delayed)"}',
        )
        self.assertTrue(any(
            tool["function"]["name"] == "get_market_quote"
            for tool in main.TOOLS
        ))

    async def test_market_quote_rejects_invalid_symbol_before_network_call(self) -> None:
        with patch("yfinance.Ticker") as ticker:
            result = await main.get_market_quote("../../etc/passwd")
        ticker.assert_not_called()
        self.assertIn("valid Yahoo Finance symbol", result)


if __name__ == "__main__":
    unittest.main()
