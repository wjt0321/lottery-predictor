# B+A Cover Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `lottery-predictor-main` 新增并行的 `team-cover` 覆盖优化实验模式，并提供相对条件随机基准的统一回测报告。

**Architecture:** 保留现有 `team -> core_pool -> rotation_matrix` 主链路不动，在 `predict.py` 中新增 `team-cover` 实验链路：先整理候选分布，再用覆盖优化出票器生成固定 5 注，最后在统一回测中与现有 `team` 和条件随机基准做对照。第一阶段只做中等重构，不重写专家体系；`team-cover` 预测沿用现有精简归档格式，而 `--team-cover-backtest` 维持只读不归档。

**Tech Stack:** Python 3、argparse、unittest、JSON 配置补丁、现有 `predict.py` / `analyze_archive.py`

---

## File Map

- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
  - 新增 `team-cover` CLI 入口
  - 新增覆盖优化链路函数
  - 新增条件随机基准与实验回测报告
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\project_config.py`
  - 新增实验模式默认配置
  - 清理 `preferred_rows` 默认语义，避免默认短路 `row_weights`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`
  - 新增对实验回测对照结果的渲染与导出支持
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\SKILL.md`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\AGENTS.md`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

### Task 1: 实验模式 CLI 与配置骨架

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\project_config.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`

- [ ] **Step 1: 写失败测试，锁定 `team-cover` CLI 和默认配置**

```python
    def test_project_config_exposes_team_cover_defaults(self):
        runtime = predict.CONFIG.to_runtime_config()
        self.assertIn("cover_mode", runtime)
        self.assertEqual(runtime["cover_mode"]["ticket_count"], 5)
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
```

- [ ] **Step 2: 运行定向测试确认失败**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_project_config_exposes_team_cover_defaults test_predict.PredictFlowTests.test_predict_help_includes_team_cover_mode`

Expected: FAIL，提示 `cover_mode` 不存在，`choices=['single', 'team']` 不包含 `team-cover`

- [ ] **Step 3: 在配置和 CLI 中补最小实现**

```python
# project_config.py
    def to_runtime_config(self) -> Dict:
        row_count = len(self.rotation_matrix_rows)
        return {
            "pool_params": {
                "core_red_pool_size": self.core_red_pool_size,
                "core_blue_pool_size": self.core_blue_pool_size,
            },
            "fusion_params": {
                "ticket_decay_step": self.ticket_decay_step,
                "min_ticket_decay": self.min_ticket_decay,
            },
            "matrix_params": {
                "matrix_type": self.rotation_matrix_type,
                "preferred_rows": [],
                "row_weights": {str(i): 1.0 / row_count for i in range(1, row_count + 1)},
            },
            "blue_params": {
                "missing_cold_threshold": self.blue_missing_cold_threshold,
                "missing_cold_bonus": self.blue_missing_cold_bonus,
                "missing_extreme_threshold": self.blue_missing_extreme_threshold,
                "missing_extreme_bonus": self.blue_missing_extreme_bonus,
                "parity_window": self.blue_parity_window,
                "zone_window": self.blue_zone_window,
                "amplitude_window": self.blue_amplitude_window,
                "heat_window": self.blue_heat_window,
                "cold_chase_cap": self.blue_cold_chase_cap,
            },
            "cover_mode": {
                "ticket_count": 5,
                "candidate_pool_size": 14,
                "blue_bucket_size": 6,
                "score_weights": {
                    "red_hit_ge2": 0.40,
                    "red_hit_ge3": 0.25,
                    "blue_pool_hit": 0.20,
                    "diversity": 0.15,
                },
            },
        }

# predict.py
    parser.add_argument('--mode', '-m', default='team', choices=['single', 'team', 'team-cover'],
                        help='预测模式：single=单策略，team=团队协同，team-cover=覆盖优化实验模式')
    parser.add_argument('--team-cover-backtest', action='store_true',
                        help='运行 team-cover 实验模式回测，并对比 team 与条件随机基准')
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_project_config_exposes_team_cover_defaults test_predict.PredictFlowTests.test_predict_help_includes_team_cover_mode`

Expected: PASS

- [ ] **Step 5: 提交骨架改动**

```bash
git add project_config.py predict.py test_predict.py
git commit -m "feat: 新增team-cover模式配置骨架"
```

