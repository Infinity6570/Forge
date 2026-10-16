import unittest

from usage_cost import anthropic_usage_summary


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


if __name__ == "__main__":
    unittest.main()
