# CLAUDE.md

This file gives Claude Code the minimum context needed to work in this repository. Use `README.md` as the human-facing source of truth.

## 交流语言

**必须使用中文与用户交流。** 解释、确认、建议统一用中文；代码注释、变量名、commit message 保持英文。

## 先看哪里

- 用户使用与完整命令：`README.md`
- 仓库内维护说明：`AGENT.md`
- 技能触发说明：`SKILL.md`
- 本轮迭代计划：`docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`

## 仓库最小上下文

- 项目性质：双色球娱乐预测与回测实验工具，不构成投注建议
- 主入口：`predict.py`
- 默认主链：`team` 模式
- 归档分析：`analyze_archive.py`
- 专家注册表：`agent_registry.py`
- 当前补丁入口：`config/weight_patch.latest.json`、`config/matrix_patch.latest.json`、`config/param_patch.latest.json`

## 当前行为摘要

- `team` 模式固定输出 `5` 注 `6+1`
- 核心流程：专家提案 -> 核心池 -> 旋转矩阵出票 -> 归档
- 位置权重已前移到核心池评分，不再只是矩阵行内排序
- `blue_params` 会进入 `BlueBallEngine`，并可被 `param patch` 覆盖
- `row_weights` 会影响默认矩阵行顺序；当前语义是“动态排序”，不是“动态淘汰”
- `--team-backtest` 已支持进度输出与最终 5 注口径指标

## 不要破坏的约束

- 不要把项目描述成真实投资或保证中奖工具
- 不要绕过开奖数据新鲜度保护，除非用户明确要求离线实验
- 不要覆盖同期旧归档；重复预测必须使用时间戳文件名
- 不要无说明改回随机拆票或可变注数
- 不要恢复 `LSTM/TensorFlow` 或重新引入 `lstm` 专家

## 高频命令

```bash
python update_data.py
python predict.py --mode team --num 5
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
python -m unittest -v
```

## 修改后同步检查

- 改专家集合：同步 `predict.py`、`analyze_archive.py`、`agent_registry.py`
- 改 CLI / 输出 / 补丁行为：同步 `README.md`、`SKILL.md`、`AGENTS.md`
- 改 `project_config.py`：同步检查 `blue_ball_engine.py`
- 改回测口径：同步检查 `README.md` 中的命令示例与指标描述
