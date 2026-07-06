# ClearML 能力边界梳理与工作流落地 Spec

## Why
当前代码仓库同时包含 ClearML 源码与少量非官方 Demo，但缺少一份面向“预测类 ML 项目（data_pipeline + models + eval）全自动化”的 ClearML 能力边界说明，导致选型与落地路径不清晰。

## What Changes
- 新增一份可落地的《ClearML 能力边界与选型建议》Markdown 报告，基于：
  - 本仓库的 ClearML 源码与示例
  - ClearML 官方文档（https://clear.ml/docs/latest/docs/）
  - ClearML 官方 GitHub 组织（https://github.com/clearml）
- 报告需面向现有工作方式（本地 SSH 到服务器运行、通过 GitLab 分支/Issue 协作）给出“值得重视的能力边界”与“不可替代/不可指望的能力边界”。
- 报告需覆盖“实验自动化”场景：对单模型做多轮优化（超参、数据集/特征选择、模型结构改动等），以及跨模型比较并选择最优方案。
- 报告需对 ClearML 各能力点给出“值得探索程度评分”，以当前已成体系的项目与流程为判准：帮助越大分越高。
- Demo 不作为当前阶段的交付重点，仅在能力边界梳理完成后再按需补充。

## Impact
- Affected specs: Experiment Tracking / Remote Execution / Pipelines / Dataset & Model Management / Automation & Monitoring
- Affected code: 以新增文档为主（不修改 ClearML SDK 源码本身）

## Confirmed Boundaries

### Confirmed: ClearML 更像“ML 工作流控制面”
根据本仓库 `README.md`、官方文档首页以及 `Workers & Queues / Pipeline / HPO / ClearML Data` 页面，ClearML 的核心能力稳定落在以下几类：
- **记录与追踪**：Task / Logger / Artifacts / Models，用于记录代码、参数、环境、日志、指标、产物。
- **远程复现与分发**：Agent + Queue，用于从 Git 拉代码、还原环境、把任务派发到远端机器。
- **自动化编排**：PipelineController / PipelineDecorator / Scheduler / Trigger / HPO，用于任务克隆、定时触发、条件触发、超参搜索与 DAG 编排。
- **资产登记**：Dataset / Model Registry / Reports，用于数据集版本、模型版本、实验结果的索引与展示。

这意味着它天然适合充当“执行、记录、调度、审计”的平台层，而不是直接替代你现有业务代码中的数据处理逻辑、特征策略和评估口径。

### Confirmed: ClearML 不负责业务决策
在你的场景里，以下环节不应误判为 ClearML 原生能力：
- **需求分析**：甲方需求的拆解、优先级和验收定义依然需要人工完成。
- **策略生成**：新增哪些特征、删哪些脏数据、换哪类模型、采用哪种评估表口径，ClearML 不会替你做决策。
- **代码质量治理**：GitLab 分支策略、Issue 生命周期、Code Review、合并规范仍由 GitLab 与团队流程承担。
- **复杂业务胶水**：Issue/MR 触发实验、结果自动回写 GitLab 评论，这些可以接入 ClearML，但通常需要你自己写 webhook/CI/API 胶水层。

### Confirmed: ClearML 自动化依赖“可复现前提”
官方 Agent 文档与本仓库已有实践都显示，若要让自动化稳定成立，必须先满足这些硬条件：
- 代码必须存在于 Agent 可访问的远端仓库，而不是只在本地工作区。
- 依赖必须显式声明，不能依赖“服务器上刚好装过”的隐式环境。
- 数据路径必须跨节点可访问，或由对象存储/共享存储统一暴露。
- 任务参数、数据版本、评估入口最好参数化，否则后续 Pipeline / HPO / Trigger 很难做成稳定自动化。

## Scenario Fit

### Requirement: 面向预测型项目的适配判断
系统 SHALL 对 `data_pipeline + models + eval` 场景给出“强适配 / 中适配 / 弱适配”判断，而不是仅罗列功能。

#### Scenario: 适合优先投入的能力（成功）
- **WHEN** 团队目标是“尽量少人工介入地重跑实验、筛选模型、沉淀结果”
- **THEN** 报告应明确以下模块属于高价值核心能力：
  - **Task / Experiment Tracking**：用于把每次数据处理、训练、评估都变成可追溯运行记录。
  - **Agent / Queue**：用于替代 SSH 手工占机运行，形成 CPU / GPU 队列化执行。
  - **HPO**：用于围绕既有训练模板做超参空间搜索和批量比较。
  - **Reports / Model Registry**：用于沉淀最佳模型和面向甲方的对比结果。

#### Scenario: 需要谨慎投入的能力（成功）
- **WHEN** 团队尝试进一步把全流程改造成无人值守
- **THEN** 报告应明确以下模块属于“有价值但依赖工程成熟度”的能力：
  - **PipelineController / PipelineDecorator**：前提是 `data_pipeline`、`models`、`eval` 已经能被拆为稳定的独立步骤，并通过参数/Artifacts 连接。
  - **Trigger / Scheduler**：适合做周期性重跑或事件驱动重跑，但只是在 ClearML 内部提供触发器，不等同于完整的业务工作流平台。
  - **Dataset**：适合数据版本追溯需求强、数据可被对象存储化管理的团队；如果你们主要依赖共享盘和固定路径，初期不宜重投入。

