# Matrix Learning And Param Patch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为彩票预测项目补齐矩阵行表现学习、`matrix_patch.latest.json`、`param_patch.latest.json` 与 `predict.py` 自动回灌能力，形成“专家权重 + 矩阵位形 + 参数补丁”联合学习闭环。

**Architecture:** `analyze_archive.py` 继续作为离线学习器，新增对 `ticketN_explain_json.matrix` 与 `core_pool` 的解析统计，输出矩阵行表现分析和两个新补丁文件。`predict.py` 在 team 模式加载补丁时，不只读取专家权重，还自动读取矩阵补丁和参数补丁，将核心池大小、蓝球池大小、专家提案衰减、矩阵行选择权重等参数回灌到出票流程中。

**Tech Stack:** Python 3, unittest, argparse, json, csv, collections, datetime

---

### Task 1: 矩阵行命中表现分析

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

**Step 1: Write the failing test**

```python
def test_build_matrix_row_ranking_aggregates_hit_metrics(self):
    records = [...]
    ranking = analyze_archive.build_matrix_row_ranking(records)
    assert ranking[0]["row_id"] == 1
    assert "red_hit_avg" in ranking[0]
    assert "hit_rate_ge2" in ranking[0]
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_matrix_row_ranking_aggregates_hit_metrics -v`
Expected: FAIL because matrix-row analysis helper does not exist yet.

**Step 3: Write minimal implementation**

```python
def build_matrix_row_ranking(records):
    ...
```

Implementation notes:
- 统计 `payload["matrix"]["row_id"]`
- 支持从 `payload` 读取：
  - `actual_result.red_hits`
  - `actual_result.blue_hit`
  - `actual_result.hit_score`
- 如果某些旧归档没有 `actual_result`，要安全跳过，不报错
- 输出字段至少包含：
  - `row_id`
  - `matrix_type`
  - `samples`
  - `red_hit_avg`
  - `blue_hit_rate`
  - `hit_rate_ge2`
  - `hit_rate_ge3`
  - `avg_score`

**Step 4: Run focused tests**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_matrix_row_ranking_aggregates_hit_metrics -v`
Expected: PASS

### Task 2: 导出 `matrix_patch.latest.json`

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

**Step 1: Write the failing test**

```python
def test_build_matrix_patch_payload_exports_row_weights(self):
    ranking = [...]
    payload = analyze_archive.build_matrix_patch_payload(ranking)
    assert payload["matrix_type"] == "10_red_guard_6_to_5"
    assert "row_weights" in payload
    assert set(payload["row_weights"].keys()) == {"1", "2", "3", "4", "5"}
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_matrix_patch_payload_exports_row_weights -v`
Expected: FAIL because matrix patch exporter does not exist yet.

**Step 3: Write minimal implementation**

```python
def build_matrix_patch_payload(matrix_ranking):
    ...
```

Implementation notes:
- 归一化行权重，防止总和不为 1
- 输出建议字段：
  - `version`
  - `matrix_type`
  - `row_weights`
  - `row_scores`
  - `origin`
- 在 `export_reports()` 中新增导出：
  - `<prefix>.matrix_patch.json`
- 新增写回函数：
  - `write_latest_matrix_patch(..., latest_patch_path="config/matrix_patch.latest.json")`

**Step 4: Run focused tests**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_matrix_patch_payload_exports_row_weights -v`
Expected: PASS

### Task 3: 导出 `param_patch.latest.json`

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

**Step 1: Write the failing test**

```python
def test_build_param_patch_payload_exports_fusion_and_pool_params(self):
    records = [...]
    payload = analyze_archive.build_param_patch_payload(records)
    assert "fusion_params" in payload
    assert "pool_params" in payload
    assert "matrix_params" in payload
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_param_patch_payload_exports_fusion_and_pool_params -v`
Expected: FAIL because param patch exporter does not exist yet.

**Step 3: Write minimal implementation**

```python
def build_param_patch_payload(records, matrix_ranking):
    ...
```

Implementation notes:
- 第一版不要做复杂机器学习，只导出可解释的建议参数
- 建议覆盖：
  - `pool_params.core_red_pool_size`
  - `pool_params.core_blue_pool_size`
  - `fusion_params.ticket_decay_step`
  - `fusion_params.min_ticket_decay`
  - `matrix_params.preferred_rows`
  - `matrix_params.matrix_type`
- 依据：
  - 归档中的 `core_pool.red_pool`
  - `matrix.row_id`
  - `actual_result`
  - 多样性替换触发率

**Step 4: Run focused tests**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests.test_build_param_patch_payload_exports_fusion_and_pool_params -v`
Expected: PASS

### Task 4: `predict.py` 自动加载参数补丁

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_load_param_patch_merges_runtime_defaults(self):
    payload = ...
    loaded = predict.load_param_patch(path)
    assert loaded["pool_params"]["core_red_pool_size"] == 10

def test_generate_rotation_matrix_tickets_respects_matrix_row_weights(self):
    snapshot = ...
    config = ...
    tickets = predict.generate_rotation_matrix_tickets(snapshot, runtime_config=config)
    assert len(tickets) == 5
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_load_param_patch_merges_runtime_defaults test_predict.PredictFlowTests.test_generate_rotation_matrix_tickets_respects_matrix_row_weights -v`
Expected: FAIL because `predict.py` does not load param patches or matrix patches yet.

**Step 3: Write minimal implementation**

```python
DEFAULT_RUNTIME_CONFIG = {...}

def load_param_patch(...):
    ...

def load_matrix_patch(...):
    ...

def resolve_runtime_config(...):
    ...
```

Implementation notes:
- 自动发现链建议为：
  - `--weight-patch` 显式路径只处理权重补丁
  - `config/param_patch.latest.json`
  - `config/matrix_patch.latest.json`
- `build_core_pool_snapshot()` 读取：
  - `core_red_pool_size`
  - `core_blue_pool_size`
  - `ticket_decay_step`
  - `min_ticket_decay`
- `generate_rotation_matrix_tickets()` 读取：
  - `matrix_type`
  - `row_weights`
  - `preferred_rows`
- 第一版可以只支持当前 `10_red_guard_6_to_5`

**Step 4: Run focused tests**

Run: `python -m unittest test_predict.PredictFlowTests.test_load_param_patch_merges_runtime_defaults test_predict.PredictFlowTests.test_generate_rotation_matrix_tickets_respects_matrix_row_weights -v`
Expected: PASS

### Task 5: 全量验证与真实回路检查

**Files:**
- Modify: none
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

**Step 1: Run full test suite**

Run: `python -m unittest -v`
Expected: PASS

**Step 2: Generate all three latest patches**

Run: `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`
Expected:
- 生成 `.weight_patch.json`
- 生成 `.matrix_patch.json`
- 生成 `.param_patch.json`

**Step 3: Write latest patches**

Run: `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report --latest-patch-path config/weight_patch.latest.json`
Expected:
- `config/weight_patch.latest.json`
- `config/matrix_patch.latest.json`
- `config/param_patch.latest.json`

**Step 4: Run one real prediction with auto-loaded patches**

Run: `python predict.py --mode team --num 5`
Expected:
- 自动读取最新权重/矩阵/参数补丁
- 仍输出固定 5 注
- 终端输出包含补丁来源说明
