import json
import os
import tempfile
import unittest

import analyze_archive


class AnalyzeArchiveTests(unittest.TestCase):
    def _write_archive(self, folder, period, rows):
        path = os.path.join(folder, f"{period}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"period={period}\n")
            f.write("generated_at=2026-04-07 00:00:00\n")
            f.write(f"ticket_count={len(rows)}\n")
            f.write("lead_summary=factor=1.00\n")
            for i, row in enumerate(rows, start=1):
                f.write(f"ticket{i}=01 02 03 04 05 06+07|hot\n")
                payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                f.write(f"ticket{i}_explain_json={payload}\n")

    def test_collect_explain_json_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_archive(
                temp_dir,
                "2026036",
                [
                    {
                        "sources": ["hot", "cycle"],
                        "red": [{"ball": 1, "agent_contributions": {"hot": 0.3, "cycle": 0.2}}],
                        "blue": {"ball": 7, "agent_contributions": {"hot": 0.4}},
                        "diversity_replacements": [],
                    }
                ],
            )
            records = analyze_archive.collect_explain_json_records(temp_dir)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["period"], "2026036")
            self.assertEqual(records[0]["ticket_index"], 1)
            self.assertEqual(records[0]["payload"]["sources"], ["hot", "cycle"])

    def test_build_agent_ranking_and_suggestions(self):
        records = [
            {
                "period": "2026036",
                "ticket_index": 1,
                "payload": {
                    "sources": ["hot", "cycle"],
                    "red": [{"ball": 1, "agent_contributions": {"hot": 0.6, "cycle": 0.2}}],
                    "blue": {"ball": 7, "agent_contributions": {"hot": 0.4}},
                    "diversity_replacements": [],
                },
            },
            {
                "period": "2026037",
                "ticket_index": 1,
                "payload": {
                    "sources": ["cold", "random"],
                    "red": [{"ball": 2, "agent_contributions": {"cold": 0.5, "random": 0.2}}],
                    "blue": {"ball": 8, "agent_contributions": {"cold": 0.1}},
                    "diversity_replacements": ["03->12"],
                },
            },
        ]
        ranking = analyze_archive.build_agent_ranking(records)
        self.assertGreater(ranking[0]["score"], ranking[-1]["score"])
        self.assertEqual(ranking[0]["agent"], "hot")
        suggestions = analyze_archive.build_tuning_suggestions(ranking, records)
        self.assertTrue(any("建议提高" in line for line in suggestions))
        self.assertTrue(any("多样性替换" in line for line in suggestions))

    def test_export_reports_and_dual_view_delta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_archive(
                temp_dir,
                "2026036",
                [
                    {
                        "sources": ["hot"],
                        "red": [{"ball": 1, "agent_contributions": {"hot": 1.0}}],
                        "blue": {"ball": 7, "agent_contributions": {"hot": 1.0}},
                        "diversity_replacements": [],
                    }
                ],
            )
            self._write_archive(
                temp_dir,
                "2026037",
                [
                    {
                        "sources": ["cold"],
                        "red": [{"ball": 2, "agent_contributions": {"cold": 1.2}}],
                        "blue": {"ball": 8, "agent_contributions": {"cold": 0.4}},
                        "diversity_replacements": ["03->12"],
                    }
                ],
            )
            all_records = analyze_archive.collect_explain_json_records(temp_dir)
            last_records = analyze_archive.collect_explain_json_records(temp_dir, limit_files=1)
            all_rank = analyze_archive.build_agent_ranking(all_records)
            last_rank = analyze_archive.build_agent_ranking(last_records)

            delta = analyze_archive.compute_dual_view_delta(last_rank, all_rank)
            self.assertIn("delta", delta[0])

            export_base = os.path.join(temp_dir, "report")
            paths = analyze_archive.export_reports(
                export_base,
                all_rank,
                last_rank,
                delta,
                suggestions=["x"],
                weight_adjustments=[{"agent": "hot", "delta": 0.2, "weight_delta": 0.02}],
            )
            self.assertTrue(os.path.isfile(paths["json"]))
            self.assertTrue(os.path.isfile(paths["csv"]))
            self.assertTrue(os.path.isfile(paths["weight_patch"]))
            with open(paths["json"], "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertIn("all_time_ranking", payload)
            self.assertIn("recent_ranking", payload)
            self.assertIn("delta_ranking", payload)
            with open(paths["weight_patch"], "r", encoding="utf-8") as f:
                patch = json.load(f)
            self.assertIn("recommended_base_weights", patch)
            self.assertIn("weight_deltas", patch)

            latest_path = os.path.join(temp_dir, "config", "weight_patch.latest.json")
            final_latest = analyze_archive.write_latest_weight_patch(paths["weight_patch"], latest_path)
            self.assertTrue(os.path.isfile(final_latest))
            with open(final_latest, "r", encoding="utf-8") as f:
                latest_payload = json.load(f)
            self.assertIn("recommended_base_weights", latest_payload)


if __name__ == "__main__":
    unittest.main()
