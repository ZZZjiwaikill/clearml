# ClearML Agent 指引（Linux 单机多卡）

这份文档面向“我已经能用 `Task.init()` 记录实验，但想把任务丢到远端机器/队列上跑”的场景，聚焦 ClearML 自带的 `clearml-agent`：它如何工作、你需要准备什么、如何启动与治理队列、以及常见问题如何排查。

仓库里也有两份官方入门教程 Notebook，可以配合阅读：

- `docs/tutorials/Getting_Started_2_Setting_Up_Agent.ipynb`：安装与启动 Agent
- `docs/tutorials/Getting_Started_3_Remote_Execution.ipynb`：SDK 下发任务到队列、Agent 拉取执行

## 1. 一句话理解 Agent

- `clearml-agent` 是“执行器”：它常驻在一台计算机上，持续监听某个队列（Queue），一旦队列里出现待执行的 Task，就拉取代码/环境/配置并执行，然后把日志、指标和产物回传到 ClearML Server。
- 它不等同于“调度系统”：队列如何划分、哪些机器对应哪些队列、GPU 如何分配，主要靠你用“队列治理 + 部署方式”来实现。

## 2. 核心概念（建议先对齐）

- Task：一次可复现的实验运行记录，也是远程执行的基本单元
- Queue：任务队列。任务被 enqueue 到队列；Agent 监听队列并拉取任务执行
- Agent：跑在执行机上的进程（通常常驻），可以监听一个或多个队列
- Worker/Slot（非强制概念）：你可以把“一个 Agent 进程”理解为一个 worker；在单机多卡场景，通常会启动多个 Agent 实例来形成多个执行 slot

