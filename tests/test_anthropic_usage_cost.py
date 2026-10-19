import unittest

from usage_cost import (
    anthropic_usage_summary,
    calculate_usage_cost,
    estimate_model_cost,
)


class AnthropicUsageCostTests(unittest.TestCase):
    def test_opus_cost_uses_opus_55_rates(self):
        line = anthropic_usage_summary("claude-opus-5-5", {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        })
        # 4 + 20 + 5 + 0.20 = 29.20
        self.assertIn("input_tokens=1000000", line)
        self.assertIn("output_tokens=1000000", line)
        self.assertIn("est_cost_usd=$29.2000", line)

    def test_missing_usage_fields_count_as_zero(self):
        line = anthropic_usage_summary("claude-opus-5-5", {})
        self.assertIn("input_tokens=0", line)
        self.assertIn("est_cost_usd=$0.0000", line)

    def test_unknown_model_is_reported_not_guessed(self):
        line = anthropic_usage_summary("claude-mystery-9", {"input_tokens": 500})
        self.assertIn("est_cost_usd=unknown", line)

    def test_haiku_long_prompt_uses_its_published_long_context_rates(self):
        usage = calculate_usage_cost("anthropic", "claude-haiku-5-5", {
            "input_tokens": 100_001,
            "output_tokens": 1,
        })
        self.assertEqual(usage["ratesPerMillion"]["input"], 0.50)
        self.assertAlmostEqual(usage["costUsd"], 0.050003)

    def test_openai_cached_tokens_are_not_double_charged_as_uncached_input(self):
        usage = calculate_usage_cost("openai", "gpt-4o", {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 25},
        })
        self.assertEqual(usage["cacheReadTokens"], 25)
        self.assertAlmostEqual(usage["costUsd"], 0.00071875)

    def test_deepseek_cache_hit_rate_is_applied_to_cached_input(self):
        usage = calculate_usage_cost("deepseek", "deepseek-chat", {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 40,
        })
        self.assertEqual(usage["cacheReadTokens"], 40)
        self.assertAlmostEqual(usage["costUsd"], 0.000074)

    def test_gemini_cache_and_context_dependent_pro_rates(self):
        fast = calculate_usage_cost("gemini", "gemini-3.5-flash-lite", {
            "input_tokens": 100,
            "output_tokens": 50,
            "cachedContentTokenCount": 40,
        })
        self.assertAlmostEqual(fast["costUsd"], 0.0001442)

        pro = calculate_usage_cost("gemini", "gemini-3.1-pro-preview", {
            "input_tokens": 200_001,
            "output_tokens": 1,
        })
        self.assertEqual(pro["ratesPerMillion"]["input"], 4.0)
        self.assertAlmostEqual(pro["costUsd"], 0.800022)

    def test_local_ollama_is_zero_hosted_token_cost_and_unknown_models_stay_unknown(self):
        local = calculate_usage_cost("ollama", "qwen2.5-coder", {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        })
        self.assertEqual(local["costUsd"], 0)
        self.assertIn("local compute excluded", local["summary"])

        unknown = calculate_usage_cost("openrouter", "custom/model", {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        })
        self.assertIsNone(unknown["costUsd"])
        self.assertFalse(unknown["costKnown"])

    def test_representative_cost_proxy_prefers_lower_published_token_rates(self):
        self.assertLess(
            estimate_model_cost("anthropic", "claude-haiku-5-5"),
            estimate_model_cost("openai", "gpt-4o-mini"),
        )


if __name__ == "__main__":
    unittest.main()