### Task 2: 红球候选分布整理与覆盖优化出票器

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`

- [ ] **Step 1: 写失败测试，锁定候选分布整理与 5 注输出**

```python
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

    def test_generate_team_cover_tickets_returns_five_diversified_rows(self):
        snapshot = {
            "red_ranked": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {n: {"zone": 1 if n <= 5 else 2 if n <= 10 else 3, "parity": n % 2, "agents": ["hot"]} for n in range(1, 15)},
            "blue_ranked": [1, 2, 3, 4, 5, 6],
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
            "blue_buckets": {"main": [1, 2], "explore": [3, 4], "reversion": [5, 6]},
        }
        tickets = predict.generate_team_cover_tickets(snapshot, runtime_config=predict.resolve_runtime_config(), seed=42)
        self.assertEqual(len(tickets), 5)
        overlaps = [len(set(tickets[0]["red"]) & set(ticket["red"])) for ticket in tickets[1:]]
        self.assertTrue(all(overlap <= 4 for overlap in overlaps))
        self.assertTrue(all("cover_strategy" in ticket["explain_json"] for ticket in tickets))
```

- [ ] **Step 2: 运行定向测试确认失败**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_build_cover_candidate_snapshot_returns_structured_scores test_predict.PredictFlowTests.test_generate_team_cover_tickets_returns_five_diversified_rows`

Expected: FAIL，提示 `build_cover_candidate_snapshot` / `generate_team_cover_tickets` 未定义

- [ ] **Step 3: 补最小实现，先打通红球覆盖优化器**

```python
def build_cover_candidate_snapshot(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    pool_size = int(runtime.get("cover_mode", {}).get("candidate_pool_size", 14))
    red_scores = {i: 0.0 for i in range(1, 34)}
    red_meta = {i: {"agents": set(), "zone": 1 if i <= 11 else 2 if i <= 22 else 3, "parity": i % 2} for i in range(1, 34)}
    blue_scores = {i: 0.0 for i in range(1, 17)}
    for agent, payload in teams.items():
        proposals = payload.get("proposals", [])
        base_weight = lead_model["weights"].get(agent, 0.0) * diff_factor
        for proposal in proposals:
            for red in proposal["red"]:
                red_scores[red] += base_weight
                red_meta[red]["agents"].add(agent)
            blue_scores[proposal["blue"]] += base_weight
    for number, meta in red_meta.items():
        agent_count = len(meta["agents"])
        if agent_count == 1:
            red_scores[number] *= 1.05
        elif agent_count >= 3:
            red_scores[number] *= 0.96
        meta["agents"] = sorted(meta["agents"])
    red_ranked = [n for n, score in sorted(red_scores.items(), key=lambda item: (-item[1], item[0])) if score > 0][:pool_size]
    blue_ranked = [n for n, score in sorted(blue_scores.items(), key=lambda item: (-item[1], item[0])) if score > 0][:6]
    return {
        "red_ranked": red_ranked,
        "red_scores": {n: round(red_scores[n], 6) for n in red_ranked},
        "red_meta": {n: red_meta[n] for n in red_ranked},
        "blue_ranked": blue_ranked,
        "blue_scores": {n: round(blue_scores[n], 6) for n in blue_ranked},
    }

def generate_team_cover_tickets(snapshot: Dict[str, object], runtime_config: Optional[Dict[str, object]] = None, seed: Optional[int] = None) -> List[Dict[str, object]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    ticket_count = int(runtime.get("cover_mode", {}).get("ticket_count", 5))
    red_ranked = list(snapshot.get("red_ranked", []))
    red_scores = snapshot.get("red_scores", {})
    rng = random.Random(seed if seed is not None else _stable_int_seed("team-cover", tuple(red_ranked)))
    tickets = []
    for ticket_index in range(ticket_count):
        candidate_pool = sorted(red_ranked, key=lambda n: (-red_scores.get(n, 0.0), n))
        if tickets:
            used = Counter(ball for ticket in tickets for ball in ticket["red"])
            candidate_pool.sort(key=lambda n: (used.get(n, 0), -red_scores.get(n, 0.0), n))
        final_red = sorted(candidate_pool[:6])
        tickets.append(
            {
                "red": final_red,
                "blue": 1,
                "sources": sorted({agent for ball in final_red for agent in snapshot.get("red_meta", {}).get(ball, {}).get("agents", [])}),
                "explain": f"cover_ticket={ticket_index + 1};focus=red-diversity",
                "explain_json": {"cover_strategy": {"ticket_index": ticket_index + 1, "focus": "red-diversity"}},
            }
        )
        red_ranked = [n for n in red_ranked if n not in final_red] + [n for n in final_red if n in red_ranked]
    return tickets
```

