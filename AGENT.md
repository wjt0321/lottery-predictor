# AGENT.md

本文件面向仓库内工作的 AI Agent / 自动化维护者，提供最小必要上下文。详细使用说明统一以 `README.md` 为准。

## 先看哪里

- 用户使用与完整命令：`README.md`
- Claude Code 入口：`CLAUDE.md`
- 技能触发说明：`SKILL.md`
- 本轮迭代计划：`docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`
- 历史设计文档：`docs/plans/`（护栏设计、自学习闭环、旋转矩阵出票等）

## 当前主链

- 主入口：`predict.py`
- 默认预测模式：`team`
- 专家注册表：`agent_registry.py`
- 全局配置中心：`project_config.py`（`GLOBAL_CONFIG` 单例）
- 数据源：`lottery_data.json`
- 归档目录：`prediction_archive/`
- 分析器：`analyze_archive.py`

`team` 模式当前固定 8 个专家：`hot`、`cold`、`missing`、`balanced`、`random`、`cycle`、`sum`、`zone`。

## 架构全景

```
lottery_data.json ──→ predict.py (team 模式主链路)
                        │
                        ├── 1. _load_patches(): 自动加载三类补丁
                        ├── 2. differential_learning(): 专家权重回测学习
                        ├── 3. 8 专家提案
                        ├── 4. build_core_pool_snapshot(): 聚合红球池(22球)+蓝球池(10球)
                        │       └── 位置权重在此阶段作用于红球评分
                        ├── 5. _build_debate_pool(): 反共识辩论（专家评估被排除的11球→重排名）
                        ├── 6. BlueBallEngine.predict(): 蓝球多维度打分
                        ├── 7. _build_blue_debate(): 蓝球反共识辩论（低分蓝球"偏科"晋升）
                        ├── 8. generate_rotation_matrix_tickets(): 旋转矩阵 22红→5注6+1
                        └── 9. 归档写入 prediction_archive/YYYYXXX.txt

prediction_archive/ ──→ analyze_archive.py
                           ├── 读归档 + lottery_data.json 真实结果回填
                           └── 导出三类补丁 → config/*.latest.json (回灌)
```

**自学习闭环**: `predict → archive → analyze → patches → predict`

## 核心模块职责

| 文件 | 角色 | 关键点 |
|------|------|--------|
| `predict.py` | 主入口 (~3500行) | team/single/team-cover 三种模式；回测；补丁回灌；反共识辩论 |
| `project_config.py` | **全局配置中心** | `ProjectConfig` dataclass → `to_runtime_config()` 生成 pool/fusion/matrix/blue/cover 五组参数 |
| `agent_registry.py` | 专家注册表 | 8 专家固定集合，不含 lstm |
| `blue_ball_engine.py` | 蓝球独立引擎 | 7 维度分析（遗漏/奇偶/区间/振幅/热度/移动平均/贝叶斯）；通过 config dict 接收参数 |
| `analyze_archive.py` | 离线分析器 | 读归档 KV 格式 → 回填真实结果 → 三类补丁 + CSV/JSON 报告 |
| `enhanced_analysis.py` | 增强分析 | 奖池影响、扩展数据融合权重 |
| `feature_importance.py` | 特征重要性 | Pearson/Spearman 相关系数，零额外依赖 |
| `visual_analyzer.py` | 可视化 | matplotlib 图表生成（可选依赖） |
| `update_data.py` | 数据更新 | Playwright + BeautifulSoup 从 500.com 抓取 |
| `manual_data_import.py` | 手动导入 | JSON/CSV/TXT 外部数据导入 |

## predict.py 关键内部函数

team 模式核心调用链：

