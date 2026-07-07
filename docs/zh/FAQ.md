# SafeVault FAQ

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## Q: 彻底删除后能恢复吗？

只能恢复已经被 SafeVault 快照捕获的版本。没有快照就没有对象内容可恢复。

## Q: 没有提前 snapshot 能恢复吗？

不能保证。SafeVault 不是裸盘恢复工具。

## Q: SafeVault 和 Git 有什么区别？

Git 保护提交历史；SafeVault 保护本地文件快照，包括未提交文件。

## Q: SafeVault 和 Time Machine/系统备份有什么区别？

系统备份覆盖整机或卷级历史；SafeVault 聚焦项目目录，不替代 OS/离机备份。

## Q: 为什么 apply 默认不删除？

删除是高风险操作，所以默认跳过，必须显式 `--allow-delete` 或 GUI 输入 `ALLOW DELETE`。

## Q: 为什么 export 不能放在 SAFEVAULT_HOME 里？

把导出备份放在 vault 内会让备份和源数据一起损坏或丢失。应保存到离机位置。

## Q: GUI 是否能远程访问？

默认不能。GUI 只绑定 `127.0.0.1` 并使用随机 token。不要暴露到公网。

## Q: Codex 会不会通过 GUI 破坏原目录？

GUI 调用现有后端安全函数，不绕过 dry-run、confirm、apply 删除确认和 restore 保护。

## Q: 为什么 GUI 要输入这些英文确认词？

`RESTORE`、`ALLOW DELETE`、`PRUNE`、`CLEAN SANDBOXES`、`OVERWRITE EXPORT`、`SKIP VERIFY`、`IMPORT`、`OVERWRITE` 都对应会写入、删除、覆盖或导入数据的操作。确认词可以降低误点风险。
