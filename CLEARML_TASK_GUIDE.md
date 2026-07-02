# ClearML Task 快速上手（能力边界版）

这份文档的目标很简单：让你能尽快看懂并用上 `from clearml import Task`，并且把 **Task 能做什么 / 不能做什么** 讲清楚。

建议按这 3 个问题去读：

- 我怎么“初始化并决定这次运行对应哪个 Task（新建/复用/续跑）”？
  - 看 `Task.init`、`reuse_last_task_id`、`continue_last_task`
- 我怎么“把参数、日志、指标曲线、图、产物”记录到 Task 里？
  - 看 `task.connect`、`task.get_logger()`、`task.upload_artifact`、`OutputModel`
- 我怎么理解“自动追踪的边界”，避免以为它会自动记录一切？
  - 看 `auto_connect_*`、以及文末「能力边界与常见坑」

***

## 0. 最简接入（尽量不影响源代码）

把 ClearML 接进一个训练脚本，最小侵入一般就是 2 行（尽量放在入口最前面）：

```python
from clearml import Task
task = Task.init(project_name="demo_project", task_name="demo_task", output_uri=True)
```

在不改训练逻辑的前提下，你通常只需要在 3 个位置“补一行”：

- 你已经有超参数 dict：`task.connect(params)`
- 你已经算出了指标：用框架自动集成（例如 XGBoost/TensorBoard）或手动 `logger.report_scalar(...)`
- 你已经产出了文件：`task.upload_artifact(name=..., artifact_object=...)`

***

## 1. 先认识 `Task` 这个类（它解决什么问题）

`Task` 可以理解成“实验/任务的一次可复现运行记录 + 远程执行的基本单元”。

把它和 ClearML 里的其他对象这样区分更清楚：

- `Task`：记录代码、环境、参数、日志、指标曲线、图表、产物文件；也可以被放进队列交给 `clearml-agent` 远程执行
- `Dataset`：记录数据版本、血缘关系和下载入口
- `Model`（尤其是 `OutputModel`）：记录模型权重与元信息，并关联到产生它的 Task

最常见的生命周期只有这一条：

```python
Task.init() -> connect(...) -> logger.report_* / upload_artifact / OutputModel -> close()
```

***

## 2. 问题一：我怎么“初始化并决定这次运行对应哪个 Task（新建/复用/续跑）”？

这一步的核心就是 `Task.init(...)`。

### 2.1 最小示例

```python
from clearml import Task

task = Task.init(
    project_name="demo_project",
    task_name="demo_task",
    output_uri=True,
)
```

### 2.2 关键参数怎么理解（新建/复用/续跑）

`Task.init` 的行为可以粗略分成三类：

- 复用同一个 Task ID（默认倾向）：`reuse_last_task_id=True`
  - 注意：复用成功时会清理上一次执行输出（console/log 等），这意味着“不会把日志追加到原 Task 上”
- 强制每次新建一个 Task：`reuse_last_task_id=False`
- 继续上次执行并保留历史：`continue_last_task=True`
  - 适合“断点续跑/追加训练”，历史 artifacts/models/logs 保留，新的上报会在历史最大 iteration 基础上继续

示例：每次都创建一个全新的 Task（推荐给“实验对比”场景）

```python
from clearml import Task

task = Task.init(
    project_name="demo_project",
    task_name="demo_task",
    reuse_last_task_id=False,
    output_uri=True,
)
```

示例：继续上一次的 Task（推荐给“续训/增量训练”场景）

```python
from clearml import Task

task = Task.init(
    project_name="demo_project",
    task_name="demo_task",
    continue_last_task=True,
    output_uri=True,
)
```

### 2.3 关于 `output_uri`：什么时候需要显式设置？

`output_uri` 用来指定模型与产物的默认输出存储位置。

- 如果你依赖“自动上传模型/产物”，建议显式设置 `output_uri=True` 或直接填写明确的远端存储地址（例如 `s3://...`）
- 如果你只是想记录实验信息，不需要上传文件，可以把 `output_uri=False`（或不设置）

