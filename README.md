# 双色球彩票预测工具

<div align="center">

# 🎱 双色球彩票预测工具

### ⚠️ 本工具仅供娱乐，不构成任何投注建议 ⚠️

**彩票本质上是随机游戏，任何预测方法都不能保证中奖。请理性购彩，量力而行。**

**如因违反娱乐用途使用本工具，使用者需自行承担全部责任**

</div>

---

## 🙏 特别感谢

### 数据来源

本项目的数据抓取功能依赖于以下网站提供的公开数据：

- **[500彩票网](https://datachart.500.com/ssq/history/history.shtml)** - 提供双色球历史开奖数据

感谢500彩票网为广大彩民提供的便利数据服务！

---

## 简介

这是一个基于历史数据统计的双色球彩票预测工具，使用多种算法策略生成号码推荐。数据来源于500彩票网的真实开奖记录。

## 功能特点

- ✅ **真实数据**：从500彩票网自动抓取最新开奖数据
- ✅ **增量更新**：智能合并新旧数据，保留完整历史
- ✅ **多策略预测**：支持追热、追冷、高遗漏、平衡、随机等多种策略
- ✅ **简单易用**：命令行操作，无需复杂配置

## 快速开始

### 安装依赖

```bash
pip install playwright
playwright install chromium
```

### 基本使用流程

```bash
# 1. 更新数据（首次使用或开奖后）
python update_data.py

# 2. 运行预测
python predict.py
```

## 脚本说明

### 1. update_data.py - 数据更新脚本

从500彩票网抓取最新开奖数据，增量更新到本地数据库。

```bash
python update_data.py
```

**特点**：
- 自动增量更新（只添加新数据，保留历史数据）
- 从500彩票网获取真实开奖数据
- 自动去重和排序

### 2. predict.py - 预测脚本

基于历史数据进行号码预测。

```bash
# 默认使用平衡策略，生成5注
python predict.py

# 使用追热策略，生成3注
python predict.py --strategy hot --num 3

# 使用所有策略
python predict.py --all

# 查看帮助
python predict.py --help
```

**参数说明**：
- `--strategy, -s`: 预测策略 (`hot`/`cold`/`missing`/`balanced`/`random`)
- `--num, -n`: 生成注数（默认5注）
- `--all, -a`: 使用所有策略

### 3. manual_data_import.py - 手动数据导入

从外部文件导入历史数据。

```bash
# 导入JSON格式
python manual_data_import.py --json data.json

# 导入CSV格式
python manual_data_import.py --csv data.csv

# 导入TXT格式
python manual_data_import.py --txt data.txt
```

## 预测策略

| 策略 | 名称 | 说明 |
|------|------|------|
| `hot` | 追热策略 | 选择近期出现频率最高的号码 |
| `cold` | 追冷策略 | 选择出现频率最低的号码 |
| `missing` | 高遗漏策略 | 选择长期未出现的号码 |
| `balanced` | 平衡策略 | 综合多种因素搭配号码（默认） |
| `random` | 随机策略 | 完全随机生成号码 |

## 数据文件

### lottery_data.json

存储历史开奖数据，自动创建和更新。

```json
{
  "metadata": {
    "total_records": 100,
    "date_range": "2025-07-24 至 2026-03-24",
    "last_updated": "2026-03-25 09:31:29",
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

## 使用示例

### 日常预测

```bash
# 更新数据后运行预测
python update_data.py
python predict.py
```

### 使用特定策略

```bash
# 追热策略，生成3注
python predict.py --strategy hot --num 3
```

### 全面预测

```bash
# 使用所有策略，每种生成2注
python predict.py --all --num 2
```

## 文件结构

```
lottery-predictor/
├── README.md              # 本文档
├── SKILL.md               # Claude技能文档
├── update_data.py         # 数据更新脚本
├── predict.py             # 预测脚本
├── manual_data_import.py  # 手动数据导入
└── lottery_data.json      # 数据文件（自动创建）
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

## 更新日志

- **2026-03-25**: 初始版本发布，支持数据自动更新和多策略预测

## 许可证

MIT License

---

<div align="center">

### ⚠️ 重要声明 ⚠️

**本工具仅供娱乐用途**

**不得用于任何形式的赌博、博彩或其他非法活动**

**如因违反上述规定使用本工具，使用者需自行承担全部法律责任**

**彩票中奖是小概率事件，请理性购彩，量力而行！**

</div>
