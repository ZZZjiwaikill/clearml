# ClearML Task 功能笔记（整理版）

>面向交付：把 Task 相关的使用方式、参数含义、页面位置、自动追踪边界整理成“可复用的速查文档”。

***

## 1. Task 是什么

1. Task 负责“实验/任务”的全生命周期管理：记录代码、环境、参数、运行日志、指标曲线、产物文件等
2. 典型用途：训练（training）、测试（testing）、数据处理（data\_processing）等任务的统一留痕与复现
3. 在现有项目中价值评价：
	1. 优点：
		1. 侵入性小（只需要添加2行代码）
		2. 自动记录环境、配置、命令行参数args等信息，便于留痕：[Task | ClearML 平台 | 自动日志记录](https://clearml.machinelearning.org.cn/docs/latest/docs/clearml_sdk/task_sdk/#automatic-logging)
		3. 虽然模型训练的参数params不会被自动记录，但手动记录只需要`task.connect(params)`即可。
	2. 目前不足（可观察如何修改）：
		1. clearml能识别的模型追踪代码有限，需要修改项目中的**导出模型**的代码，或显式导出模型[Task | ClearML 平台 | 手动记录模型](https://clearml.machinelearning.org.cn/docs/latest/docs/clearml_sdk/task_sdk/#logging-models-manually)

***

## 2. 最小用法（初始化）

```python
task = Task.init(
    project_name=...,
    task_name=...,
	task_type=Task.TaskTypes.training,   # 可不填写
    output_uri=True/False,
)
```

***

## 3. 常用参数与语义

- project\_name
	- 项目归属（在 ClearML 的 Projects 视图下用于组织结构）
- task\_name
	- 任务名（用于快速定位某次运行/实验）
- task\_type（可选）
	- **说明：使用的是SDK里Python类的属性，类似枚举，而不是直接写字符串值**
		- 虽然也支持直接写字符串，但巍峨了
	- 默认 training
	- 可选值：training / testing / inference / data\_processing / application / monitor / controller / optimizer / service / qc / custom
	- 影响：主要是 UI 图标与人工识别，不改变记录内容本身
- output\_uri（关键开关）
	- 若需要上传模型文件/产物到远端存储，必须显式开启 output\_uri
>其他参数参考：[Task | ClearML | Task.init](https://clear.ml/docs/latest/docs/references/sdk/task/#taskinit)

***

## 4. 命名与工程组织（待确定的规范点）

- 任务命名（task\_name/title）建议统一规范，便于跨人协作检索
	- 需要进一步明确：task\_name 与 title/展示名如何约定更好
- 数据处理代码放置位置（目录结构）需要统一：建议明确“数据处理任务”属于哪类项目/子目录

***

## 5. 页面位置与信息分区（UI 速查）

入口：`PROJECTS`（左侧第 5 个“脑图”图标）→ 选择具体 Project → 进入某个 Task

- EXECUTION
	- 运行环境与代码信息：例如 Python 版本、git 状态（uncommitted changes）、Python packages、容器信息等
- CONFIGURATION
	- 参数记录方式：
	- General：模型训练参数，手动通过 `task.connect(params)` 导出
	- Args：自动检测命令行参数（`parser.add_argument(...)`）并记录
	- 其他（未验证）：`task.set_parameter()`、`task.connect_configuration()`（外部配置文件）
- ARTIFACTS
	- 典型用途：管理训练好的模型产物，但也可存储任意文件类型
	- 关键观察（与功率预测项目相关）：
		- 现有项目保存 xgb 模型用 `pkl.dump(model, open(...model_{forecast_index}.dat, "wb"))`
		- 该方式**不会自然触发 ClearML 的模型追踪**（至少默认情况下）
		- 可选方向：改为框架原生保存（如 `save_model`）或显式上传（`task.upload_artifact(...)`），而不是改 ClearML 源码
- INFO
	- 运行时间线与系统细节
	- 观察：同样代码多次运行，会连续写在同一任务 log 中；出现“新字段/明显代码变化”可能会被识别为新 task
- CONSOLE
	- 运行时日志备份；支持下载与过滤
- SCALARS
	- 训练/评估过程数值曲线（使用clearml支持的框架/接口可自动采集）
	- GPU 与机器监控指标：通常在使用 GPU 时自动触发
- PLOTS / DEBUG SAMPLES
	- 当任务未结束时，`plt.show()` 会被自动检测并上传到对应 tab
	- 具体“进 Plots 还是 Debug Samples”的分流逻辑属于实现细节，待进一步研究。

***

## 6. 自动追踪的边界（实用结论，短版）

总体判断标准（可操作层面）：

1. 先初始化：必须在 `Task.init()` 之后，ClearML 才有“接管上下文”
2. 再走通道：后续记录/保存要走 ClearML 已支持的接口/框架通道，才更可能被自动采集到 Scalars/Artifacts

与当前项目最相关的两条：

1. 训练指标：只在内存里算、只 print 到控制台，通常不会自动进入 Scalars；需要通过支持的日志通道“报出去”
2. 模型产物：普通 `pickle.dump(...)` 不一定被识别为模型产物；要追踪就用“框架保存接口”或显式上传

***

## 7. 官方资料（放在文末便于追溯）

1. GitHub：<https://github.com/clearml>
	1. 优先关注：clearml、clearml-agent
	2. clearml 仓库内：docs/tutorials，有示例教程（覆盖面很小，但上手很简单）
2. 官方文档
	1. 中文：<https://clearml.machinelearning.org.cn/docs/latest/docs>
	2. 英文：<https://clear.ml/docs/latest/docs/>
	3. 比对发现两版内容并不同步，英文版会更详细。建议优先阅读英文版。

