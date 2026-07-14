import csv
import json
import os
import tempfile
import unittest

from backtest_reporting import (
    _build_rolling_calibration_folds,
    _build_threshold_candidates,
    _paired_outcome_summary,
    _runtime_with_thresholds,
    _stability_objective,
    _stability_stats,
    export_backtest_report,
)
from project_config import GLOBAL_CONFIG


class BacktestReportingTests(unittest.TestCase):
    def test_stability_helpers_preserve_characterized_results(self):
        overall = {
            "best_of_5_avg_score": 3.75,
            "avg_overlap": 3.4,
            "best_of_5_hit_rate_ge2": 0.5,
            "best_of_5_hit_rate_ge3": 0.25,
            "best_of_5_hit_rate_ge4": 0.1,
            "final_blue_hit_rate": 0.2,
        }
        self.assertEqual(_stability_objective(overall), 0.271)
        self.assertEqual(
            _stability_stats([1, 2, 3, 4], bootstrap_iterations=400),
            {
                "samples": 4,
                "mean": 2.5,
                "std": 1.118034,
                "min": 1.0,
                "q25": 1.75,
                "median": 2.5,
                "q75": 3.25,
                "max": 4.0,
                "ci95_low": 1.5,
                "ci95_high": 3.5,
            },
        )
        paired = _paired_outcome_summary([0.1, 0.0, -0.2, 0.3])
        self.assertEqual(paired["positive_count"], 2)
        self.assertEqual(paired["tie_count"], 1)
        self.assertEqual(paired["negative_count"], 1)
        self.assertEqual(paired["dynamic_positive_ratio"], 0.5)
        self.assertEqual(paired["objective_delta"]["mean"], 0.05)

    def test_threshold_candidates_and_runtime_preserve_defaults(self):
        candidates = _build_threshold_candidates(
            one_thresholds=(0.38, 0.42),
            two_thresholds=(0.58,),
            gap_thresholds=(0.04, 0.06),
        )
        self.assertEqual(candidates, [
            {"one_score_threshold": 0.42, "two_score_threshold": 0.58, "min_score_gap": 0.04},
            {"one_score_threshold": 0.38, "two_score_threshold": 0.58, "min_score_gap": 0.04},
            {"one_score_threshold": 0.42, "two_score_threshold": 0.58, "min_score_gap": 0.06},
        ])
        runtime = _runtime_with_thresholds(
            GLOBAL_CONFIG.to_runtime_config(),
            {"one_score_threshold": 0.4, "two_score_threshold": 0.6, "min_score_gap": 0.05},
        )
        fusion = runtime["fusion_params"]
        self.assertEqual(fusion["anti_ticket_strategy"], "dynamic")
        self.assertEqual(fusion["anti_ticket_dynamic_one_score_threshold"], 0.4)
        self.assertEqual(fusion["anti_ticket_dynamic_two_score_threshold"], 0.6)
        self.assertEqual(fusion["anti_ticket_dynamic_min_score_gap"], 0.05)

    def test_rolling_folds_preserve_chronological_boundaries(self):
        records = [{"period": str(index)} for index in range(100, 0, -1)]
        folds = _build_rolling_calibration_folds(
            records, train_cycles=10, validation_cycles=5, fold_count=2, min_history=20
        )
        summarized = [
            (
                fold["fold"], fold["train_end_period"], fold["validation_start_period"],
                fold["validation_end_period"], len(fold["train_records"]), len(fold["validation_records"]),
            )
            for fold in folds
        ]
        self.assertEqual(summarized, [
            (1, "90", "91", "95", 90, 95),
            (2, "95", "96", "100", 95, 100),
        ])

    def test_export_backtest_report_writes_json_and_csv(self):
        report = {
            "mode": "test",
            "aggregate": {"score": 0.25, "label": "ok"},
            "runs": [{"window": 36, "seed": 42, "metric": 0.1}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = os.path.join(temp_dir, "report")
            paths = export_backtest_report(report, prefix)
            self.assertEqual(set(paths), {"json", "runs_csv", "summary_csv"})
            with open(paths["json"], "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), report)
            with open(paths["runs_csv"], "r", encoding="utf-8-sig", newline="") as handle:
                run_rows = list(csv.DictReader(handle))
            self.assertEqual(run_rows[0]["window"], "36")
            with open(paths["summary_csv"], "r", encoding="utf-8-sig", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertIn({"path": "aggregate.score", "value": "0.25"}, summary_rows)


if __name__ == "__main__":
    unittest.main()