```
run_team_mode()
  ├── _load_patches()              # 自动发现 weight/matrix/param 补丁
  ├── differential_learning()      # 专家权重回测学习
  ├── [8 个 agent_*_propose()]     # 各专家独立提案
  ├── build_core_pool_snapshot()   # 加权聚合 + 位置权重评分
  ├── _build_debate_pool()         # 反共识辩论：专家评估排除的11球→合并重排名
  ├── BlueBallEngine(records, blue_params).predict()  # 蓝球打分
  ├── _build_blue_debate()         # 蓝球辩论：低分蓝球偏科晋升
  ├── generate_rotation_matrix_tickets()  # 22红→5注6+1
  │     └── _select_blue_ball_for_row()   # 蓝球去重选择
  └── _archive_prediction()        # 写入归档
```

回测入口：`_run_team_backtest()` / `_run_team_cover_backtest()`

## 配置系统

`project_config.py::ProjectConfig` 是唯一配置来源：

- **核心池**: `core_red_pool_size=22`, `core_blue_pool_size=10`, `rotation_matrix_type="22_red_cover_6_to_5"`
- **出票**: `team_ticket_count=5`, `ticket_decay_step=0.06`, `min_ticket_decay=0.55`
- **辩论**: `debate_factor=0.6`，控制反共识辩论影响力
- **学习**: `learning_rate=0.25`, `decay_gamma=0.85`, `default_learn_cycles=30`
- **蓝球**: 全部 `blue_*` 参数通过 `to_runtime_config()["blue_params"]` 传入 `BlueBallEngine`
- **位置权重**: `pos_weight_min=0.6`, `pos_weight_max=1.5`

三类补丁覆盖范围：
- `weight_patch`：8 专家基础权重增减
- `matrix_patch`：矩阵 `preferred_rows` / `row_weights`
- `param_patch`：pool / fusion / matrix / blue / cover 任意子集

## 补丁回灌优先级

```
weight_patch:  --weight-patch 显式路径 > config/weight_patch.latest.json > 不加载
matrix_patch:  config/matrix_patch.latest.json (自动发现) > 内置默认
param_patch:   config/param_patch.latest.json (自动发现) > ProjectConfig 默认值
```

补丁文件缺失不阻断预测，自动回退。

## 测试结构

| 文件 | 测试内容 |
|------|----------|
| `test_predict.py` | predict.py 核心流程 (PredictFlowTests) |
| `test_blue_engine.py` | BlueBallEngine 蓝球引擎 |
| `test_analyze_archive.py` | analyze_archive.py 归档分析 |
| `test_update_data.py` | update_data.py 数据更新 |

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
- 不要覆盖同期已有归档；重复预测必须追加时间戳（格式 `YYYYXXX_timestamp.txt`）。
- 不要无说明改回随机拆票或可变注数（team 模式固定 5 注）。
- 不要恢复 `LSTM/TensorFlow` 或重新引入 `lstm` 专家，除非用户明确要求。

## 修改时同步检查

- 改专家集合：同时检查 `predict.py`、`analyze_archive.py`、`agent_registry.py`、`README.md`、`SKILL.md`
- 改 CLI / 补丁 / 输出行为：同步更新 `README.md`、`CLAUDE.md`、`AGENTS.md`、`SKILL.md`
- 改 `project_config.py`：同步检查 `blue_ball_engine.py`、`to_runtime_config()` 输出、`param_patch` 回灌路径
- 改 `BlueBallEngine` 参数：同步 `project_config.py` 的 `blue_*` 字段和 `to_runtime_config()["blue_params"]`
- 改端到端回测：同步检查 `README.md` 中的命令示例与指标描述

## 常用验证

```bash
# 全量测试
python -m unittest -v

# 单个测试文件
python -m unittest test_predict -v
python -m unittest test_blue_engine -v
python -m unittest test_analyze_archive -v

# 单条用例
python -m unittest test_predict.PredictFlowTests.test_agent_teams_excludes_lstm -v

# 功能验证
python predict.py --mode team --num 5 --seed 42
python predict.py --mode team-cover --num 5 --seed 42
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
```
