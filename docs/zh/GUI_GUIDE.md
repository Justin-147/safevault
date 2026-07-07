# SafeVault GUI 指南

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 启动 GUI

```bash
safevault ui --open
```

GUI 默认绑定 `127.0.0.1`，使用启动时打印的随机 token。它是本地工具，不是远程管理控制台。

## 2. Dashboard

Dashboard 显示版本、SAFEVAULT_HOME、doctor/verify 快速状态、roots 数量、快照数量、对象库大小和最近 sandbox。

## 3. Roots 页面

Roots 页面可以添加受保护目录、手动 snapshot、查看 root detail，并提供 unprotect dry-run/confirm。

## 4. Restore 页面

Versions 页面通过绝对路径查看版本历史，可以恢复 latest 或指定 version。覆盖已有文件时仍由后端 `restore_file()` 负责快照或备份。

## 5. Sandboxes 页面

Sandboxes 页面列出 sandbox 和 diff 计数。Detail 页面可以 apply dry-run、apply without delete，或者在输入 `ALLOW DELETE` 后 apply with delete。

## 6. Maintenance 页面

Maintenance 页面提供 doctor、verify、prune dry-run/confirm、sandbox-clean dry-run/confirm 和 retention-plan。

## 7. Export/Import 页面

Export 默认深度校验；skip verify 会显示为不推荐。Import 默认 dry-run，confirm 需要输入 `IMPORT`，overwrite 需要输入 `OVERWRITE`。

## 8. 常见警告含义

- `Local UI only. Not a remote admin console.`：GUI 只应本地访问。
- `ALLOW DELETE`：允许 apply 删除文件，风险较高。
- `IMPORT` / `OVERWRITE`：确认导入或覆盖目标 SAFEVAULT_HOME。

