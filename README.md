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

**新增功能**：
- 🔬 **高级分析模块**：时间加权、关联分析、模式识别、遗传算法
- 🧠 **LSTM神经网络**：深度学习预测模型
- 🤖 **9-Agent团队模式**：多策略协同预测

## 功能特点

- ✅ **真实数据**：从500彩票网自动抓取最新开奖数据
- ✅ **增量更新**：智能合并新旧数据，保留完整历史
- ✅ **多策略预测**：支持9种预测策略（含3种新增高级策略）
- ✅ **团队协同**：9个AI Agent协同决策，动态权重融合
- ✅ **高级分析**：时间加权、关联分析、模式识别、遗传算法
- ✅ **深度学习**：可选LSTM神经网络预测（需安装TensorFlow）
- ✅ **简单易用**：命令行操作，无需复杂配置

## 快速开始

### 安装依赖

```bash
# 基础依赖
pip install playwright
playwright install chromium

# 可选：LSTM神经网络支持
pip install tensorflow numpy
```

### 基本使用流程

```bash
# 1. 更新数据（首次使用或开奖后）
python update_data.py

# 2. 运行预测（默认团队模式）
python predict.py

# 3. 使用高级分析
python predict.py --advanced
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
# 默认使用团队模式，生成5注
python predict.py

# 使用追热策略，生成3注
python predict.py --mode single --strategy hot --num 3

# 使用所有策略
python predict.py --mode single --all

# 使用高级综合分析
python predict.py --advanced

# 使用LSTM神经网络（需安装TensorFlow）
python predict.py --mode single --strategy lstm --num 3

# 查看帮助
python predict.py --help
```

**参数说明**：
- `--mode, -m`: 预测模式 (`single`=单策略, `team`=团队模式，默认team)
- `--strategy, -s`: 预测策略 (`hot`/`cold`/`missing`/`balanced`/`random`/`cycle`/`sum`/`zone`/`lstm`)
- `--num, -n`: 生成注数（默认5注）
- `--all, -a`: 使用所有策略
- `--advanced, -adv`: 使用高级综合分析
- `--learn-cycles`: 团队模式回看期数（默认24期）
- `--seed`: 随机种子（用于复现实验）
- `--weight-patch`: 显式指定权重补丁路径（未指定时自动尝试 `config/weight_patch.latest.json`）

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

### 4. analyze_archive.py - 归档分析与补丁导出

读取 `prediction_archive` 中的 `ticketN_explain_json`，输出贡献排行、双视角差异、建议权重增减量，并可导出 JSON/CSV/权重补丁。

```bash
# 基础分析
python analyze_archive.py --archive-dir prediction_archive

# 导出报告 + 写回最新补丁
python analyze_archive.py \
  --archive-dir prediction_archive \
  --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json
```

**参数说明**：
- `--recent-limit`: 最近N张票据视角（用于“最近N期 vs 全历史”对比）
- `--suggest-step`: 建议权重变动幅度上限（默认0.02）
- `--export-prefix`: 导出报告路径前缀（生成 `.json`/`.csv`/`.weight_patch.json`）
- `--latest-patch-path`: 固定写回最新补丁路径（默认 `config/weight_patch.latest.json`）

## 预测策略

### 基础策略（5种）

| 策略 | 名称 | 说明 |
|------|------|------|
| `hot` | 追热策略 | 选择近期出现频率最高的号码 |
| `cold` | 追冷策略 | 选择出现频率最低的号码 |
| `missing` | 高遗漏策略 | 选择长期未出现的号码 |
| `balanced` | 平衡策略 | 综合多种因素搭配号码（默认） |
| `random` | 随机策略 | 完全随机生成号码 |

### 高级策略（3种，新增）

| 策略 | 名称 | 说明 |
|------|------|------|
| `cycle` | 周期性策略 | 分析号码出现间隔的周期性规律 |
| `sum` | 和值趋势策略 | 基于历史平均和值±标准差预测 |
| `zone` | 区间平衡策略 | 分析1-11/12-22/23-33三区分布均衡 |

### 深度学习策略（1种，新增）

| 策略 | 名称 | 说明 |
|------|------|------|
| `lstm` | LSTM神经网络 | 使用深度学习模型学习时间序列模式 |

## 高级分析模块

### 综合分析（--advanced）

使用以下4种高级分析方法融合生成预测：

1. **时间加权分析** - 指数衰减权重，近期数据影响更大
2. **号码关联分析** - 马尔可夫链 + 共现频率分析
3. **模式识别** - 连号、同尾号、奇偶比、大小比、区间分布
4. **遗传算法优化** - 进化算法优化号码组合

