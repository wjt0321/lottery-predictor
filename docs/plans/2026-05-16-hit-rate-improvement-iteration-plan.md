# 2026-05-16 预测命中率改进迭代计划

> 项目性质：娱乐型预测与回测实验工具，不构成投注建议。本文目标不是承诺提高真实彩票命中率，而是修复当前链路中的伪学习、伪回灌和覆盖效率问题，让后续优化有可靠指标可依赖。

## 1. 审查结论

当前系统已经具备多 Agent、核心池、旋转矩阵、归档分析和补丁回灌能力，但还有几处会削弱命中率实验价值的问题：

1. 蓝球覆盖被重复选择稀释，`used_blues` 创建后没有写入，导致 5 注可能反复使用同一个蓝球。
2. `matrix_patch` 导出了 `row_weights`，运行时也加载了，但出票时没有真正使用行权重。
3. `param_patch` 中的矩阵行“动态淘汰”实际只改变顺序，因为低表现行最后又被追加回来。
4. 位置权重逻辑在矩阵行内排序 6 个号码后仍取全部 6 个，基本不改变最终红球集合。
5. `project_config.py` 中的蓝球参数没有传入 `BlueBallEngine`，蓝球引擎实际使用内部默认值。
6. 当前控制台回测主要评估单专家，不等价于最终的 team + core_pool + matrix + blue_engine 完整出票链。

因此下一轮迭代建议优先修“信号能否作用到出票”和“回测是否能代表最终链路”，再做参数增强。

## 2. 迭代目标

### P0 目标

- 让 5 注蓝球候选尽量无重复，提高蓝球覆盖效率。
- 让蓝球运行参数统一从 `project_config.py` / `param_patch` 进入 `BlueBallEngine`。
- 新增端到端 team 矩阵回测，统计最终 5 注而不是只统计单专家。

### P1 目标

- 让 `matrix_patch.row_weights` 真实影响矩阵行使用方式。
- 修正“动态淘汰”语义，避免文档和实际行为不一致。
- 将位置权重前移到红球核心池评分，或改造为真正会改变候选集合的行内选择逻辑。

### P2 目标

- 在端到端回测稳定后，再调专家权重、蓝球维度权重、核心池大小和矩阵候选池。
- 增加归档分析报告中的真实链路指标，减少依赖单期命中噪声。

## 3. 推荐实施顺序

## 阶段一：修复蓝球覆盖与配置回灌

涉及文件：

- `predict.py`
- `blue_ball_engine.py`
- `project_config.py`
- `test_predict.py`
- `test_blue_engine.py`

### 3.1 修复蓝球去重未生效

当前位置：

- `predict.py` 中 `generate_rotation_matrix_tickets()`
- `used_blues: Set[int] = set()`
- `final_blue = _select_blue_ball_for_row(...)`

建议改法：

1. 每次生成 `final_blue` 后执行 `used_blues.add(final_blue)`。
2. 如果蓝球池大小小于 5，允许重复，但优先消耗未使用蓝球。
3. 将 `_select_blue_ball_for_row()` 的随机选择改为可复现随机源，避免同样输入反复产生不同归档。

验收标准：

- 当 `blue_pool` 至少有 5 个号码时，team 模式 5 注蓝球应尽量不重复。
- 新增测试覆盖：构造 6 个蓝球候选，生成 5 注后 `len(set(blues)) >= 4`，理想为 5。
- `python -m unittest test_predict -v` 通过。

### 3.2 统一蓝球配置入口

当前问题：

- `project_config.py` 中有 `blue_missing_cold_threshold`、`blue_missing_cold_bonus` 等配置。
- `BlueBallEngine(records)` 调用时没有传 config。
- `BlueBallEngine` 内部仍读取 `missing_cold_threshold` 这类短 key。

建议改法：

1. 在 `ProjectConfig.to_runtime_config()` 中增加：

```json
"blue_params": {
  "missing_cold_threshold": 20,
  "missing_cold_bonus": 1.8,
  "missing_extreme_threshold": 40,
  "missing_extreme_bonus": 2.5,
  "parity_window": 15,
  "zone_window": 30,
  "amplitude_window": 30,
  "heat_window": 20,
  "cold_chase_cap": 3
}
```

2. 在 `generate_team_matrix_tickets()` 中：

```python
blue_config = runtime.get("blue_params", {})
blue_engine = BlueBallEngine(records, config=blue_config)
```

