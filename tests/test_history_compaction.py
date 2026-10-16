import unittest

from conversation_threads import compact_history_turn


class HistoryCompactionTests(unittest.TestCase):
    def test_large_tool_result_is_truncated_with_a_note(self):
        turn = {"role": "tool", "tool_call_id": "c1", "content": "x" * 10_000}
        result = compact_history_turn(turn, limit=4000)
        self.assertTrue(result["content"].startswith("x" * 4000))
        self.assertIn("6000 characters omitted", result["content"])
        self.assertEqual(result["tool_call_id"], "c1")
        # The stored turn must not be mutated.
        self.assertEqual(len(turn["content"]), 10_000)

    def test_compaction_is_deterministic_for_cache_stability(self):
        turn = {"role": "tool", "tool_call_id": "c1", "content": "abc" * 5000}
        self.assertEqual(compact_history_turn(turn, limit=1000), compact_history_turn(turn, limit=1000))

    def test_small_tool_results_are_unchanged(self):
        turn = {"role": "tool", "tool_call_id": "c1", "content": "short"}
        self.assertIs(compact_history_turn(turn, limit=4000), turn)

    def test_user_and_assistant_turns_are_never_compacted(self):
        for role in ("user", "assistant", "system"):
            turn = {"role": role, "content": "y" * 50_000}
            self.assertIs(compact_history_turn(turn, limit=4000), turn)

    def test_zero_limit_disables_compaction(self):
        turn = {"role": "tool", "tool_call_id": "c1", "content": "z" * 50_000}
        self.assertIs(compact_history_turn(turn, limit=0), turn)


if __name__ == "__main__":
    unittest.main()
