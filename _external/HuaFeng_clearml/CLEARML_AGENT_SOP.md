# HuaFeng + ClearML Agent SOP（不改原仓库）

本文以原项目路径 `/mnt/md0/zhouyunqi/HuaFeng` 为例，说明如何把它“拓展到可被 ClearML Agent 执行并可追溯”，且不修改原仓库代码。策略是：创建一个新的工作目录（本仓库里示例为 `_external/HuaFeng_clearml`），只复制 `src/` 和 `docs/`，不复制 `data/` 与 `outputs/`。

## 0. 是否有必要接入 Agent（适用边界）

适合接入（收益明显）：

- 你要在同一台多卡机上跑多份实验（不同站点/不同 forecast_index/不同特征窗口），希望用队列把任务丢出去并发跑
- 你希望每次运行自动沉淀：参数、Console、关键输出文件（模型/预测/评估报表），便于对比与回溯
- 你希望后续做“定时跑批”（每天/每小时），用同一套 SOP 复用

不适合或收益较小：

- 你只有一次性离线运行需求，且输出文件留在本地即可，不需要实验对比/审计
- 你无法提供“agent 能拉到的代码版本”（没有可访问的 Git 远端，也不想使用 `clearml-task` 打包上传）
- 你希望跨机器/容器复现，但当前项目大量使用绝对路径且缺少依赖锁定文件（需要额外工程化后才适合）

## 1. 落地目录与复制策略（不动原仓库）

原仓库体积很大（主要是 `data/`），不建议全量复制。推荐只复制代码与文档：

- 复制：`src/`、`docs/`、`.gitignore`
- 不复制：`data/`、`outputs/`、`.git/`

在本环境里，由于 `/mnt/md0/zhouyunqi` 上层目录无法新建同级目录（只读限制），示例工作目录放在：

- `clearml/_external/HuaFeng_clearml`

你在自己的机器上可把它放到与原仓库同级，例如：

- `/mnt/md0/zhouyunqi/HuaFeng_clearml`

## 2. 代码层改造点（只在复制目录里改）

新增两个 ClearML entry 脚本（不修改原有训练/流水线脚本）：

- 全链路：`src/scripts/clearml_run_full_pipeline_xgboost.py`
- 仅训练：`src/scripts/clearml_train_xgboost_wind.py`

它们做的事情：

- `Task.init(...)` 创建/绑定任务
- `task.execute_remotely(queue=...)` 把任务入队并结束本地进程
- 在远端真正执行时，通过 `subprocess` 调用原始脚本
- 执行完成后，把 `outputs/` 作为 artifact 上传（并从 `summary.csv` 中尽量解析数值指标上报为 Scalars）

## 3. 运行前置条件（必须满足）

### 3.1 ClearML 配置

- 提交机与执行机都需要 `~/clearml.conf`
- 必须能访问 `api_server/web_server/files_server`

### 3.2 代码可拉取（远程执行的硬要求）

当你使用 `task.execute_remotely(...)` 时，agent 会根据 Task 里记录的 `repository + commit_id` 拉代码，因此：

- 你的代码必须 push 到 agent 可访问的 Git 远端（GitHub / GitLab / 内网 Git）
- 仅本地 commit 不 push 会失败（agent checkout 不到 commit）

如果你不想 push 代码，可以改用 `clearml-task`（脚本打包上传，不依赖 git）。

### 3.3 数据可访问

本项目默认数据路径为 `/mnt/md0/zhouyunqi/HuaFeng/data`。远端执行必须满足：

- agent 运行机器能访问同样路径（同机执行最简单）
- 或者你为不同机器做路径映射（在 `clearml.conf` 中用 `sdk.storage.path_substitution`）

## 4. 标准执行 SOP（建议顺序）

1) 在 ClearML UI 创建队列（建议至少）：

- `cpu`
- `gpu`

2) 执行机启动 agent：

```bash
clearml-agent daemon --queue "cpu" --foreground
CUDA_VISIBLE_DEVICES=0 clearml-agent daemon --queue "gpu" --foreground
```

3) 提交机运行（会快速退出，表示已入队）：

全链路（默认输出到复制目录下的 `outputs/`）：

```bash
python src/scripts/clearml_run_full_pipeline_xgboost.py --clearml-queue gpu
```

仅训练：

```bash
python src/scripts/clearml_train_xgboost_wind.py --clearml-queue gpu --gpu_id 0
```

4) 在 ClearML Web UI 查看：

- Task 状态：Pending -> In Progress -> Completed
- Artifacts：包含 `outputs/`（模型、预测、评估）
- Scalars：如果 `summary.csv` 里存在可解析的数值字段，会自动上报到 `metrics/*`

## 5. 扩展到更广泛业务的 SOP（通用化模板）

对任意一个“脚本型项目”，用 Agent 接入时建议统一按下面模板评估与改造：

1) 找入口：选择一个“最靠近业务目标”的入口脚本（全链路/训练/评估），并明确输入输出目录
2) 做一个 ClearML entry：只新增一个 wrapper，不改核心逻辑
3) 记录三类资产：

- 参数：`task.connect(...)` 或把 CLI 参数记录下来
- 指标：有框架自动集成就用自动；没有就从输出报表里解析并 `logger.report_scalar`
- 产物：对输出目录/关键文件 `upload_artifact`

4) 处理三类复现约束：

- 代码：必须能从远端拉到 commit（或用 clearml-task 打包）
- 依赖：提供 requirements/conda env 导出，避免“今天能跑明天不能跑”
- 数据：同路径/可访问，或统一用 ClearML Dataset/存储映射