#### Scenario: 当前不应高优先级投入的能力（成功）
- **WHEN** 团队当前目标仍是先打通离线实验与自动评估闭环
- **THEN** 报告应明确以下能力属于低优先级外围探索：
  - **Serving**：偏在线服务部署，不是当前离线预测和结果交付的核心瓶颈。
  - **Cloud / K8s Orchestration**：偏大规模基础设施治理，对单机多卡服务器不是当前主矛盾。

## Decision Output

### Requirement: 给出可执行的选型结论
系统 SHALL 在 spec 中输出明确的选型建议，而非停留在“功能介绍”。

#### Scenario: 形成推荐实施顺序（成功）
- **WHEN** 用户基于 spec 决定是否继续实施
- **THEN** 能得到一个清晰的优先级序列：
  1. **先上 Task / Logger / Model / Report**，把每次数据、训练、评估记录下来。
  2. **再上 Agent / Queue**，把 SSH 手工跑改为队列化远程执行。
  3. **然后上 HPO**，把“换参数反复跑”的人工操作批量化。
  4. **最后再评估 Pipeline / Trigger / Scheduler / Dataset**，只对高频、稳定、已参数化的流程做自动编排。

#### Scenario: 形成边界判断（成功）
- **WHEN** 用户评估 ClearML 是否能支撑“几乎全自动”
- **THEN** spec 必须得出以下边界结论：
  - **能自动化**：任务记录、远程执行、批量调参、结果汇总、部分流程编排、部分条件/定时触发。
  - **不能自动化替代**：需求理解、特征/模型策略设计、业务规则解释、GitLab 协作治理、跨系统审批。
  - **需要额外建设胶水层**：GitLab Issue/MR 触发、结果回写、审批门禁、与企业内部数据平台/制表流程的深度集成。

## ADDED Requirements

### Requirement: ClearML 能力边界报告
系统 SHALL 在仓库中新增一份 Markdown 报告，系统性说明 ClearML 的能力边界，并以“预测类项目全自动工作流”为中心进行映射。

#### Scenario: 内容覆盖（成功，重点）
- **WHEN** 用户阅读报告
- **THEN** 能快速且深入地回答以下核心问题：
  - **ClearML 核心模块的定位与场景映射**：
    - 分类详述 Experiment, Agent, Pipelines, Datasets, Models, Reports, Serving, Orchestration 等模块各自的核心机制。
    - 精准映射到 `data_pipeline`（数据清洗/特征工程）、`models`（模型训练与调优）、`eval`（结果评估）等具体业务阶段。
  - **自动化环节的收益分析**：
    - 在本场景下，每个模块能具体替代哪些纯人工操作（例如：免去手动配置环境、自动记录并可视化多轮超参组合、自动对比不同模型/特征路线的 Eval 结果并高亮最优项）。
  - **落地的前置条件与基础设施要求**：
    - 清单化列出每个模块运转的硬性要求（例如：代码必须 Push 到 Agent 可访问的 GitLab 分支、环境依赖需显式声明、SSH 节点需正确配置 Worker 队列、数据集的远端存储权限等）。
  - **能力边界与“不适用”场景（避坑指南）**：
    - 明确界定 ClearML **明确做不到** 或 **不适合由它主导** 的事情（例如：业务侧特征生成策略的构思、模型网络架构的创新设计、甲方特定业务约束的解释权等，明确这些仍需人工在前期定义好）。
  - **与现有 GitLab + Issue 工作流的深度对接方案**：
    - 阐述如何将 GitLab 上的代码版本变更作为自动化实验的触发源。
    - 阐述如何将 ClearML 的 Eval 对比结果、最佳模型图表或报告链接，自动回写/总结到 GitLab 的 Issue 中，实现需求验收的闭环。
  - **（核心重点）每个能力点的“值得探索程度”深度评分与落地分析**：
    - **评分基准**：严格以“对目前成体系的项目、成型的代码流程和实验思路而言，帮助越大分越高”为判准。
    - **详尽理由**：结合“代码侵入度（是否只需加两行代码）”、“实验效率提升度（节省的纯调参/对比时间）”、“现有流程兼容性”进行全方位论证。
    - **落地门槛**：评估团队的学习成本、环境搭建成本，以及对现有工程结构的改造阵痛期。
    - **篇幅要求**：该部分（模块能力深度剖析与评分）必须极为详实，**占整个报告总篇幅的 70% 以上**。

### Requirement: 值得探索程度评分
系统 SHALL 在报告中对每个 ClearML 能力点给出评分与理由，评分应可复用为团队内部的技术决策依据。

#### Scenario: 评分可落地（成功）
- **WHEN** 用户按评分挑选 1-3 个能力点优先验证
- **THEN** 报告提供：
  - 分值（例如 0-5 或 0-10）、评分理由（收益/成本/风险/前置条件）
  - 推荐验证顺序与“最小验证标准”（看见什么现象算验证成功）

## MODIFIED Requirements
无

## REMOVED Requirements
无
