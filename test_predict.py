import tempfile
import unittest

import predict


class PredictFlowTests(unittest.TestCase):
    def test_evaluate_last_prediction_gap_match(self):
        archive = {"period": "2026002", "ticket1": "01 02 03 04 05 06+07|hot,cold"}
        latest = {"period": "2026002", "red_balls": [1, 8, 9, 10, 11, 12], "blue_ball": 7}
        result = predict.evaluate_last_prediction_gap(archive, latest)
        self.assertTrue(result["matched"])
        self.assertEqual(result["red_hits"], 1)
        self.assertEqual(result["blue_hit"], 1)

    def test_save_and_load_compact_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = predict.ARCHIVE_DIR
            predict.ARCHIVE_DIR = temp_dir
            try:
                predict.save_compact_prediction(
                    target_period="2026888",
                    tickets=[{"red": [1, 2, 3, 4, 5, 6], "blue": 7, "sources": ["hot", "balanced"]}],
                    lead_summary="factor=1.00",
                )
                loaded = predict.load_latest_archive()
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded["period"], "2026888")
                self.assertIn("ticket1", loaded)
            finally:
                predict.ARCHIVE_DIR = old_dir

    def test_build_expert_teams_count(self):
        records = [
            {"period": "2026002", "date": "2026-01-03", "red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 7},
            {"period": "2026001", "date": "2026-01-01", "red_balls": [7, 8, 9, 10, 11, 12], "blue_ball": 13},
        ]
        teams = predict.build_expert_teams(records, tickets=2, seed=7)
        self.assertEqual(len(teams), 5)
        valid = [name for name, payload in teams.items() if len(payload.get("proposals", [])) == 2]
        self.assertGreaterEqual(len(valid), 3)

    def test_build_lead_agent_report(self):
        lead_model = {
            "weights": {"hot": 0.31, "cold": 0.12, "missing": 0.18, "balanced": 0.35, "random": 0.04},
            "diff_scores": {"hot": 0.06, "cold": -0.08, "missing": -0.01, "balanced": 0.21, "random": -0.18},
        }
        gap = {"factor": 1.0}
        teams = {
            "hot": {"proposals": [{}], "error": ""},
            "cold": {"proposals": [{}], "error": ""},
            "missing": {"proposals": [{}], "error": ""},
            "balanced": {"proposals": [{}], "error": ""},
            "random": {"proposals": [], "error": "x"},
        }
        report = predict.build_lead_agent_report(lead_model, gap, teams)
        self.assertEqual(report["top_agent"], "balanced")
        self.assertIn("策略风格=", report["archive_summary"])
        self.assertEqual(len(report["top3"]), 3)


if __name__ == "__main__":
    unittest.main()
