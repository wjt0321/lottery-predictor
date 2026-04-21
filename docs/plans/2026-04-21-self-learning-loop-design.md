# Self-Learning Loop Design Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 移除 LSTM/TensorFlow 依赖，并将项目演进为基于归档回测、专家加权和参数自适应的真正自学习闭环。

**Architecture:** 预测层保留可解释的规则型专家，学习层不再直接预测号码，而是利用真实开奖结果对每个专家和参数组做逐期评分。评分结果写入归档分析，汇总成权重补丁与参数补丁，下一期预测时自动回灌，形成“预测 -> 开奖 -> 评分 -> 调参 -> 再预测”的闭环。

**Tech Stack:** Python 3, unittest, argparse, json, datetime, collections

---

## 目标架构

### 1. 预测层
- 专家集合固定为：`hot`、`cold`、`missing`、`balanced`、`random`、`cycle`、`sum`、`zone`
- 每个专家输出：
  - 候选红球/蓝球
  - 专家解释信息
  - 可调参数快照（窗口期、阈值、权重）
- 主代理只做两件事：
  - 根据近期表现分配专家权重
  - 根据多样性约束融合多注结果

### 2. 评分层
- 真实开奖写入后，对上一期归档逐个专家评分
- 评分不追求“是否中奖”，而追求稳定的统计目标：
  - 红球命中数
  - 蓝球命中
  - 红球 `2+` 命中率
  - 红球 `3+` 命中率
  - 多注覆盖率
- 评分结果同时保留：
  - 全历史累计分
  - 最近 N 期分
  - 时间衰减分
  - 稳定度惩罚

### 3. 学习层
- 学习对象不是“下期号码”，而是：
  - 专家基础权重
  - 热号窗口、冷号窗口
  - 遗漏排序阈值
  - 和值范围宽度
  - 分区平衡强度
  - 多样性惩罚系数
- 输出两个补丁文件：
  - `weight_patch.latest.json`
  - `param_patch.latest.json`

### 4. 闭环流程
1. `python update_data.py`
2. 用最新真实数据校验上一期预测归档
3. 运行归档分析器生成新权重/参数补丁
4. `python predict.py --mode team`
5. 将本期专家提案、融合结果、参数快照继续归档

---

## 数据设计

### 归档增强字段
- `lead_summary`: 保留总览
- `ticketN_explain_json`: 保留每球来源
- 新增建议字段：
  - `ticketN_agent_scores_snapshot`
  - `ticketN_param_snapshot`
  - `learning_context`

### 新增补丁文件
- `config/param_patch.latest.json`

建议结构：

```json
{
  "strategy_params": {
    "hot": {"recent_periods": 36},
    "cold": {"recent_periods": 48},
    "missing": {"top_k": 12},
    "sum": {"sigma_scale": 0.9},
    "zone": {"target_bias": 1.15}
  },
  "fusion_params": {
    "diversity_penalty": 0.62,
    "agreement_bonus_red": 0.08,
    "agreement_bonus_blue": 0.10
  }
}
```

---

## 实施任务

### Task 1: 通过测试锁定“无 LSTM”行为

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_agent_teams_excludes_lstm(self):
    ...

def test_single_mode_choices_no_longer_accept_lstm(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_agent_teams_excludes_lstm -v`
Expected: FAIL because `lstm` is still present.

**Step 3: Write minimal implementation**

```python
# 在 predict.py 中移除 lstm 触点
```

**Step 4: Run focused tests**

Run: `python -m unittest test_predict.PredictFlowTests.test_agent_teams_excludes_lstm -v`
Expected: PASS

### Task 2: 移除 LSTM 代码、文档与依赖入口

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Delete: `c:\Users\wxb\.claude\skills\lottery-predictor-main\lstm_predictor.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_predict_module_import_has_no_tensorflow_side_effect(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.py -v`
Expected: FAIL until code and docs are updated.

**Step 3: Write minimal implementation**

```python
# 删除 LSTM import、策略分支、CLI 选项与文档说明
```

**Step 4: Run focused tests**

Run: `python -m unittest test_predict.py -v`
Expected: PASS

### Task 3: 为自学习闭环准备设计落点

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Create: `c:\Users\wxb\.claude\skills\lottery-predictor-main\docs\plans\2026-04-21-self-learning-loop-design.md`

**Step 1: Document the loop**

```text
预测 -> 归档 -> 开奖校验 -> 评分 -> 权重/参数补丁 -> 下一期预测
```

**Step 2: Verify consistency**

Run: manual read-through
Expected: README and design document no longer mention LSTM as active strategy.

### Task 4: 全量验证

**Files:**
- Modify: none
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Run full test suite**

Run: `python -m unittest -v`
Expected: PASS

**Step 2: Run one real prediction**

Run: `python predict.py --mode team --num 3`
Expected: no TensorFlow warning, no `lstm` agent in report, prediction completes.
