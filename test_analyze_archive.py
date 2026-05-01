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

    def test_collect_explain_json_records_attaches_actual_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_archive(
                temp_dir,
                "2026036",
                [
                    {
                        "sources": ["hot"],
                        "red": [
                            {"ball": 1, "agent_contributions": {"hot": 0.7}},
                            {"ball": 2, "agent_contributions": {"cold": 0.6}},
                        ],
                        "blue": {"ball": 7, "agent_contributions": {"hot": 0.4}},
                        "matrix": {"type": "10_red_guard_6_to_5", "row_id": 1},
                    }
                ],
            )

            records = analyze_archive.collect_explain_json_records(
                temp_dir,
                actual_records=[
                    {
                        "period": "2026036",
                        "red_balls": [1, 3, 5, 7, 9, 11],
                        "blue_ball": 7,
                    }
                ],
            )

            actual = records[0]["payload"]["actual_result"]
            self.assertEqual(actual["red_hits"], 3)
            self.assertEqual(actual["blue_hit"], 1)
            self.assertEqual(actual["hit_score"], 4.5)
            self.assertEqual(actual["actual_red_balls"], [1, 3, 5, 7, 9, 11])
            self.assertEqual(actual["actual_blue_ball"], 7)

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

    def test_build_agent_ranking_filters_retired_agents(self):
        records = [
            {
                "period": "2026036",
                "ticket_index": 1,
                "payload": {
                    "sources": ["hot", "lstm"],
                    "red": [{"ball": 1, "agent_contributions": {"hot": 0.6, "lstm": 0.9}}],
                    "blue": {"ball": 7, "agent_contributions": {"hot": 0.4, "lstm": 0.3}},
                    "diversity_replacements": [],
                },
            }
        ]
        ranking = analyze_archive.build_agent_ranking(records)
        agents = [row["agent"] for row in ranking]
        self.assertIn("hot", agents)
        self.assertNotIn("lstm", agents)

    def test_build_agent_ranking_uses_only_hit_contributions_when_actual_result_exists(self):
        records = [
            {
                "period": "2026036",
                "ticket_index": 1,
                "payload": {
                    "sources": ["hot", "cold"],
                    "red": [
                        {"ball": 1, "agent_contributions": {"hot": 0.4}},
                        {"ball": 2, "agent_contributions": {"cold": 9.0}},
                    ],
                    "blue": {"ball": 7, "agent_contributions": {"hot": 0.5}},
                    "actual_result": {
                        "actual_red_balls": [1, 3, 5, 7, 9, 11],
                        "actual_blue_ball": 7,
                        "red_hits": 1,
                        "blue_hit": 1,
                        "hit_score": 2.5,
                    },
                },
            }
        ]

        ranking = analyze_archive.build_agent_ranking(records)

        self.assertEqual(ranking[0]["agent"], "hot")
        self.assertGreater(ranking[0]["score"], ranking[1]["score"])

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

    def test_build_weight_patch_payload_filters_retired_agents(self):
        ranking = [{"agent": "hot", "score": 1.0}, {"agent": "lstm", "score": 2.0}]
        weight_adjustments = [{"agent": "hot", "delta": 0.1, "weight_delta": 0.02}, {"agent": "lstm", "delta": 0.2, "weight_delta": 0.01}]
        payload = analyze_archive.build_weight_patch_payload(ranking, weight_adjustments)
        self.assertIn("hot", payload["agents"])
        self.assertNotIn("lstm", payload["agents"])

    def test_build_matrix_row_ranking_aggregates_hit_metrics(self):
        records = [
            {
                "period": "2026044",
                "ticket_index": 1,
                "payload": {
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 1},
                    "actual_result": {"red_hits": 3, "blue_hit": 1, "hit_score": 4.5},
                },
            },
            {
                "period": "2026045",
                "ticket_index": 1,
                "payload": {
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 1},
                    "actual_result": {"red_hits": 1, "blue_hit": 0, "hit_score": 1.0},
                },
            },
            {
                "period": "2026044",
                "ticket_index": 2,
                "payload": {
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 2},
                    "actual_result": {"red_hits": 2, "blue_hit": 0, "hit_score": 2.0},
                },
            },
            {
                "period": "2026039",
                "ticket_index": 3,
                "payload": {
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 3},
                },
            },
        ]
        ranking = analyze_archive.build_matrix_row_ranking(records)
        self.assertEqual(len(ranking), 2)
        self.assertEqual(ranking[0]["row_id"], 1)
        self.assertEqual(ranking[0]["matrix_type"], "10_red_guard_6_to_5")
        self.assertEqual(ranking[0]["samples"], 2)
        self.assertAlmostEqual(ranking[0]["red_hit_avg"], 2.0)
        self.assertAlmostEqual(ranking[0]["blue_hit_rate"], 0.5)
        self.assertAlmostEqual(ranking[0]["hit_rate_ge2"], 0.5)
        self.assertAlmostEqual(ranking[0]["hit_rate_ge3"], 0.5)
        self.assertAlmostEqual(ranking[0]["avg_score"], 2.75)

    def test_render_report_includes_matrix_row_ranking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_archive(
                temp_dir,
                "2026044",
                [
                    {
                        "sources": ["hot"],
                        "red": [{"ball": 1, "agent_contributions": {"hot": 1.0}}],
                        "blue": {"ball": 7, "agent_contributions": {"hot": 0.5}},
                        "diversity_replacements": [],
                        "matrix": {"type": "10_red_guard_6_to_5", "row_id": 4},
                        "actual_result": {"red_hits": 3, "blue_hit": 1, "hit_score": 4.5},
                    }
                ],
            )
            report = analyze_archive.render_report(temp_dir, top_k=5, recent_limit=5)
            self.assertIn("矩阵行表现", report)
            self.assertIn("row=4", report)
            self.assertIn("avg_score=4.500000", report)

    def test_build_matrix_patch_payload_exports_row_weights(self):
        matrix_ranking = [
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 1, "avg_score": 4.5},
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 2, "avg_score": 2.0},
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 3, "avg_score": 1.5},
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 4, "avg_score": 1.0},
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 5, "avg_score": 1.0},
        ]
        payload = analyze_archive.build_matrix_patch_payload(matrix_ranking)
        self.assertEqual(payload["matrix_type"], "10_red_guard_6_to_5")
        self.assertEqual(payload["origin"], "analyze_archive")
        self.assertEqual(set(payload["row_weights"].keys()), {"1", "2", "3", "4", "5"})
        self.assertAlmostEqual(sum(payload["row_weights"].values()), 1.0, places=6)
        self.assertGreater(payload["row_weights"]["1"], payload["row_weights"]["5"])

    def test_export_reports_writes_matrix_patch_and_latest_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_base = os.path.join(temp_dir, "report")
            paths = analyze_archive.export_reports(
                export_base,
                all_time_ranking=[{"agent": "hot", "score": 1.0}],
                recent_ranking=[{"agent": "hot", "score": 1.2}],
                delta_ranking=[{"agent": "hot", "recent_score": 1.2, "all_time_score": 1.0, "delta": 0.2}],
                suggestions=["x"],
                weight_adjustments=[{"agent": "hot", "delta": 0.2, "weight_delta": 0.02}],
                matrix_ranking=[
                    {"matrix_type": "10_red_guard_6_to_5", "row_id": 1, "avg_score": 2.0},
                    {"matrix_type": "10_red_guard_6_to_5", "row_id": 2, "avg_score": 1.0},
                ],
            )
            self.assertTrue(os.path.isfile(paths["matrix_patch"]))
            latest_path = os.path.join(temp_dir, "config", "matrix_patch.latest.json")
            final_latest = analyze_archive.write_latest_matrix_patch(paths["matrix_patch"], latest_path)
            self.assertTrue(os.path.isfile(final_latest))
            with open(final_latest, "r", encoding="utf-8") as f:
                latest_payload = json.load(f)
            self.assertIn("row_weights", latest_payload)

    def test_build_param_patch_payload_exports_fusion_and_pool_params(self):
        records = [
            {
                "period": "2026044",
                "ticket_index": 1,
                "payload": {
                    "diversity_replacements": ["03->12"],
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 1},
                    "core_pool": {"red_pool": [12, 2, 22, 24, 6, 3, 5, 13, 25, 23], "blue_pool": [13, 4, 10]},
                    "actual_result": {"red_hits": 3, "blue_hit": 1, "hit_score": 4.5},
                },
            },
            {
                "period": "2026045",
                "ticket_index": 2,
                "payload": {
                    "diversity_replacements": [],
                    "matrix": {"type": "10_red_guard_6_to_5", "row_id": 4},
                    "core_pool": {"red_pool": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "blue_pool": [3, 5]},
                    "actual_result": {"red_hits": 1, "blue_hit": 0, "hit_score": 1.0},
                },
            },
        ]
        matrix_ranking = [
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 1, "avg_score": 4.5},
            {"matrix_type": "10_red_guard_6_to_5", "row_id": 4, "avg_score": 1.0},
        ]
        payload = analyze_archive.build_param_patch_payload(records, matrix_ranking)
        self.assertEqual(payload["origin"], "analyze_archive")
        self.assertIn("pool_params", payload)
        self.assertIn("fusion_params", payload)
        self.assertIn("matrix_params", payload)
        self.assertEqual(payload["pool_params"]["core_red_pool_size"], 10)
        self.assertEqual(payload["pool_params"]["core_blue_pool_size"], 3)
        self.assertIn("ticket_decay_step", payload["fusion_params"])
        self.assertEqual(payload["matrix_params"]["matrix_type"], "10_red_guard_6_to_5")
        self.assertEqual(payload["matrix_params"]["preferred_rows"], [1, 4, 2, 3, 5])

    def test_export_reports_writes_param_patch_and_latest_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_base = os.path.join(temp_dir, "report")
            records = [
                {
                    "period": "2026044",
                    "ticket_index": 1,
                    "payload": {
                        "diversity_replacements": ["03->12"],
                        "matrix": {"type": "10_red_guard_6_to_5", "row_id": 1},
                        "core_pool": {"red_pool": [12, 2, 22, 24, 6, 3, 5, 13, 25, 23], "blue_pool": [13, 4, 10]},
                        "actual_result": {"red_hits": 3, "blue_hit": 1, "hit_score": 4.5},
                    },
                }
            ]
            matrix_ranking = [{"matrix_type": "10_red_guard_6_to_5", "row_id": 1, "avg_score": 4.5}]
            paths = analyze_archive.export_reports(
                export_base,
                all_time_ranking=[{"agent": "hot", "score": 1.0}],
                recent_ranking=[{"agent": "hot", "score": 1.2}],
                delta_ranking=[{"agent": "hot", "recent_score": 1.2, "all_time_score": 1.0, "delta": 0.2}],
                suggestions=["x"],
                weight_adjustments=[{"agent": "hot", "delta": 0.2, "weight_delta": 0.02}],
                matrix_ranking=matrix_ranking,
                records=records,
            )
            self.assertTrue(os.path.isfile(paths["param_patch"]))
            latest_path = os.path.join(temp_dir, "config", "param_patch.latest.json")
            final_latest = analyze_archive.write_latest_param_patch(paths["param_patch"], latest_path)
            self.assertTrue(os.path.isfile(final_latest))
            with open(final_latest, "r", encoding="utf-8") as f:
                latest_payload = json.load(f)
            self.assertIn("pool_params", latest_payload)


if __name__ == "__main__":
    unittest.main()
