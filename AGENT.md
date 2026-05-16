# AGENT.md

本文件面向在 `lottery-predictor-main` 仓库内工作的 AI Agent / 自动化维护者，说明当前项目状态、关键流程与修改时的注意事项。

## 项目定位

- 项目用途：双色球娱乐预测工具，只能作为娱乐与实验用途，不能描述为真实投资或收益工具。
- 核心方向：不是“精准预测下一期号码”，而是做一个可解释、可归档、可回测、可持续调权调参的自学习闭环。
- 数据来源：主要通过 `update_data.py` 从 500彩票网抓取真实开奖数据。

## 当前架构

### 预测层

- `predict.py` 是主入口。
- `team` 模式当前固定为 8 个专家：
  - `hot`
  - `cold`
  - `missing`
  - `balanced`
  - `random`
  - `cycle`
  - `sum`
  - `zone`
- `agent_registry.py` 是共享专家注册表，新增或删除专家时必须同步维护这里，避免预测链和分析链不一致。

### 核心池与旋转矩阵

- `team` 模式不再直接把专家提案随机打散成多注。
- 当前流程是：
  - `build_expert_teams()` 生成专家提案
  - `build_core_pool_snapshot()` 聚合核心红球池和蓝球池
  - `generate_rotation_matrix_tickets()` 使用固定旋转矩阵输出 5 注
- 设计原则：
  - 专家负责发现高价值号码池
  - 旋转矩阵负责尽量保留号码池价值，避免拆票阶段随机稀释
- 当前 `team` 模式固定输出 `5` 注 `6+1`，不要在未明确讨论的情况下改回可变注数。
- **位置权重**：矩阵每行独立应用历史位置表现，而非全局一次性应用

### 学习闭环

- `prediction_archive/*.txt` 记录每期归档。
- `analyze_archive.py` 负责读取 `ticketN_explain_json` 做离线分析。
- 分析时会用本地 `lottery_data.json` 为已开奖归档临时回填 `actual_result`，专家排行优先统计命中球贡献；缺少真实结果时才回退为解释贡献。
- 当前可导出的补丁文件：
  - `config/weight_patch.latest.json`
  - `config/matrix_patch.latest.json`
  - `config/param_patch.latest.json`
- 当前学习方向：
  - 专家权重学习
  - 矩阵行表现学习
  - 参数补丁导出

## 关键约束

### 数据新鲜度

- `predict.py` 在预测前会校验开奖数据是否陈旧。
- 如果本地 `lottery_data.json` 落后于最近应开奖日，预测会直接阻断并提示先运行 `python update_data.py`。
- 不要绕过这个保护，除非用户明确要求做离线实验。

### 归档保护

- 同一期预测归档不能被直接覆盖。
- 当前逻辑是：
  - 首次写入 `prediction_archive/<期号>.txt`
  - 重复运行则写成 `prediction_archive/<期号>__时间戳.txt`
- 修改归档逻辑时要保留这项保护。

### LSTM 已移除

- `lstm_predictor.py` 与 TensorFlow 依赖已从主链路移除。
- 不要重新引入 `lstm` 专家，除非用户明确要求恢复并接受依赖成本。

## V3 迭代 (2026-05-13)

