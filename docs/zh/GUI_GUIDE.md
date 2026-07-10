# SafeVault GUI 指南

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 启动 GUI

```bash
safevault ui --open
```

GUI 默认绑定 `127.0.0.1`，使用启动时打印的随机 token。token 是一次启动期间的访问口令，可以放在 URL query、`X-SafeVault-Token` header 或本地 cookie 中。默认只监听 `127.0.0.1` 是为了避免局域网或公网机器访问你的本地 vault。它是本地工具，不是远程管理控制台，不要暴露到公网。

## 2. 恢复首页

恢复首页显示后台保护状态、保护目录、最近保护点、备份状态、健康状态和对象库
空间使用，同时提供最近删除、最近修改、时间线、搜索和一键恢复入口。

## 3. Roots 页面

Roots 页面可以添加受保护目录、手动 snapshot、查看 root detail，并提供 unprotect dry-run/confirm。添加目录相当于 `safevault init`；创建快照相当于 `safevault snapshot --reason ui-manual`。

## 4. Deleted / Versions 恢复

Deleted 页面显示最近删除记录。Versions 页面通过绝对路径查看版本历史，可以恢复
latest 或指定 version。恢复会写入目标路径；如果目标已存在，仍由后端
`restore_file()` 负责先保存当前版本。普通模式使用浏览器本地确认框，高级模式
仍要求输入 `RESTORE`。

## 5. Sandboxes 页面

Sandboxes 页面列出 sandbox 和 diff 计数。Detail 页面可以 dry-run、apply without delete，或者在输入 `ALLOW DELETE` 后 apply with delete。删除需要 `ALLOW DELETE`，因为 apply 默认跳过删除，避免一次误操作删掉原项目文件。

## 6. Maintenance 页面

Maintenance 页面提供 doctor、verify、prune dry-run/confirm、sandbox-clean dry-run/confirm 和 retention-plan。prune 会删除未引用对象，所以确认执行必须输入 `PRUNE`。sandbox clean 会删除 applied sandbox 目录，所以确认执行必须输入 `CLEAN SANDBOXES`。

## 7. Export/Import 页面

Export 默认深度校验；skip verify 不推荐，必须输入 `SKIP VERIFY`。覆盖已有 export 文件必须输入 `OVERWRITE EXPORT`。Import 默认 dry-run。默认表单会验证 archive，但不会写入目标 SAFEVAULT_HOME。要真正导入，需要取消 dry-run、勾选 confirm 并输入 `IMPORT`；overwrite 需要输入 `OVERWRITE`。即使勾选 confirm，只要 dry-run 仍开启，就不会写入目标 SAFEVAULT_HOME。

## 8. 常见警告含义

- `Local UI only. Not a remote admin console.`：GUI 只应本地访问。
- `RESTORE`：高级模式下确认恢复会写入目标路径；普通模式使用本地确认框。
- `ALLOW DELETE`：允许 apply 删除文件，风险较高。
- `PRUNE`：确认删除未引用对象。
- `CLEAN SANDBOXES`：确认清理 applied sandbox 目录。
- `OVERWRITE EXPORT`：确认覆盖已有导出文件。
- `SKIP VERIFY`：确认跳过导出前深度校验。
- `IMPORT` / `OVERWRITE`：确认导入或覆盖目标 SAFEVAULT_HOME。
