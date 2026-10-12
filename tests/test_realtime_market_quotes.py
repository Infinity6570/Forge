from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import main


class RealtimeMarketQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_gold_uses_keyless_real_time_endpoint_first(self) -> None:
        fetch = AsyncMock(return_value={"price": 2456.78})
        with (
            patch.object(main, "_fetch_market_json", fetch),
            patch.object(main, "get_vault_secret", side_effect=AssertionError("key not needed")),
        ):
            result = json.loads(await main.get_realtime_gold_quote())

        self.assertEqual(
            result,
            {
                "price": 2456.78,
                "unit": "USD/oz",
                "symbol": "XAU/USD",
                "latency": "0s Real-time",
            },
        )
        fetch.assert_awaited_once_with("https://api.gold-api.com/price/XAU")

    async def test_gold_uses_optional_goldapi_key_only_after_primary_fails(self) -> None:
        secret = "do-not-return-this-gold-key"
        fetch = AsyncMock(side_effect=[RuntimeError("feed unavailable"), {"price": 2501.25}])
        with (
            patch.object(main, "_fetch_market_json", fetch),
            patch.object(main, "get_vault_secret", return_value=secret) as get_secret,
        ):
            result_text = await main.get_realtime_gold_quote()

        self.assertEqual(
            json.loads(result_text),
            {
                "price": 2501.25,
                "unit": "USD/oz",
                "symbol": "XAU/USD",
                "latency": "0s Real-time",
            },
        )
        get_secret.assert_called_once_with("GOLDAPI_IO_KEY")
        self.assertEqual(
            fetch.await_args_list[1].args,
            ("https://www.goldapi.io/api/XAU/USD",),
        )
        self.assertEqual(
            fetch.await_args_list[1].kwargs["headers"],
            {"x-access-token": secret},
        )
        self.assertNotIn(secret, result_text)

    async def test_gold_yahoo_fallback_has_explicit_delay_warning(self) -> None:
        with (
            patch.object(main, "_fetch_market_json", new=AsyncMock(side_effect=RuntimeError())),
            patch.object(main, "get_vault_secret", return_value=None),
            patch.object(
                main,
                "market_quote_sync",
                return_value={"symbol": "GC=F", "current_price": 2477.5},
            ) as yahoo,
        ):
            result = json.loads(await main.get_realtime_gold_quote())

        self.assertEqual(result["price"], 2477.5)
        self.assertEqual(result["unit"], "USD/oz")
        self.assertEqual(result["latency"], "[15-Min Delayed CME Contract]")
        self.assertEqual(result["data_source"], "Yahoo Finance")
        yahoo.assert_called_once_with("GC=F")

    async def test_oilprice_api_returns_wti_in_usd_per_barrel(self) -> None:
        api_key = "private-oilprice-test-key"
        fetch = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "code": "WTI_USD",
                    "price": 71.3,
                    "as_of": "2026-10-12T08:00:00Z",
                    "stale": False,
                },
            }
        )
        with (
            patch.object(main, "_fetch_market_json", fetch),
            patch.object(
                main,
                "get_vault_secret",
                side_effect=lambda name: api_key if name == "OILPRICEAPI_KEY" else None,
            ) as get_secret,
        ):
            result_text = await main.get_realtime_energy_quote("crude oil")
            result = json.loads(result_text)

        self.assertEqual(result["asset"], "WTI")
        self.assertEqual(result["price"], 71.3)
        self.assertEqual(result["unit"], "USD/barrel")
        self.assertEqual(result["latency"], "0s Real-time")
        self.assertEqual(result["source_as_of"], "2026-10-12T08:00:00Z")
        self.assertFalse(result["stale"])
        fetch.assert_awaited_once_with(
            "https://api.oilpriceapi.com/v1/prices/latest",
            params={"by_code": "WTI_USD"},
            headers={"Authorization": f"Token {api_key}"},
        )
        self.assertEqual(
            [call.args[0] for call in get_secret.call_args_list],
            ["OILPRICEAPI_KEY"],
        )
        self.assertNotIn(api_key, result_text)

    async def test_commodity_api_key_supports_natural_gas_unit(self) -> None:
        fetch = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "code": "NATURAL_GAS_USD",
                    "price": 3.15,
                    "freshness": {"status": "stale"},
                },
            }
        )
        with (
            patch.object(main, "_fetch_market_json", fetch),
            patch.object(
                main,
                "get_vault_secret",
                side_effect=lambda name: "alternate-key" if name == "COMMODITY_API_KEY" else None,
            ) as get_secret,
        ):
            result = json.loads(await main.get_realtime_energy_quote("natural gas"))

        self.assertEqual(result["asset"], "NATURAL_GAS")
        self.assertEqual(result["price"], 3.15)
        self.assertEqual(result["unit"], "USD/MMBtu")
        self.assertTrue(result["stale"])
        self.assertEqual(result["latency"], "Source timestamped · stale")
        self.assertEqual(
            [call.args[0] for call in get_secret.call_args_list],
            ["OILPRICEAPI_KEY", "COMMODITY_API_KEY"],
        )
        self.assertEqual(
            fetch.await_args.kwargs["params"],
            {"by_code": "NATURAL_GAS_USD"},
        )

    async def test_energy_does_not_claim_real_time_without_source_freshness(self) -> None:
        with (
            patch.object(
                main,
                "_fetch_market_json",
                new=AsyncMock(
                    return_value={
                        "status": "success",
                        "data": {"code": "WTI_USD", "price": 69.5},
                    }
                ),
            ),
            patch.object(main, "get_vault_secret", return_value="oil-api-key"),
        ):
            result = json.loads(await main.get_realtime_energy_quote("WTI"))

        self.assertEqual(result["stale"], "unknown")
        self.assertEqual(result["latency"], "Source freshness unknown")

    async def test_energy_without_key_falls_back_with_delay_flag(self) -> None:
        with (
            patch.object(main, "get_vault_secret", return_value=None),
            patch.object(
                main,
                "market_quote_sync",
                return_value={"symbol": "CL=F", "current_price": 70.1},
            ) as yahoo,
        ):
            result = json.loads(await main.get_realtime_energy_quote("WTI"))

        self.assertEqual(result["price"], 70.1)
        self.assertEqual(result["unit"], "USD/barrel")
        self.assertEqual(result["symbol"], "WTI/USD")
        self.assertEqual(result["latency"], "[15-Min Delayed CME Contract]")
        yahoo.assert_called_once_with("CL=F")

    async def test_invalid_energy_asset_is_rejected_without_network_access(self) -> None:
        fetch = AsyncMock()
        with (
            patch.object(main, "_fetch_market_json", fetch),
            patch.object(main, "get_vault_secret") as get_secret,
        ):
            result = json.loads(await main.get_realtime_energy_quote("silver"))

        self.assertIn("error", result)
        fetch.assert_not_awaited()
        get_secret.assert_not_called()

    async def test_tool_registry_and_dispatch_include_live_quote_tools(self) -> None:
        names = {tool["function"]["name"] for tool in main.TOOLS}
        self.assertIn("get_realtime_gold_quote", names)
        self.assertIn("get_realtime_energy_quote", names)

        with patch.object(main, "get_realtime_energy_quote", new=AsyncMock(return_value="live")) as quote:
            result = await main.execute_tool(
                "get_realtime_energy_quote",
                {"asset": "WTI"},
                "gemini",
                {"model": "gemini-test"},
                "",
                "task-test",
            )
        self.assertEqual(result, "live")
        quote.assert_awaited_once_with("WTI")


if __name__ == "__main__":
    unittest.main()