3. 控制台诊断用的 `BlueBallEngine(records)` 也同步传入相同配置。
4. `param_patch.latest.json` 后续允许覆盖 `blue_params`。

验收标准：

- 修改 `blue_missing_cold_threshold` 或补丁中的 `blue_params.missing_cold_threshold` 后，蓝球追冷结果会发生可观察变化。
- 新增单测验证 `resolve_runtime_config()` 返回 `blue_params`，且 `BlueBallEngine` 接收参数后阈值变化生效。

## 阶段二：新增端到端 team 矩阵回测

涉及文件：

- `predict.py`
- `analyze_archive.py`
- `test_predict.py`
- `README.md`

### 3.3 新增最终链路回测函数

当前 `backtest_report()` 更像单专家回测，无法衡量最终 5 注矩阵出票效果。

建议新增函数：

```python
def team_matrix_backtest_report(
    records: List[Dict],
    cycles: int = 36,
    seed: Optional[int] = None,
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    ...
```

每个样本期的流程：

1. 只使用目标期开奖前的历史数据。
2. 训练 lead agent。
3. 构建 expert teams。
4. 调用 `generate_team_matrix_tickets()` 生成 5 注。
5. 对 5 注分别计算：
   - 红球命中数
   - 蓝球是否命中
   - `hit_score`
   - 是否红球 2+
   - 是否红球 3+
6. 汇总：
   - 单注平均分
   - 每期 best-of-5 平均分
   - best-of-5 红 2+ 率
   - best-of-5 红 3+ 率
   - 蓝球候选池命中率
   - 最终 5 注蓝球命中率
   - 矩阵行表现

验收标准：

- 控制台输出同时展示“单专家回测”和“最终链路回测”，避免误读。
- 分析报告可以读取该指标，作为后续补丁生成依据。
- 固定 `--seed` 时端到端回测结果可复现。

### 3.4 增加 CLI 参数

建议新增：

```bash
python predict.py --mode team --num 5 --team-backtest
```

或单独报告：

```bash
python predict.py --team-backtest --backtest-cycles 36
```

验收标准：

- 不影响默认预测命令。
- 回测不会写入 `prediction_archive`。
- README 同步说明新命令。

## 阶段三：让矩阵补丁真实影响出票

涉及文件：

- `predict.py`
- `analyze_archive.py`
- `test_analyze_archive.py`
- `test_predict.py`

### 3.5 明确矩阵行策略

当前 `preferred_rows` 最终总会补齐 1-5 行，所以“淘汰”并不是真的淘汰。

推荐二选一：

方案 A：改名为动态排序

- 保留 5 注固定输出。
- 文档、字段和注释改为 `row_priority` 或 `preferred_rows`。
- 不再声称低表现行被排除。

方案 B：扩展候选矩阵后再动态选择 5 行

- 内置更多矩阵行，例如 14 球池生成 8-12 条候选行。
- 根据 `row_weights` 选择表现最好的 5 行。
- 这样“淘汰”才有实际意义。

推荐采用方案 B，但实现成本更高；如果要快速稳定，先采用方案 A。

验收标准：

- 如果采用方案 A：`analyze_archive.py` 注释、报告、README 统一为“排序”。
- 如果采用方案 B：新增测试验证低权重候选行不会进入最终 5 注。

### 3.6 使用 `row_weights`

建议最低成本实现：

1. 读取 `runtime["matrix_params"]["row_weights"]`。
2. 当 `preferred_rows` 缺失时，按 `row_weights` 降序生成 `row_order`。
3. 当 `preferred_rows` 存在时，以 `preferred_rows` 为主，`row_weights` 作为同级排序或诊断输出。

更进一步：

- 将 `row_weights` 写入 `explain_json.matrix.row_weight`。
- 在 `analyze_archive.py` 中用端到端表现持续更新行权重。

验收标准：

- 构造 `row_weights={"5": 0.9, "1": 0.1}` 时，默认 row_order 优先第 5 行。
- 归档 explain_json 能看到当前行权重。

## 阶段四：修正位置权重的作用方式

涉及文件：

- `predict.py`
- `test_predict.py`

当前位置权重问题：

- 矩阵行固定选 6 个池位。
- 对这 6 个号码排序后仍取 6 个。
- 最终再排序为升序，位置权重不会改变号码集合。

推荐改法：

方案 A：前移到核心池评分

