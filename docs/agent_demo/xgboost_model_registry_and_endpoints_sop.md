# XGBoost Model Registry And Endpoints SOP

## 目标

这份 SOP 解决两个问题：

- 训练脚本运行后，模型不只是一个 Task 附件文件，而是注册成 ClearML 的模型实体，出现在 `Models` 页面
- 你清楚知道为什么它不会仅靠训练脚本自动出现在 `Models Endpoints`，以及后续要怎么部署到 Endpoint

适用脚本：

- [xgboost_iris_task.py](file:///mnt/md0/zhouyunqi/clearml/docs/agent_demo/xgboost_iris_task.py)

## 先说结论

- `booster.save_model("best_model.json")` 只是在磁盘上保存文件
- 想让 ClearML 把它当成“模型实体”管理，需要显式使用 `OutputModel.update_weights(...)`
- `Models` 和 `Models Endpoints` 不是同一层
- 训练脚本负责把模型注册进 `Models`
- `Models Endpoints` 需要额外的部署/Serving 流程，通常由 `clearml-serving` 或对应的推理服务完成

## 本次代码改了什么

脚本现在在训练完成后会自动执行以下动作：

1. 保存本地模型文件 `best_model.json`
2. 创建 `OutputModel`
3. 把训练超参写进模型 configuration
4. 把 `task_id`、`dataset`、`model_path`、`test_accuracy` 写进模型 metadata
5. 把本地模型文件上传并注册为 ClearML 模型实体
6. 给模型添加 `xgboost`、`iris`、`ready-for-serving` 标签
7. 默认将模型 `publish`
8. 给当前 Task 上传一个 `serving_manifest` artifact，里面包含 `model_id`

这样做完以后：

- 你可以在 `Models` 页面看到这个模型
- 这个模型有可追踪的来源 Task、超参、指标、标签和 metadata
- 你后续部署 Endpoint 时，可以直接拿 `model_id`

## 一、训练并注册模型

### 1. 本地直接运行

```bash
python docs/agent_demo/xgboost_iris_task.py
```

可选参数：

```bash
python docs/agent_demo/xgboost_iris_task.py \
  --project-name "Getting Started-zyq" \
  --task-name "XGBoost Training Script" \
  --model-name "xgboost_iris_model"
```

如果你不想自动 `publish`：

```bash
python docs/agent_demo/xgboost_iris_task.py --no-publish-model
```

### 2. 运行后你应该看到什么

终端里会看到类似信息：

```text
Registered ClearML model id: <model_id>
Model registered under Models. To appear in Models Endpoints, deploy this model with ClearML Serving / clearml-serving using the model_id above.
```

在 ClearML Web UI 中：

- `Tasks` 页面：出现一个新 Task
- 该 Task 的 `Artifacts`：有 `serving_manifest`
- 该 Task 的 `Scalars`：有 `metrics/test_accuracy`
- `Models` 页面：出现一个名为 `xgboost_iris_model` 的模型实体

### 3. 在 `Models` 页面检查的重点

打开模型后重点看：

- `Created By Task` 是否关联回训练任务
- `Configuration` 是否保存了 `max_depth`、`eta`、`objective` 等参数
- `Metadata` 是否包含 `task_id`、`dataset`、`model_path`、`test_accuracy`
- `Tags` 是否包含 `xgboost`、`iris`、`ready-for-serving`
- 状态是否为 `Published`

## 二、为什么你之前在 `Models Endpoints` 看不到

因为你之前做的是“训练并保存模型文件”，而不是“部署推理服务”。

可以把它理解成两步：

1. `Training / Registry`
   - 产出模型
   - 注册模型
   - 记录模型来源、参数、指标、版本
   - 对应 ClearML 的 `Tasks` 和 `Models`
2. `Serving / Endpoint`
   - 把模型挂到一个在线推理服务
   - 分配可访问的推理入口
   - 采集线上请求/响应或部署状态
   - 对应 ClearML 的 `Models Endpoints`

所以：

- 训练脚本可以自动完成第 1 步
- 训练脚本本身通常不能单独完成第 2 步

## 三、把模型部署到 `Models Endpoints` 的 SOP

### 前提条件

你需要具备以下条件：

- ClearML Server 已启用模型服务/Endpoints 相关能力
- 已部署或准备部署 `clearml-serving`
- 推理环境可以访问 ClearML Server 和模型存储

项目里的参考入口：

- [README.md](file:///mnt/md0/zhouyunqi/clearml/README.md) 提到了 [clearml-serving](https://github.com/clearml/clearml-serving)

### 步骤 1：先拿到模型 ID

方法 1：

- 查看脚本运行终端输出里的 `Registered ClearML model id: ...`

方法 2：

- 打开训练 Task
- 在 `Artifacts` 里查看 `serving_manifest`
- 读取其中的 `model_id`

方法 3：

- 直接去 `Models` 页面找到 `xgboost_iris_model`

### 步骤 2：确认模型已经发布

如果脚本使用默认参数运行，模型已经自动 `publish`。

如果你用了 `--no-publish-model`，请在以下两种方式中选一种：

- 在 Web UI 里手动 Publish
- 或重新运行脚本并开启默认发布行为

### 步骤 3：在 Serving 侧创建部署

在 `clearml-serving` 或你的 Serving 流程中：

- 新建一个服务或 endpoint
- 指定上一步拿到的 `model_id`
- 指定输入输出 schema、前后处理逻辑、资源需求
- 启动推理服务容器或 worker

此时 ClearML 才会开始在 `Models Endpoints` 侧显示这个模型的部署状态与入口信息。

### 步骤 4：验证 Endpoint

部署成功后，检查：

- `Models Endpoints` 页面是否出现新 endpoint
- endpoint 是否绑定了正确的模型版本
- endpoint 状态是否为可用
- 请求测试是否返回预期结果

## 四、如果你要结合 Agent 使用

如果你的目的是：

- 先本地生成一个脚本型 Task
- 再在平台上 `Clone`
- 再 `Enqueue` 给 agent 去跑

那就按下面顺序：

1. 先运行一次本地脚本，确认模型注册逻辑正常
2. `git add/commit/push`，确保 agent 能拉到最新脚本
3. 在 Web UI 中 Clone 这个 Task
4. 必要时修改 `General` 超参
5. Enqueue 到 `cpu` 或 `gpu` 队列
6. 等 agent 远程执行完成后，在 `Models` 中检查新模型是否也被正确注册

注意：

- agent 能做的是“远程训练并注册模型”
- agent 本身不等于“自动创建线上 Endpoint”
- 远程训练完成后，仍然需要 Serving/部署流程来进入 `Models Endpoints`

## 五、排障清单

### 情况 1：Task 成功了，但 `Models` 页面没有模型

优先检查：

- 代码里是否调用了 `OutputModel.update_weights(...)`
- 模型文件路径是否真实存在
- `output_uri=True` 是否生效
- 任务 Console 中是否出现模型上传失败

### 情况 2：`Models` 有模型，但 `Models Endpoints` 为空

这通常不是训练脚本问题，而是还没有部署。

优先检查：

- 是否已经部署 `clearml-serving`
- 是否在 Serving 侧创建了 endpoint
- 是否把正确的 `model_id` 绑定到部署
- Serving worker 是否在线

### 情况 3：本地能跑，Agent 远程跑后没有模型

优先检查：

- 新脚本是否已经 commit 并 push
- agent 拉到的仓库版本里是否包含该脚本
- 远程环境是否安装了 `xgboost`、`scikit-learn`
- agent Console 中是否有模型上传异常

## 六、一句话记忆

- `save_model(...)` 只是生成文件
- `OutputModel.update_weights(...)` 才是注册 ClearML 模型实体
- `Models` 是模型注册中心
- `Models Endpoints` 是模型部署结果展示
