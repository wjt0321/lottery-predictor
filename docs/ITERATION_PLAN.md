# 双色球预测项目 — 代码迭代计划

> 基于 2026-05-14 全面代码审查生成的迭代路线图。
> 按优先级分四个阶段，每个改动独立可测试。

---

## 第一阶段：修复策略信号丢失（高优先级，低风险）

### 1.1 候选号码→最终红球：改用加权采样

| 项目 | 内容 |
|------|------|
| **文件** | `predict.py` 函数 `_safe_red_sample`（约第 482-490 行） |
| **问题** | `rng.sample(candidates, 6)` 从候选池中随机无放回抽取 6 个。候选池内部的排名信息（如 hot 策略中热 1 和热 10 的差异）完全丢失。5 次提案 × 8 Agent = 40 次抽取后，候选池内所有号码累计得分趋同。 |
| **改法** | 改为加权不放回采样：排名靠前的号码获得更高入选概率。例如 `weight = exp(-rank * 0.3)`，然后按权重不放回采样 6 个。 |
| **验证** | 运行 `python predict.py --mode single --strategy hot --num 5`，检查同一策略的 5 注中，排名靠前的号码出现频率应明显高于排名靠后的。 |

### 1.2 修复 Agent 权重更新全是负数

| 项目 | 内容 |
|------|------|
| **文件** | `analyze_archive.py` 函数 `_window_agent_performance`（约第 765-835 行）和 `build_weight_adjustments`（约第 327-352 行） |
| **问题** | 8 个 Agent 的 `weight_delta` 全部为负（见 `config/weight_patch.latest.json`），说明计算有系统性偏差。根因是 `_window_agent_performance` 中用单次随机采样评估 Agent 能力，噪声远大于 Agent 间的真实差异。 |
| **改法** | 1. 在 `_window_agent_performance` 中，每个 Agent 在每期历史窗口上运行 N 次（N≥20）取平均分，降低噪声。<br>2. `build_weight_adjustments` 输出的 `weight_deltas` 强制归一化到总和为 0。 |
| **验证** | 运行 `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`，检查导出的 weight_patch 中 weight_deltas 应有正有负。 |

---

## 第二阶段：修复分析维度的结构性错误（高优先级）

### 2.1 位置权重改到矩阵行级别应用

| 项目 | 内容 |
|------|------|
| **文件** | `predict.py` 函数 `build_core_pool_snapshot`（约第 1297-1302 行） |
| **问题** | `best_pos = max(pos_weights[p].get(ball, 0.5) for p in range(6))` 取 6 个位置中的最大值。号码 01 在第 1 位表现好，它在第 6 位也拿同样的加成 —— 等价于所有热门号码在所有位置都加分，位置分析价值归零。 |
| **改法** | 将位置权重从 `build_core_pool_snapshot` 移除，移到 `generate_rotation_matrix_tickets`。矩阵第 i 行对应第 i 个出票位次的加权。例如第 1 行的 `pos_weights[0]` 决定选那些历史上在第 1 位出现频率高的号码。 |
| **验证** | 运行测试 `python -m unittest test_predict.TestPredictFlowTests.test_generate_rotation_matrix_tickets_uses_pool_of_ten -v` 确保矩阵输出不受影响。 |

### 2.2 蓝球引擎归一化区间放宽

| 项目 | 内容 |
|------|------|
| **文件** | `blue_ball_engine.py` 方法 `predict`（约第 310-316 行） |
| **问题** | 分数压缩到 [0.5, 1.5]，区分度损失。在 `generate_team_matrix_tickets` 融合时（约第 1514 行），引擎分与 Agent 分融合，窄区间导致 6 维分析的区分度被稀释。 |
| **改法** | 1. 归一化区间改为 [0.1, 3.0] 或不归一化直接使用原始分。<br>2. 在 `generate_team_matrix_tickets` 的 `combined_blue` 计算中，融合前对引擎分做独立的 MinMax 归一化到 [0, 1]，确保两路信号贡献均衡。 |
| **验证** | 运行 `python -c "from blue_ball_engine import BlueBallEngine; import json; data=json.load(open('lottery_data.json')); r=BlueBallEngine(data['records']).predict(6); print(r['scores'])"`，检查 16 个号的分值跨度是否明显大于 [0.5, 1.5]。 |

### 2.3 冷号追号从硬替换改为软加权

