# 自动备份

自动备份复用 SafeVault 现有 export 校验路径：

```bash
safevault backup configure --target D:\SafeVaultBackups --schedule daily
safevault backup status
safevault backup run
safevault backup disable
```

备份文件命名：

```text
safevault-backup-YYYYMMDD-HHMMSS.tar.gz
safevault-latest.tar.gz
```

安全规则：

- 备份目录不能位于 `SAFEVAULT_HOME` 内。
- 备份目录不能位于受保护 root 内。
- 自动备份不会删除用户文件。
- `safevault-latest.tar.gz` 只覆盖 SafeVault 自己的 latest 备份文件。
- 备份仍建议放到外置硬盘、同步盘或其他离机位置。

SafeVault 不是 OS 备份、Time Machine 或云同步的替代品。自动备份只是减少忘记
手动 export 的风险。
