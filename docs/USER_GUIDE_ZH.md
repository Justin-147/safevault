# SafeVault 用户指南

SafeVault 的目标是：安装一次，后台自动保护；误删、覆盖或 AI 修改出错时，
打开 Recovery Home 找回文件。普通用户不需要理解 snapshot 编号、hash 或对象库。

## 日常使用

```bash
safevault ui --open
safevault daemon status
safevault backup status
```

GUI 首页会显示受保护目录、daemon 健康状态、最近删除、最近修改、恢复时间线、
搜索和一键恢复入口。“最近删除”和“最近修改”每 5 秒自动更新；刚删除文件后无需
重新打开页面，通常几秒内即可看到。

顶部几个高级入口的用途：

- “AI 修改保护”：让 Codex 等工具先在项目副本中工作，确认差异后再应用；
- “健康与清理”：检查恢复数据是否完整，并清理无引用对象；
- “外部备份”：把恢复数据复制到其他磁盘，或从已有备份导入。

状态栏还会显示本地对象库用量和配置的空间预算。v1.1.5 的默认目标为 10GB；智能
保留仍只提供规划与 dry-run，因此 SafeVault 不会静默删除历史版本。

## 管理存储空间

在 Recovery Home 顶部打开“存储”，可以看到：

- 当前 SafeVault 数据位置、对象库和总占用；
- 当前磁盘剩余空间以及是否位于系统盘；
- 每个保护目录即使只留最新可恢复版本仍需的最低空间；
- 占用最大的已跟踪文件。

修改“空间目标”只会调整提醒值。若最低可恢复体积已经超过 10GB，应从“保护目录”
缩小范围，优先排除可重新下载或生成的视频、安装包、模型、数据集、构建产物。
不要直接在文件管理器里删除 SafeVault 对象库。

迁移到其他磁盘时，选择一个空目录。SafeVault 会停止后台保护、检查目标剩余空间、
复制数据库和对象、校验后再切换。若希望释放原磁盘空间，勾选删除旧副本并输入
`MOVE STORAGE`；校验失败时原数据不会被删除。大 vault 逐个校验可能需要较长时间。

高级用户可使用：

```bash
safevault storage status
safevault storage analyze
safevault storage budget 10
safevault storage migrate D:\SafeVaultData --remove-source --confirm "MOVE STORAGE"
```

## 保护文件夹

首次向导默认推荐 Desktop、Documents、Pictures，项目工作区默认不勾选。可以在
向导中直接输入其他路径，之后也可从 GUI 的“保护目录”页面添加或取消保护：

```bash
safevault protect add C:\Users\you\Documents --profile documents
safevault roots
```

SafeVault 会拒绝文件系统根目录、`SAFEVAULT_HOME` 和已配置备份目录等危险路径。

## 恢复误删文件

打开 `safevault ui --open`，在“最近删除的文件”里找到目标文件并点击 Restore。
普通恢复使用本地确认动作；删除、导入、覆盖、prune 等高风险操作仍需要明确
确认词。

如果文件没有出现，先确认它所在目录显示为“正在监听”。只有在删除前已被初始扫描
或自动保存捕获的文件才能恢复；刚创建后立刻删除、尚未来得及保存的文件可能没有
可恢复内容。

## 从 AI 或批量修改中恢复

建议通过 SafeVault 运行 AI 工具：

```bash
safevault run --project C:\Users\you\Projects\app -- codex
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
```

Codex、Cursor、Aider、Claude、Windsurf 等 AI 编程工具的 sandbox 会记录
`before-ai-change` 和 `after-ai-change` 恢复点。watcher 检测到大规模文件变化
时会记录 `after-large-change` 重要恢复点，方便在 Recovery Home 时间线中回到
风险修改前后。
如果短时间出现大量疑似加密扩展名，SafeVault 会记录
`emergency-mass-change` 恢复点并发出 error 通知。

## 备份

备份目录必须在受保护目录和 `SAFEVAULT_HOME` 外：

```bash
safevault backup configure --target E:\SafeVaultBackups --schedule daily
safevault backup run
safevault backup status
```

如果要防止本机磁盘损坏，请使用外置硬盘、NAS 或另一台机器。

## 暂停或关闭保护

```bash
safevault protect pause C:\Users\you\Documents --duration 30m
safevault protect resume C:\Users\you\Documents
safevault protect remove C:\Users\you\Documents --confirm
```

“停止自动保护”只停止监听，已有快照和历史仍可恢复。“彻底移除历史记录”则会删除
数据库中的版本和恢复索引，之后无法通过 SafeVault 恢复；该操作会要求预览并输入
目录 ID 或完整路径确认。

托盘中的“退出 SafeVault”会停止当前会话的 daemon、恢复首页和托盘。Windows 开机
启动设置决定下次登录时是否重新开始保护。

浏览器只是本地恢复界面，关闭浏览器标签不会停止 daemon。首次设置后，初始扫描会
继续在后台进行。若目录很大，请在恢复首页观察“最近保护点”和本地存储占用。

Windows 用户可以移除开机启动项：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_user.ps1
```

## 已知限制

SafeVault 是本地工具，不是远程管理控制台，不是恶意代码沙箱，也不是裸盘恢复。
如果要防止本机磁盘损坏，请把备份保存到外置硬盘、NAS 或其他机器。
