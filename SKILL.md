---
name: lottery-predictor
description: Use when user asks for 双色球/Double Color Ball prediction, 推荐号, 更新开奖数据, 回测, 归档分析, 补丁回灌, 或直接运行 lottery-predictor-main 项目命令。
---

# 双色球彩票预测器

## 用途

- 用于双色球娱乐预测、趋势分析、开奖数据更新、端到端回测、归档分析和补丁回灌
- 默认优先 `team` 模式
- 仅供娱乐，不构成任何投注建议

## 触发场景

- 用户要预测下一期号码或给几注推荐号
- 用户要更新开奖数据或检查数据是否过期
- 用户要分析热冷号、遗漏、团队权重、矩阵表现
- 用户要导出 / 应用 `weight`、`matrix`、`param` 补丁
- 用户要运行这个项目、执行回测、运行 `team-cover` 实验模式、更新相关文档

## 用户可能会这样说

- “帮我预测下一期双色球”
- “给我来 5 注双色球推荐号”
- “跑一下 team 模式预测”
- “更新一下双色球开奖数据”
- “帮我检查本地开奖数据是不是过期了”
- “跑一下 36 期回测”
- “分析 prediction_archive，看最近命中情况”
- “把最新补丁导出来并写回配置”
- “帮我看看矩阵行表现和专家权重”
- “直接运行这个彩票预测项目”

## 当前要点

- `team` 模式固定输出 `5` 注 `6+1`
- 位置权重已前移到核心池评分阶段
- `blue_params` 会进入 `BlueBallEngine`
- `row_weights` 表示动态排序，不表示真实淘汰
- `--team-backtest` 会输出进度和最终 5 注口径指标
- `--mode team-cover` 固定输出 `5` 注实验票，并写入 `prediction_archive`
- `--team-cover-backtest` 会输出 `team_cover` / `team` / `conditional_random` 三组对照指标与 uplift

## 最小命令集

- 更新数据：`python update_data.py`
- 团队预测：`python predict.py --mode team --num 5`
- 实验出票：`python predict.py --mode team-cover --num 5 --seed 42`
- 端到端回测：`python predict.py --team-backtest --backtest-cycles 36 --seed 42`
- 实验对照回测：`python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42`
- 归档分析：`python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`
- 全量测试：`python -m unittest -v`

## 典型执行路径

- 日常预测：先检查 / 更新数据，再运行 `team` 模式预测
- 覆盖实验：运行 `--mode team-cover --num 5`，查看实验票输出并确认已归档
- 性能或效果验证：运行 `--team-backtest --backtest-cycles 36 --seed 42`
- 覆盖实验验证：运行 `--team-cover-backtest --backtest-cycles 36 --seed 42`
- 学习闭环：分析 `prediction_archive`，导出报告和三类补丁
- 迭代开发：修改代码后优先跑 `python -m unittest -v`

## 运行约束

- 权重补丁：`--weight-patch` 显式路径 > `config/weight_patch.latest.json` > 不加载
- 参数补丁：默认自动尝试 `config/param_patch.latest.json`
- 矩阵补丁：默认自动尝试 `config/matrix_patch.latest.json`
- 数据过期时，预测会阻断并提示先运行 `python update_data.py`
- 归档文件保留 `ticketN_explain_json` 与 `lead_summary`
- `team-cover` 预测会写入 `prediction_archive`；`team-cover-backtest` 只读历史数据且不写归档

## 不要使用本技能的场景

- 用户讨论的是其他彩票、股票、基金、加密货币或体育博彩项目
- 用户只是在问通用 Python / Git / Markdown 问题，且与本仓库无关
- 用户没有要预测、更新数据、回测、分析归档、运行本项目中的任何需求
- 用户只想编辑与本项目无关的文档或代码

## 识别优先级提示

- 只要用户明确提到“双色球”“推荐号”“开奖数据”“回测”“prediction_archive”“weight patch / matrix patch / param patch”，优先考虑本技能
- 只要用户是在 `lottery-predictor-main` 仓库里要求执行命令、改代码、查结果，也优先考虑本技能
- 若用户提到“卡住了”“没输出”“跑回测很慢”，通常对应 `predict.py --team-backtest` 或 `python predict.py --team-cover-backtest`

## Example

### Example 1
- 用户：“帮我预测下一期双色球，给我 5 注号码。”
- 应触发：运行本技能，优先使用 `team` 模式，必要时先检查数据是否过期。

### Example 2
- 用户：“更新一下开奖数据，然后帮我跑一次团队预测。”
- 应触发：运行本技能，依次执行 `python update_data.py` 和 `python predict.py --mode team --num 5`。

### Example 3
- 用户：“帮我跑 36 期回测，我看之前像卡住了一样。”
- 应触发：运行本技能，使用 `python predict.py --team-backtest --backtest-cycles 36 --seed 42`，并关注进度输出、耗时和最终指标。

### Example 4
- 用户：“帮我跑一下 team-cover 对照回测，别写归档。”
- 应触发：运行本技能，使用 `python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42`，并确认输出三组对照指标与 uplift。

### Example 5
- 用户：“分析一下 prediction_archive，把最新补丁写回 config。”
- 应触发：运行本技能，调用 `analyze_archive.py` 导出报告并写回 `weight patch`、`matrix patch`、`param patch`。

### Example 6
- 用户：“帮我看看最近矩阵行表现和专家权重，为什么命中率这么低？”
- 应触发：运行本技能，优先阅读归档分析结果、矩阵补丁、权重补丁和 team 回测指标。

### Example 7
- 用户：“在 lottery-predictor-main 里帮我修一下回测没输出的问题。”
- 应触发：运行本技能，因为这是本仓库内的回测链路与 CLI 行为问题。

## 详细文档

- 完整使用说明：[`README.md`](./README.md)
- 仓库内维护说明：[`AGENT.md`](./AGENT.md)
- 命中率改进计划：[`docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`](./docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md)
