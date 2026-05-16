# Hit Rate Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成蓝球链路、端到端回测、矩阵权重与位置权重的整轮迭代，并保持默认 team 模式兼容。

**Architecture:** 先打通蓝球配置与蓝球去重，再建立 team 端到端回测口径，随后让矩阵权重生效，最后把位置权重前移到核心池评分。所有改动都围绕现有 `team -> core_pool -> rotation_matrix -> archive` 主链做增量演进。

**Tech Stack:** Python 3、unittest、JSON 配置补丁、命令行接口

---

### Task 1: 蓝球链路测试与实现

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_blue_engine.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\project_config.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`

- [ ] Step 1: 为 `blue_params` 回灌与蓝球去重补测试
- [ ] Step 2: 运行定向测试确认失败
- [ ] Step 3: 实现运行时 `blue_params` 与可复现蓝球选择
- [ ] Step 4: 重新运行定向测试确认通过

### Task 2: team 端到端回测测试与实现

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`

- [ ] Step 1: 为 `team_matrix_backtest_report()` 和 CLI 行为补测试
- [ ] Step 2: 运行定向测试确认失败
- [ ] Step 3: 实现端到端回测与 CLI 参数
- [ ] Step 4: 重新运行定向测试确认通过

### Task 3: 矩阵权重与位置权重测试与实现

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_analyze_archive.py`

- [ ] Step 1: 为 `row_weights` 默认排序和位置权重前移补测试
- [ ] Step 2: 运行定向测试确认失败
- [ ] Step 3: 实现矩阵权重生效与位置权重前移
- [ ] Step 4: 重新运行定向测试确认通过

### Task 4: 文档与全量验证

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\README.md`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\analyze_archive.py`

- [ ] Step 1: 更新 README 与分析器文案
- [ ] Step 2: 运行 `python -m unittest -v`
- [ ] Step 3: 运行 `python predict.py --team-backtest --backtest-cycles 36 --seed 42`
- [ ] Step 4: 运行 `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`