| 项目 | 内容 |
|------|------|
| **文件** | `blue_ball_engine.py` 方法 `predict`（约第 328-333 行） |
| **问题** | `pool[-1] = num` 无条件把候选池最后一个元素替换为冷号。可能覆盖有 6 维证据支持的高分候选号。 |
| **改法** | 删除硬替换逻辑。冷号通过遗漏维度分数自然参与排序，如果遗漏值足够突出就能自然进入前 N。或设独立的"冷号配额"（如 6 个候选池中最多 1 个冷号配额，由分数最高的冷号获得）。 |
| **验证** | 检查引擎输出的 `pool` 是否依然包含遗漏值高的号码（它们应该自然出现在排名的前几位）。 |

---

## 第三阶段：完善团队模式出票逻辑（中优先级）

### 3.1 旋转矩阵增加多样性约束

| 项目 | 内容 |
|------|------|
| **文件** | `predict.py` 函数 `generate_rotation_matrix_tickets`（约第 1369-1482 行） |
| **问题** | 矩阵模式没有多样性惩罚。`judge_with_lead_agent` 中的多样性替换逻辑在矩阵模式下从未触发，`explain_json` 中的 `diversity_replacements` 永远为空数组。 |
| **改法** | 在 `generate_rotation_matrix_tickets` 生成完 5 注后，检查注间红球重叠度。如果某注与已生成注重叠 ≥4 个红球，交换该行对应的 1-2 个池位索引。交换逻辑：优先换出 `pool_sources` 中 Agent 来源较少（跨 Agent 共识低）或分数最低的号码。 |
| **验证** | 运行团队模式 `python predict.py --mode team`，检查 5 注中任意两注的红球重叠度应 ≤4。 |

### 3.2 统一蓝球选择路径

| 项目 | 内容 |
|------|------|
| **文件** | `predict.py` 函数 `generate_prediction`（约第 576-606 行）和 `generate_team_matrix_tickets`（约第 1498-1552 行） |
| **问题** | `generate_prediction` 中每个 Agent 独立选蓝球，但这些蓝球在团队模式下只用于加权累加，最终蓝球池被 `BlueBallEngine` 完全重算。Agent 的蓝球提案贡献只有 30%（70% 来自引擎），两路不一致。 |
| **改法** | Agent 提案的蓝球只做 `source` 标记，不出现在蓝球分数计算中。蓝球完全由 `BlueBallEngine` + `cold_chase` 决定。删除 `generate_team_matrix_tickets` 中的 Agent 蓝球融合逻辑，简化蓝球路径。 |
| **验证** | 运行团队模式，检查归档文件中的 `ticketN_explain_json` 的 `blue` 字段信息是否完整。 |

---

## 第四阶段：参数与架构清理（低优先级）

### 4.1 统一蓝球分析函数

**文件**：`predict.py`（约第 112-211 行的 `analyze_blue_patterns`）
**问题**：`predict.py` 中有独立的蓝球模式分析函数，与 `blue_ball_engine.py` 功能重叠、参数不一致。
**改法**：删除 `predict.py` 中的 `analyze_blue_patterns`，所有蓝球分析统一走 `BlueBallEngine`。

### 4.2 回测评估增加多次采样

**文件**：`predict.py` 函数 `_window_agent_performance` 和 `backtest_report`
**问题**：每个 Agent 每期只用一次采样，方差极大，导致 `diff_scores` 不可靠。
**改法**：增加 `num_trials=20` 参数，每次运行 20 次取均值和置信区间。

### 4.3 核池大小确认

**文件**：`config/param_patch.latest.json`
**现状**：`core_red_pool_size=10`，使用 `10_red_guard_6_to_5` 矩阵。
**建议**：保持 10 球方案，前提是 1.1（加权采样）已修复。10 个强信号号码比 14 个稀释号码更有意义。

---

## 迭代顺序建议

```
1.1 (加权采样) → 2.1 (位置权重) → 2.2 (蓝球归一化)
  → 2.3 (冷号软加权) → 3.1 (矩阵多样性) → 1.2 (权重学习修复)
  → 3.2 (蓝球路径统一) → 4.x (清理项)
```

前 3 个改动（1.1、2.1、2.2）覆盖了最主要的结构性问题，建议一次迭代完成。之后每个改动独立可测试、可回滚。

## 验证命令汇总

```bash
# 测试
python -m unittest -v

# 单策略预测
python predict.py --mode single --strategy hot --num 5

# 团队预测
python predict.py --mode team

# 归档分析 + 补丁导出
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report --latest-patch-path config/weight_patch.latest.json --latest-matrix-patch-path config/matrix_patch.latest.json --latest-param-patch-path config/param_patch.latest.json
```
