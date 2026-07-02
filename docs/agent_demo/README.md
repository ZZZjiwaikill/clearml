# ClearML Agent 最小 Demo（CPU + GPU）

这组 demo 用来验证两件事：

- Agent 能从队列拿到 Task 并执行（CPU demo）
- GPU 队列 + 单机多卡（限制 `CUDA_VISIBLE_DEVICES`）能把任务跑在指定 GPU 上（GPU demo）

## 1. 前置

- 执行机（跑 agent 的那台）与提交机（你运行脚本 enqueue 任务的那台）都需要能访问 ClearML Server
- 两边都需要配置 `~/clearml.conf`（模板见 [docs/clearml.conf](file:///mnt/md0/zhouyunqi/clearml/docs/clearml.conf)）

## 2. 启动 Agent

如果你看到错误：

```
clearml_agent: ERROR: Could not find queue with name/id "cpu"
```

说明 ClearML Server 里还没有名为 `cpu` 的队列。处理方式二选一：

- 在 ClearML Web UI 的 Queues/Agents 页面创建队列 `cpu`（以及 `gpu`）
- 临时改用默认队列：把下面命令里的 `cpu` 改成 `default`（并相应地把 demo 的 `CLEARML_QUEUE` 设为 `default`）

CPU（前台启动，便于观察日志）：

```bash
clearml-agent daemon --queue "cpu" --foreground
```

GPU（单机多卡，一卡一个 agent 实例；示例启动两张卡，你可以扩展到 0-9）：

```bash
CUDA_VISIBLE_DEVICES=0 clearml-agent daemon --queue "gpu" --foreground
CUDA_VISIBLE_DEVICES=1 clearml-agent daemon --queue "gpu" --foreground
```

systemd 常驻方式参考：[clearml-agent-guide-zh.md:L159-L196](file:///mnt/md0/zhouyunqi/clearml/docs/clearml-agent-guide-zh.md#L159-L196)

## 3. 提交任务（enqueue）

如果你使用的是 `task.execute_remotely(...)` 方式（本 demo 就是这种），需要注意：

- Agent 执行时会根据 Task 里记录的 Repository/Commit 去拉取代码
- 因此脚本路径必须存在于 Agent 能拉到的代码版本里
- 如果你是“本地新建的文件但还没提交/推送到远端仓库”，Agent 侧就会报 `No such file or directory`

不想提交/推送也能跑的话，可以改用 `clearml-task` CLI（它会把脚本打包上传，不依赖 Git 仓库路径）。

CPU demo（最小 print + 上报少量 scalar）：

```bash
python docs/agent_demo/cpu_print_task.py
```

GPU demo（MNIST 最小训练；如果环境里有 TensorBoard 则用 `SummaryWriter` 写标量并被 ClearML 自动捕获，否则会自动回退到 `logger.report_scalar`）：

```bash
python docs/agent_demo/gpu_mnist_task.py
```

可选参数（都通过环境变量）：

- `CLEARML_QUEUE`：覆盖默认队列名（CPU 默认 `cpu`，GPU 默认 `gpu`）
- `MAX_STEPS`：GPU demo 的最大训练 step（默认 200）

示例：

```bash
CLEARML_QUEUE=gpu MAX_STEPS=50 python docs/agent_demo/gpu_mnist_task.py
```

## 4. 你应该看到的现象

- 你本地运行脚本后会“很快退出”，因为 `execute_remotely(..., exit_process=True)` 会把任务丢进队列后结束本地进程
- ClearML Web UI 中 Task 状态从 Pending -> In Progress -> Completed
- GPU demo 会在 Console 里打印 loss，并在 Scalars 中看到 `train/loss` 曲线（优先来自 TensorBoard；缺少 TensorBoard 时走 ClearML Logger 回退）
