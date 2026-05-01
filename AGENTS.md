# AGENTS.md

This file provides guidance to Codex when working in this repository.

## 项目概述

- 项目名称：双色球彩票预测工具
- 项目性质：娱乐型预测与回测实验工具，不构成投注建议
- 当前方向：基于真实开奖数据、可解释归档、专家加权、旋转矩阵出票和补丁回灌，形成可持续优化的自学习闭环

## 文档入口

- 人类用户说明：`README.md`
- Agent 工作说明：`AGENT.md`
- 技能触发说明：`SKILL.md`

## 常用命令

```bash
# 安装依赖
pip install playwright requests beautifulsoup4
playwright install chromium

# 更新数据
python update_data.py

# 默认团队预测模式（固定输出 5 注）
python predict.py --mode team --num 5

# 单策略预测
python predict.py --mode single --strategy hot --num 3

# 使用所有单策略做快速对比
python predict.py --mode single --all --num 3

# 高级综合分析
python predict.py --advanced --num 5

# 导出分析报告与补丁
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report

# 写回最新补丁
python analyze_archive.py \
  --archive-dir prediction_archive \
  --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json \
  --latest-matrix-patch-path config/matrix_patch.latest.json \
  --latest-param-patch-path config/param_patch.latest.json

# 运行测试
python -m unittest -v
```

## 当前架构

### 预测模式

1. `single`：独立使用单个策略出号
2. `team`：8 个专家先生成候选提案，再聚合核心号码池，并通过固定旋转矩阵输出 5 注
3. `advanced`：使用时间加权、关联分析、模式识别和遗传算法做综合分析

### 团队模式专家

当前专家集合由 `agent_registry.py` 统一维护：

- `hot`
- `cold`
- `missing`
- `balanced`
- `random`
- `cycle`
- `sum`
- `zone`

不要在只改 `predict.py` 的情况下单独增删专家，预测链与分析链需要保持一致。

### team 模式核心流程

1. 读取 `lottery_data.json`
2. 进行开奖数据新鲜度校验，数据落后则阻断预测
3. 读取上期归档并计算差异调节系数
4. 读取 `weight patch`，训练主 Agent 差异学习模型
5. 生成 8 个专家团队提案
6. 聚合 `core_pool`
7. 使用旋转矩阵固定输出 5 注
8. 归档 `ticketN_explain` 与 `ticketN_explain_json`

## 自学习闭环

### 归档分析器

- `analyze_archive.py` 会读取 `prediction_archive/*.txt`
- 当前会导出：
  - 命中贡献排行（可用 `lottery_data.json` 回填真实开奖结果）
  - 双视角差异
  - 矩阵行表现
  - 权重补丁
  - 矩阵补丁
  - 参数补丁

### 补丁文件

- `config/weight_patch.latest.json`
- `config/matrix_patch.latest.json`
- `config/param_patch.latest.json`

### 运行时回灌

`predict.py` 在 `team` 模式下会自动尝试加载：

1. `weight patch`
2. `param patch`
3. `matrix patch`

如果补丁不存在，则回退到内置默认配置。

## 关键约束

### 数据保护

- 预测前必须检查开奖数据是否已过期
- 如果最近应开奖日已经过去，而本地数据未更新，应提示先执行 `python update_data.py`

### 归档保护

- 同一期首次归档使用 `prediction_archive/<期号>.txt`
- 如果重复运行同一期预测，必须改用带时间戳的新文件名，避免覆盖旧归档

### 输出约束

- `team` 模式固定输出 `5` 注 `6+1`
- 核心池与旋转矩阵逻辑是当前主链，不要无说明地改回随机拆票

### 已移除能力

- `LSTM/TensorFlow` 已从主链路移除
- 不要恢复 `lstm` 专家，除非用户明确要求并接受依赖成本

## 关键文件

| 文件 | 作用 |
|------|------|
| `predict.py` | 预测主脚本，含团队学习、核心池与旋转矩阵出票 |
| `analyze_archive.py` | 归档分析、矩阵表现统计、补丁导出 |
| `update_data.py` | 真实开奖数据抓取与增量更新 |
| `agent_registry.py` | 共享专家注册表 |
| `manual_data_import.py` | 支持手动导入外部开奖数据 |
| `lottery_data.json` | 历史开奖数据 |
| `prediction_archive/*.txt` | 每期精简预测归档 |

## 修改建议

- 修改专家集合时，同时检查：
  - `predict.py`
  - `analyze_archive.py`
  - `agent_registry.py`
  - `README.md`
  - `SKILL.md`
- 修改命令行参数、补丁逻辑或输出行为时，同步更新文档说明
- 修改数据更新逻辑后，优先验证：
  - `python update_data.py`
  - `python -m unittest test_update_data -v`
