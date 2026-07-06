# Git 笔记：为 ClearML Agent 远程执行排障与落地（实战记录）

这份笔记总结了我们这次把 ClearML 的 `Task.execute_remotely()` 跑通时，围绕 Git 遇到的问题、定位思路与解决命令。核心结论一句话：

`execute_remotely` 模式下，Agent 只认 Task 里记录的 “远端仓库 + commit”，所以**必须保证该 commit 在远端可被 clone/checkout**。

## 1. 场景背景：为什么 Git 会变成关键路径

你本地运行 demo 脚本后很快退出，日志类似：

- `Switching to remote execution...`
- `ClearML Terminating local execution process - continuing execution remotely`

这表示本地进程只是“把任务入队并结束”，真正执行发生在执行机的 `clearml-agent` 上。

当 agent 拿到任务后，会从 Task 元信息里读取：

- `repository`：远端仓库地址
- `branch`
- `version_num`：commit id
- `entry_point`：入口脚本路径（相对于 repo 根目录）

然后在执行机上做：clone/fetch -> checkout commit -> 执行 entry_point。

## 2. 我们遇到的 Git 相关问题与解决

### 2.1 问题 A：脚本在执行机找不到（No such file or directory）

现象（agent 侧）：

- `can't open file '.../task_repository/.../docs/agent_demo/cpu_print_task.py': [Errno 2] No such file or directory`

根因：

- 入口脚本 `docs/agent_demo/cpu_print_task.py` 在你本地存在，但**在 agent 实际 checkout 到的那个 commit 里不存在**（例如文件未提交，或提交了但后续 commit 未被记录/同步）。

处理要点：

- 确保脚本路径存在于你将要 push 的 commit 中
- 重新运行一次脚本生成新 Task（让它记录新的 commit）

### 2.2 问题 B：只 commit 未 push，agent checkout 失败（unable to read tree）

现象（agent 侧）：

- `fatal: unable to read tree (<commit_id>)`
- `Repository cloning failed ... git checkout <commit_id> --force`
- `Failed cloning repository. 1) Make sure you pushed the requested commit`

根因：

- 你本地提交了 commit，但没有 push 到远端。
- agent 只能从 `repository=<远端URL>` 拉代码，所以远端没有这个 commit 时就无法 checkout。

解决动作（关键思想：让 commit 在远端可见）：

- 把提交 push 到你 fork 的 GitHub 仓库（而不是官方仓库）
- 重新运行 demo 产生新 Task（新 Task 里记录的 commit 必须是远端可访问的）

### 2.3 问题 C：push 被拒绝（rejected, fetch first / non-fast-forward）

现象（你本地）：

- `! [rejected] HEAD -> master (fetch first)`
- `Updates were rejected because the remote contains work that you do not have locally.`

根因：

- 远端分支（例如 `origin/master`）上已经有提交，而你本地分支历史不包含它。
- Git 默认不允许用“非 fast-forward”的方式覆盖远端分支历史。

方案（我们采用的是方案 A：推新分支，最稳妥）：

- 不强行推 `master`，推一个新分支用于远程执行：

```bash
git fetch origin
git checkout -b agent-demo
git push -u origin agent-demo
```

为什么这招适合 ClearML：

- ClearML 远程执行只需要远端能拿到 commit；分支名不是关键。
- 推新分支不影响你 fork 仓库的默认分支历史，也避免 `rebase/merge/force` 带来的额外复杂度。

可选方案（如果你坚持要更新 `master`）：

- 先同步远端再推（rebase 或 merge），再 `git push origin HEAD:master`
- 或者（不推荐）强制推：`git push --force-with-lease ...`

## 3. 我们使用过/提到过的 Git 命令清单（按用途归类）

### 3.1 查看与确认远端信息

```bash
git remote -v
```

用途：

- 确认 `origin` 的 fetch/push URL 指向哪里（官方仓库还是你 fork 的仓库）

### 3.2 修改 origin 指向（HTTP/SSH 切换）

把远端改成 HTTPS：

```bash
git remote set-url origin https://github.com/<user>/<repo>.git
```

把远端改成 SSH：

```bash
git remote set-url origin git@github.com:<user>/<repo>.git
```

说明（结合你提供的资料摘要）：

- 有文章会提到用 HTTPS 时可能会反复提示用户名密码（甚至建议配置 `user.password`）。
- 但 GitHub 已不支持“账号密码”进行 Git HTTPS 推送；通常需要 Personal Access Token（PAT）或直接使用 SSH。

### 3.3 推送新分支（方案 A）

```bash
git fetch origin
git checkout -b agent-demo
git push -u origin agent-demo
```

说明：

- `-u`（`--set-upstream`）会把本地分支与远端分支关联起来，后续可以直接 `git push` / `git pull`。

## 4. GitHub 认证相关笔记（结合你提供的三篇资料做整理）

### 4.1 HTTPS 推送反复要求输入账号密码 / 认证失败

常见现象：

- push 时弹出账号密码输入框，输入后提示密码错误
- 或报错类似：`remote: Invalid username or token. Password authentication is not supported ...`

关键结论：

- GitHub 不再支持用账号密码进行 Git HTTPS 推送
- 解决方式通常是：
  - 使用 SSH key（推荐，长期稳定）
  - 或使用 HTTPS + PAT（Personal Access Token）

### 4.2 SSH key 方式（推荐）

生成 key：

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

查看公钥并添加到 GitHub：

```bash
cat ~/.ssh/id_ed25519.pub
```

测试连接：

```bash
ssh -T git@github.com
```

切换 repo remote 为 SSH：

```bash
git remote set-url origin git@github.com:<user>/<repo>.git
```

### 4.3 关于“配置用户名/邮箱/密码”的补充澄清

你提供的资料里提到：

- `git config --global user.name ...`
- `git config --global user.email ...`

这两项用于**提交信息（commit author）**，是必需且正确的。

但像 `git config --global user.password ...` 这类做法不建议作为通用方案：

- 对 GitHub 来说，HTTPS 推送通常不再接受账号密码
- 也不建议在 git config 里明文保存敏感凭据

## 5. 跟 ClearML Agent 强相关的一条“最终检查清单”

当你再次遇到 agent clone/checkout 失败时，按这 5 条从上到下排：

1. Task 里显示的 `repository` 是否是你 fork 的仓库（而不是官方仓库）
2. Task 里显示的 `version_num` commit 是否已经 push 到远端
3. Task 里显示的 `entry_point` 路径在该 commit 中是否存在
4. 执行机是否具备访问远端仓库的权限（SSH key / PAT）
5. agent 是否被旧缓存干扰（必要时清理 `~/.clearml/vcs-cache` 对应 repo 缓存）

