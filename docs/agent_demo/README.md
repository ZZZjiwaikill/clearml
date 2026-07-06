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

## 5. Clone 到 GPU 队列后的典型现象

如果你先创建了一个脚本型 Task，然后在 ClearML Web UI 里执行：

- `Clone`
- 选择队列 `gpu`
- `Enqueue`

并且该任务随后被 `gpu1` 抢占到，那么通常会看到下面这条链路：

1. 原始 Task 只是“基线任务”，本身可能是本地跑出来的，也可能是之前某次 agent 跑出来的。
2. `Clone` 后会生成一个新的 Task 副本，它继承原任务的脚本入口、参数、仓库信息和运行配置。
3. `Enqueue` 到 `gpu` 队列后，这个 cloned task 的状态会先变成 `queued`。
4. 监听 `gpu` 队列的 agent 中，某一个空闲实例会先抢到任务。你的场景里是 `gpu1` 抢到了，所以该任务随后转成 `in_progress`。
5. `gpu1` 会在自己的执行环境里做这些事：读取任务配置、拉取仓库、checkout 到对应 commit、创建或复用虚拟环境、安装依赖、最后启动脚本。
6. 如果脚本正常结束，任务状态会变成 `completed`；如果依赖、仓库或运行时报错，则会变成 `failed`。

对应现象通常是：

- 在 Task 页面里，`Execution`/`Worker` 相关区域会显示该任务是被某个 GPU worker 执行的，例如 `gpu1`
- 在 Queues 页面里，`gpu` 队列的 pending 数量会先增加，再在任务被取走后减少
- 在 Workers 页面里，`gpu1` 会从空闲变成忙碌，任务结束后再回到空闲
- 在 Task 的 Console 里，你会看到 agent 的准备阶段日志，例如环境准备、依赖安装、启动脚本等

## 6. 如何判断一个任务是否经过了 Agent

最直接的判断方法不是看“它是不是出现在 ClearML 平台里”，而是看“它是不是经过了队列，并被某个 worker 执行”。

### 6.1 明确经过 Agent 的信号

- Task 曾经进入某个队列，状态出现过 `queued`
- Task 后来被某个 worker 接管，状态变成 `in_progress`
- Task 页面能看到明确的执行 worker 信息，例如 `cpu` 队列 worker、`gpu0`、`gpu1`
- Console 日志里出现 agent 侧准备流程，例如：

```text
Environment setup completed successfully
Starting Task Execution
```

- 你能从 Workers 页面看到某个 agent 在这段时间内从 idle 变成 busy

### 6.2 没有经过 Agent 的常见信号

- 你是直接在本机运行 `python your_script.py`
- Task 没有进入任何队列，没有出现 `queued`
- Workers 页面没有任何 agent 因这个任务而忙起来
- 任务从创建后很快就在本地完成，整个过程中没有“被哪个 worker 执行”的迹象

一句话记忆：

- “本地直接跑”只说明 ClearML SDK 在记录任务
- “入队并被 worker 拿走”才说明任务真的经过了 Agent

## 7. 为什么 `cpu_print_task.py` 和 `gpu_mnist_task.py` 会经过 Agent，而 `xgboost_iris_task.py` 默认不会

核心差异只有一个：是否调用了 `task.execute_remotely(...)`。

### 7.1 会经过 Agent 的两个脚本

`cpu_print_task.py` 和 `gpu_mnist_task.py` 都有这一步：

- [cpu_print_task.py](file:///mnt/md0/zhouyunqi/clearml/docs/agent_demo/cpu_print_task.py)
- [gpu_mnist_task.py](file:///mnt/md0/zhouyunqi/clearml/docs/agent_demo/gpu_mnist_task.py)

它们在 `Task.init(...)` 之后立刻执行：

```python
task.execute_remotely(queue_name=queue_name, exit_process=True)
```

这句的含义是：

1. 把当前任务提交到指定队列
2. 让本地进程退出，不在当前机器继续往下跑
3. 等待监听该队列的 clearml-agent 在远端接手

所以它们的行为模式是：

- 你本地运行脚本
- 脚本很快退出
- 任务进入 `cpu` 或 `gpu` 队列
- 某个 agent 抢到任务并真正执行后续训练/打印逻辑

### 7.2 默认不会经过 Agent 的脚本

`xgboost_iris_task.py` 只有 `Task.init(...)`，没有 `task.execute_remotely(...)`：

- [xgboost_iris_task.py](file:///mnt/md0/zhouyunqi/clearml/docs/agent_demo/xgboost_iris_task.py)

所以它的默认行为是：

1. 你在当前机器直接运行 `python docs/agent_demo/xgboost_iris_task.py`
2. ClearML 只是在平台上创建并记录这个 Task
3. 训练代码继续在当前这个本地 Python 进程里执行
4. 后台已经启动的 CPU/GPU agents 只是继续监听队列，不会接手这个任务

也就是说，它不是“不能经过 Agent”，而是“默认这次运行没有走 Agent 通道”。

如果你希望它也经过 Agent，有两种做法：

- 做法 A：像前两个 demo 一样，在代码里增加 `task.execute_remotely(queue_name=...)`
- 做法 B：先本地跑一次，生成一个标准脚本型 Task；然后在 Web UI 中 `Clone` 这个任务，再 `Enqueue` 到 `cpu` 或 `gpu` 队列，让 agent 去执行 cloned task

## 8. 书写要点

写这类说明时，建议始终把下面几点分开写清楚：

- `Task.init()` 的作用：创建并记录一个 ClearML Task，不等于自动交给 Agent 执行
- `task.execute_remotely()` 的作用：把当前任务送入队列，并让 agent 接手
- `Clone` 的作用：复制一个已有 Task，便于改参数和重跑；仅 clone 不会触发执行
- `Enqueue` 的作用：把任务放进指定队列；只有 enqueue 之后 agent 才有机会抢占
- `Worker/Agent` 的作用：监听队列、拉取代码、建环境、执行脚本
- 判断任务是否经过 Agent 的关键证据：是否入队、是否被某个 worker 执行、Console 中是否出现 agent 准备日志

最容易混淆的一点是：

- “任务出现在 ClearML 平台”不代表它经过了 Agent
- “任务被放进队列并被某个 worker 执行”才代表它经过了 Agent
