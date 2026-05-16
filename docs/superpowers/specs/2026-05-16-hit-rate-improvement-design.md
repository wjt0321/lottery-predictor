# 2026-05-16 命中率改进设计说明

## 目标

- 修复蓝球覆盖与蓝球配置未真正作用到出票链路的问题。
- 新增端到端 `team` 矩阵回测，统一优化口径。
- 让 `row_weights` 真实影响矩阵出票顺序。
- 让位置权重前移到核心池评分，真正改变候选集合。

## 设计范围

- 修改 `predict.py`、`project_config.py`、`blue_ball_engine.py`、`analyze_archive.py`、`README.md`。
- 更新 `test_predict.py`、`test_blue_engine.py`、`test_analyze_archive.py`。
- 保持 `team` 模式固定输出 5 注 `6+1`。
- 不恢复 `LSTM/TensorFlow`，不改专家集合。

## 关键设计

### 蓝球链路

- `ProjectConfig.to_runtime_config()` 输出统一的 `blue_params`。
- 所有 `BlueBallEngine` 调用统一接收 `config=runtime["blue_params"]`。
- `generate_rotation_matrix_tickets()` 使用可复现随机源选蓝球，并在每次出票后写入 `used_blues`。

### 端到端回测

- 新增 `team_matrix_backtest_report()`，按 walk-forward 方式回放完整链路：
  - 训练 `lead_model`
  - 构建专家团队
  - 生成 5 注矩阵票
  - 统计单注与 best-of-5 指标
- CLI 增加 `--team-backtest` 和 `--backtest-cycles`。
- 回测只输出报告，不写归档。

### 矩阵权重

- 若未显式提供 `preferred_rows`，则按 `row_weights` 降序生成默认 `row_order`。
- `explain_json.matrix` 增加 `row_weight`，便于归档分析器回看。
- `analyze_archive.py` 将“动态淘汰”语义改为“动态排序”，避免补丁描述与实际行为不一致。

### 位置权重

- 删除当前矩阵行内“排序后仍取满 6 个”的无效逻辑。
- 在 `build_core_pool_snapshot()` 中根据号码历史排序位置适配度对 `red_scores` 加权。
- 位置权重只影响核心池排序，不改变矩阵 5 注固定输出结构。

## 验证

- 先写失败测试，再补最小实现。
- 执行 `python -m unittest -v`。
- 执行 `python predict.py --team-backtest --backtest-cycles 36 --seed 42`。
- 执行 `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`。
