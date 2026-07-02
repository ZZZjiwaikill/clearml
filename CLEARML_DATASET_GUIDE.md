# ClearML Dataset 快速上手

这份文档的目标很简单：让你能尽快看懂并用上 `from clearml import Dataset`。

建议按这 3 个问题去读：

- 我怎么“注册并上传”一个数据集版本？
  - 看 `create / add_files / upload / finalize`
- 我怎么“在训练代码里使用”一个已存在的数据集？
  - 看 `get / get_local_copy`
- 我怎么“基于旧版本派生新版本”？
  - 看 `parent/child dataset` 示例

## 1. 先认识 `Dataset` 这个类

`Dataset` 可以理解成“数据的一个可版本化快照”。

你可以把它和 ClearML 里的其他对象这样区分：

- `Task`：记录训练或处理过程
- `Model`：记录模型输入输出
- `Dataset`：记录数据版本、血缘关系和下载入口

最常见的生命周期只有这一条：

```python
Dataset.create() -> add_files() / add_external_files() -> upload() -> finalize()
```

## 2. 常用字段和属性

下面这些属性最值得先认识，不需要一开始把源码里所有内部字段都看完。

| 属性                     | 含义            | 什么时候会用到                     |
| ---------------------- | ------------- | --------------------------- |
| `dataset.id`           | 当前数据集版本的唯一 ID | 精确复现、日志记录、做 parent/child 继承 |
| `dataset.project`      | 数据集所属项目名      | 检查数据集被建到哪个项目下               |
| `dataset.name`         | 数据集名称         | 和 `project` 一起定位数据集         |
| `dataset.version`      | 当前版本号         | 固定版本、发布版本时使用                |
| `dataset.tags`         | 标签列表          | 给数据集分类、过滤                   |
| `dataset.file_entries` | 本地上传文件条目列表    | 想检查当前版本包含了哪些本地文件            |
| `dataset.link_entries` | 外部链接文件条目列表    | 想检查哪些文件来自外部存储               |

一个最小例子：

```python
from clearml import Dataset

dataset = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
)

print("id =", dataset.id)
print("project =", dataset.project)
print("name =", dataset.name)
print("version =", dataset.version)
print("tags =", dataset.tags)
```

## 3. 常用方法怎么分类看

直接按“你要解决什么问题”来记。

| 你要解决的问题       | 优先看这些方法                                                                                 |
| ------------- | --------------------------------------------------------------------------------------- |
| 注册并上传一个数据集版本  | `create`、`add_files`、`add_external_files`、`upload`、`finalize`                           |
| 在训练代码里使用已有数据集 | `get`、`get_local_copy`                                                                  |
| 基于旧版本继续增量更新   | `get`、`create(parent_datasets=...)`、`add_files`、`sync_folder`、`remove_files`、`finalize` |
| 想本地继续加工       | `get_mutable_local_copy`                                                                |
| 想把版本设为稳定可用    | `publish`                                                                               |

## 4. 问题一：我怎么“注册并上传”一个数据集版本？

这是数据生产阶段最常见的需求。

### 4.1 先记住这几个方法

- `Dataset.create(...)`
  - 创建一个新的数据集版本
- `add_files(...)`
  - 把本地文件或目录登记进数据集
- `add_external_files(...)`
  - 把远端存储中的文件或目录登记进数据集
- `upload()`
  - 把本地文件真正上传到远端存储
- `finalize()`
  - 冻结当前版本，冻结后才能稳定复用

### 4.2 最小示例：本地目录做成一个 Dataset

```python
from clearml import Dataset

# 1) 创建一个新的数据集版本
ds = Dataset.create(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
)

# 2) 把本地目录登记进数据集
ds.add_files("/path/to/local_data")

# 3) 把本地文件上传到远端存储
ds.upload()

# 4) 冻结当前版本
ds.finalize()
```

### 4.3 如果数据已经在远端存储

这时重点看 `add_external_files()`，常见于 `s3://`、`gs://`、`azure://`、`file://` 等来源。

```python
from clearml import Dataset

ds = Dataset.create(
    dataset_project="demo_project",
    dataset_name="remote_dataset",
)

# 直接登记远端目录
ds.add_external_files(
    source_url="s3://my-bucket/raw_data/",
    dataset_path="raw_data",
)

# 外部链接通常不需要再 upload 本体，但仍然要 finalize
ds.finalize()
```

### 4.4 这一类方法怎么记

- `create`：先创建版本
- `add_files` / `add_external_files`：再把内容放进去
- `upload`：如果是本地文件，就上传
- `finalize`：最后冻结

## 5. 问题二：我怎么“在训练代码里使用”一个已存在的数据集？

这是数据消费阶段最常见的需求。

### 5.1 先记住这几个方法

- `Dataset.get(...)`
  - 获取一个已存在的数据集版本
- `get_local_copy()`
  - 下载到本地缓存目录，并返回本地路径
- `get_mutable_local_copy()`
  - 下载一份可写副本，适合你还要继续改文件

### 5.2 最小示例：训练代码里拿到数据路径

