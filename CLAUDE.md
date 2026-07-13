# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
Use `README.md` as the human-facing source of truth.

## 交流语言

**必须使用中文与用户交流。** 解释、确认、建议统一用中文；代码注释、变量名、commit message 保持英文。

## 架构全景

```
lottery_data.json ──→ predict.py (team 模式主链路)
                        │
                        ├── 1. 差异学习: 专家权重回测学习
                        ├── 2. 8 专家提案: hot/cold/missing/balanced/random/cycle/sum/zone
                        ├── 3. build_core_pool_snapshot(): 聚合红球池(22球) + 蓝球池(10球)
                        │       └── 位置权重在此阶段作用于红球评分
                        ├── 4. BlueBallEngine.predict(): 独立蓝球引擎多维度打分
                        │       └── 参数入口: project_config.py → to_runtime_config() → param_patch 覆盖
                        ├── 5. _build_debate_pool(): 反共识辩论回合
                        │       └── 专家重新评估被排除的11球 → 合并重排名 → 可能晋升/降级
                        ├── 6. _build_blue_debate(): 蓝球反共识辩论
                        │       └── 低分蓝球某维度突出者可晋升入池
                        ├── 7. generate_rotation_matrix_tickets(): 旋转矩阵 22红→5注6+1
                        │       └── row_weights 影响行顺序(动态排序，非淘汰)
                        └── 8. 写入 prediction_archive/YYYYXXX.txt

prediction_archive/ ──→ analyze_archive.py
                           │
                           ├── 读归档 + lottery_data.json 真实结果回填
                           ├── 输出: 贡献排行 / 双视角差异 / 矩阵行表现 / 建议权重
                           └── 导出三类补丁 → config/*.latest.json (回灌到下次预测)
```

**自学习闭环**: `predict → archive → analyze → patches → predict`

## 核心模块职责

| 文件 | 角色 | 关键点 |
|------|------|--------|
| `predict.py` | 主入口 (~3500行) | team/single/team-cover 三种模式；回测；补丁回灌；反共识辩论 |
| `project_config.py` | **全局配置中心** | `ProjectConfig` dataclass → `to_runtime_config()` 生成 pool/fusion/matrix/blue/cover 五组参数；`GLOBAL_CONFIG` 单例 |
| `agent_registry.py` | 专家注册表 | `AGENT_TEAMS = (hot, cold, missing, balanced, random, cycle, sum, zone)`，不含 lstm |
| `blue_ball_engine.py` | 蓝球独立引擎 | 7 维度分析：遗漏/奇偶/区间转移/振幅/热度/移动平均/贝叶斯；通过 `config` dict 接收参数 |
| `analyze_archive.py` | 离线分析器 | 读归档 KV 格式，回填真实开奖结果，生成三类补丁和 CSV/JSON 报告 |
| `enhanced_analysis.py` | 增强分析 | 奖池影响分析、扩展数据融合权重 |
| `feature_importance.py` | 特征重要性 | Pearson/Spearman 相关系数，零额外依赖 |
| `visual_analyzer.py` | 可视化 | matplotlib 图表生成（可选依赖） |
| `update_data.py` | 数据更新 | Playwright + BeautifulSoup 从 500.com 抓取，增量合并 |
| `manual_data_import.py` | 手动导入 | JSON/CSV/TXT 外部数据导入 |

## predict.py 关键内部函数

team 模式核心调用链：

```
main() → run_team_mode()
  ├── _load_patches()              # 自动发现并加载 weight/matrix/param 三类补丁
  ├── differential_learning()      # 专家权重回测学习，学习率/衰减由 config 控制
  ├── [8 个 agent_*_propose()]     # 各专家独立提案，返回 (red_candidates, blue_candidates)
  ├── build_core_pool_snapshot()   # 加权聚合红球池 + 位置权重评分，输出 ranked_red_pool
  ├── _build_debate_pool()         # 反共识辩论：专家评估11个被排除球 → 合并重排名取22
  ├── BlueBallEngine(records, blue_params).predict()  # 蓝球多维度打分
  ├── _build_blue_debate()         # 蓝球辩论：低分蓝球"偏科"强项晋升
  ├── generate_team_matrix_tickets()      # 旋转矩阵 + 第5注科学偏移
  │     ├── _build_offset_candidate_profiles() # 全33红球独立反证画像
  │     ├── _select_scientific_offset_reds()   # 第5注偏移球约束组合搜索
  │     └── _select_blue_ball_for_row()        # 每行选蓝球，优先去重
  └── _archive_prediction()        # 写入 prediction_archive/YYYYXXX.txt
```

回测调用链：
```
--team-backtest → _run_team_backtest()
  └── walk-forward: 对每期历史快照，运行完整 team 管线 → 对比真实结果 → 汇总指标

--team-cover-backtest → _run_team_cover_backtest()
  └── 三链路并排: team_cover / team / conditional_random → uplift 对比
```

## 配置系统

