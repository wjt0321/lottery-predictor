# V6 稳定性验证与动态科学偏移实施计划

日期：2026-07-14

## Task 1：配置与契约测试

**修改：** `project_config.py`, `test_predict.py`

1. 为默认 `dynamic` 策略、1/2 球门槛、分差门槛和证据覆盖门槛写失败测试。
2. 确认 `to_runtime_config()["fusion_params"]` 完整输出新参数。
3. 最小实现配置，运行定向测试转绿。

## Task 2：泛化约束选择器

**修改：** `predict.py`, `test_algorithm_correctness.py`

1. 写测试覆盖 offset_count=1、offset_count=2、0 个候选、最高核心保留、次佳分差和确定性。
2. 将 `_select_scientific_offset_reds` 泛化为 1/2 球组合。
3. 保持固定 scientific=2 的已有测试兼容。

## Task 3：动态策略决策与第 5 注集成

**修改：** `predict.py`, `test_predict.py`

1. 写动态选择 2、降级为 1、无证据保留 0 的失败测试。
2. 实现 `_choose_dynamic_offset_plan`。
3. 第 5 注解释保存决策置信度、候选方案和原矩阵反事实票。
4. 保留 `legacy` 和固定 `scientific` 路径。

## Task 4：反事实回测与蓝球排名校准

**修改：** `predict.py`, `test_predict.py`, `test_algorithm_correctness.py`

1. 写同注实际票与原矩阵票得分差的单元测试。
2. 扩展 `team_matrix_backtest_report` 的 `counterfactual` 和 `blue_calibration`。
3. 验证空样本返回完整零值结构。

## Task 5：稳定性回测聚合

**修改：** `predict.py`, `test_predict.py`

1. 用 mock team report 写多窗口、多 seed、配对 dynamic/legacy 的失败测试。
2. 实现综合目标、均值/标准差/极值、配对差值、正向比例和验收护栏。
3. 验证 determinism 和 progress callback。

## Task 6：CLI 与文档

**修改：** `predict.py`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`

1. 增加 `--team-stability-backtest`、`--stability-windows`、`--stability-seeds`。
2. 输出运行矩阵、聚合指标、反事实归因和蓝球校准。
3. 同步架构、命令、配置、娱乐用途和避免事后调参说明。

## Task 7：验证、提交与推送

1. `python -m py_compile predict.py project_config.py test_algorithm_correctness.py test_predict.py`
2. `python -m unittest test_algorithm_correctness -v`
3. `python -m unittest test_predict -v`
4. `python -m unittest -v`
5. 运行代表性 stability 实验（至少 36/72 两窗口、两个 seed；资源允许时扩展）。
6. 检查 `git diff --check`、工作树和文档一致性。
7. 提交功能分支，快进合并 `main`，在合并结果上复验并推送。
