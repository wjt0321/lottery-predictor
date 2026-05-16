# AGENT.md

本文件面向仓库内工作的 AI Agent / 自动化维护者，提供最小必要上下文。详细使用说明统一以 `README.md` 为准。

## 先看哪里

- 用户使用与完整命令：`README.md`
- Claude Code 入口：`CLAUDE.md`
- 技能触发说明：`SKILL.md`
- 本轮迭代计划：`docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`

## 当前主链

- 主入口：`predict.py`
- 默认预测模式：`team`
- 专家注册表：`agent_registry.py`
- 数据源：`lottery_data.json`
- 归档目录：`prediction_archive/`
- 分析器：`analyze_archive.py`

`team` 模式当前固定 8 个专家：`hot`、`cold`、`missing`、`balanced`、`random`、`cycle`、`sum`、`zone`。

## 当前行为要点

- `team` 模式固定输出 `5` 注 `6+1`。
- 核心流程是：专家提案 -> `build_core_pool_snapshot()` -> `generate_rotation_matrix_tickets()`。
- 位置权重已前移到核心池评分阶段，影响 `red_pool` 候选集合。
- `matrix_patch.row_weights` 会影响默认 `row_order`；若有 `preferred_rows`，以显式顺序为主。
- 蓝球参数统一通过 `blue_params` 进入 `BlueBallEngine`。
- `--team-backtest` 会输出最终 5 注口径指标，并在运行时打印进度。

## 硬约束

- 不要把项目描述为真实投资、收益或保证中奖工具。
- 不要绕过数据新鲜度保护，除非用户明确要求离线实验。
- 不要覆盖同期已有归档；重复预测必须追加时间戳。
- 不要无说明改回随机拆票或可变注数。
- 不要恢复 `LSTM/TensorFlow` 或重新引入 `lstm` 专家，除非用户明确要求。

## 修改时同步检查

- 改专家集合：同时检查 `predict.py`、`analyze_archive.py`、`agent_registry.py`、`README.md`、`SKILL.md`
- 改 CLI / 补丁 / 输出行为：同步更新 `README.md`、`CLAUDE.md`、`AGENTS.md`
- 改 `project_config.py`：同步检查 `blue_ball_engine.py` 与 `param patch` 回灌
- 改端到端回测：同步检查 `README.md` 中的命令示例与指标描述

## 常用验证

```bash
python -m unittest -v
python predict.py --mode team --num 5 --seed 42
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
```
