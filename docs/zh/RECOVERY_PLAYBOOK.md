# SafeVault 恢复手册

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 刚误删单个文件

```bash
safevault deleted --since 24h
safevault restore /path/to/file --latest
```

## 2. Codex 删除了一批文件

先查看 sandbox diff：

```bash
safevault apply <sandbox-id> --dry-run
```

默认 apply 会跳过删除。确认需要删除时才使用 `--allow-delete`。

## 3. apply 后发现覆盖了内容

SafeVault 会在 apply 前后创建快照。使用 `versions` 找到 apply 前版本并 restore。

## 4. vault.db 或 objects 损坏

先运行：

```bash
safevault doctor --deep
safevault verify --deep
```

如果导出备份健康，可导入到新的 SAFEVAULT_HOME。

## 5. 换机器恢复 SafeVault export

```bash
safevault import --input safevault-export.tar.gz --target-home /new/safevault-home --dry-run
safevault import --input safevault-export.tar.gz --target-home /new/safevault-home --confirm
```

## 6. 目录里有 symlink

SafeVault 不跟随指向受保护 root 外部的 symlink。sandbox 中外部 symlink 会变成 placeholder，并由 sidecar metadata 识别。

