---
name: "lottery-predictor"
description: "Provides entertaining Double Color Ball (双色球) lottery number predictions using statistical analysis and machine learning algorithms. Invoke when user asks for lottery predictions, number recommendations, or wants to analyze lottery trends."
---

# 双色球彩票预测器 (Double Color Ball Predictor)

> **⚠️ 免责声明**：本工具仅供娱乐，不构成任何投注建议。彩票本质上是随机游戏，任何预测方法都不能保证中奖。请理性购彩，量力而行。

## 快速开始

### 完整使用流程

```bash
# Step 1: 更新真实数据
python update_data.py

# Step 2: 运行预测
python predict.py

# 或者使用特定策略
python predict.py --strategy hot --num 3
```

## 脚本说明

### 1. 数据更新脚本 (`update_data.py`)

**功能**：从500彩票网抓取最新开奖数据，增量更新到本地数据库

**使用方法**：
```bash
python update_data.py
```

**输出示例**：
```
============================================================
🔄 双色球数据更新工具
============================================================
📁 现有数据: 100 期

📡 正在从500彩票网获取数据...
✅ 获取到 100 条数据
✅ 新增 0 条记录
📊 当前共 100 条记录

💾 数据已保存到 lottery_data.json
📅 数据范围: 2025-07-24 至 2026-03-24
============================================================
```

**特点**：
- ✅ 自动增量更新（只添加新数据，保留历史数据）
- ✅ 从500彩票网获取真实开奖数据
- ✅ 自动去重和排序

### 2. 预测脚本 (`predict.py`)

**功能**：基于历史数据进行号码预测，支持单策略与多 Agent 团队协同，并自动归档精简预测结果

**使用方法**：
```bash
# 默认使用多 Agent 团队模式，生成5注
python predict.py

# 使用单策略模式（追热），生成3注
python predict.py --mode single --strategy hot --num 3

# 使用团队模式并固定随机种子（便于复现）
python predict.py --mode team --num 3 --seed 42

# 使用所有策略
python predict.py --mode single --all

# 查看帮助
python predict.py --help
```

**参数说明**：
- `--mode, -m`: 预测模式（`team`/`single`，默认 `team`）
- `--strategy, -s`: 预测策略 (`hot`/`cold`/`missing`/`balanced`/`random`)
- `--num, -n`: 生成注数（默认5注）
- `--all, -a`: 在 `single` 模式下使用所有策略
- `--learn-cycles`: 主 Agent 差异学习回看期数（仅 `team` 模式生效，默认24）
- `--seed`: 随机种子，用于复现实验结果

**输出示例**：
```
============================================================
🎱 双色球预测结果
============================================================

📊 基于 100 期历史数据
📅 数据范围: 2025-07-24 至 2026-03-24
🕐 数据更新时间: 2026-03-25 09:13:56

🔥 热号TOP10: 03 13 09 22 30 18 23 02 25 01
❄️ 冷号BOTTOM10: 17 26 15 05 04 11 21 08 12 14

============================================================
🎯 预测号码
============================================================

🤖 多Agent团队模式（回看 24 期进行差异学习）
🧠 主Agent差异学习: 上期命中：红球 2 个，蓝球未命中，差异调节系数 1.00。
👑 主Agent学习权重:
  - balanced 权重 0.274 | 差异均值 +0.181
  - hot      权重 0.228 | 差异均值 +0.062
  - missing  权重 0.191 | 差异均值 -0.011
  ...

团队融合结果:
  第1注: 红球 02 03 13 23 25 30 + 蓝球 08 | 来源 hot,balanced,missing
  第2注: 红球 01 02 03 09 23 30 + 蓝球 10 | 来源 hot,cold,balanced
  ...

💾 已归档本期精简预测: prediction_archive/2026033.txt

⚠️ 仅供娱乐，不构成投注建议！
============================================================
```

### 3. 手动数据导入 (`manual_data_import.py`)

**功能**：从外部文件导入历史数据

**使用方法**：
```bash
# 导入JSON格式
python manual_data_import.py --json data.json

# 导入CSV格式
python manual_data_import.py --csv data.csv

# 导入TXT格式
python manual_data_import.py --txt data.txt
```

## 预测策略说明

### 1. 追热策略 (`hot`)

基于最近30期数据统计，选择出现频率最高的号码。

**原理**：认为热号有延续趋势