### 2.4 一个进程里能不能 init 多个 Task？

可以，但需要显式 `close()` 当前 Task 后再初始化新的 Task。

***

## 3. 问题二：我怎么“把参数/日志/指标曲线/图/产物”记录到 Task 里？

这一步可以分成三条通道：Configuration（参数/配置）、Results（Scalars/Plots）、Artifacts/Models（产物与模型）。

### 3.1 参数与配置（Configuration）

最常用的是 `task.connect(dict)`：

```python
from clearml import Task

task = Task.init(project_name="demo_project", task_name="connect_params", output_uri=True)

params = {
    "lr": 1e-3,
    "batch_size": 64,
    "model": "resnet18",
}
params = task.connect(params)
```

要点：

- `task.connect` 返回的往往是一个“可追踪更新的代理对象”，后续修改字典内容通常也会被同步记录
- 远程执行时，这些参数默认可被 UI 覆盖；如果你希望“以代码为准”，使用 `ignore_remote_overrides=True`

补充澄清：

- 命令行参数（argparse/click/fire/jsonargparse 等）通常可以自动记录
- 代码里构造的 dict/config 不会被“自动理解成超参数”，推荐显式 `task.connect(...)` 或 `task.connect_configuration(...)`

### 3.2 日志与指标（Console / Scalars / Plots）

#### Console（日常 print/logging）

默认情况下，stdout/stderr/logging 会被自动接入到 Task 的 Console。

但注意：

- Console 是“文本日志”，不会自动变成 “Scalars 曲线”
- 想要曲线需要走 ClearML 的“标量上报通道”：要么显式调用 `logger.report_*`，要么使用框架自动集成（例如 XGBoost / TensorBoard 等会在后台自动上报，下一节讲）

#### Scalars（曲线）

```python
from clearml import Task

task = Task.init(project_name="demo_project", task_name="scalar_demo", output_uri=True)
logger = task.get_logger()

for i in range(100):
    logger.report_scalar(title="train", series="loss", iteration=i, value=1.0 / (i + 1))
logger.flush()
```

### 3.3 产物（Artifacts）

最通用的方式是 `task.upload_artifact(name=..., artifact_object=...)`，它支持非常多类型（文件/目录/dict/DataFrame/ndarray/PIL Image/任意对象 pickle 等）。

最小例子：

```python
from clearml import Task

task = Task.init(project_name="demo_project", task_name="artifact_demo", output_uri=True)

task.upload_artifact(
    name="metrics_summary",
    artifact_object={"acc": 0.91, "loss": 0.23},
)
```

更多“尽量不侵入训练代码”的常见例子：

上传本地文件（最常见）：

```python
task.upload_artifact(name="config_yaml", artifact_object="/path/to/config.yaml")
```

上传本地目录（会自动打包成 zip 再上传）：

```python
task.upload_artifact(name="predictions_dir", artifact_object="/path/to/preds/")
```

上传通配符匹配的一批文件（会自动打包成 zip 再上传）：

```python
task.upload_artifact(name="checkpoints", artifact_object="/path/to/ckpt/*.pt")
```

上传 pandas DataFrame（会序列化成文件后上传）：

```python
import pandas as pd

df = pd.DataFrame([{"id": 1, "score": 0.91}, {"id": 2, "score": 0.87}])
task.upload_artifact(name="eval_table", artifact_object=df)
```

上传 numpy ndarray（会序列化成文件后上传）：

```python
import numpy as np

arr = np.random.randn(10, 3)
task.upload_artifact(name="embeddings_sample", artifact_object=arr)
```

上传任意 Python 对象（最省事，但可移植性最差；依赖 pickle）：

```python
task.upload_artifact(
    name="postprocess_object",
    artifact_object={"thresholds": [0.1, 0.5, 0.9]},
    auto_pickle=True,
)
```

### 3.4 模型（Models / OutputModel）

