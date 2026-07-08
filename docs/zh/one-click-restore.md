# 一键恢复

SafeVault GUI 首页现在是 Recovery Home。误删文件后，打开：

```bash
safevault ui --open
```

首页会显示最近删除的文件。点击 Restore 后，普通模式不需要输入 `RESTORE`，
但浏览器表单仍会提交显式确认。高级模式和旧版本页面仍兼容 `RESTORE`。

恢复边界：

- 只能恢复已经被 SafeVault 快照捕获的版本。
- 如果目标路径已有文件，SafeVault 会先保存当前版本，再恢复所选版本。
- 不做裸盘恢复。
- 不是恶意代码沙箱。
- 不会绕过系统权限。

CLI 仍可使用：

```bash
safevault recent deleted --since 24h
safevault restore <file> --latest
```
