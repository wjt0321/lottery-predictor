---
name: lottery-predictor
description: Use when user asks for Double Color Ball (双色球) prediction, number recommendations, trend analysis, or wants to run/update this lottery predictor project.
---

# 双色球彩票预测器

## 概览
- 用于本项目内的双色球娱乐预测与趋势分析
- 默认优先团队模式（`--mode team`），支持 8 专家协同、旋转矩阵出票与可解释归档
- 仅供娱乐，不构成任何投注建议

## 核心特性（V3 迭代）
- **加权采样**：红球候选池排名靠前的号码获得更高入选概率
- **位置权重矩阵**：矩阵每行独立按历史位置表现调整排序
- **增强蓝球引擎**：归一化区间 [0.1, 3.0]，区分度扩大 2.9 倍，冷号软加权
- **多样性约束**：旋转矩阵注间红球重叠 ≥4 时自动交换低共识号码
- **权重修复**：`weight_deltas` 强制总和为 0，避免全为负数

## 何时使用
- 用户要“预测下一期号码 / 给几注推荐号”
- 用户要“更新开奖数据 / 校验数据是否最新”
- 用户要“分析趋势、热冷号、遗漏、团队权重、矩阵表现”
- 用户要“导出并应用补丁（weight/matrix/param patch）”
- 用户要“运行迭代计划、合并分支、更新文档”

## 最小操作流程
- 更新数据：`python update_data.py`
- 团队预测：`python predict.py --mode team --num 5`
- 单策略对比：`python predict.py --mode single --all --num 3`
- 归档分析并默认写回三类最新补丁：`python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`

## 常用命令
- 团队预测（可复现）：`python predict.py --mode team --num 3 --seed 42`
- 显式加载权重补丁：`python predict.py --mode team --weight-patch config/weight_patch.latest.json`
- 默认自动回灌三类补丁：`python predict.py --mode team --num 5`
- 高级分析：`python predict.py --advanced --num 5`
- 导入外部数据：`python manual_data_import.py --json data.json`

## 回退链与归档
- 权重补丁回退链：`--weight-patch` 显式路径 > `config/weight_patch.latest.json` > 不加载
- 参数补丁回退链：默认自动尝试 `config/param_patch.latest.json`，不存在则使用内置默认配置
- 矩阵补丁回退链：默认自动尝试 `config/matrix_patch.latest.json`，不存在则使用内置默认配置
- 若本地开奖数据落后于最近应开奖日，`predict.py` 会阻断预测并提示先运行 `python update_data.py`
- 归档文件会记录 `lead_summary`，其中包含 `patch_source`（`explicit/default/none`）
- 每注可解释信息在 `ticketN_explain` 与 `ticketN_explain_json`
- 归档分析会用 `lottery_data.json` 对已开奖期临时回填 `actual_result`，权重补丁优先依据真实命中贡献生成
- 蓝球分析**统一走 BlueBallEngine**，不再走旧 `analyze_blue_patterns`

## 详细文档
- 详细参数、策略说明、长示例请查看 [README.md](./README.md)
- 迭代计划与代码审计请查看 [ITERATION_PLAN.md](./ITERATION_PLAN.md)
