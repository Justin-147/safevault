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
搜索和一键恢复入口。

状态栏还会显示本地对象库用量和配置的空间预算。v1.0.2 的智能保留只提供规划
与 dry-run，因此 SafeVault 不会静默删除历史版本。

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