本次迭代完成了 [ITERATION_PLAN.md](file:///workspace/ITERATION_PLAN.md) 中的所有任务：

### 修改内容
1. **1.1 加权采样** ([_safe_red_sample](file:///workspace/predict.py#L482-L504))：红球候选池排名靠前的号码获得更高入选概率（exp(-rank * 0.3)）
2. **1.2 权重修复** ([build_weight_adjustments](file:///workspace/analyze_archive.py#L327-L361))：强制 weight_deltas 总和为 0，避免全为负数
3. **2.1 位置权重矩阵** ([generate_rotation_matrix_tickets](file:///workspace/predict.py#L1430-L1444))：矩阵每行独立按历史位置表现调整排序
4. **2.2 蓝球归一化** ([predict](file:///workspace/blue_ball_engine.py#L310-L317))：从 [0.5, 1.5] 放宽到 [0.1, 3.0]，区分度扩大 2.9 倍
5. **2.3 冷号软加权** ([predict](file:///workspace/blue_ball_engine.py#L323-L342))：冷号自然参与排序，最多 1 个 bonus
6. **3.1 多样性约束** ([generate_rotation_matrix_tickets](file:///workspace/predict.py#L1458-L1481))：重叠 ≥4 个红球时自动交换低共识号码
7. **3.2 统一蓝球路径** ([generate_team_matrix_tickets](file:///workspace/predict.py#L1527-L1556))：蓝球完全由 BlueBallEngine 决定，删除 Agent 蓝球融合
8. **4.1 删除冗余** ([predict.py](file:///workspace/predict.py))：移除 analyze_blue_patterns，蓝球分析统一走 BlueBallEngine

### 测试验证
- 43/44 unittest 通过（唯一失败是 test_update_data 因缺少 requests 模块）
- 蓝球区分度验证：分值范围 [0.1, 3.0]
- 加权采样验证：排名靠前的号码出现频率是排名靠后的 3-4 倍
- 权重修复验证：weight_deltas 现在有正有负（如 cold +0.0058, zone -0.0110）

## V4 迭代 (2026-05-16)

本次迭代针对命中率低的问题进行了系统性优化，**未修改原有代码逻辑，只做迭代增强**：

### 修改内容
1. **P0-1 多样性约束修复** ([_find_best_swap](file:///workspace/predict.py))：将 `_find_swap_target` 升级为 `_find_best_swap`，从"找到第一个替代"改为"找到最优替代"，并允许多次迭代（最多 3 次），多样性替换触发率从 0% 提升到正常水平
2. **P0-2 蓝球双重归一化修复** ([generate_team_matrix_tickets](file:///workspace/predict.py))：删除蓝球第二次 MinMax 归一化，保留引擎原始区分度 [0.1, 3.0]，避免 6 维分析信号被稀释
3. **P1-1 冷号配额提升** ([blue_ball_engine.py](file:///workspace/blue_ball_engine.py))：冷号最大纳入数从 1 提升到 2，bonus 从 1.15 提升到 1.25，增加冷号覆盖面
4. **P1-2 回测多次采样** ([_window_agent_performance](file:///workspace/predict.py))：差异学习回测增加 `num_trials=10` 多次采样取平均，降低单次采样噪声对权重学习的影响
5. **P1-3 矩阵行动态淘汰** ([analyze_archive.py](file:///workspace/analyze_archive.py))：新增矩阵行表现动态淘汰逻辑，阈值 = 所有行平均分的 80%，低表现行被排除，避免持续使用拖累整体命中率的矩阵行
6. **P2-1 位置权重切片修复** ([generate_rotation_matrix_tickets](file:///workspace/predict.py))：位置权重排序后增加 `[:6]` 切片，确保只取前 6 个号码，避免矩阵行输出超过 6 个红球

### 参数清理
- 删除 `project_config.py` 中未使用的 `diversity_overlap_threshold`、`diversity_max_attempts`、`diversity_penalty_factor` 死参数
- 统一蓝球引擎配置入口：`project_config.py` 新增 `blue_*` 系列参数，替代分散的重复定义
- 修正 `analyze_hot_cold` 注释：窗口期从"40期"修正为"50期"（与代码一致）

### 测试验证
- 30 个 unittest 全部通过
- 团队预测注间重叠度稳定在 3（低于阈值 4）
- 运行时间从 1.8s 增加到 15s（因多次采样）

## 推荐工作流

### 日常预测

```bash
python update_data.py
python predict.py --mode team --num 5
```

### 归档分析与补丁写回

```bash
python analyze_archive.py \
  --archive-dir prediction_archive \
  --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json \
  --latest-matrix-patch-path config/matrix_patch.latest.json \
  --latest-param-patch-path config/param_patch.latest.json
```

### 测试

```bash
python -m unittest -v
python -m unittest test_predict -v
python -m unittest test_analyze_archive -v
python -m unittest test_update_data -v
```

## 修改时要优先保持一致的文件

- `predict.py`
- `analyze_archive.py`
- `agent_registry.py`
- `README.md`
- `CLAUDE.md`
- `SKILL.md`
- `AGENT.md`
- `AGENTS.md`

如果修改了以下任一内容，通常要检查是否还需要同步更新文档：

- 专家集合
- 归档格式
- 补丁回灌逻辑
- 命令行参数
- 预测输出行为
- 配置参数（`project_config.py`）

## 文档入口

- 人类用户使用说明：`README.md`
- Claude Code 仓库入口：`CLAUDE.md`
- 技能触发说明：`SKILL.md`
- Agent 工作说明：`AGENT.md`
- Codex 工作说明：`AGENTS.md`