```python
from clearml import Dataset

# 1) 获取一个已存在的数据集
dataset = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
)

# 2) 下载到本地缓存目录
dataset_path = dataset.get_local_copy()

print("dataset_path =", dataset_path)
```

说明：

- `get_local_copy()` 不支持手动指定下载目录
- 它返回的是 ClearML 缓存目录中的只读副本
- 如果你想自己指定落地目录，请改用 `get_mutable_local_copy(target_folder=...)`

例如：

```python
from clearml import Dataset

dataset = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
)

# 手动指定下载后的本地目录
dataset_path = dataset.get_mutable_local_copy(
    target_folder="/tmp/demo_dataset_copy",
    overwrite=True,
)

print("dataset_path =", dataset_path)
```

### 5.3 如果你想让训练任务明确记录“用了哪份数据”

推荐在 `Task.init()` 之后配合 `alias` 使用。

```python
from clearml import Dataset, Task

task = Task.init(
    project_name="train_project",
    task_name="train_with_dataset",
)

# alias 会把这份数据集引用记录到当前任务里
dataset = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
    alias="train_data",
    overridable=True,
)

dataset_path = dataset.get_local_copy()
print("dataset_path =", dataset_path)
```

这里的 `alias` 自动对应**当前进程里的活动任务**，也就是 `Task.current_task()`。

### 5.4 这一类方法怎么记

- `get`：先找到数据集
- `get_local_copy`：再拿到本地可读路径
- `get_mutable_local_copy`：如果你需要本地可写副本，就用它

## 6. 问题三：我怎么“基于旧版本派生新版本”？

这是做增量更新、数据修复、数据扩充时最重要的一组方法。

### 6.1 先记住这几个方法

- `Dataset.get(...)`
  - 先拿到旧版本
- `Dataset.create(parent_datasets=[parent.id])`
  - 基于旧版本创建子版本
- `add_files(...)`
  - 给新版本补充新增文件
- `sync_folder(...)`
  - 把本地目录的真实状态同步到数据集
- `remove_files(...)`
  - 从新版本里删除不需要的文件
- `finalize()`
  - 冻结新版本

### 6.2 最小示例：基于旧版本补一批新文件

```python
from clearml import Dataset

# 1) 取到旧版本
parent = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
)

# 2) 基于旧版本创建子版本
child = Dataset.create(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
    parent_datasets=[parent.id],
)

# 3) 给子版本补充新增文件
child.add_files("/path/to/new_data", dataset_path="new_data")

# 4) 上传并冻结
child.upload()
child.finalize()
```

### 6.3 如果你的本地目录就是“当前真实状态”

这时重点看 `sync_folder()`，它适合做目录级同步。

```python
from clearml import Dataset

# 直接基于现有版本创建一个可写子版本
ds = Dataset.get(
    dataset_project="demo_project",
    dataset_name="demo_dataset",
    writable_copy=True,
)

# 同步本地目录到数据集内部 images/ 路径
ds.sync_folder(
    local_path="/path/to/current_images",
    dataset_path="images",
)

ds.upload()
ds.finalize()
```

### 6.4 这一类方法怎么记

- 先 `get` 旧版本
- 再 `create(parent_datasets=[parent.id])` 建子版本
- 然后补文件、同步目录或删文件
- 最后 `finalize`

## 7. 场景选型速查

| 场景          | 推荐方法                                           |
| ----------- | ---------------------------------------------- |
| 本地目录注册成数据集  | `create` + `add_files` + `upload` + `finalize` |
| 远端对象存储纳管    | `create` + `add_external_files` + `finalize`   |
| 训练代码拿到数据路径  | `get` + `get_local_copy`                       |
| 任务里记录数据集依赖  | `get(alias=..., overridable=True)`             |
| 基于旧版本增量更新   | `get` + `create(parent_datasets=[...])`        |
| 本地目录按真实状态同步 | `sync_folder`                                  |
| 本地继续加工一份副本  | `get_mutable_local_copy`                       |

## 8. 最值得先记住的注意事项

### 9.1 `finalize()` 很关键

如果不 `finalize()`，通常会出现这些问题：

- 版本没有真正冻结
- 后续下载和复用不稳定
- 不适合作为父版本继续派生

### 9.2 `add_files()` 和 `add_external_files()` 不一样

- `add_files()`：登记本地文件，通常后面要 `upload()`
- `add_external_files()`：登记远端链接，通常不需要重新上传文件本体

### 9.3 训练里推荐配 `alias`

`alias` 的好处是：

- 当前任务会明确记录“用了哪份数据”
- 后续远端执行时更容易替换数据集版本

### 9.4 `get_local_copy()` 和 `get_mutable_local_copy()` 的区别

- `get_local_copy()`：适合训练时只读消费
- `get_mutable_local_copy()`：适合拿到本地后继续修改

## 9. 一句话总结

如果只记一句：

`Dataset` 的核心不是“存文件”，而是“把数据做成可版本化、可复现、可继承、可被任务稳定引用的快照”。
