import io
import tempfile
import unittest
import json
import os
import subprocess
import sys
from datetime import datetime
from unittest import mock

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
        self.assertGreaterEqual(len(snapshot["red_pool"]), 10)
        self.assertEqual(snapshot["red_pool"][:4], [1, 2, 3, 4])
        self.assertGreaterEqual(len(snapshot["blue_pool"]), 2)
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
        runtime_config = {
            "pool_params": {"core_red_pool_size": 10, "core_blue_pool_size": 2},
            "matrix_params": {"matrix_type": "10_red_guard_6_to_5", "preferred_rows": [1, 2, 3, 4, 5]},
        }
        tickets = predict.generate_rotation_matrix_tickets(snapshot, runtime_config=runtime_config)
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
            self.assertEqual(ticket["explain_json"]["matrix"]["type"], "14_red_guard_6_to_5")
            self.assertEqual(len(ticket["explain_json"]["core_pool"]["red_pool"]), 14)

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

    def test_train_lead_agent_keeps_initial_weights_as_prior(self):
        records = self._build_mock_records(72)
        initial = {agent: (20.0 if agent == "hot" else 1.0) for agent in predict.AGENT_TEAMS}

        lead = predict.train_lead_agent(records, learning_cycles=12, initial_weights=initial)

        self.assertEqual(max(lead["weights"], key=lead["weights"].get), "hot")
        self.assertGreater(lead["weights"]["hot"], lead["weights"]["balanced"])

    def test_train_lead_agent_is_deterministic_for_same_records(self):
        records = self._build_mock_records(72)

        first = predict.train_lead_agent(records, learning_cycles=12)
        second = predict.train_lead_agent(records, learning_cycles=12)

        self.assertEqual(first["weights"], second["weights"])
        self.assertEqual(first["avg_scores"], second["avg_scores"])

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
            "matrix_params": {
                "matrix_type": "10_red_guard_6_to_5",
                "preferred_rows": [5, 3, 1, 2, 4],
                "row_weights": {"5": 0.4, "3": 0.25, "1": 0.2, "2": 0.1, "4": 0.05},
            },
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

    def test_default_runtime_config_includes_blue_params(self):
        runtime = predict.resolve_runtime_config()
        self.assertIn("blue_params", runtime)
        self.assertEqual(
            runtime["blue_params"]["missing_cold_threshold"],
            predict.CONFIG.blue_missing_cold_threshold,
        )
        self.assertEqual(
            runtime["blue_params"]["cold_chase_cap"],
            predict.CONFIG.blue_cold_chase_cap,
        )

    def test_project_config_exposes_team_cover_defaults(self):
        runtime = predict.CONFIG.to_runtime_config()
        self.assertIn("cover_mode", runtime)
        self.assertEqual(runtime["cover_mode"]["ticket_count"], predict.CONFIG.team_ticket_count)
        self.assertEqual(runtime["cover_mode"]["candidate_pool_size"], predict.CONFIG.core_red_pool_size)
        self.assertEqual(runtime["cover_mode"]["blue_bucket_size"], predict.CONFIG.core_blue_pool_size)
        self.assertIn("score_weights", runtime["cover_mode"])
        self.assertEqual(runtime["matrix_params"]["preferred_rows"], [])

    def test_predict_help_includes_team_cover_mode(self):
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
        self.assertIn("team-cover", output)
        self.assertIn("--team-cover-backtest", output)

    def test_team_cover_backtest_report_contains_three_way_comparison(self):
        records = self._build_mock_records(72)
        report = predict.team_cover_backtest_report(records, cycles=12, seed=42)
        self.assertIn("team_cover", report)
        self.assertIn("team", report)
        self.assertIn("conditional_random", report)
        self.assertIn("comparison", report)
        self.assertIn("team_cover_vs_random_uplift", report["comparison"])
        self.assertIn("team_vs_random_uplift", report["comparison"])
        self.assertIn("avg_overlap", report["team_cover"])
        self.assertIn("avg_overlap", report["conditional_random"])

    def test_team_cover_backtest_report_is_deterministic_with_seed(self):
        records = self._build_mock_records(72)
        first = predict.team_cover_backtest_report(records, cycles=8, seed=42)
        second = predict.team_cover_backtest_report(records, cycles=8, seed=42)
        self.assertEqual(first, second)

    def test_team_cover_backtest_report_aggregates_three_way_metrics(self):
        records = self._build_mock_records(72)
        report = predict.team_cover_backtest_report(records, cycles=10, seed=42)
        for key in ["team_cover", "team", "conditional_random"]:
            self.assertEqual(report[key]["samples"], 10)
        for metric in [
            "avg_ticket_score",
            "best_of_5_avg_score",
            "best_of_5_hit_rate_ge2",
            "best_of_5_hit_rate_ge3",
            "blue_pool_hit_rate",
            "final_blue_hit_rate",
            "avg_overlap",
        ]:
            self.assertIn(metric, report["conditional_random"])
        self.assertAlmostEqual(
            report["comparison"]["team_cover_vs_random_uplift"]["avg_ticket_score"],
            round(report["team_cover"]["avg_ticket_score"] - report["conditional_random"]["avg_ticket_score"], 6),
        )
        self.assertAlmostEqual(
            report["comparison"]["team_vs_random_uplift"]["best_of_5_hit_rate_ge2"],
            round(report["team"]["best_of_5_hit_rate_ge2"] - report["conditional_random"]["best_of_5_hit_rate_ge2"], 6),
        )
        self.assertAlmostEqual(
            report["comparison"]["team_cover_vs_random_uplift"]["avg_overlap"],
            round(report["conditional_random"]["avg_overlap"] - report["team_cover"]["avg_overlap"], 6),
        )

    def test_team_cover_backtest_report_skips_unaligned_samples(self):
        records = self._build_mock_records(72)
        original_generate_team = predict.generate_final_team_tickets
        call_state = {"count": 0}

        def flaky_generate_team(*args, **kwargs):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return []
            return original_generate_team(*args, **kwargs)

        with mock.patch.object(predict, "generate_final_team_tickets", side_effect=flaky_generate_team):
            report = predict.team_cover_backtest_report(records, cycles=2, seed=42)

        self.assertEqual(report["team"]["samples"], 1)
        self.assertEqual(report["team_cover"]["samples"], 1)
        self.assertEqual(report["conditional_random"]["samples"], 1)

    def test_generate_conditional_random_tickets_uses_fixed_baseline_source(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1, "parity": n % 2, "agents": ["hot", "cold"]}
                for n in range(1, 15)
            },
            "blue_ranked": [1, 2, 3, 4, 5, 6],
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
            "blue_buckets": {"main": [1, 2], "explore": [3, 4], "reversion": [5, 6]},
            "valid_agents": ["hot", "cold", "zone"],
        }
        tickets = predict.generate_conditional_random_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 3}},
            seed=42,
        )
        self.assertEqual(len(tickets), 3)
        self.assertTrue(all(ticket["sources"] == [predict.CONDITIONAL_RANDOM_SOURCE] for ticket in tickets))

    def test_main_dispatches_team_cover_backtest(self):
        records = self._build_mock_records(72)
        data = {
            "records": records,
            "metadata": {"last_updated": "2026-05-19 10:00:00"},
        }
        report = {
            "team_cover": {"samples": 12, "avg_ticket_score": 1.5},
            "team": {"samples": 12, "avg_ticket_score": 1.2},
            "conditional_random": {"samples": 12, "avg_ticket_score": 1.0},
            "comparison": {"team_cover_vs_random_uplift": {"avg_ticket_score": 0.5}},
        }
        with mock.patch.object(sys, "argv", ["predict.py", "--team-cover-backtest", "--backtest-cycles", "12", "--seed", "42"]), \
             mock.patch.object(predict, "load_data", return_value=data), \
             mock.patch.object(predict, "is_data_stale", return_value=(False, {})), \
             mock.patch.object(predict, "analyze_hot_cold", return_value={"hot_red": list(range(1, 11)), "cold_red": list(range(24, 34))}), \
             mock.patch.object(predict, "resolve_weight_patch_path", return_value=(None, "none")), \
             mock.patch.object(predict, "load_weight_patch", return_value=None), \
             mock.patch.object(predict, "resolve_runtime_config", return_value={"cover_mode": {"ticket_count": 5}}), \
             mock.patch.object(predict, "team_cover_backtest_report", return_value=report) as mocked_report, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            predict.main()

        mocked_report.assert_called_once()
        called_args, called_kwargs = mocked_report.call_args
        self.assertEqual(called_args[0], records)
        self.assertEqual(called_kwargs["cycles"], 12)
        self.assertEqual(called_kwargs["seed"], 42)
        self.assertEqual(called_kwargs["runtime_config"], {"cover_mode": {"ticket_count": 5}})
        self.assertIn("progress_callback", called_kwargs)
        output = fake_stdout.getvalue()
        self.assertIn("team-cover 对照回测", output)
        self.assertIn("实验模式", output)
        self.assertIn("条件随机基准", output)
        self.assertNotIn("未实现", output)

    def test_main_team_cover_mode_outputs_tickets_and_archives_prediction(self):
        records = self._build_mock_records(72)
        data = {
            "records": records,
            "metadata": {"last_updated": "2026-05-19 10:00:00"},
        }
        cover_tickets = [
            {
                "red": [1, 2, 3, 4, 5, 6],
                "blue": 7,
                "sources": ["hot", "zone"],
                "explain": "cover ticket 1",
                "explain_json": {"cover_strategy": {"ticket_index": 1}},
            },
            {
                "red": [8, 9, 10, 11, 12, 13],
                "blue": 14,
                "sources": ["cold", "missing"],
                "explain": "cover ticket 2",
                "explain_json": {"cover_strategy": {"ticket_index": 2}},
            },
        ]
        with mock.patch.object(sys, "argv", ["predict.py", "--mode", "team-cover", "--seed", "42"]), \
             mock.patch.object(predict, "load_data", return_value=data), \
             mock.patch.object(predict, "is_data_stale", return_value=(False, {})), \
             mock.patch.object(predict, "analyze_hot_cold", return_value={"hot_red": list(range(1, 11)), "cold_red": list(range(24, 34))}), \
             mock.patch.object(predict, "resolve_runtime_config", return_value={"cover_mode": {"ticket_count": 5}}), \
             mock.patch.object(predict, "next_target_period", return_value="2099001"), \
             mock.patch.object(predict, "next_draw_date_str", return_value="2099-01-01"), \
             mock.patch.object(predict, "train_lead_agent", return_value={"weights": {"hot": 1.0}, "diff_scores": {"hot": 0.0}}), \
             mock.patch.object(predict, "build_expert_teams", return_value={"hot": {"proposals": [], "error": ""}}), \
             mock.patch.object(predict, "build_cover_candidate_snapshot", return_value={"red_ranked": list(range(1, 15))}) as mocked_snapshot, \
             mock.patch.object(predict, "generate_team_cover_tickets", return_value=cover_tickets) as mocked_generate, \
             mock.patch.object(
                 predict,
                 "build_archive_lead_summary",
                 return_value="factor=1.00;mode=team_cover;patch_source=none;agents=hot;report=覆盖实验",
             ) as mocked_summary, \
             mock.patch.object(predict, "save_compact_prediction", return_value="prediction_archive/2099001.txt") as mocked_archive, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            predict.main()

        mocked_snapshot.assert_called_once()
        mocked_generate.assert_called_once_with(
            {"red_ranked": list(range(1, 15))},
            runtime_config={"cover_mode": {"ticket_count": 5}},
            seed=42,
        )
        mocked_summary.assert_called_once()
        mocked_archive.assert_called_once_with(
            "2099001",
            cover_tickets,
            "factor=1.00;mode=team_cover;patch_source=none;agents=hot;report=覆盖实验",
        )
        output = fake_stdout.getvalue()
        self.assertIn("第1注", output)
        self.assertIn("第2注", output)
        self.assertIn("已归档本期精简预测", output)

    def test_build_cover_candidate_snapshot_returns_structured_scores(self):
        teams = {
            "hot": {"proposals": [{"red": [1, 2, 3, 4, 5, 6], "blue": 1}], "error": ""},
            "cold": {"proposals": [{"red": [7, 8, 9, 10, 11, 12], "blue": 2}], "error": ""},
            "zone": {"proposals": [{"red": [1, 7, 13, 19, 25, 31], "blue": 3}], "error": ""},
        }
        lead_model = {
            "weights": {"hot": 0.4, "cold": 0.3, "zone": 0.3},
            "diff_scores": {"hot": 0.0, "cold": 0.0, "zone": 0.0},
        }
        snapshot = predict.build_cover_candidate_snapshot(teams, lead_model, diff_factor=1.0)
        self.assertIn("red_ranked", snapshot)
        self.assertIn("red_meta", snapshot)
        self.assertIn("blue_ranked", snapshot)
        self.assertTrue(snapshot["red_ranked"])
        self.assertIn("agents", snapshot["red_meta"][1])
        self.assertIn("blue_scores", snapshot)

    def test_build_cover_candidate_snapshot_adds_blue_buckets(self):
        records = self._build_mock_records(40)
        teams = predict.build_expert_teams(records, tickets=2, seed=7)
        lead_model = predict.train_lead_agent(records, learning_cycles=12)
        snapshot = predict.build_cover_candidate_snapshot(
            teams,
            lead_model,
            diff_factor=1.0,
            runtime_config=predict.resolve_runtime_config(),
        )
        self.assertIn("blue_buckets", snapshot)
        self.assertIn("main", snapshot["blue_buckets"])
        self.assertIn("explore", snapshot["blue_buckets"])
        self.assertIn("reversion", snapshot["blue_buckets"])

    def test_build_cover_candidate_snapshot_prefers_engine_pool_and_cold_chase_for_blue_buckets(self):
        teams = {
            "hot": {"proposals": [{"red": [1, 2, 3, 4, 5, 6], "blue": 16}], "error": ""},
            "cold": {"proposals": [{"red": [7, 8, 9, 10, 11, 12], "blue": 15}], "error": ""},
        }
        lead_model = {
            "weights": {"hot": 0.5, "cold": 0.5},
            "diff_scores": {"hot": 0.0, "cold": 0.0},
        }
        records = self._build_mock_records(40)

        class FakeBlueBallEngine:
            def __init__(self, _records, config=None):
                self.config = config or {}

            def predict(self, pool_size=6):
                _ = pool_size
                return {
                    "pool": [11, 9, 7, 5, 3, 1],
                    "scores": {n: 2.0 - n * 0.05 for n in range(1, 17)},
                    "details": {"next_odd_prob": 0.55},
                    "cold_chase": [(5, 22), (3, 19), (16, 18)],
                }

        with mock.patch.object(predict, "BlueBallEngine", FakeBlueBallEngine):
            snapshot = predict.build_cover_candidate_snapshot(
                teams,
                lead_model,
                diff_factor=1.0,
                records=records,
                runtime_config=predict.resolve_runtime_config(),
            )

        self.assertEqual(snapshot["blue_buckets"]["main"], [11, 9])
        self.assertEqual(snapshot["blue_buckets"]["explore"], [5, 3])
        self.assertEqual(snapshot["blue_buckets"]["reversion"], [7, 1])

    def test_generate_team_cover_tickets_returns_five_diversified_rows(self):
        snapshot = {
            "red_ranked": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1 if n <= 5 else 2 if n <= 10 else 3, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [1, 2, 3, 4, 5, 6],
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
        }
        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config=predict.resolve_runtime_config(),
            seed=42,
        )
        self.assertEqual(len(tickets), 5)
        overlaps = [len(set(tickets[0]["red"]) & set(ticket["red"])) for ticket in tickets[1:]]
        self.assertTrue(all(overlap <= 4 for overlap in overlaps))
        self.assertTrue(all("cover_strategy" in ticket["explain_json"] for ticket in tickets))
        self.assertTrue(all("focus" in ticket["explain_json"]["cover_strategy"] for ticket in tickets))

    def test_generate_team_cover_tickets_prefers_high_score_combo_under_overlap_cap(self):
        snapshot = {
            "red_ranked": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
            "red_scores": {
                1: 10.0,
                2: 9.0,
                3: 8.0,
                4: 7.0,
                5: 6.0,
                6: 5.0,
                7: 4.9,
                8: 4.8,
                9: 1.0,
                10: 1.0,
                11: 1.0,
                12: 1.0,
                13: 0.9,
                14: 0.8,
            },
            "red_meta": {
                n: {"zone": 1 if n <= 5 else 2 if n <= 10 else 3, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [1, 2, 3],
            "blue_scores": {1: 2.0, 2: 1.5, 3: 1.0},
        }

        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 2}},
            seed=42,
        )

        self.assertEqual(tickets[0]["red"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(tickets[1]["red"], [1, 2, 3, 4, 7, 8])

    def test_generate_team_cover_tickets_spreads_blue_buckets(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [1, 2, 3, 4, 5, 6],
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
            "blue_buckets": {"main": [1, 2], "explore": [3, 4], "reversion": [5, 6]},
        }
        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config=predict.resolve_runtime_config(),
            seed=42,
        )
        blues = [ticket["blue"] for ticket in tickets]
        self.assertGreaterEqual(len(set(blues)), 4)
        self.assertTrue(all("blue_bucket" in ticket["explain_json"]["cover_strategy"] for ticket in tickets))

    def test_generate_team_cover_tickets_keeps_bucket_priority_without_blue_scores(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [6, 4, 2, 5, 3, 1],
            "blue_scores": {},
            "blue_buckets": {"main": [6, 4], "explore": [5, 3], "reversion": [2, 1]},
        }
        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 3}},
            seed=42,
        )
        self.assertEqual([ticket["blue"] for ticket in tickets], [6, 5, 2])

    def test_generate_team_cover_tickets_fallback_prefers_unused_blue_from_other_bucket(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [6, 5, 4, 2, 1],
            "blue_scores": {6: 1.6, 5: 1.5, 4: 1.4, 2: 1.2, 1: 1.0},
            "blue_buckets": {"main": [6], "explore": [5, 4], "reversion": [2]},
        }
        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 4}},
            seed=42,
        )
        self.assertEqual([ticket["blue"] for ticket in tickets[:4]], [6, 5, 2, 4])
        self.assertEqual(tickets[3]["explain_json"]["cover_strategy"]["blue_bucket"], "explore")
        self.assertEqual(tickets[3]["explain_json"]["cover_strategy"]["selected_blue"], 4)

    def test_generate_team_cover_tickets_keeps_bucket_priority_when_some_blue_scores_missing(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {
                n: {"zone": 1, "parity": n % 2, "agents": ["hot"]}
                for n in range(1, 15)
            },
            "blue_ranked": [6, 4, 2, 5, 3, 1],
            "blue_scores": {4: 1.4},
            "blue_buckets": {"main": [6, 4], "explore": [5, 3], "reversion": [2, 1]},
        }
        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 3}},
            seed=42,
        )
        self.assertEqual([ticket["blue"] for ticket in tickets], [6, 5, 2])

    def test_generate_team_cover_tickets_uses_structure_bonus_when_scores_are_close(self):
        snapshot = {
            "red_ranked": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 23, 24],
            "red_scores": {
                1: 1.50,
                2: 1.49,
                3: 1.48,
                4: 1.47,
                5: 1.46,
                6: 1.45,
                7: 1.00,
                8: 1.00,
                9: 1.00,
                10: 1.00,
                11: 1.00,
                12: 1.00,
                23: 0.96,
                24: 0.95,
            },
            "red_meta": {
                n: {"zone": 1 if n <= 11 else 2 if n <= 22 else 3, "parity": n % 2, "agents": ["hot"]}
                for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 23, 24]
            },
            "blue_ranked": [1, 2, 3],
            "blue_scores": {1: 2.0, 2: 1.5, 3: 1.0},
        }

        tickets = predict.generate_team_cover_tickets(
            snapshot,
            runtime_config={"cover_mode": {"ticket_count": 2, "candidate_pool_size": 14}},
            seed=42,
        )

        self.assertEqual(tickets[0]["red"], [1, 2, 3, 4, 5, 6])
        self.assertTrue(any(ball >= 23 for ball in tickets[1]["red"]))

    def test_load_param_patch_can_override_blue_params(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            patch_path = os.path.join(temp_dir, "param_patch.latest.json")
            payload = {
                "blue_params": {
                    "missing_cold_threshold": 9,
                    "cold_chase_cap": 2,
                }
            }
            with open(patch_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            loaded = predict.load_param_patch(patch_path)
            self.assertEqual(loaded["blue_params"]["missing_cold_threshold"], 9)
            self.assertEqual(loaded["blue_params"]["cold_chase_cap"], 2)

    def test_generate_team_matrix_tickets_passes_blue_params_to_engine(self):
        teams = {
            "hot": {"proposals": [{"red": [1, 2, 3, 4, 5, 6], "blue": 1}], "error": ""},
            "cold": {"proposals": [{"red": [7, 8, 9, 10, 11, 12], "blue": 2}], "error": ""},
        }
        lead_model = {
            "weights": {"hot": 0.5, "cold": 0.5},
            "diff_scores": {"hot": 0.0, "cold": 0.0},
        }
        records = self._build_mock_records(40)
        captured = {}

        class FakeBlueBallEngine:
            def __init__(self, _records, config=None):
                captured["config"] = config

            def predict(self, pool_size=6):
                _ = pool_size
                return {
                    "pool": [1, 2, 3, 4, 5, 6],
                    "scores": {i: 2.0 - i * 0.1 for i in range(1, 17)},
                    "details": {"next_odd_prob": 0.5},
                    "cold_chase": [],
                }

        runtime_config = predict.resolve_runtime_config()
        runtime_config["blue_params"]["missing_cold_threshold"] = 9

        with mock.patch.object(predict, "BlueBallEngine", FakeBlueBallEngine):
            predict.generate_team_matrix_tickets(
                teams,
                lead_model,
                diff_factor=1.0,
                records=records,
                runtime_config=runtime_config,
            )

        self.assertEqual(captured["config"]["missing_cold_threshold"], 9)

    def test_generate_rotation_matrix_tickets_tracks_used_blues(self):
        snapshot = {
            "red_pool": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "blue_pool": [1, 2, 3, 4, 5, 6],
            "red_scores": {n: 1.0 for n in range(1, 11)},
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
            "pool_sources": {n: ["hot"] for n in range(1, 11)},
            "blue_sources": {n: ["hot"] for n in range(1, 7)},
            "red_agent_contrib": {n: {"hot": 1.0} for n in range(1, 11)},
            "blue_agent_contrib": {n: {"hot": 1.0} for n in range(1, 7)},
            "valid_agents": ["hot"],
        }
        runtime_config = {
            "pool_params": {"core_red_pool_size": 10, "core_blue_pool_size": 6},
            "matrix_params": {"matrix_type": "10_red_guard_6_to_5", "preferred_rows": [1, 2, 3, 4, 5]},
        }

        class FakeRandom:
            def choice(self, seq):
                return seq[0]

        with mock.patch.object(predict.random, "Random", return_value=FakeRandom()):
            tickets = predict.generate_rotation_matrix_tickets(snapshot, runtime_config=runtime_config)

        blues = [ticket["blue"] for ticket in tickets]
        self.assertEqual(blues, [1, 2, 3, 4, 5])

    def test_generate_rotation_matrix_tickets_uses_row_weights_when_preferred_rows_missing(self):
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
            "matrix_params": {
                "matrix_type": "10_red_guard_6_to_5",
                "preferred_rows": [],
                "row_weights": {"5": 0.9, "3": 0.4, "1": 0.2, "2": 0.1, "4": 0.05},
            },
        }
        tickets = predict.generate_rotation_matrix_tickets(snapshot, runtime_config=runtime_config)
        self.assertEqual([ticket["matrix_row_id"] for ticket in tickets], [5, 3, 1, 2, 4])

    def test_build_core_pool_snapshot_applies_position_weights_before_matrix(self):
        teams = {
            "hot": {
                "proposals": [
                    {"red": [1, 2, 3, 4, 5, 9], "blue": 1},
                    {"red": [1, 6, 7, 8, 9, 10], "blue": 2},
                ],
                "error": "",
            },
            "cold": {
                "proposals": [
                    {"red": [1, 11, 12, 13, 14, 9], "blue": 3},
                    {"red": [1, 15, 16, 17, 18, 9], "blue": 4},
                ],
                "error": "",
            },
        }
        lead_model = {
            "weights": {"hot": 0.5, "cold": 0.5},
            "diff_scores": {"hot": 0.0, "cold": 0.0},
        }
        pos_weights = [{n: 0.5 for n in range(1, 34)} for _ in range(6)]
        for pos_map in pos_weights:
            pos_map[1] = 0.2
            pos_map[9] = 2.0

        snapshot = predict.build_core_pool_snapshot(
            teams,
            lead_model,
            diff_factor=1.0,
            runtime_config={"pool_params": {"core_red_pool_size": 6, "core_blue_pool_size": 4}},
            pos_weights=pos_weights,
        )
        self.assertLess(snapshot["red_pool"].index(9), snapshot["red_pool"].index(1))

    def test_team_matrix_backtest_report_has_end_to_end_metrics(self):
        records = self._build_mock_records(72)
        report = predict.team_matrix_backtest_report(records, cycles=12, seed=42)
        self.assertIn("overall", report)
        self.assertIn("matrix_rows", report)
        self.assertGreater(report["overall"]["samples"], 0)
        self.assertIn("avg_ticket_score", report["overall"])
        self.assertIn("best_of_5_avg_score", report["overall"])
        self.assertIn("best_of_5_hit_rate_ge2", report["overall"])
        self.assertIn("blue_pool_hit_rate", report["overall"])
        self.assertIn("final_blue_hit_rate", report["overall"])

    def test_team_matrix_backtest_report_is_deterministic_with_seed(self):
        records = self._build_mock_records(72)
        first = predict.team_matrix_backtest_report(records, cycles=12, seed=42)
        second = predict.team_matrix_backtest_report(records, cycles=12, seed=42)
        self.assertEqual(first, second)

    def test_team_matrix_backtest_report_emits_progress_updates(self):
        records = self._build_mock_records(72)
        updates = []

        def on_progress(update):
            updates.append(update)

        report = predict.team_matrix_backtest_report(records, cycles=3, seed=42, progress_callback=on_progress)
        self.assertEqual(report["overall"]["samples"], 3)
        self.assertEqual(len(updates), 3)
        self.assertEqual(updates[0]["current"], 1)
        self.assertEqual(updates[-1]["total"], 3)
        self.assertIn("period", updates[0])

    def test_team_matrix_backtest_report_uses_lightweight_lead_training(self):
        records = self._build_mock_records(72)
        train_calls = []
        old_train = predict.train_lead_agent
        old_build = predict.build_expert_teams
        old_generate = predict.generate_final_team_tickets
        try:
            def fake_train_lead_agent(*args, **kwargs):
                train_calls.append(kwargs)
                return {
                    "weights": {agent: 1 / len(predict.AGENT_TEAMS) for agent in predict.AGENT_TEAMS},
                    "diff_scores": {agent: 0.0 for agent in predict.AGENT_TEAMS},
                }

            def fake_build_expert_teams(_history, tickets, seed):
                _ = seed
                return {
                    agent: {
                        "proposals": [{"red": [1, 2, 3, 4, 5, 6], "blue": 1} for _ in range(tickets)],
                        "error": "",
                    }
                    for agent in predict.AGENT_TEAMS
                }

            def fake_generate_final_team_tickets(*args, **kwargs):
                _ = args, kwargs
                return [
                    {
                        "red": [1, 2, 3, 4, 5, 6],
                        "blue": 1,
                        "matrix_row_id": row_id,
                        "explain_json": {"core_pool": {"blue_pool": [1, 2, 3, 4, 5, 6]}},
                    }
                    for row_id in range(1, 6)
                ]

            predict.train_lead_agent = fake_train_lead_agent
            predict.build_expert_teams = fake_build_expert_teams
            predict.generate_final_team_tickets = fake_generate_final_team_tickets

            predict.team_matrix_backtest_report(records, cycles=3, seed=42)
        finally:
            predict.train_lead_agent = old_train
            predict.build_expert_teams = old_build
            predict.generate_final_team_tickets = old_generate

        self.assertEqual(len(train_calls), 3)
        self.assertEqual(train_calls[0]["num_trials"], 4)
        self.assertEqual(train_calls[0]["window_sizes"], (8, 24))

    def test_build_archive_lead_summary_contains_patch_source(self):
        lead_report = {"healthy_agents": ["hot", "cold"], "archive_summary": "策略风格=保守"}
        summary = predict.build_archive_lead_summary(1.0, lead_report, patch_source="default")
        self.assertIn("patch_source=default", summary)

    def test_build_archive_lead_summary_supports_team_cover_mode(self):
        lead_report = {"healthy_agents": ["hot", "cold"], "archive_summary": "策略风格=覆盖"}
        summary = predict.build_archive_lead_summary(
            1.0,
            lead_report,
            patch_source="default",
            mode="team_cover",
        )
        self.assertIn("mode=team_cover", summary)


if __name__ == "__main__":
    unittest.main()
