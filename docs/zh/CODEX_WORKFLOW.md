# Codex 安全工作流

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

推荐流程：

```bash
safevault init <project>
safevault snapshot <project> --reason before-codex
safevault run --project <project> -- codex
safevault sandboxes --latest
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
```

`safevault run` 会复制项目到 sandbox，Codex 在复制目录中工作，原项目不会被 run 直接修改。

## 删除策略

`safevault apply <sandbox-id>` 默认跳过删除。只有在你审查 diff 后明确同意，才使用：

```bash
safevault apply <sandbox-id> --allow-delete
```

GUI 中 apply with delete 也必须输入 `ALLOW DELETE`。

## GUI 审查 diff

打开：

```bash
safevault ui --open
```

进入 Sandboxes 页面，查看 created、modified、deleted 条目，再执行 dry-run。

