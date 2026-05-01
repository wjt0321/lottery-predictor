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
- ♻️ **自学习闭环方向**：基于归档回测持续调权调参
- 🤖 **8-Agent团队模式**：先聚合核心号码池，再用旋转矩阵固定出票 5 注

## 功能特点

- ✅ **真实数据**：从500彩票网自动抓取最新开奖数据
- ✅ **增量更新**：智能合并新旧数据，保留完整历史
- ✅ **多策略预测**：支持8种预测策略（含3种新增高级策略）
- ✅ **团队协同**：8个AI Agent协同决策，聚合 10 球核心池后固定输出 5 注
- ✅ **高级分析**：时间加权、关联分析、模式识别、遗传算法
- ✅ **自学习闭环**：归档分析、权重补丁、参数补丁设计
- ✅ **简单易用**：命令行操作，无需复杂配置

## 快速开始

### 安装依赖

```bash
# 基础依赖
pip install playwright
playwright install chromium
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
# 默认使用团队模式，固定生成5注
python predict.py

# 使用追热策略，生成3注
python predict.py --mode single --strategy hot --num 3

# 使用所有策略
python predict.py --mode single --all

# 使用高级综合分析
python predict.py --advanced

# 查看帮助
python predict.py --help
```

**参数说明**：
- `--mode, -m`: 预测模式 (`single`=单策略, `team`=团队模式，默认team)
- `--strategy, -s`: 预测策略 (`hot`/`cold`/`missing`/`balanced`/`random`/`cycle`/`sum`/`zone`)
- `--num, -n`: 生成注数（`team` 模式固定输出 5 注，`single` 模式按传入值）
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

读取 `prediction_archive` 中的 `ticketN_explain_json`，并自动用本地 `lottery_data.json` 回填已开奖期的真实命中结果。分析器会输出命中贡献排行、双视角差异、建议权重增减量、矩阵行表现，并可导出报告与三类补丁；如果找不到真实结果，则回退为解释贡献统计。

```bash
# 基础分析
python analyze_archive.py --archive-dir prediction_archive

# 导出报告（生成 JSON / CSV / 三类 patch）
python analyze_archive.py \
  --archive-dir prediction_archive \
  --export-prefix prediction_archive/analysis_report

# 导出报告 + 写回最新补丁
python analyze_archive.py \
  --archive-dir prediction_archive \
  --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json \
  --latest-matrix-patch-path config/matrix_patch.latest.json \
  --latest-param-patch-path config/param_patch.latest.json
```

**参数说明**：
- `--recent-limit`: 最近N张票据视角（用于“最近N期 vs 全历史”对比）
- `--suggest-step`: 建议权重变动幅度上限（默认0.02）
- `--export-prefix`: 导出报告路径前缀，生成以下文件：
  - `.json`
  - `.csv`
  - `.weight_patch.json`
  - `.matrix_patch.json`
  - `.param_patch.json`
- `--latest-patch-path`: 固定写回最新权重补丁路径（默认 `config/weight_patch.latest.json`）
- `--latest-matrix-patch-path`: 固定写回最新矩阵补丁路径（默认 `config/matrix_patch.latest.json`）
- `--latest-param-patch-path`: 固定写回最新参数补丁路径（默认 `config/param_patch.latest.json`）

**补丁文件说明**：
- `weight patch`：用于调整 8 位专家的基础权重，优先基于真实命中贡献生成
- `matrix patch`：用于记录矩阵行表现与行权重
- `param patch`：用于回灌核心池大小、出票衰减参数和完整矩阵偏好顺序

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

### 团队模式与自学习闭环（--mode team）

`team` 模式是当前项目的主链路，由 8 个专家协同工作，并串联“出号 -> 归档 -> 分析 -> 补丁回灌”的闭环。

#### 1. 团队模式流程

1. 每个专家基于不同策略生成候选注
2. 主 Agent 通过历史回测学习专家权重
3. 系统聚合核心红球池和蓝球池
4. 使用固定旋转矩阵输出 5 注 `6+1`
5. 自动归档预测结果用于后续评估

#### 2. 旋转矩阵出票

- `team` 模式不再把专家提案直接随机打散成多注
- 系统会先汇总出 `10` 个核心红球与少量蓝球候选池
- 随后使用固定 `5` 行旋转矩阵，把核心池压缩为 `5` 注 `6+1`
- 这样可以尽量保留号码池价值，避免在拆票阶段把高价值号码关系随机稀释

#### 3. 自学习闭环

- 历史归档会保留每注解释信息，供后续回测分析
- `analyze_archive.py` 负责离线学习，当前可输出命中贡献排行、双视角差异、矩阵行表现以及三类补丁
- 分析器会根据本地真实开奖数据给旧归档临时补齐 `actual_result`，避免只按预测解释的“自我贡献”调权
- 当前闭环已经升级为“权重 + 矩阵 + 参数”联合学习

#### 4. 补丁回灌规则

- `predict.py` 在 `team` 模式下会自动尝试回灌最新补丁
- `weight patch`
  - 支持显式指定：`--weight-patch config/weight_patch.latest.json`
  - 未显式指定时，自动尝试 `config/weight_patch.latest.json`
- `param patch`
  - 当前不提供单独 CLI 参数
  - 默认自动尝试 `config/param_patch.latest.json`
- `matrix patch`
  - 当前不提供单独 CLI 参数
  - 默认自动尝试 `config/matrix_patch.latest.json`
