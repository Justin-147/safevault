# 自动保护模式

SafeVault 0.2.0rc1 的自动保护模式用于减少用户日常操作负担。完成一次配置后，
后台 daemon 会持续观察启用的 root，并在文件变化后自动创建快照。

常用命令：

```bash
safevault protect auto-detect
safevault protect add <path> --profile coding
safevault protect list
safevault protect pause <path> --duration 30m
safevault protect resume <path>
safevault protect remove <path> --confirm
```

安全边界：

- 不保护文件系统根目录。
- 不保护 `SAFEVAULT_HOME`，也不保护包含 `SAFEVAULT_HOME` 的目录。
- 不把备份目录作为受保护 root。
- 不跟随外部 symlink。
- 不自动删除用户文件。
- 只能恢复已经被 SafeVault 快照捕获的版本。

`protect remove --confirm` 只停用自动保护策略，不删除历史快照和对象库。
如果要删除 root 元数据，请使用更明确的 `safevault unprotect --confirm`。
