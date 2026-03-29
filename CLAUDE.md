# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

双色球彩票预测工具，基于历史数据统计生成号码推荐。数据来源于500彩票网。

## 常用命令

```bash
# 安装依赖
pip install playwright && playwright install chromium

# 更新数据
python update_data.py

# 默认团队预测模式
python predict.py

# 单策略预测
python predict.py --mode single --strategy hot --num 3

# 使用所有策略
python predict.py --mode single --all

# 固定随机种子复现
python predict.py --mode team --num 3 --seed 42

# 运行测试
python -m pytest test_predict.py
python test_predict.py
```

## 架构说明

### 预测模式

1. **单策略模式 (`single`)**: 独立使用 `hot/cold/missing/balanced/random` 策略之一
2. **团队模式 (`team`)**: 5个子Agent（hot/cold/missing/balanced/random）各自提出候选，主Agent根据历史回测动态赋权融合

### 核心流程 (team模式)

1. 读取 `lottery_data.json` 最新数据
2. 从 `prediction_archive/` 读取上期预测
3. 对比上期预测与实际开奖，计算差异调节系数
4. `train_lead_agent()` 执行24期回测差异学习，输出5个Agent权重
5. `build_expert_teams()` 生成各Agent候选注
6. `judge_with_lead_agent()` 融合为最终号码并归档

### 关键文件

| 文件 | 作用 |
|------|------|
| `predict.py` | 预测主脚本，含所有预测策略和融合逻辑 |
| `update_data.py` | 从500彩票网抓取开奖数据 |
| `manual_data_import.py` | 支持JSON/CSV/TXT格式手动导入 |
| `lottery_data.json` | 历史开奖数据（自动生成） |
| `prediction_archive/*.txt` | 每期精简预测归档 |

### 数据格式

```json
{
  "metadata": {"total_records": 100, "source": "500.com-real"},
  "records": [{"period": "2026032", "date": "2026-03-24", "red_balls": [1,3,11,18,31,33], "blue_ball": 2}]
}
```

### 归档格式 (`prediction_archive/YYYYNNN.txt`)

```
period=2026033
generated_at=2026-03-29 10:00:00
ticket_count=5
lead_summary=factor=1.00;mode=team;...
ticket1=02 03 13 23 25 30+08|hot,balanced,missing
```