`project_config.py::ProjectConfig` 是唯一配置来源，关键默认值：

- **核心池**: `core_red_pool_size=22`, `core_blue_pool_size=10`, `rotation_matrix_type=”22_red_cover_6_to_5”`
- **出票**: `team_ticket_count=5`, `ticket_decay_step=0.06`, `min_ticket_decay=0.55`, `anti_ticket_red_count=2`；第5注默认 `anti_ticket_strategy="scientific"`，保留4个核心并从独立反证候选中约束选择2个偏移球
- **辩论**: `debate_factor=0.6`，控制反共识辩论影响力（越高反共识球越容易晋升）
- **学习**: `learning_rate=0.25`, `decay_gamma=0.85`, `default_learn_cycles=30`
- **蓝球**: 全部 `blue_*` 参数通过 `to_runtime_config()[“blue_params”]` 传入 `BlueBallEngine`
- **位置权重**: `pos_weight_min=0.6`, `pos_weight_max=1.5`，在核心池评分阶段生效

`param_patch` 可覆盖 `pool_params` / `fusion_params` / `matrix_params` / `blue_params` / `cover_mode` 任意子集。
`matrix_patch` 可覆盖 `preferred_rows` 和 `row_weights`。
`weight_patch` 调整 8 专家基础权重。

## 补丁回灌优先级

```
weight_patch:  --weight-patch 显式路径 > config/weight_patch.latest.json > 内置默认(不加载)
matrix_patch:  config/matrix_patch.latest.json (自动发现) > 内置默认
param_patch:   config/param_patch.latest.json (自动发现) > ProjectConfig 默认值
```

补丁文件缺失不阻断预测，自动回退。

## 测试结构

```
test_predict.py        # predict.py 核心流程测试 (PredictFlowTests)
test_blue_engine.py    # BlueBallEngine 蓝球引擎测试
test_analyze_archive.py # analyze_archive.py 归档分析测试
test_update_data.py    # update_data.py 数据更新测试
```

运行方式：
```bash
python -m unittest -v                          # 全部测试
python -m unittest test_predict -v             # 单个测试文件
python -m unittest test_predict.PredictFlowTests.test_agent_teams_excludes_lstm -v  # 单个用例
```

## 依赖

- **必需**: `playwright` + `chromium` 浏览器, `beautifulsoup4`, `requests`
- **可选**: `matplotlib`（`visual_analyzer.py` 图表生成）

## 先看哪里

- 用户使用与完整命令：`README.md`
- 仓库内维护说明：`AGENT.md`
- 技能触发说明：`SKILL.md`
- 本轮迭代计划：`docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`
- 历史设计文档：`docs/plans/`（护栏设计、自学习闭环、旋转矩阵出票等）

## 仓库最小上下文

- 项目性质：双色球娱乐预测与回测实验工具，不构成投注建议
- 主入口：`predict.py`，默认主链：`team` 模式
- 8 专家固定集合：`hot/cold/missing/balanced/random/cycle/sum/zone`（定义于 `agent_registry.py`）
- 归档格式：`prediction_archive/YYYYXXX.txt`，KV 格式，含 `ticketN_explain_json` 和 `lead_summary`
- 数据格式：`lottery_data.json`，`records` 按日期倒序，每期含 `period/date/red_balls/blue_ball`

## 不要破坏的约束

- 不要把项目描述成真实投资或保证中奖工具
- 不要绕过开奖数据新鲜度保护，除非用户明确要求离线实验
- 不要覆盖同期旧归档；重复预测必须使用时间戳文件名（格式 `YYYYXXX_timestamp.txt`）
- 不要无说明改回随机拆票或可变注数（team 模式固定 5 注）
- 不要恢复 `LSTM/TensorFlow` 或重新引入 `lstm` 专家

## 高频命令

```bash
# 数据与预测
python update_data.py
python predict.py --mode team --num 5
python predict.py --mode team-cover --num 5 --seed 42

# 回测
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42
# Offline sensitivity experiment only:
python predict.py --team-cover-backtest --backtest-use-current-patches --backtest-cycles 36 --seed 42

# 归档分析
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json \
  --latest-matrix-patch-path config/matrix_patch.latest.json \
  --latest-param-patch-path config/param_patch.latest.json

# 测试
python -m unittest -v
python -m unittest test_predict -v
```

## 修改后同步检查

- 改专家集合：同步 `predict.py`、`analyze_archive.py`、`agent_registry.py`、`README.md`、`SKILL.md`
- 改 CLI / 输出 / 补丁行为：同步 `README.md`、`SKILL.md`、`AGENTS.md`、`CLAUDE.md`
- 改 `project_config.py`：同步检查 `blue_ball_engine.py`、`to_runtime_config()` 输出、`param_patch` 回灌路径
- 改回测口径：同步检查 `README.md` 中的命令示例与指标描述
- 改 `BlueBallEngine` 参数：同步 `project_config.py` 的 `blue_*` 字段和 `to_runtime_config()[“blue_params”]`
