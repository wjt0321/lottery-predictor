# Rotation Matrix Ticketing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在团队模式中引入“核心号码池 + 旋转矩阵出票”层，固定只输出 5 注 6+1 号码，尽量保留专家聚合号码池的价值。

**Architecture:** 8 位专家先输出候选提案，主代理不再逐注随机拆票，而是先汇总成 10 个核心红球池和少量蓝球候选池。随后使用固定的 5 行旋转矩阵模板，将 10 红球压缩成 5 注 6 红组合，并为每一注附带矩阵行与号码池解释信息。

**Tech Stack:** Python 3, unittest, argparse, json, collections, random

---

### Task 1: 锁定 5 注固定出票与矩阵模板行为

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_resolve_team_ticket_count_is_fixed_to_five(self):
    ...

def test_generate_rotation_matrix_tickets_uses_pool_of_ten(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_resolve_team_ticket_count_is_fixed_to_five test_predict.PredictFlowTests.test_generate_rotation_matrix_tickets_uses_pool_of_ten -v`
Expected: FAIL because the helper and matrix layer do not exist yet.

**Step 3: Write minimal implementation**

```python
TEAM_TICKET_COUNT = 5
ROTATION_MATRIX_ROWS = (...)
```

**Step 4: Run focused tests**

Run: same command as Step 2
Expected: PASS

### Task 2: 构建核心号码池聚合层

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_build_core_pool_snapshot_collects_top10_red_pool(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_build_core_pool_snapshot_collects_top10_red_pool -v`
Expected: FAIL because the pool snapshot helper does not exist yet.

**Step 3: Write minimal implementation**

```python
def build_core_pool_snapshot(...):
    ...
```

**Step 4: Run focused tests**

Run: same command as Step 2
Expected: PASS

### Task 3: 接入 team 模式并扩展归档解释

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_generate_team_matrix_tickets_builds_archive_ready_payload(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_generate_team_matrix_tickets_builds_archive_ready_payload -v`
Expected: FAIL because team mode still uses per-ticket weighted sampling.

**Step 3: Write minimal implementation**

```python
def generate_team_matrix_tickets(...):
    ...
```

**Step 4: Run focused tests**

Run: same command as Step 2
Expected: PASS

### Task 4: 验证真实输出

**Files:**
- Modify: none
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Run full test suite**

Run: `python -m unittest -v`
Expected: PASS

**Step 2: Run one real prediction**

Run: `python predict.py --mode team --num 9`
Expected: despite requested 9, final output is still fixed to 5 注，且每注解释包含矩阵信息。