- [ ] **Step 4: 运行定向测试确认通过**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_build_cover_candidate_snapshot_returns_structured_scores test_predict.PredictFlowTests.test_generate_team_cover_tickets_returns_five_diversified_rows`

Expected: PASS

- [ ] **Step 5: 提交红球覆盖优化器**

```bash
git add predict.py test_predict.py
git commit -m "feat: 新增红球覆盖优化出票器"
```

### Task 3: 蓝球分桶覆盖与实验模式解释信息

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`

- [ ] **Step 1: 写失败测试，锁定蓝球分桶与去重分配**

```python
    def test_build_cover_candidate_snapshot_adds_blue_buckets(self):
        records = self._build_mock_records(40)
        teams = predict.build_expert_teams(records, tickets=2, seed=7)
        lead_model = predict.train_lead_agent(records, learning_cycles=12)
        snapshot = predict.build_cover_candidate_snapshot(teams, lead_model, diff_factor=1.0, runtime_config=predict.resolve_runtime_config())
        self.assertIn("blue_buckets", snapshot)
        self.assertIn("main", snapshot["blue_buckets"])
        self.assertIn("explore", snapshot["blue_buckets"])
        self.assertIn("reversion", snapshot["blue_buckets"])

    def test_generate_team_cover_tickets_spreads_blue_buckets(self):
        snapshot = {
            "red_ranked": list(range(1, 15)),
            "red_scores": {n: 2.0 - (n * 0.05) for n in range(1, 15)},
            "red_meta": {n: {"zone": 1, "parity": n % 2, "agents": ["hot"]} for n in range(1, 15)},
            "blue_ranked": [1, 2, 3, 4, 5, 6],
            "blue_scores": {n: 2.0 - n * 0.1 for n in range(1, 7)},
            "blue_buckets": {"main": [1, 2], "explore": [3, 4], "reversion": [5, 6]},
        }
        tickets = predict.generate_team_cover_tickets(snapshot, runtime_config=predict.resolve_runtime_config(), seed=42)
        blues = [ticket["blue"] for ticket in tickets]
        self.assertGreaterEqual(len(set(blues)), 4)
        self.assertTrue(all("blue_bucket" in ticket["explain_json"]["cover_strategy"] for ticket in tickets))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_build_cover_candidate_snapshot_adds_blue_buckets test_predict.PredictFlowTests.test_generate_team_cover_tickets_spreads_blue_buckets`

Expected: FAIL，提示 `blue_buckets` 缺失，或 5 注蓝球全部落在同一个桶

- [ ] **Step 3: 补最小实现，接入蓝球引擎分桶与解释信息**

```python
def _build_blue_buckets(records: List[Dict], blue_scores: Dict[int, float], runtime_config: Optional[Dict[str, object]] = None) -> Dict[str, List[int]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    engine = BlueBallEngine(records, config=_runtime_blue_params(runtime))
    result = engine.predict(pool_size=int(runtime.get("cover_mode", {}).get("blue_bucket_size", 6)))
    ranked = list(result.get("pool", []))
    cold = [num for num, _miss in result.get("cold_chase", [])]
    main = ranked[:2]
    explore = [n for n in cold if n not in main][:2]
    reversion = [n for n in ranked if n not in main and n not in explore][:2]
    return {"main": main, "explore": explore, "reversion": reversion}

def _assign_cover_blue(ticket_index: int, blue_buckets: Dict[str, List[int]], used_blues: Set[int]) -> Tuple[int, str]:
    order = ["main", "explore", "reversion", "main", "explore"]
    bucket_name = order[ticket_index % len(order)]
    for candidate in blue_buckets.get(bucket_name, []):
        if candidate not in used_blues:
            return candidate, bucket_name
    for fallback_name in ["main", "explore", "reversion"]:
        for candidate in blue_buckets.get(fallback_name, []):
            if candidate not in used_blues:
                return candidate, fallback_name
    fallback = next(iter(blue_buckets.get("main", [1])), 1)
    return fallback, "main"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_build_cover_candidate_snapshot_adds_blue_buckets test_predict.PredictFlowTests.test_generate_team_cover_tickets_spreads_blue_buckets`

Expected: PASS

- [ ] **Step 5: 提交蓝球覆盖实现**

```bash
git add predict.py test_predict.py
git commit -m "feat: 新增蓝球分桶覆盖策略"
```

