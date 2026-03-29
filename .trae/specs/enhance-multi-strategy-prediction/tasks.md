# Tasks
- [x] Task 1: 设计 Agent Teams 与主Agent职责模型
  - [x] SubTask 1.1: 定义 3-5 个专家 Agent Teams 的输入输出契约
  - [x] SubTask 1.2: 定义主Agent的裁决输入、迭代学习输入与输出格式
  - [x] SubTask 1.3: 约束专家团队互不干扰并保留故障隔离机制

- [x] Task 2: 实现主Agent预测前差异学习流程
  - [x] SubTask 2.1: 读取上期精简预测结果与最新真实数据
  - [x] SubTask 2.2: 计算差异并生成主Agent迭代学习摘要
  - [x] SubTask 2.3: 将差异学习结果注入主Agent最终评判上下文

- [x] Task 3: 实现专家团队独立分析与结果交换
  - [x] SubTask 3.1: 在统一流程中调度各专家团队独立分析
  - [x] SubTask 3.2: 汇总各专家结果并提供给主Agent裁决
  - [x] SubTask 3.3: 保留每个专家的摘要结论用于可追溯展示

- [x] Task 4: 实现主Agent最终裁决与精简结果输出
  - [x] SubTask 4.1: 按主Agent规则生成最终预测号码集
  - [x] SubTask 4.2: 输出来源专家与主Agent评判摘要
  - [x] SubTask 4.3: 控制输出数据长度仅保留必要预测信息

- [x] Task 5: 增加精简预测结果文件夹与循环读取机制
  - [x] SubTask 5.1: 创建固定归档目录并按期写入精简预测文本
  - [x] SubTask 5.2: 新任务开始时优先读取上期精简预测用于差异对比
  - [x] SubTask 5.3: 保障读写失败时流程可降级继续执行

- [x] Task 6: 更新 Skills 文档并完成闭环回归验证
  - [x] SubTask 6.1: 更新 SKILL.md 描述新的多Agent闭环流程
  - [x] SubTask 6.2: 增加最小回归验证覆盖完整闭环主路径
  - [x] SubTask 6.3: 回归验证 update_data.py 与 manual_data_import.py 正常可用

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 2, Task 3
- Task 5 depends on Task 4
- Task 6 depends on Task 4, Task 5