补充阅读（Task 本身的能力边界与最佳实践）：[CLEARML_TASK_GUIDE.md](file:///mnt/md0/zhouyunqi/clearml/CLEARML_TASK_GUIDE.md)

## 3. 前置准备（Agent 启动前必须具备）

### 3.1 ClearML Server 三个地址可访问

你需要确认 Agent 所在机器能访问：

- Web Server（网页 UI）
- API Server（任务与元数据 API）
- Files Server（上传/下载 artifacts、models 的文件服务）

仓库提供了配置样例，可参考 [clearml.conf](file:///mnt/md0/zhouyunqi/clearml/docs/clearml.conf#L2-L16)。

### 3.2 准备 Access Key / Secret Key

- 在 ClearML Web UI 创建（或获取）你的 Access Key / Secret Key
- 不要把真实 key 提交进仓库

配置样例中也有提示，见 [clearml.conf](file:///mnt/md0/zhouyunqi/clearml/docs/clearml.conf#L12-L13)。

### 3.3 执行机的基础网络能力

Agent 执行任务时通常需要：

- 能访问代码仓库（Git）或能直接访问你提交到 ClearML 的代码包
- 能访问 Python 包源（pip）或你自己的离线/内网镜像源
- 能访问数据所在的存储（本地盘 / NAS / S3 等），否则任务即使被拉起也会在数据加载阶段失败

## 4. 配置文件（SDK 与 Agent 通用）

### 4.1 放置位置与推荐做法

通常把配置放在执行机用户目录：

- `~/clearml.conf`

仓库提供了样例：`docs/clearml.conf`（旧命名样例在 `docs/trains.conf`，一般不再建议使用）。

### 4.2 最小可用配置（示例）

把下面字段补齐即可跑通 Agent 的认证与通信（字段名与结构以样例为准）：

```conf
api {
  web_server: "https://<your-clearml-web>"
  api_server: "https://<your-clearml-api>"
  files_server: "https://<your-clearml-files>"

  credentials {
    access_key: "<access_key>"
    secret_key: "<secret_key>"
  }
}
```

完整字段（含缓存、存储映射等）参考 [clearml.conf](file:///mnt/md0/zhouyunqi/clearml/docs/clearml.conf)。

### 4.3 存储路径映射（多机环境常见痛点）

如果你有“同一份数据/模型，在不同机器上挂载路径不同”的情况，优先使用 `sdk.storage.path_substitution` 做路径替换映射，避免在代码里写一堆 if/else。

样例见 [clearml.conf](file:///mnt/md0/zhouyunqi/clearml/docs/clearml.conf#L66-L78)。

## 5. 安装与启动 Agent（Linux 物理机）

### 5.1 安装

参考教程 Notebook 的命令示例：

```bash
pip install --upgrade clearml-agent
```

对应位置见 [Getting_Started_2_Setting_Up_Agent.ipynb](file:///mnt/md0/zhouyunqi/clearml/docs/tutorials/Getting_Started_2_Setting_Up_Agent.ipynb#L145-L147)。

建议（非强制）：

- 用独立 venv/conda 环境来安装 agent，避免污染系统 Python
- 把 agent 的运行用户与训练用户保持一致（特别是需要访问本地数据盘/NFS 时）

### 5.2 前台启动（最适合第一次验证）

```bash
clearml-agent daemon --queue "default" --foreground
```

对应位置见 [Getting_Started_2_Setting_Up_Agent.ipynb](file:///mnt/md0/zhouyunqi/clearml/docs/tutorials/Getting_Started_2_Setting_Up_Agent.ipynb#L155-L171)。

你应该能在日志里看到：

- 成功连接到 API Server
- 监听队列 `default`
- 当队列里出现任务时开始拉取并执行

### 5.3 常驻启动（建议用 systemd 托管）

如果你希望 Agent 在机器重启后自动拉起，推荐用 systemd（示例仅供参考，按你的 Python 环境路径调整）：

```ini
[Unit]
Description=ClearML Agent (default queue)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h
ExecStart=/usr/bin/env clearml-agent daemon --queue "default" --foreground
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

关键点：

- 尽量让 Agent 在前台运行并交给 systemd 管理（`--foreground`），避免后台守护进程难排障
- 如果你用 venv/conda，确保 `ExecStart` 能拿到正确的 `clearml-agent` 可执行文件

## 6. 队列（Queue）怎么设计：从“能跑”到“好用”

### 6.1 最小可用：先跑通一个 default

第一次建议只做两件事：

- 让 agent 监听一个队列（例如 `default`）
- 从 SDK 或 UI 往这个队列塞一个任务，确认任务会被拉起并完成

### 6.2 推荐的队列划分方式（单机 CPU + 10 GPU）

在单机多卡上，队列建议尽量少、语义清晰：

- `cpu`：CPU-only 任务（数据处理、推理、轻量训练）
- `gpu`：单卡/常规 GPU 训练
- `gpu-ddp`（可选）：明确要求多卡的任务（DDP 等），避免它们被“一卡一任务”的 agent 实例误接走

### 6.3 单机多卡的实用落地方式（推荐：10 个 agent 实例 + 限制可见 GPU）

ClearML Agent 本身更像“从队列取任务并跑”的执行器。要在单机 10 卡上把并发跑满，常见做法是启动多个 agent 实例，并在服务层面限定 GPU 可见性：

- agent-0：`CUDA_VISIBLE_DEVICES=0`
- agent-1：`CUDA_VISIBLE_DEVICES=1`
- …

这样每个任务在其对应 agent 进程内只能看到指定 GPU，从而实现“一卡一任务”的粗粒度隔离。

如果你希望“开机自启 + 10 实例常驻”，推荐用 systemd 的模板服务（`@` 实例化）：

```ini
[Unit]
Description=ClearML Agent (gpu queue) - gpu %i
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h
Environment=CUDA_VISIBLE_DEVICES=%i
ExecStart=/usr/bin/env clearml-agent daemon --queue "gpu" --foreground
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用方式（示例）：

- 启动 0-9 共 10 个实例：`systemctl enable --now clearml-agent-gpu@{0..9}`
- 查看单个实例日志：`journalctl -u clearml-agent-gpu@3 -f`

如果你有多卡任务（DDP 等），建议单独准备：

- 一个 `gpu-ddp` 队列
- 少量“允许看到多张卡”的 agent 实例（不要设置 `CUDA_VISIBLE_DEVICES` 或设置为多卡列表）

## 7. 任务如何进入队列（两种主流方式）

### 7.1 方式一：在代码里把当前任务远程化（最常用）

如果你的脚本本来就是 ClearML Task（已 `Task.init()`），最常见是直接：

```python
from clearml import Task

task = Task.init(project_name="demo", task_name="train", output_uri=True)
task.execute_remotely(queue_name="gpu", exit_process=True)
```

这会把任务 enqueue 到 `gpu` 队列，然后本地进程退出，等待 agent 在远端拉起执行。

### 7.2 方式二：克隆一个已有 Task，再入队（适合做批量参数变体）

教程 Notebook 给了完整流程（获取 Task → clone → update_parameters → enqueue），参考：

- [Getting_Started_3_Remote_Execution.ipynb](file:///mnt/md0/zhouyunqi/clearml/docs/tutorials/Getting_Started_3_Remote_Execution.ipynb#L235-L287)

这种方式的优点是：

- 原任务作为“基线”保留不动
- 每次变体都有独立 Task 记录，方便对比与审计

## 8. 运行期行为：你应该预期什么

- 第一次远程执行通常更慢：需要拉代码、安装依赖、初始化缓存；后续复跑会快很多（教程也有说明，见 [Getting_Started_3_Remote_Execution.ipynb](file:///mnt/md0/zhouyunqi/clearml/docs/tutorials/Getting_Started_3_Remote_Execution.ipynb#L358-L358)）
- Task 状态流转：Pending / In Progress / Completed / Failed（见 [Getting_Started_3_Remote_Execution.ipynb](file:///mnt/md0/zhouyunqi/clearml/docs/tutorials/Getting_Started_3_Remote_Execution.ipynb#L346-L353)）
- 日志与指标回传：
  - Console（stdout/stderr）通常自动上报
  - Scalars/Plots/Artifacts 是否上报取决于你是否使用了 ClearML 的 Logger / 框架自动集成 / 显式 upload

## 9. 常见问题排查（按出现频率排序）

### 9.1 Agent 启动了但不拿任务

优先检查：

- 监听的队列名是否一致（agent 的 `--queue` 与任务 enqueue 的 `queue_name`）
- 该队列是否真的有 Pending 的任务
- agent 日志里是否有权限/认证错误（key 不对、server 地址不通）

### 9.2 任务一直 Pending

常见原因：

- 没有任何 agent 监听该队列
- agent 所在机器不可用（进程挂了、网络断了）
- 队列监听了但 agent 启动用户没有权限访问环境/数据导致立即失败又重试（需要看 agent 端日志）

### 9.3 远程执行时报依赖安装失败

建议：

- 确认执行机能访问 pip 源（或配置企业内网镜像）
- 对需要编译的包（如某些 CUDA 相关包）提前在镜像/环境里准备好
- 尽量在任务里固定依赖版本，减少“今天能装明天装不上”的不确定性

### 9.4 artifact/model 上传失败或上传到本地没进远端

检查：

- `Task.init(..., output_uri=True)` 是否设置（建议显式设置）
- Files Server 是否可访问
- storage 配置是否正确（例如 S3 需要额外凭证配置；这部分通常属于存储侧配置而非 agent 本身）

### 9.5 “Repository Detection” 之类 Git 警告

在非 Git 仓库环境下运行（例如直接拷贝脚本到某目录）时出现此类警告通常是正常现象，不影响任务记录本身；但会影响“代码版本可追溯性”。推荐始终在可追踪的代码仓库中运行任务。

## 10. 建议的最小落地路径（你可以按这个顺序做）

1. 在执行机上写好 `~/clearml.conf` 并验证能连通 Server
2. 前台启动一个 agent：监听 `default`
3. 用任意一个最小 Task（甚至一个 print 脚本）把任务 enqueue 到 `default`，确认 agent 能拿到并跑完
4. 再开始做队列治理：至少拆出 `cpu/gpu` 两个队列
5. 如果是单机多卡，决定是否用“多实例 agent + CUDA_VISIBLE_DEVICES”跑并发
