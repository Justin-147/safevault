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

Codex/Cursor sandbox 会记录 `before-ai-change` 和 `after-ai-change` 恢复点。
watcher 检测到大规模文件变化时会记录 `after-large-change` 重要恢复点，方便在
Recovery Home 时间线中回到风险修改前后。

## 暂停或关闭保护

```bash
safevault protect pause C:\Users\you\Documents --duration 30m
safevault protect resume C:\Users\you\Documents
safevault protect remove C:\Users\you\Documents --confirm
```

暂停和移除保护不会删除已经保存的快照或对象内容。

## 已知限制

SafeVault 是本地工具，不是远程管理控制台，不是恶意代码沙箱，也不是裸盘恢复。
如果要防止本机磁盘损坏，请把备份保存到外置硬盘、NAS 或其他机器。
