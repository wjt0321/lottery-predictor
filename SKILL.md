---
name: lottery-predictor
description: Use when user asks for Double Color Ball (双色球) prediction, number recommendations, trend analysis, or wants to run/update this lottery predictor project.
---

# 双色球彩票预测器

## 概览
- 用于本项目内的双色球娱乐预测与趋势分析
- 默认优先团队模式（`--mode team`），支持多策略与可解释归档
- 仅供娱乐，不构成任何投注建议

## 何时使用
- 用户要“预测下一期号码 / 给几注推荐号”
- 用户要“更新开奖数据 / 校验数据是否最新”
- 用户要“分析趋势、热冷号、遗漏、团队权重”
- 用户要“导出并应用权重补丁（weight patch）”

## 最小操作流程
- 更新数据：`python update_data.py`
- 团队预测：`python predict.py --mode team --num 5`
- 单策略对比：`python predict.py --mode single --all --num 3`
- 归档分析：`python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report`

## 常用命令
- 团队预测（可复现）：`python predict.py --mode team --num 3 --seed 42`
- 使用补丁预测：`python predict.py --mode team --weight-patch config/weight_patch.latest.json`
- 高级分析：`python predict.py --advanced --num 5`
- 导入外部数据：`python manual_data_import.py --json data.json`

## 回退链与归档
- 权重补丁回退链：`--weight-patch` 显式路径 > `config/weight_patch.latest.json` > 不加载
- 归档文件会记录 `lead_summary`，其中包含 `patch_source`（`explicit/default/none`）
- 每注可解释信息在 `ticketN_explain` 与 `ticketN_explain_json`

## 详细文档
- 详细参数、策略说明、长示例请查看 [README.md](./README.md)
