import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import parameter_promotion


class ParameterPromotionTests(unittest.TestCase):
    def _calibration_report(self, deltas=(0.02, 0.01, 0.03), candidate_gap=0.06, counts=(3, 0)):
        candidate = {
            "one_score_threshold": 0.42,
            "two_score_threshold": 0.58,
            "min_score_gap": candidate_gap,
        }
        default = {
            "one_score_threshold": 0.42,
            "two_score_threshold": 0.58,
            "min_score_gap": 0.04,
        }
        folds = []
        for index, delta in enumerate(deltas, start=1):
            folds.append({
                "fold": index,
                "validation_samples": 12,
                "selected_thresholds": dict(candidate),
                "selected_vs_default_delta": float(delta),
                "candidate_ranking": [
                    {"thresholds": dict(default), "distance_from_default": 0.0},
                    {"thresholds": dict(candidate), "distance_from_default": abs(candidate_gap - 0.04)},
                ],
            })
        mean = sum(deltas) / len(deltas)
        frequency = [{"thresholds": dict(candidate), "count": counts[0], "ratio": counts[0] / max(1, sum(counts))}]
        if counts[1]:
            alternative = dict(candidate)
            alternative["min_score_gap"] = 0.02
            frequency.append({"thresholds": alternative, "count": counts[1], "ratio": counts[1] / sum(counts)})
        return {
            "report_schema_version": "threshold-calibration/v1",
            "folds": folds,
            "aggregate": {
                "selected_vs_default_delta": {
                    "samples": len(deltas),
                    "mean": mean,
                    "ci95_low": min(deltas),
                    "ci95_high": max(deltas),
                },
                "selection_frequency": frequency,
            },
        }

    @staticmethod
    def _stability_report(ci_low=0.004, positive_ratio=0.8, samples=24):
        return {
            "report_schema_version": "stability-report/v2",
            "aggregate": {
                "paired": {
                    "dynamic_positive_ratio": positive_ratio,
                    "objective_delta": {"samples": samples, "ci95_low": ci_low, "mean": 0.01},
                }
            },
        }

    def test_eligible_report_emits_candidate_patch(self):
        result = parameter_promotion.review_parameter_promotion(
            self._calibration_report(), self._stability_report()
        )
        self.assertEqual(result["decision"], "eligible")
        self.assertTrue(result["eligible"])
        self.assertTrue(all(gate["passed"] for gate in result["gates"]))
        self.assertEqual(
            result["candidate_patch"]["fusion_params"],
            {
                "anti_ticket_dynamic_one_score_threshold": 0.42,
                "anti_ticket_dynamic_two_score_threshold": 0.58,
                "anti_ticket_dynamic_min_score_gap": 0.06,
            },
        )

    def test_zero_validation_uplift_is_held(self):
        report = self._calibration_report(deltas=(0.0, 0.0, 0.0), counts=(2, 1))
        result = parameter_promotion.review_parameter_promotion(report, self._stability_report())
        self.assertEqual(result["decision"], "hold")
        self.assertNotIn("candidate_patch", result)
        failed = {gate["name"] for gate in result["gates"] if not gate["passed"]}
        self.assertIn("positive_validation_mean", failed)
        self.assertIn("positive_fold_ratio", failed)

    def test_current_real_report_is_held(self):
        root = Path(__file__).resolve().parent
        calibration = json.loads((root / "prediction_archive" / "v8_threshold_calibration_2026079.json").read_text(encoding="utf-8"))
        stability = json.loads((root / "prediction_archive" / "v8_stability_2026079.json").read_text(encoding="utf-8"))
        result = parameter_promotion.review_parameter_promotion(calibration, stability)
        self.assertEqual(result["decision"], "hold")
        self.assertEqual(result["candidate_thresholds"]["min_score_gap"], 0.06)
        self.assertEqual(result["observed"]["selected_vs_default_mean"], 0.0)

    def test_tied_or_unchanged_candidate_is_held(self):
        tied = parameter_promotion.review_parameter_promotion(
            self._calibration_report(counts=(2, 2)), self._stability_report()
        )
        self.assertIn("unique_threshold_leader", {g["name"] for g in tied["gates"] if not g["passed"]})
        unchanged = parameter_promotion.review_parameter_promotion(
            self._calibration_report(candidate_gap=0.04), self._stability_report()
        )
        self.assertIn("candidate_differs_from_default", {g["name"] for g in unchanged["gates"] if not g["passed"]})

    def test_sample_concentration_ci_and_stability_gates_hold(self):
        report = self._calibration_report(counts=(1, 2))
        report["folds"][0]["validation_samples"] = 4
        report["aggregate"]["selected_vs_default_delta"]["ci95_low"] = -0.001
        result = parameter_promotion.review_parameter_promotion(
            report, self._stability_report(ci_low=-0.002, positive_ratio=0.5, samples=8),
            min_concentration=0.8,
        )
        failed = {gate["name"] for gate in result["gates"] if not gate["passed"]}
        self.assertTrue({
            "minimum_validation_samples",
            "threshold_concentration",
            "validation_ci_nonnegative",
            "stability_minimum_runs",
            "stability_positive_ratio",
            "stability_ci_nonnegative",
        }.issubset(failed))

    def test_malformed_schema_returns_auditable_hold(self):
        result = parameter_promotion.review_parameter_promotion({"report_schema_version": "other"})
        self.assertEqual(result["decision"], "hold")
        self.assertFalse(result["eligible"])
        self.assertIn("calibration_schema", {g["name"] for g in result["gates"] if not g["passed"]})

    def test_cli_writes_candidate_only_for_eligible_decision(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp_dir:
            calibration_path = Path(temp_dir) / "calibration.json"
            stability_path = Path(temp_dir) / "stability.json"
            decision_path = Path(temp_dir) / "decision.json"
            candidate_path = Path(temp_dir) / "param_patch.candidate.json"
            calibration_path.write_text(json.dumps(self._calibration_report()), encoding="utf-8")
            stability_path.write_text(json.dumps(self._stability_report()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, "parameter_promotion.py",
                    "--calibration-report", str(calibration_path),
                    "--stability-report", str(stability_path),
                    "--output", str(decision_path),
                    "--candidate-patch-output", str(candidate_path),
                ],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(decision_path.read_text(encoding="utf-8"))["decision"], "eligible")
            patch = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(patch["fusion_params"]["anti_ticket_dynamic_min_score_gap"], 0.06)

    def test_cli_refuses_latest_patch_target(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp_dir:
            calibration_path = Path(temp_dir) / "calibration.json"
            stability_path = Path(temp_dir) / "stability.json"
            latest_path = Path(temp_dir) / "param_patch.latest.json"
            latest_path.write_text('{"sentinel": true}', encoding="utf-8")
            calibration_path.write_text(json.dumps(self._calibration_report()), encoding="utf-8")
            stability_path.write_text(json.dumps(self._stability_report()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, "parameter_promotion.py",
                    "--calibration-report", str(calibration_path),
                    "--stability-report", str(stability_path),
                    "--candidate-patch-output", str(latest_path),
                ],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(latest_path.read_text(encoding="utf-8")), {"sentinel": True})

    def test_cli_writes_hold_audit_but_not_candidate_patch(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp_dir:
            decision_path = Path(temp_dir) / "decision.json"
            candidate_path = Path(temp_dir) / "param_patch.candidate.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "parameter_promotion.py",
                    "--calibration-report",
                    str(root / "prediction_archive" / "v8_threshold_calibration_2026079.json"),
                    "--stability-report",
                    str(root / "prediction_archive" / "v8_stability_2026079.json"),
                    "--output",
                    str(decision_path),
                    "--candidate-patch-output",
                    str(candidate_path),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(decision_path.is_file())
            self.assertFalse(candidate_path.exists())
            self.assertEqual(json.loads(decision_path.read_text(encoding="utf-8"))["decision"], "hold")


if __name__ == "__main__":
    unittest.main()
