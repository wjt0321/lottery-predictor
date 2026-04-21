import tempfile
import unittest
import json
import os
import subprocess
import sys
from datetime import datetime

import predict


class PredictFlowTests(unittest.TestCase):
    def _build_mock_records(self, total=60):
        records = []
        for p in range(total, 0, -1):
            base = (p % 28) + 1
            red = sorted({base, base + 1, base + 2, base + 3, base + 4, base + 5})
            red = [((n - 1) % 33) + 1 for n in red]
            records.append(
                {
                    "period": str(2026000 + p),
                    "date": f"2026-01-{(p % 28) + 1:02d}",
                    "red_balls": sorted(red),
                    "blue_ball": ((p - 1) % 16) + 1,
                }
            )
        return records

    def test_evaluate_last_prediction_gap_match(self):
        archive = {"period": "2026002", "ticket1": "01 02 03 04 05 06+07|hot,cold"}
        latest = {"period": "2026002", "red_balls": [1, 8, 9, 10, 11, 12], "blue_ball": 7}
        result = predict.evaluate_last_prediction_gap(archive, latest)
        self.assertTrue(result["matched"])
        self.assertEqual(result["red_hits"], 1)
        self.assertEqual(result["blue_hit"], 1)

    def test_agent_teams_excludes_lstm(self):
        self.assertNotIn("lstm", predict.AGENT_TEAMS)

    def test_predict_help_has_no_tensorflow_warning(self):
        project_root = os.path.abspath(os.path.dirname(__file__) or ".")
        result = subprocess.run(
            [sys.executable, "predict.py", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = f"{result.stdout}\n{result.stderr}"
        self.assertNotIn("TensorFlow未安装", output)
        self.assertNotIn("lstm", output.lower())

    def test_is_data_stale_flags_missing_draw(self):
        stale, detail = predict.is_data_stale("2026-04-16", now=datetime(2026, 4, 21, 12, 0, 0))
        self.assertTrue(stale)
        self.assertEqual(detail["latest_record_date"], "2026-04-16")
        self.assertEqual(detail["expected_latest_draw_date"], "2026-04-19")

    def test_is_data_stale_allows_pre_draw_window(self):
        stale, detail = predict.is_data_stale("2026-04-19", now=datetime(2026, 4, 21, 12, 0, 0))
        self.assertFalse(stale)
        self.assertEqual(detail["expected_latest_draw_date"], "2026-04-19")

    def test_is_data_stale_handles_invalid_date(self):
        stale, detail = predict.is_data_stale("bad-date", now=datetime(2026, 4, 21, 12, 0, 0))
        self.assertTrue(stale)
        self.assertIn("error", detail)

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

    def test_save_compact_archive_with_explain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = predict.ARCHIVE_DIR
            predict.ARCHIVE_DIR = temp_dir
            try:
                path = predict.save_compact_prediction(
                    target_period="2026999",
                    tickets=[
                        {
                            "red": [1, 2, 3, 4, 5, 6],
                            "blue": 7,
                            "sources": ["hot", "balanced"],
                            "explain": "来源Agent=hot,balanced;红球贡献=01:hot(0.23);蓝球贡献=07:balanced(0.31);多样性替换=无",
                        }
                    ],
                    lead_summary="factor=1.00",
                )
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("ticket1_explain=", content)
                self.assertIn("多样性替换", content)
            finally:
                predict.ARCHIVE_DIR = old_dir

    def test_save_compact_archive_with_explain_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = predict.ARCHIVE_DIR
            predict.ARCHIVE_DIR = temp_dir
            try:
                path = predict.save_compact_prediction(
                    target_period="2026998",
                    tickets=[
                        {
                            "red": [1, 2, 3, 4, 5, 6],
                            "blue": 7,
                            "sources": ["hot", "balanced"],
                            "explain": "来源Agent=hot,balanced;红球贡献=01:hot(0.23);蓝球贡献=07:balanced(0.31);多样性替换=无",
                            "explain_json": {
                                "sources": ["hot", "balanced"],
                                "red": [{"ball": 1, "top_agent": "hot", "top_contribution": 0.23}],
                                "blue": {"ball": 7, "top_agent": "balanced", "top_contribution": 0.31},
                                "diversity_replacements": [],
                            },
                        }
                    ],
                    lead_summary="factor=1.00",
                )
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("ticket1_explain_json=", content)
                json_line = next(line for line in content.splitlines() if line.startswith("ticket1_explain_json="))
                payload = json_line.split("=", 1)[1]
                decoded = json.loads(payload)
                self.assertEqual(decoded["sources"], ["hot", "balanced"])
                self.assertEqual(decoded["blue"]["ball"], 7)
            finally:
                predict.ARCHIVE_DIR = old_dir

    def test_save_compact_prediction_keeps_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = predict.ARCHIVE_DIR
            predict.ARCHIVE_DIR = temp_dir
            try:
                path1 = predict.save_compact_prediction(
                    target_period="2026997",
                    tickets=[{"red": [1, 2, 3, 4, 5, 6], "blue": 7, "sources": ["hot"]}],
                    lead_summary="factor=1.00",
                )
                with open(path1, "r", encoding="utf-8") as f:
                    original_content = f.read()

                path2 = predict.save_compact_prediction(
                    target_period="2026997",
                    tickets=[{"red": [7, 8, 9, 10, 11, 12], "blue": 13, "sources": ["cold"]}],
                    lead_summary="factor=0.95",
                )

                self.assertNotEqual(os.path.normpath(path1), os.path.normpath(path2))
                with open(path1, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), original_content)
                with open(path2, "r", encoding="utf-8") as f:
                    updated_content = f.read()
                self.assertIn("ticket1=07 08 09 10 11 12+13|cold", updated_content)
            finally:
                predict.ARCHIVE_DIR = old_dir

    def test_load_latest_archive_prefers_latest_timestamped_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = predict.ARCHIVE_DIR
            predict.ARCHIVE_DIR = temp_dir
            try:
                predict.save_compact_prediction(
                    target_period="2026996",
                    tickets=[{"red": [1, 2, 3, 4, 5, 6], "blue": 7, "sources": ["hot"]}],
                    lead_summary="factor=1.00",
                )
                predict.save_compact_prediction(
                    target_period="2026996",
                    tickets=[{"red": [7, 8, 9, 10, 11, 12], "blue": 13, "sources": ["cold"]}],
                    lead_summary="factor=0.95",
                )
                latest = predict.load_latest_archive()
                self.assertIsNotNone(latest)
                self.assertEqual(latest["period"], "2026996")
                self.assertEqual(latest["ticket1"], "07 08 09 10 11 12+13|cold")
            finally:
                predict.ARCHIVE_DIR = old_dir

    def test_build_expert_teams_count(self):
        records = [
            {"period": "2026002", "date": "2026-01-03", "red_balls": [1, 2, 3, 4, 5, 6], "blue_ball": 7},
            {"period": "2026001", "date": "2026-01-01", "red_balls": [7, 8, 9, 10, 11, 12], "blue_ball": 13},
        ]
        teams = predict.build_expert_teams(records, tickets=2, seed=7)
        self.assertEqual(len(teams), len(predict.AGENT_TEAMS))
        valid = [name for name, payload in teams.items() if len(payload.get("proposals", [])) == 2]
        self.assertGreaterEqual(len(valid), 3)

    def test_resolve_team_ticket_count_is_fixed_to_five(self):
        self.assertEqual(predict.resolve_team_ticket_count(1), 5)
        self.assertEqual(predict.resolve_team_ticket_count(5), 5)
        self.assertEqual(predict.resolve_team_ticket_count(9), 5)

    def test_build_core_pool_snapshot_collects_top10_red_pool(self):
        teams = {
            "hot": {
                "proposals": [
                    {"red": [1, 2, 3, 4, 5, 6], "blue": 1},
                    {"red": [1, 2, 3, 7, 8, 9], "blue": 2},
                ],
                "error": "",
            },
            "cold": {
                "proposals": [
                    {"red": [1, 2, 3, 4, 7, 10], "blue": 2},
                    {"red": [1, 2, 8, 9, 10, 11], "blue": 3},
                ],
                "error": "",
            },
            "balanced": {
                "proposals": [
                    {"red": [1, 3, 4, 5, 6, 10], "blue": 1},
                    {"red": [2, 4, 6, 8, 10, 12], "blue": 2},
                ],
                "error": "",
            },
        }
        lead_model = {
            "weights": {"hot": 0.5, "cold": 0.2, "balanced": 0.3},
            "diff_scores": {"hot": 0.0, "cold": 0.0, "balanced": 0.0},
        }
        snapshot = predict.build_core_pool_snapshot(teams, lead_model, diff_factor=1.0)
        self.assertEqual(len(snapshot["red_pool"]), 10)
        self.assertEqual(snapshot["red_pool"][:4], [1, 2, 3, 4])
        self.assertEqual(snapshot["blue_pool"][:2], [2, 1])
        self.assertIn("hot", snapshot["pool_sources"][1])

    def test_generate_rotation_matrix_tickets_uses_pool_of_ten(self):
        snapshot = {
            "red_pool": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "blue_pool": [3, 5],
            "red_scores": {n: 1.0 for n in range(1, 11)},
            "blue_scores": {3: 1.0, 5: 0.8},
            "pool_sources": {n: ["hot", "balanced"] for n in range(1, 11)},
            "valid_agents": ["hot", "balanced"],
        }
        tickets = predict.generate_rotation_matrix_tickets(snapshot)
        self.assertEqual(len(tickets), 5)
        covered = set()
        for index, ticket in enumerate(tickets, start=1):
            self.assertEqual(len(ticket["red"]), 6)
            self.assertTrue(set(ticket["red"]).issubset(set(snapshot["red_pool"])))
            self.assertIn(ticket["blue"], snapshot["blue_pool"])
            self.assertEqual(ticket["matrix_row_id"], index)
            covered.update(ticket["red"])
        self.assertEqual(covered, set(snapshot["red_pool"]))

    def test_generate_team_matrix_tickets_builds_archive_ready_payload(self):
        teams = {
            "hot": {
                "proposals": [
                    {"red": [1, 2, 3, 4, 5, 6], "blue": 1},
                    {"red": [1, 2, 3, 7, 8, 9], "blue": 2},
                ],
                "error": "",
            },
            "cold": {
                "proposals": [
                    {"red": [1, 2, 3, 4, 7, 10], "blue": 2},
                    {"red": [1, 2, 8, 9, 10, 11], "blue": 3},
                ],
                "error": "",
            },
            "balanced": {
                "proposals": [
                    {"red": [1, 3, 4, 5, 6, 10], "blue": 1},
                    {"red": [2, 4, 6, 8, 10, 12], "blue": 2},
                ],
                "error": "",
            },
        }
        lead_model = {
            "weights": {"hot": 0.5, "cold": 0.2, "balanced": 0.3},
            "diff_scores": {"hot": 0.0, "cold": 0.0, "balanced": 0.0},
        }
        tickets = predict.generate_team_matrix_tickets(teams, lead_model, diff_factor=1.0)
        self.assertEqual(len(tickets), 5)
        for ticket in tickets:
            self.assertIn("explain_json", ticket)
            self.assertEqual(ticket["explain_json"]["matrix"]["type"], "10_red_guard_6_to_5")
            self.assertEqual(len(ticket["explain_json"]["core_pool"]["red_pool"]), 10)

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

    def test_backtest_report_has_unified_metrics(self):
        records = self._build_mock_records(72)
        report = predict.backtest_report(records, learning_cycles=24, windows=[12, 24, 36])
        self.assertIn("overall", report)
        self.assertIn("by_agent", report)
        self.assertIn("window_reports", report)
        self.assertGreater(report["overall"]["samples"], 0)
        self.assertIn("hit_rate_ge2", report["overall"])
        self.assertIn("blue_hit_rate", report["overall"])
        self.assertTrue(set(predict.AGENT_TEAMS).issubset(set(report["by_agent"].keys())))

    def test_train_lead_agent_uses_multi_window_decay(self):
        records = self._build_mock_records(70)
        old_generate = predict.generate_prediction
        old_score = predict._ticket_score
        try:
            agent_code = {name: i + 1 for i, name in enumerate(predict.AGENT_TEAMS)}

            def fake_generate_prediction(_records, strategy="balanced", rng=None):
                code = agent_code[strategy]
                return [code, code + 1, code + 2, code + 3, code + 4, code + 5], (code % 16) + 1

            def fake_ticket_score(red, blue, actual):
                _ = blue
                period_num = int(actual["period"])
                marker = red[0]
                if period_num >= 2026060:
                    return 4.0 if marker == agent_code["balanced"] else 1.0
                return 4.0 if marker == agent_code["hot"] else 1.0

            predict.generate_prediction = fake_generate_prediction
            predict._ticket_score = fake_ticket_score

            lead = predict.train_lead_agent(
                records,
                learning_cycles=24,
                window_sizes=(12, 24),
                window_weights=(0.7, 0.3),
                decay_gamma=0.9,
            )
            self.assertIn("window_reports", lead)
            self.assertIn("meta", lead)
            self.assertAlmostEqual(sum(lead["weights"].values()), 1.0, places=6)
            self.assertGreater(lead["weights"]["balanced"], lead["weights"]["hot"])
        finally:
            predict.generate_prediction = old_generate
            predict._ticket_score = old_score

    def test_judge_with_lead_agent_applies_ticket_diversity(self):
        teams = {}
        for agent in predict.AGENT_TEAMS:
            teams[agent] = {
                "proposals": [
                    {"red": [1, 2, 3, 4, 5, 6], "blue": 1},
                    {"red": [1, 2, 3, 4, 5, 6], "blue": 1},
                ],
                "error": "",
            }
        lead_model = {
            "weights": {agent: 1 / len(predict.AGENT_TEAMS) for agent in predict.AGENT_TEAMS},
            "diff_scores": {agent: 0.0 for agent in predict.AGENT_TEAMS},
        }
        first_ticket = predict.judge_with_lead_agent(
            teams,
            lead_model=lead_model,
            diff_factor=1.0,
            ticket_index=0,
            seed=42,
            existing_tickets=[],
        )
        second_ticket = predict.judge_with_lead_agent(
            teams,
            lead_model=lead_model,
            diff_factor=1.0,
            ticket_index=1,
            seed=42,
            existing_tickets=[first_ticket],
        )
        self.assertIsNotNone(first_ticket)
        self.assertIsNotNone(second_ticket)
        self.assertIn("explain", second_ticket)
        self.assertIn("来源Agent=", second_ticket["explain"])
        self.assertIn("红球贡献=", second_ticket["explain"])
        self.assertIn("蓝球贡献=", second_ticket["explain"])
        self.assertIn("多样性替换=", second_ticket["explain"])
        overlap = len(set(first_ticket["red"]) & set(second_ticket["red"]))
        self.assertLessEqual(overlap, 4)

    def test_load_weight_patch_recommended_base_weights(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            patch_path = f"{temp_dir}/weight_patch.json"
            payload = {
                "recommended_base_weights": {"hot": 0.2, "cold": 0.1, "missing": 0.1, "balanced": 0.2, "random": 0.1, "cycle": 0.1, "sum": 0.1, "zone": 0.1, "lstm": 0.05},
                "weight_deltas": {"hot": 0.01},
            }
            with open(patch_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            loaded = predict.load_weight_patch(patch_path)
            self.assertAlmostEqual(sum(loaded.values()), 1.0, places=6)
            self.assertGreater(loaded["hot"], loaded["zone"])
            self.assertNotIn("lstm", loaded)

    def test_train_lead_agent_accepts_initial_weights(self):
        records = self._build_mock_records(72)
        initial = {agent: (2.0 if agent == "hot" else 1.0) for agent in predict.AGENT_TEAMS}
        lead = predict.train_lead_agent(records, learning_cycles=12, initial_weights=initial)
        self.assertIn("meta", lead)
        self.assertEqual(lead["meta"]["initial_weights_applied"], True)

    def test_auto_discover_weight_patch_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = f"{temp_dir}/config"
            os.makedirs(config_dir, exist_ok=True)
            patch_path = f"{config_dir}/weight_patch.latest.json"
            with open(patch_path, "w", encoding="utf-8") as f:
                json.dump({"recommended_base_weights": {"hot": 1.0}}, f, ensure_ascii=False)
            discovered = predict.find_default_weight_patch(temp_dir)
            self.assertEqual(os.path.normpath(discovered), os.path.normpath(patch_path))

    def test_resolve_weight_patch_path_fallback_chain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = os.path.join(temp_dir, "config")
            os.makedirs(config_dir, exist_ok=True)
            latest_path = os.path.join(config_dir, "weight_patch.latest.json")
            explicit_path = os.path.join(temp_dir, "explicit.weight_patch.json")
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump({"recommended_base_weights": {"hot": 1.0}}, f, ensure_ascii=False)
            with open(explicit_path, "w", encoding="utf-8") as f:
                json.dump({"recommended_base_weights": {"cold": 1.0}}, f, ensure_ascii=False)

            path1, source1 = predict.resolve_weight_patch_path(explicit_path, project_root=temp_dir)
            self.assertEqual(os.path.normpath(path1), os.path.normpath(explicit_path))
            self.assertEqual(source1, "explicit")

            path2, source2 = predict.resolve_weight_patch_path(None, project_root=temp_dir)
            self.assertEqual(os.path.normpath(path2), os.path.normpath(latest_path))
            self.assertEqual(source2, "default")

            os.remove(latest_path)
            path3, source3 = predict.resolve_weight_patch_path(None, project_root=temp_dir)
            self.assertIsNone(path3)
            self.assertEqual(source3, "none")

    def test_load_param_patch_merges_runtime_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            patch_path = os.path.join(temp_dir, "param_patch.latest.json")
            payload = {
                "pool_params": {"core_red_pool_size": 10, "core_blue_pool_size": 4},
                "fusion_params": {"ticket_decay_step": 0.12},
                "matrix_params": {"preferred_rows": [5, 3, 1], "matrix_type": "10_red_guard_6_to_5"},
            }
            with open(patch_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            loaded = predict.load_param_patch(patch_path)
            self.assertEqual(loaded["pool_params"]["core_red_pool_size"], 10)
            self.assertEqual(loaded["pool_params"]["core_blue_pool_size"], 4)
            self.assertEqual(loaded["fusion_params"]["ticket_decay_step"], 0.12)
            self.assertEqual(loaded["fusion_params"]["min_ticket_decay"], predict.DEFAULT_RUNTIME_CONFIG["fusion_params"]["min_ticket_decay"])
            self.assertEqual(loaded["matrix_params"]["preferred_rows"], [5, 3, 1])

    def test_generate_rotation_matrix_tickets_respects_preferred_rows(self):
        snapshot = {
            "red_pool": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "blue_pool": [3, 5],
            "red_scores": {n: 1.0 for n in range(1, 11)},
            "blue_scores": {3: 1.0, 5: 0.8},
            "pool_sources": {n: ["hot", "balanced"] for n in range(1, 11)},
            "blue_sources": {3: ["hot"], 5: ["balanced"]},
            "red_agent_contrib": {n: {"hot": 1.0} for n in range(1, 11)},
            "blue_agent_contrib": {3: {"hot": 1.0}, 5: {"balanced": 0.8}},
            "valid_agents": ["hot", "balanced"],
        }
        runtime_config = {
            "pool_params": {"core_red_pool_size": 10, "core_blue_pool_size": 2},
            "fusion_params": {"ticket_decay_step": 0.08, "min_ticket_decay": 0.65},
            "matrix_params": {"matrix_type": "10_red_guard_6_to_5", "preferred_rows": [5, 3, 1, 2, 4], "row_weights": {"5": 0.4, "3": 0.25, "1": 0.2, "2": 0.1, "4": 0.05}},
        }
        tickets = predict.generate_rotation_matrix_tickets(snapshot, runtime_config=runtime_config)
        self.assertEqual(len(tickets), 5)
        self.assertEqual([ticket["matrix_row_id"] for ticket in tickets], [5, 3, 1, 2, 4])

    def test_resolve_runtime_config_auto_discovers_param_and_matrix_patch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = os.path.join(temp_dir, "config")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "param_patch.latest.json"), "w", encoding="utf-8") as f:
                json.dump({"pool_params": {"core_blue_pool_size": 4}}, f, ensure_ascii=False)
            with open(os.path.join(config_dir, "matrix_patch.latest.json"), "w", encoding="utf-8") as f:
                json.dump({"matrix_type": "10_red_guard_6_to_5", "row_weights": {"5": 0.6}, "preferred_rows": [5, 3, 1, 2, 4]}, f, ensure_ascii=False)
            runtime = predict.resolve_runtime_config(project_root=temp_dir)
            self.assertEqual(runtime["pool_params"]["core_blue_pool_size"], 4)
            self.assertEqual(runtime["matrix_params"]["preferred_rows"], [5, 3, 1, 2, 4])
            self.assertEqual(runtime["matrix_params"]["row_weights"]["5"], 0.6)

    def test_build_archive_lead_summary_contains_patch_source(self):
        lead_report = {"healthy_agents": ["hot", "cold"], "archive_summary": "策略风格=保守"}
        summary = predict.build_archive_lead_summary(1.0, lead_report, patch_source="default")
        self.assertIn("patch_source=default", summary)


if __name__ == "__main__":
    unittest.main()