- 在 `build_core_pool_snapshot()` 聚合红球分数后，根据号码历史位置适配度调整 `red_scores`。
- 这样会影响 `red_pool`，是真正有效的。

方案 B：每个矩阵位允许候选替换

- 对行内每个池位，允许从相邻高分池位或候补池中选更符合位置权重的号码。
- 实现复杂，容易引入重复和过拟合。

推荐先采用方案 A。

验收标准：

- 构造测试数据，使某号码位置权重明显更高时，它能进入或提升红球核心池排序。
- 保持 `team` 模式仍固定输出 5 注，每注 6+1。

## 4. 指标与回测口径

后续所有“命中率改进”应至少同时看以下指标：

| 指标 | 说明 | 用途 |
|------|------|------|
| 单注平均分 | 红球命中 + 蓝球 1.5 分 | 衡量单票质量 |
| best-of-5 平均分 | 每期 5 注取最高分 | 衡量实际出票覆盖 |
| best-of-5 红 2+ 率 | 5 注里至少一注红球 2+ | 衡量红球基础覆盖 |
| best-of-5 红 3+ 率 | 5 注里至少一注红球 3+ | 衡量高价值覆盖 |
| 蓝球池命中率 | 蓝球候选池是否包含开奖号 | 衡量蓝球引擎候选质量 |
| 最终蓝球命中率 | 5 注蓝球是否命中 | 衡量蓝球出票选择 |
| 矩阵行平均分 | 每行历史表现 | 反馈矩阵行权重 |
| 重复度 | 5 注红球/蓝球重复程度 | 衡量覆盖效率 |

注意：

- 不建议只看最近 1-3 期表现。
- 权重补丁至少基于 24-36 期端到端回测。
- 参数调优要用 walk-forward，不能用未来数据。

## 5. 建议测试清单

每轮实现后执行：

```bash
python -m unittest -v
python predict.py --mode team --num 5 --seed 42
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
```

如果新增端到端回测命令，再执行：

```bash
python predict.py --team-backtest --backtest-cycles 36 --seed 42
```

重点人工检查：

1. 默认预测仍固定输出 5 注。
2. 每注仍为 6 个红球 + 1 个蓝球。
3. 重复预测同一期不会覆盖旧归档。
4. 数据过期保护仍能阻断预测。
5. `config/*.latest.json` 不存在时能回退默认配置。
6. `config/*.latest.json` 存在时，控制台和归档能显示已应用。

## 6. 推荐任务拆分

### 任务 1：蓝球覆盖修复

- 修复 `used_blues` 未写入。
- 蓝球选择改为可复现。
- 新增测试覆盖蓝球去重。

预期收益：低风险、立刻提升 5 注覆盖效率。

### 任务 2：蓝球配置回灌

- `ProjectConfig.to_runtime_config()` 增加 `blue_params`。
- `BlueBallEngine` 调用处传入配置。
- 测试补丁覆盖蓝球阈值。

预期收益：让后续蓝球参数调优真正生效。

### 任务 3：端到端 team 矩阵回测

- 新增最终链路回测函数。
- 新增 CLI 参数。
- 输出 best-of-5 指标。

预期收益：建立可靠优化指标，避免被单专家回测误导。

### 任务 4：矩阵行权重生效

- 明确动态排序或动态淘汰语义。
- 使用 `row_weights` 排序或选择矩阵行。
- 归档行权重。

预期收益：让归档分析器生成的矩阵补丁真正影响出票。

### 任务 5：位置权重前移

- 将位置权重作用到核心池红球评分。
- 删除或简化当前行内无效排序逻辑。

预期收益：减少无效复杂度，让位置统计真正改变候选池。

## 7. 风险控制

- 不恢复 LSTM/TensorFlow 主链路，避免引入重依赖和不可解释模型。
- 不把单期命中作为权重大幅调整依据。
- 不让补丁一次性改变过多参数，优先小步迭代。
- 不删除现有归档，所有回测只读历史数据。
- 所有新增随机行为都应支持 `--seed` 复现。

## 8. 第一轮建议落地范围

第一轮只做以下三项：

1. 修复蓝球去重。
2. 打通蓝球配置回灌。
3. 新增端到端 team 矩阵回测。

这三项完成后，再根据新的端到端指标决定是否调整矩阵行权重、位置权重和专家权重。这样能先把“仪表盘”和“控制线”接稳，再讨论具体参数怎么拧。
