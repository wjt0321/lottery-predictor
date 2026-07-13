import unittest
from unittest import mock

import analyze_archive
import feature_importance
import predict
from blue_ball_engine import BlueBallEngine


class _ZeroRandom:
    def random(self):
        return 0.0

    def sample(self, population, k):
        return list(population[:k])


class AlgorithmCorrectnessTests(unittest.TestCase):
    def test_missing_uses_most_recent_red_occurrence(self):
        records = [
            {"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 1},
            {"red_balls": [7, 8, 9, 10, 11, 12], "blue_ball": 2},
            {"red_balls": [13, 14, 15, 16, 17, 18], "blue_ball": 3},
            {"red_balls": [1, 19, 20, 21, 22, 23], "blue_ball": 1},
        ]
        self.assertEqual(predict.analyze_missing(records)["red_missing"][1], 0)

    def test_missing_uses_most_recent_blue_occurrence(self):
        records = [
            {"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 7},
            {"red_balls": [7, 8, 9, 10, 11, 12], "blue_ball": 2},
            {"red_balls": [13, 14, 15, 16, 17, 18], "blue_ball": 3},
            {"red_balls": [19, 20, 21, 22, 23, 24], "blue_ball": 7},
        ]
        self.assertEqual(predict.analyze_blue_missing(records)["blue_missing"][7], 0)

    def test_cycle_score_uses_current_gap_in_newest_first_records(self):
        records = []
        for idx in range(10):
            reds = [1, 2, 3, 4, 5, 6] if idx in (1, 4, 7) else [2, 3, 4, 5, 6, 7]
            records.append({"red_balls": reds, "blue_ball": 1})
        score = predict.analyze_cycle(records, max_period=10)["cycle_scores"][1]
        self.assertAlmostEqual(score, 2.0 / 3.0, places=6)

    def test_safe_red_sample_preserves_candidate_ranking(self):
        ranked = list(range(33, 0, -1))
        selected = predict._safe_red_sample(_ZeroRandom(), ranked, required=6)
        self.assertEqual(selected, [28, 29, 30, 31, 32, 33])

    def test_blue_zone_transition_learns_old_to_new_direction(self):
        # Newest-first zones: 0,1,2,2,2,0. Chronological transitions from
        # zone 0 point to zone 2, not zone 1.
        blues = [1, 6, 11, 12, 13, 2]
        records = [{"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": b} for b in blues]
        probs = BlueBallEngine(records).analyze_zone_transition()[1]
        self.assertEqual(tuple(round(v, 6) for v in probs), (0.25, 0.25, 0.5))

    def test_blue_parity_reversal_only_uses_current_run(self):
        # The latest parity run has length 1; an older run of four evens must
        # not trigger a reversal adjustment against the latest odd result.
        blues = [1, 2, 4, 6, 8, 3]
        records = [{"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": b} for b in blues]
        next_odd_prob, _ = BlueBallEngine(records).analyze_parity_cycle()
        self.assertGreater(next_odd_prob, 0.5)

    def test_blue_missing_score_honors_cold_bonus_config(self):
        engine = BlueBallEngine([], config={
            "missing_cold_threshold": 10,
            "missing_cold_bonus": 1.6,
            "missing_extreme_threshold": 20,
            "missing_extreme_bonus": 2.4,
        })
        scores = engine.missing_score({1: 10, 2: 15, 3: 20})
        self.assertAlmostEqual(scores[1], 1.6)
        self.assertAlmostEqual(scores[2], 2.0)
        self.assertAlmostEqual(scores[3], 2.4)

    def test_feature_importance_uses_only_older_history_for_each_target(self):
        records = [
            {
                "period": str(100 - idx),
                "red_balls": [1, 2, 3, 4, 5, 6],
                "blue_ball": 1,
            }
            for idx in range(15)
        ]
        calls = []

        def capture(history, period_idx):
            calls.append((list(history), period_idx))
            return {"synthetic": float(len(calls))}

        with mock.patch.object(feature_importance, "extract_features_for_period", side_effect=capture):
            feature_importance.compute_feature_importance(records, min_periods=10)

        self.assertEqual(len(calls), 5)
        for target_idx, (history, period_idx) in enumerate(calls):
            self.assertEqual(period_idx, 0)
            self.assertIs(history[0], records[target_idx + 1])
            self.assertNotIn(records[target_idx], history)
            self.assertGreaterEqual(len(history), 10)


    def test_backtest_priors_are_clean_by_default(self):
        runtime, weights, source = predict.resolve_backtest_priors(False)
        self.assertEqual(runtime, predict.DEFAULT_RUNTIME_CONFIG)
        self.assertIsNot(runtime, predict.DEFAULT_RUNTIME_CONFIG)
        self.assertIsNone(weights)
        self.assertEqual(source, "clean")

    def test_backtest_priors_can_be_opted_in_explicitly(self):
        with mock.patch.object(predict, "resolve_runtime_config", return_value={"pool_params": {"core_red_pool_size": 19}}), \
             mock.patch.object(predict, "resolve_weight_patch_path", return_value=("weights.json", "explicit")), \
             mock.patch.object(predict, "load_weight_patch", return_value={"hot": 0.2}):
            runtime, weights, source = predict.resolve_backtest_priors(True, "weights.json")
        self.assertEqual(runtime["pool_params"]["core_red_pool_size"], 19)
        self.assertEqual(weights, {"hot": 0.2})
        self.assertEqual(source, "explicit")

    def test_archive_learning_normalizes_exposure_and_counts_misses(self):
        rows = []
        for idx in range(10):
            rows.append({
                "payload": {
                    "sources": ["hot"],
                    "red": [{"ball": 1, "agent_contributions": {"hot": 100.0}}],
                    "blue": {},
                    "actual_result": {
                        "actual_red_balls": [1, 3, 5, 7, 9, 11] if idx == 0 else [2, 3, 5, 7, 9, 11],
                        "actual_blue_ball": 16,
                    },
                }
            })
        for _ in range(2):
            rows.append({
                "payload": {
                    "sources": ["cold"],
                    "red": [{"ball": 2, "agent_contributions": {"cold": 1.0}}],
                    "blue": {},
                    "actual_result": {
                        "actual_red_balls": [2, 3, 5, 7, 9, 11],
                        "actual_blue_ball": 16,
                    },
                }
            })

        ranking = analyze_archive.build_agent_ranking(rows)
        by_agent = {row["agent"]: row for row in ranking}
        self.assertGreater(by_agent["cold"]["score"], by_agent["hot"]["score"])
        self.assertAlmostEqual(by_agent["hot"]["score"], 0.1)
        self.assertEqual(by_agent["hot"]["exposure"], 10.0)

    def test_blue_debate_uses_full_scores_and_existing_engine_details(self):
        class FailingEngine:
            def predict(self, pool_size=16):
                raise AssertionError("blue debate should reuse the existing engine result")

        snapshot = {
            "blue_pool": list(range(1, 11)),
            "blue_scores": {n: float(20 - n) for n in range(1, 11)},
            "blue_scores_full": {n: float(20 - n) for n in range(1, 17)},
            "blue_engine_details": {
                "missing_scores": {16: 2.5},
                "amp_scores": {},
                "heat_scores": {},
            },
        }
        updated = predict._build_blue_debate(snapshot, FailingEngine())
        self.assertIn(16, updated["blue_pool"])
        self.assertIn(16, updated["blue_debate_promoted"])
        self.assertEqual(len(updated["blue_pool"]), 10)


    def test_blue_debate_requires_relative_dimension_standout(self):
        snapshot = {
            "blue_pool": list(range(1, 11)),
            "blue_scores": {n: float(20 - n) for n in range(1, 11)},
            "blue_scores_full": {n: float(20 - n) for n in range(1, 17)},
            "blue_engine_details": {
                "missing_scores": {n: 1.0 for n in range(1, 17)},
                "amp_scores": {n: 1.5 if n <= 10 else 0.9 for n in range(1, 17)},
                "heat_scores": {n: 1.5 if n <= 10 else 0.9 for n in range(1, 17)},
            },
        }
        updated = predict._build_blue_debate(snapshot, None)
        self.assertEqual(updated["blue_pool"], list(range(1, 11)))
        self.assertNotIn("blue_debate_promoted", updated)

    def test_hybrid_anti_ticket_keeps_model_core(self):
        base = [1, 2, 3, 4, 5, 6]
        scores = {n: float(34 - n) for n in range(1, 34)}
        mixed = predict._mix_anti_consensus_reds(
            base,
            anti_candidates=list(range(23, 34)),
            red_scores=scores,
            anti_count=2,
            rng=_ZeroRandom(),
        )
        self.assertEqual(len(mixed), 6)
        self.assertEqual(len(set(mixed) & set(base)), 4)
        self.assertEqual(len(set(mixed) & set(range(23, 34))), 2)


    def test_four_red_one_blue_metric_requires_same_ticket(self):
        summary = predict._empty_multi_ticket_backtest_summary()
        target = {"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 16}
        tickets = [
            {"red": [1, 2, 3, 4, 20, 21], "blue": 1},
            {"red": [1, 2, 3, 20, 21, 22], "blue": 16},
        ]

        predict._accumulate_multi_ticket_backtest(summary, tickets, target)
        result = predict._finalize_multi_ticket_backtest(summary)

        self.assertEqual(result["best_of_5_hit_count_4plus1"], 0)
        self.assertEqual(result["best_of_5_hit_rate_4plus1"], 0.0)
        self.assertEqual(result["best_of_5_hit_rate_ge4_plus_blue"], 0.0)

    def test_four_red_one_blue_metric_counts_exact_and_higher_joint_hits(self):
        summary = predict._empty_multi_ticket_backtest_summary()
        target = {"red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 16}

        predict._accumulate_multi_ticket_backtest(
            summary,
            [{"red": [1, 2, 3, 4, 20, 21], "blue": 16}],
            target,
        )
        predict._accumulate_multi_ticket_backtest(
            summary,
            [{"red": [1, 2, 3, 4, 5, 21], "blue": 16}],
            target,
        )
        result = predict._finalize_multi_ticket_backtest(summary)

        self.assertEqual(result["best_of_5_hit_count_4plus1"], 1)
        self.assertEqual(result["best_of_5_hit_rate_4plus1"], 0.5)
        self.assertEqual(result["best_of_5_hit_count_ge4_plus_blue"], 2)
        self.assertEqual(result["best_of_5_hit_rate_ge4_plus_blue"], 1.0)


if __name__ == "__main__":
    unittest.main()