### 2. 追冷策略 (`cold`)

选择出现频率最低的号码。

**原理**：认为冷号即将回补

### 3. 高遗漏策略 (`missing`)

选择长期未出现的号码（遗漏值大）。

**原理**：认为遗漏值大的号码即将开出

### 4. 平衡策略 (`balanced`)

综合热号、冷号、高遗漏号码进行搭配。

**原理**：兼顾多种可能性

### 5. 完全随机 (`random`)

使用随机数生成号码。

**原理**：彩票本质是随机游戏

### 6. 多 Agent 团队模式 (`team`)

由 `hot/cold/missing/balanced/random` 五个子 Agent 同时给出提案，主 Agent 基于近期历史进行差异学习后动态赋权，再将各 Agent 投票融合为最终号码。

**原理**：
1. **多视角提案**：不同策略提供互补候选池；
2. **主 Agent 差异学习**：按“单轮得分 - 团队均值”更新权重；
3. **权重融合采样**：红球按加权无放回采样，蓝球按加权采样。

## 主Agent闭环迭代

每次执行 `python predict.py --mode team` 时，系统会按以下顺序运行：

1. 读取最新真实开奖数据；
2. 从 `prediction_archive` 读取上一期精简预测结果；
3. 主Agent执行“上期预测 vs 最新真实数据”差异学习；
4. 5 个专家 Agent Teams 独立给出候选结果；
5. 主Agent汇总专家结果并给出最终裁决；
6. 将当期最终预测写入下一期的精简归档文件。

## 数据文件

### 数据格式 (`lottery_data.json`)

```json
{
  "metadata": {
    "total_records": 100,
    "date_range": "2025-07-24 至 2026-03-24",
    "last_updated": "2026-03-25 09:13:56",
    "source": "500.com-real",
    "is_real": true
  },
  "records": [
    {
      "period": "2026032",
      "date": "2026-03-24",
      "red_balls": [1, 3, 11, 18, 31, 33],
      "blue_ball": 2
    }
  ]
}
```

### 数据来源

- **主要来源**：500彩票网 (datachart.500.com)
- **数据类型**：真实开奖记录
- **更新频率**：每周二、四、日开奖后

### 精简预测归档 (`prediction_archive/*.txt`)

每个文件按期号命名，只保留必要信息：
- 预测目标期号
- 生成时间
- 注数与每注红蓝球
- 来源专家与主Agent摘要

## 完整工作流程

### 首次使用

```bash
# 1. 获取历史数据
python update_data.py

# 2. 团队预测（默认）
python predict.py

# 3. 单策略全量对比（可选）
python predict.py --mode single --all
```

### 日常使用

```bash
# 每次预测前更新数据（可选）
python update_data.py

# 运行团队预测
python predict.py
```

### 批量预测

```bash
# 团队模式批量预测
python predict.py --mode team --num 3

# 单策略模式批量对比
python predict.py --mode single --all --num 3
```

## 技术说明

### 为什么这些方法"有趣"但不"有效"

1. **随机性本质**：双色球开奖是独立随机事件
2. **赌徒谬误**：认为"长期未出的号码即将出现"是认知偏差
3. **统计规律≠预测能力**：历史数据规律不代表未来走势

### 最佳实践

1. **定期更新数据**：开奖后运行 `python update_data.py`
2. **多样化尝试**：可以尝试不同策略增加乐趣
3. **理性购彩**：将预测视为娱乐，而非投资
4. **设定预算**：购彩金额不应超过娱乐预算

## 文件结构

```
lottery-predictor/
├── SKILL.md                    # 本文档
├── README.md                   # 项目说明文档
├── update_data.py              # 数据更新脚本
├── predict.py                  # 预测脚本
├── manual_data_import.py       # 手动数据导入
├── lottery_data.json           # 数据文件（自动创建）
└── prediction_archive/         # 精简预测归档目录（自动创建）
```

## 示例场景

### 场景1：日常预测

```bash
$ python update_data.py
✅ 数据已更新

$ python predict.py
🎱 预测结果...
```

### 场景2：使用特定策略

```bash
$ python predict.py --strategy hot --num 3
🎯 追热策略预测...
```

### 场景3：全面预测

```bash
$ python predict.py --all --num 2
🎯 所有策略预测...
```

---

**再次提醒**：彩票中奖是小概率事件，请理性购彩，量力而行。本工具仅供娱乐！