- 如果相关文件不存在，系统会自动回退到内置默认配置

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

### config/*.latest.json

`config/` 目录用于保存当前默认回灌的最新补丁文件：

- `weight_patch.latest.json`
  - 记录专家基础权重与建议权重增减量
  - `predict.py` 可通过 `--weight-patch` 显式指定，或默认自动发现
- `matrix_patch.latest.json`
  - 记录矩阵行表现、行权重与偏好行顺序
  - `predict.py` 在 `team` 模式下默认自动发现并回灌
- `param_patch.latest.json`
  - 记录核心池大小、出票衰减参数与矩阵偏好参数
  - `predict.py` 在 `team` 模式下默认自动发现并回灌

如果这些文件不存在，系统会自动回退到内置默认配置，不会阻断预测。

### prediction_archive/analysis_report.*

当执行 `analyze_archive.py --export-prefix prediction_archive/analysis_report` 时，会生成一组分析产物：

- `analysis_report.json`
  - 结构化保存贡献排行、双视角差异、矩阵排行与建议项
- `analysis_report.csv`
  - 便于快速查看和外部处理的表格结果
- `analysis_report.weight_patch.json`
  - 本轮分析导出的权重补丁
- `analysis_report.matrix_patch.json`
  - 本轮分析导出的矩阵补丁
- `analysis_report.param_patch.json`
  - 本轮分析导出的参数补丁

这些文件是“本轮分析结果”，而 `config/*.latest.json` 是“当前默认回灌入口”。

## 按场景速查表

| 场景 | 目标 | 推荐命令 |
|------|------|----------|
| 预测 | 团队模式日常预测（默认主链） | `python update_data.py`<br>`python predict.py --mode team --num 5` |
| 预测 | 单策略快速对比 | `python predict.py --mode single --all --num 3` |
| 预测 | 指定策略复现实验 | `python predict.py --mode single --strategy hot --num 3 --seed 42` |
| 分析 | 高级综合分析 | `python predict.py --advanced --num 5` |
| 分析 | 归档贡献分析与调参建议 | `python analyze_archive.py --archive-dir prediction_archive --recent-limit 20 --top-k 10` |
| 分析 | 导出报告并写回三类补丁 | `python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report --latest-patch-path config/weight_patch.latest.json --latest-matrix-patch-path config/matrix_patch.latest.json --latest-param-patch-path config/param_patch.latest.json` |
| 补丁回灌 | 显式加载权重补丁参与团队预测 | `python predict.py --mode team --weight-patch config/weight_patch.latest.json --num 5` |
| 补丁回灌 | 默认自动回灌三类补丁 | `python predict.py --mode team --num 5` |
| 补丁回灌 | 补丁缺失时回退内置默认配置 | `python predict.py --mode team --num 5`（若 `config/*.latest.json` 不存在则自动回退） |

## 文件结构

```
lottery-predictor/
├── AGENT.md                  # 仓库内 Agent 工作说明
├── CLAUDE.md                 # Claude Code 仓库入口说明
├── README.md                 # 本文档
├── SKILL.md                  # Claude 技能文档
├── agent_registry.py         # 共享专家注册表
├── analyze_archive.py        # 归档分析与补丁导出
├── update_data.py            # 数据更新脚本
├── predict.py                # 预测主脚本
├── manual_data_import.py     # 手动数据导入
├── lottery_data.json         # 数据文件（自动创建）
├── config/
│   ├── weight_patch.latest.json  # 最新专家权重补丁
│   ├── matrix_patch.latest.json  # 最新矩阵补丁
│   └── param_patch.latest.json   # 最新参数补丁
└── prediction_archive/       # 预测归档目录
    ├── 2026038.txt
    └── analysis_report.*     # 导出的分析报告与补丁
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

#### 自学习闭环
- 输入：历史预测归档、真实开奖结果、专家贡献明细
- 学习对象：专家权重、矩阵行偏好、窗口参数、融合参数
- 输出：`weight_patch.latest.json`、`matrix_patch.latest.json`、`param_patch.latest.json`

### 最佳实践

1. **定期更新数据**：开奖后运行 `python update_data.py`
2. **多样化尝试**：可以尝试不同策略增加乐趣
3. **理性购彩**：将预测视为娱乐，而非投资
4. **设定预算**：购彩金额不应超过娱乐预算
5. **组合策略**：团队模式比单策略更稳定

## 更新日志

- **2026-04-21**:
  - 增加数据新鲜度保护与归档防覆盖，避免用旧数据预测或覆盖同期原始归档
  - 移除 `LSTM/TensorFlow` 主链依赖，团队模式稳定收敛到 8 个规则型专家
  - 团队模式升级为“核心号码池 + 旋转矩阵出票”，固定输出 5 注 `6+1`
  - 自学习闭环扩展到三类补丁：`weight patch`、`matrix patch`、`param patch`
  - `predict.py` 新增补丁自动回灌，形成“分析 -> 写回 -> 再预测”的闭环
  - 新增 `AGENT.md`，并同步更新 `CLAUDE.md` 与 README 文档入口
  - 修复 `update_data.py` 的数据范围显示顺序，统一为“旧日期 -> 新日期”
- **2026-04-06**: 
  - 新增3个高级Agent：周期性(cycle)、和值趋势(sum)、区间平衡(zone)
  - 新增高级综合分析模块（时间加权、关联分析、模式识别、遗传算法）
  - 团队模式扩展至8个Agent
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
