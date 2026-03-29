# Claude Code Skills 多Agent团队融合预测增强 Spec

## Why
当前仓库是一个 Claude Code Skills 形式的双色球娱乐预测工具，已具备“抓取新数据 + 增量保存 + 基础预测”闭环。为了进一步提升极客化与可进化能力，需要引入多Agent团队协作与主Agent差异学习机制，让预测形成可循环迭代流程。

## What Changes
- 设计 3-5 个相互独立的资深专家 Agent Teams，各自基于统一数据输入进行独立研究分析。
- 增加主Agent角色，负责整合专家结论并拥有最终裁决权输出最终预测。
- 增加主Agent任务前差异学习流程：每次新任务开始前，对比上次预测结果与真实开奖结果并生成差异迭代结论。
- 增加端到端编排流程：数据采集 -> 主Agent差异迭代 -> 专家团队独立分析 -> 结果汇总交换 -> 主Agent最终评判输出。
- 增加精简预测结果存档目录，按期保存短文本结果，供下一轮预测直接读取使用。
- 保持 `SKILL.md` 现有调用方式兼容，不改变“更新数据 -> 预测”的技能使用路径。

## Impact
- Affected specs: Agent 团队协作、主Agent差异学习、预测融合裁决、精简结果循环存档
- Affected code: `predict.py`、`SKILL.md`、`update_data.py`（流程衔接）、新增预测归档目录与最小结果文件读写模块

## ADDED Requirements
### Requirement: 专家 Agent Teams 独立分析
系统 SHALL 支持 3-5 个资深专家 Agent Teams 在同一轮任务中独立运行，互不共享中间推理状态。

#### Scenario: 多专家并行研究
- **WHEN** 用户在 Skills 流程中触发预测
- **THEN** 系统向每个专家 Agent Teams 提供统一输入数据
- **THEN** 各专家独立产出候选结果与理由摘要
- **THEN** 任一专家失败不影响其余专家完成分析

### Requirement: 主Agent最终裁决
系统 SHALL 提供单一主Agent负责接收专家团队结果并输出最终裁决结果。

#### Scenario: 专家结果汇总后裁决
- **WHEN** 专家 Agent Teams 都完成或超时结束
- **THEN** 系统将各专家结果交换并汇总给主Agent
- **THEN** 主Agent基于既定裁决规则输出唯一最终结果集

### Requirement: 主Agent差异学习迭代
系统 SHALL 在每次新任务开始前由主Agent执行“上次预测 vs 最新真实结果”差异对比与学习迭代。

#### Scenario: 预测前差异分析
- **WHEN** 系统已存在上一期精简预测存档且已采集到新一期真实数据
- **THEN** 主Agent计算预测差异并生成迭代摘要
- **THEN** 主Agent在最终裁决阶段引用该迭代结论调节评判权重

### Requirement: 精简预测结果循环存档
系统 SHALL 将每次最终预测结果以精简文本格式保存到指定目录，供下一轮直接读取。

#### Scenario: 预测结果入档
- **WHEN** 主Agent输出当期最终结果
- **THEN** 系统在固定文件夹按期号写入精简预测结果文本
- **THEN** 文本仅保存必要预测号码与最小元数据，避免冗长内容

### Requirement: 端到端闭环编排
系统 SHALL 按固定顺序执行完整闭环：采集数据 -> 主Agent差异学习 -> 专家独立分析 -> 结果交换 -> 主Agent裁决 -> 精简结果存档。

#### Scenario: 完整闭环执行成功
- **WHEN** 用户触发一次标准预测流程
- **THEN** 系统按顺序执行全部环节并输出最终结果
- **THEN** 下一轮预测可直接读取历史精简结果与真实数据进行差异学习

## MODIFIED Requirements
### Requirement: 预测执行入口
系统 SHALL 将现有流程升级为“数据采集 -> 主Agent差异学习 -> 多专家分析 -> 主Agent裁决 -> 结果存档”，并保持既有 Skills 调用方式兼容。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次变更为能力增强，不删除当前数据抓取与导入能力。
**Migration**: 无需迁移，现有命令入口继续可用。
