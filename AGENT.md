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

### 学习闭环

- `prediction_archive/*.txt` 记录每期归档。
- `analyze_archive.py` 负责读取 `ticketN_explain_json` 做离线分析。
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

如果修改了以下任一内容，通常要检查是否还需要同步更新文档：

- 专家集合
- 归档格式
- 补丁回灌逻辑
- 命令行参数
- 预测输出行为

## 文档入口

- 人类用户使用说明：`README.md`
- Claude Code 仓库入口：`CLAUDE.md`
- 技能触发说明：`SKILL.md`
- 本文件：`AGENT.md`