```bash
python predict.py --advanced --num 5
```

### 团队模式（--mode team）

9个AI Agent协同工作：

1. 每个Agent基于不同策略生成候选注
2. 主Agent通过24期历史回测学习各Agent权重
3. 动态融合生成最终预测
4. 自动归档预测结果用于后续评估

```bash
python predict.py --mode team --num 5 --learn-cycles 24
```

## 数据文件

### lottery_data.json

存储历史开奖数据，自动创建和更新。

```json
{
  "metadata": {
    "total_records": 105,
    "date_range": "2025-07-24 至 2026-04-05",
    "last_updated": "2026-04-06 14:12:34",
    "source": "500.com-real",
    "is_real": true
  },
  "records": [
    {
      "period": "2026037",
      "date": "2026-04-05",
      "red_balls": [11, 22, 27, 29, 31, 33],
      "blue_ball": 12
    }
  ]
}
```

### prediction_archive/

预测归档目录，存储每期预测结果用于回测分析。

## 按场景速查表

| 场景 | 目标 | 推荐命令 |
|------|------|----------|
| 预测 | 日常团队预测（默认） | `python update_data.py`<br>`python predict.py --mode team --num 5` |
| 预测 | 单策略快速对比 | `python predict.py --mode single --all --num 3` |
| 预测 | 指定策略复现实验 | `python predict.py --mode single --strategy hot --num 3 --seed 42` |
| 分析 | 高级综合分析 | `python predict.py --advanced --num 5` |
| 分析 | 归档贡献分析与调参建议 | `python analyze_archive.py --archive-dir prediction_archive --recent-limit 20 --top-k 10` |
| 分析 | 导出报告 + 自动写回最新补丁 | `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report` |
| 补丁回灌 | 显式加载权重补丁预测 | `python predict.py --mode team --weight-patch config/weight_patch.latest.json --num 5` |
| 补丁回灌 | 默认自动发现并加载补丁 | `python predict.py --mode team --num 5` |
| 补丁回灌 | 关闭自动发现（无补丁文件时） | `python predict.py --mode team --num 5`（未提供 `--weight-patch` 且 `config/weight_patch.latest.json` 不存在） |

## 文件结构

```
lottery-predictor/
├── README.md                 # 本文档
├── SKILL.md                  # Claude技能文档
├── update_data.py            # 数据更新脚本
├── predict.py                # 预测主脚本
├── lstm_predictor.py         # LSTM神经网络模块（新增）
├── manual_data_import.py     # 手动数据导入
├── lottery_data.json         # 数据文件（自动创建）
└── prediction_archive/       # 预测归档目录
    └── 2026038.txt
```

## 技术说明

### 为什么这些方法"有趣"但不"有效"

1. **随机性本质**：双色球开奖是独立随机事件
2. **赌徒谬误**：认为"长期未出的号码即将出现"是认知偏差
3. **统计规律≠预测能力**：历史数据规律不代表未来走势
4. **大数定律**：短期预测无法突破概率极限

### 算法原理

#### 周期性分析（cycle）
- 分析每个号码的出现间隔
- 计算间隔的方差（方差越小，周期性越强）
- 预测即将到达周期点的号码

#### 和值趋势分析（sum）
- 计算历史平均和值和标准差
- 目标范围：平均和值 ± 1个标准差
- 选择能使和值落入目标范围的号码组合

#### 区间平衡分析（zone）
- 分析1-11（前区）、12-22（中区）、23-33（后区）分布
- 向理想分布2-2-2靠拢
- 优先选择偏少区域的热号

#### LSTM神经网络
- 输入：过去10期开奖（49维one-hot向量）
- 网络：2层LSTM + Dropout
- 输出：红球概率分布（33维）+ 蓝球概率（16维）

### 最佳实践

1. **定期更新数据**：开奖后运行 `python update_data.py`
2. **多样化尝试**：可以尝试不同策略增加乐趣
3. **理性购彩**：将预测视为娱乐，而非投资
4. **设定预算**：购彩金额不应超过娱乐预算
5. **组合策略**：团队模式比单策略更稳定

## 更新日志

- **2026-04-06**: 
  - 新增3个高级Agent：周期性(cycle)、和值趋势(sum)、区间平衡(zone)
  - 新增LSTM神经网络预测模块
  - 新增高级综合分析模块（时间加权、关联分析、模式识别、遗传算法）
  - 团队模式扩展至9个Agent
  - 优化蓝球预测逻辑
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
