# SafeVault 恢复手册

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 刚误删单个文件

打开恢复首页，在“最近删除”中找到文件并点击“恢复”。普通恢复使用本地确认框，
不要求输入确认词。也可以使用 CLI：

```bash
safevault deleted --since 24h
safevault restore /path/to/file --latest
```

如果原位置已经存在文件，SafeVault 会先保存当前版本。需要保留两份文件时，在历史
页面选择“恢复到其他位置”。

## 2. Codex 删除了一批文件

先查看 sandbox diff：

```bash
safevault apply <sandbox-id> --dry-run
```

默认 apply 会跳过删除。确认需要删除时才使用 `--allow-delete`。
GUI 中应用删除必须输入 `ALLOW DELETE`。

## 3. apply 后发现覆盖了内容

SafeVault 会在 apply 前后创建恢复点。优先在 Recovery Home 时间线中选择
`before-ai-change` 或 apply 前的恢复点；高级用户也可以使用 `versions` 查找版本。

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

SafeVault 不跟随指向受保护 root 外部的 symlink。sandbox 中外部 symlink 会变成
placeholder，并由 sidecar metadata 识别。