如果你希望模型作为 ClearML 的“模型实体”被管理（而不是一个普通文件），用 `OutputModel`：

```python
from clearml import Task, OutputModel

task = Task.init(project_name="demo_project", task_name="model_demo", output_uri=True)
output_model = OutputModel(task=task)

output_model.update_weights(weights_filename="/path/to/model.onnx")
```

***

## 4. 问题三：我怎么理解“自动追踪的边界”？

ClearML 的“自动追踪”主要来自 `Task.init(..., auto_connect_frameworks=True, auto_connect_streams=True, ...)` 触发的框架集成与日志接管。

### 4.1 它能自动做什么（常见）

- 自动记录 stdout/stderr/logging 到 Console（默认开启）
- 自动连接常见参数解析器（默认开启）
- 自动对一批框架打补丁：Matplotlib / TensorBoard(X) / PyTorch / XGBoost / scikit-learn / Keras / LightGBM / Hydra / Joblib 等（默认开启，且可细粒度配置）
- 自动创建资源监控曲线（默认开启）

### 4.2 它不能自动做什么（务必先知道）

- 不能“读懂”你代码里的任意 Python 变量并自动当成超参数或指标
  - 解决方式：`task.connect(...)` / `logger.report_scalar(...)`
- 不能保证捕获你写到磁盘的每一个文件并把它们都当成 Artifacts/Models
  - 解决方式：显式 `task.upload_artifact(...)`，或者按框架最佳实践调用支持的保存接口（再配合 `output_uri`）
- 不能替代 `Dataset` 的“数据版本化”
  - Task 可以记录“你用了哪个 Dataset / 数据路径”，但它不是“数据集版本实体”
- 不能在你已经运行了框架代码之后再“追溯性补记”
  - 实务建议：尽量在脚本入口最开始就 `Task.init()`，避免错过自动集成的接管时机

### 4.3 最推荐的实践：把“自动”当成加分项，把“关键记录”显式写出来

- 参数：关键超参数永远 `task.connect(params)`，不要只靠自动 arg parser
- 指标：如果你不依赖框架自动集成，就显式 `logger.report_scalar(...)`，不要只靠 print
- 产物：关键文件永远 `task.upload_artifact(...)` / `OutputModel.update_weights(...)`

***

## 5. 远程执行：Task 能做什么，Task 不能做什么

### 5.1 Task 能做的：把当前任务放进队列让 agent 跑

最直接的入口是 `task.execute_remotely(queue_name=...)`。

简化理解：

- 本地跑：你调用 `execute_remotely` 后，Task 会被 enqueue 到指定 queue，然后本地进程退出（默认 `exit_process=True`）
- agent 跑：如果已经在 agent 上运行，这个调用是 no-op（不会重复 enqueue）

### 5.2 Task 不能做的：替你“提供算力/调度器/环境”

Task 只负责“记录与编排入口”。真正的远程执行依赖：

- clearml-agent（执行器）
- 队列与资源（你自己的机器、k8s、云资源等）
- 正确的环境复现（依赖、数据访问权限、storage 凭证等）

***

## 6. 场景选型速查

| 场景                     | 推荐接口                                         |
| ---------------------- | -------------------------------------------- |
| 想快速把脚本接入 ClearML       | `Task.init(project, name, output_uri=True)`  |
| 想记录超参数，并支持 UI 覆盖后远程复跑  | `task.connect(params)`                       |
| 想把指标变成曲线               | `task.get_logger().report_scalar(...)`       |
| 想上传任意中间产物/文件/统计表       | `task.upload_artifact(name, obj)`            |
| 想把模型作为“模型实体”管理         | `OutputModel(task=task).update_weights(...)` |
| 想把任务丢给 clearml-agent 跑 | `task.execute_remotely(queue_name=...)`      |

***

## 7. 一句话总结

如果只记一句：

`Task` 的核心不是“帮你自动记录一切”，而是“提供一个可复现、可远程执行、并且可显式上报关键过程与产物的实验载体；自动追踪只是锦上添花”。