### Task 4: 实验回测、条件随机基准与对照报告

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`

- [ ] **Step 1: 写失败测试，锁定三组对照输出与 uplift 字段**

```python
    def test_team_cover_backtest_report_contains_three_way_comparison(self):
        records = self._build_mock_records(72)
        report = predict.team_cover_backtest_report(records, cycles=12, seed=42)
        self.assertIn("team_cover", report)
        self.assertIn("team", report)
        self.assertIn("conditional_random", report)
        self.assertIn("comparison", report)
        self.assertIn("team_cover_vs_random_uplift", report["comparison"])
        self.assertIn("team_vs_random_uplift", report["comparison"])

    def test_team_cover_backtest_report_tracks_diversity_metric(self):
        records = self._build_mock_records(72)
        report = predict.team_cover_backtest_report(records, cycles=6, seed=42)
        self.assertIn("avg_overlap", report["team_cover"])
        self.assertIn("avg_overlap", report["conditional_random"])
```

```python
    def test_render_experiment_report_includes_cover_uplift(self):
        report = analyze_archive.render_experiment_report(
            {
                "team_cover": {"avg_score": 1.80, "hit_rate_ge2": 0.60},
                "team": {"avg_score": 1.55, "hit_rate_ge2": 0.52},
                "conditional_random": {"avg_score": 1.40, "hit_rate_ge2": 0.48},
                "comparison": {
                    "team_cover_vs_random_uplift": {"avg_score": 0.40, "hit_rate_ge2": 0.12},
                    "team_vs_random_uplift": {"avg_score": 0.15, "hit_rate_ge2": 0.04},
                },
            }
        )
        self.assertIn("team_cover_vs_random_uplift", report)
        self.assertIn("avg_score=0.400000", report)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_team_cover_backtest_report_contains_three_way_comparison test_predict.PredictFlowTests.test_team_cover_backtest_report_tracks_diversity_metric test_analyze_archive.AnalyzeArchiveTests.test_render_experiment_report_includes_cover_uplift`

Expected: FAIL，提示 `team_cover_backtest_report` / `render_experiment_report` 未定义

- [ ] **Step 3: 补最小实现，输出三组对照结果**

```python
def team_cover_backtest_report(records: List[Dict], cycles: int = 36, seed: Optional[int] = None, runtime_config: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    samples = list(iterate_archived_cycles(records, cycles=cycles))
    summary = {
        "team_cover": {"samples": 0, "avg_score": 0.0, "hit_rate_ge2": 0.0, "hit_rate_ge3": 0.0, "blue_pool_hit_rate": 0.0, "avg_overlap": 0.0},
        "team": {"samples": 0, "avg_score": 0.0, "hit_rate_ge2": 0.0, "hit_rate_ge3": 0.0, "blue_pool_hit_rate": 0.0, "avg_overlap": 0.0},
        "conditional_random": {"samples": 0, "avg_score": 0.0, "hit_rate_ge2": 0.0, "hit_rate_ge3": 0.0, "blue_pool_hit_rate": 0.0, "avg_overlap": 0.0},
    }
    for sample_index, (history_timeline, target) in enumerate(samples):
        history = list(reversed(history_timeline))
        sample_seed = _stable_int_seed("team-cover-backtest", seed or 0, sample_index, target.get("period", ""))
        team_report = generate_final_team_tickets(
            build_expert_teams(history, tickets=5, seed=sample_seed),
            train_lead_agent(history, learning_cycles=min(12, len(history))),
            diff_factor=1.0,
            records=history,
            runtime_config=runtime,
            seed=sample_seed,
        )
        cover_report = generate_team_cover_tickets_from_records(history, runtime_config=runtime, seed=sample_seed)
        random_report = generate_conditional_random_tickets_from_records(history, runtime_config=runtime, seed=sample_seed)
        _accumulate_cover_metrics(summary["team"], team_report, target)
        _accumulate_cover_metrics(summary["team_cover"], cover_report, target)
        _accumulate_cover_metrics(summary["conditional_random"], random_report, target)
    comparison = {
        "team_cover_vs_random_uplift": _build_cover_uplift(summary["team_cover"], summary["conditional_random"]),
        "team_vs_random_uplift": _build_cover_uplift(summary["team"], summary["conditional_random"]),
    }
    return {**summary, "comparison": comparison}
```

```python
def render_experiment_report(report: Dict[str, object]) -> str:
    lines = ["实验模式对照结果"]
    for key in ["team_cover", "team", "conditional_random"]:
        metrics = report.get(key, {})
        lines.append(f"{key}: avg_score={metrics.get('avg_score', 0.0):.6f}, hit_rate_ge2={metrics.get('hit_rate_ge2', 0.0):.6f}, avg_overlap={metrics.get('avg_overlap', 0.0):.6f}")
    comparison = report.get("comparison", {})
    for key in ["team_cover_vs_random_uplift", "team_vs_random_uplift"]:
        uplift = comparison.get(key, {})
        lines.append(f"{key}: avg_score={uplift.get('avg_score', 0.0):.6f}, hit_rate_ge2={uplift.get('hit_rate_ge2', 0.0):.6f}")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_team_cover_backtest_report_contains_three_way_comparison test_predict.PredictFlowTests.test_team_cover_backtest_report_tracks_diversity_metric test_analyze_archive.AnalyzeArchiveTests.test_render_experiment_report_includes_cover_uplift`

Expected: PASS

- [ ] **Step 5: 提交回测与报告改动**

```bash
git add predict.py analyze_archive.py test_predict.py test_analyze_archive.py
git commit -m "feat: 新增team-cover对照回测报告"
```

### Task 5: 主流程接线、文档同步与全量验证

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\SKILL.md`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\AGENTS.md`

- [ ] **Step 1: 写失败测试，锁定 CLI 调度行为**

```python
    def test_main_dispatches_team_cover_backtest(self):
        records = self._build_mock_records(72)
        with mock.patch.object(predict, "load_data", return_value=records), \
             mock.patch.object(predict, "team_cover_backtest_report", return_value={"team_cover": {"avg_score": 1.0}, "team": {}, "conditional_random": {}, "comparison": {}}) as mocked_report, \
             mock.patch.object(sys, "argv", ["predict.py", "--team-cover-backtest", "--backtest-cycles", "12", "--seed", "42"]):
            predict.main()
        mocked_report.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest -v test_predict.PredictFlowTests.test_main_dispatches_team_cover_backtest`

Expected: FAIL，提示 `main()` 未调度 `team_cover_backtest_report`

- [ ] **Step 3: 接通 CLI，补文档，保持现有主链路兼容**

```python
# predict.py
    if args.team_cover_backtest:
        report = team_cover_backtest_report(records, cycles=args.backtest_cycles, seed=args.seed, runtime_config=runtime_config)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if args.mode == "team-cover":
        lead_model = train_lead_agent(records, learning_cycles=args.learn_cycles)
        teams = build_expert_teams(records, tickets=resolve_team_ticket_count(args.num), seed=args.seed)
        snapshot = build_cover_candidate_snapshot(teams, lead_model, diff_factor=1.0, runtime_config=runtime_config)
        tickets = generate_team_cover_tickets(snapshot, runtime_config=runtime_config, seed=args.seed)
        for index, ticket in enumerate(tickets, start=1):
            print(f"第{index}注: {' '.join(f'{n:02d}' for n in ticket['red'])} + {ticket['blue']:02d}")
        return
```

```markdown
<!-- README.md / SKILL.md / AGENTS.md 需要出现的命令 -->
- `python predict.py --mode team-cover --num 5`
- `python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42`
- `team-cover` 预测会写入 `prediction_archive`
- 验收口径为相对条件随机基准 uplift，而非绝对预测承诺
```

- [ ] **Step 4: 运行全量验证**

Run: `python -m unittest -v`

Expected: 全部 PASS

Run: `python predict.py --team-cover-backtest --backtest-cycles 12 --seed 42`

Expected: 输出 JSON，对象中包含 `team_cover`、`team`、`conditional_random`、`comparison`

Run: `python predict.py --mode team-cover --num 5 --seed 42`

Expected: 输出 5 注号码，并写入 `prediction_archive`

- [ ] **Step 5: 提交接线与文档**

```bash
git add predict.py README.md SKILL.md AGENTS.md test_predict.py
git commit -m "docs: 补充team-cover实验模式说明"
```

## Self-Review Notes

- Spec coverage:
  - 实验模式 CLI：Task 1、Task 5
  - 红球候选分布与覆盖出票：Task 2
  - 蓝球分桶覆盖：Task 3
  - 条件随机基准与对照回测：Task 4
  - 文档与现有语义清理：Task 1、Task 5
- Placeholder scan:
  - 未使用 `TODO`、`TBD`、`similar to`
  - 每个测试/实现步骤都给出具体代码与命令
- Type consistency:
  - `build_cover_candidate_snapshot()`
  - `generate_team_cover_tickets()`
  - `team_cover_backtest_report()`
  - `render_experiment_report()`
