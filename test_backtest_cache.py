import unittest

import backtest_cache


class BacktestContextCacheTests(unittest.TestCase):
    @staticmethod
    def _records():
        return [
            {"period": "2026002", "red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 7},
            {"period": "2026001", "red_balls": [2, 3, 4, 5, 6, 7], "blue_ball": 8},
        ]

    def test_key_is_deterministic_and_covers_invariant_inputs(self):
        base = backtest_cache.make_backtest_context_key(
            self._records(), cycles=36, seed=42, initial_weights={"hot": 0.2}, ticket_count=5
        )
        same = backtest_cache.make_backtest_context_key(
            self._records(), cycles=36, seed=42, initial_weights={"hot": 0.2}, ticket_count=5
        )
        self.assertEqual(base, same)
        variants = [
            backtest_cache.make_backtest_context_key(self._records(), 72, 42, {"hot": 0.2}, 5),
            backtest_cache.make_backtest_context_key(self._records(), 36, 7, {"hot": 0.2}, 5),
            backtest_cache.make_backtest_context_key(self._records(), 36, 42, {"hot": 0.3}, 5),
            backtest_cache.make_backtest_context_key(self._records(), 36, 42, {"hot": 0.2}, 4),
        ]
        changed_records = self._records()
        changed_records[0]["blue_ball"] = 9
        variants.append(backtest_cache.make_backtest_context_key(changed_records, 36, 42, {"hot": 0.2}, 5))
        self.assertTrue(all(value != base for value in variants))

    def test_get_or_prepare_tracks_hits_misses_and_lru_eviction(self):
        cache = backtest_cache.BacktestContextCache(max_entries=2)
        calls = []

        def prepare(name):
            return lambda: calls.append(name) or [name]

        self.assertEqual(cache.get_or_prepare("a", prepare("a")), ["a"])
        self.assertEqual(cache.get_or_prepare("b", prepare("b")), ["b"])
        self.assertEqual(cache.get_or_prepare("a", prepare("a-again")), ["a"])
        self.assertEqual(cache.get_or_prepare("c", prepare("c")), ["c"])
        self.assertEqual(cache.get_or_prepare("b", prepare("b-again")), ["b-again"])
        self.assertEqual(calls, ["a", "b", "c", "b-again"])
        self.assertEqual(cache.snapshot(), {
            "max_entries": 2,
            "entries": 2,
            "hits": 1,
            "misses": 4,
            "evictions": 2,
            "prepared_samples": 4,
        })

    def test_prepared_sample_count_uses_value_length(self):
        cache = backtest_cache.BacktestContextCache(max_entries=1)
        cache.get_or_prepare("x", lambda: [1, 2, 3])
        cache.get_or_prepare("x", lambda: [])
        self.assertEqual(cache.snapshot()["prepared_samples"], 3)

    def test_invalid_capacity_is_rejected(self):
        with self.assertRaises(ValueError):
            backtest_cache.BacktestContextCache(max_entries=0)


if __name__ == "__main__":
    unittest.main()
