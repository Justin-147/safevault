# SafeVault 用户手册

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 安装 SafeVault

```bash
pip install -e '.[dev,ui]'
```

## 2. 初始化保护目录

```bash
safevault init ~/Projects/myapp
```

## 3. 手动快照

```bash
safevault snapshot ~/Projects/myapp --reason before-change
```

## 4. 查看文件历史

```bash
safevault versions ~/Projects/myapp/file.py
```

## 5. 恢复误删文件

```bash
safevault restore ~/Projects/myapp/file.py --latest
```

在 GUI 中恢复文件必须输入 `RESTORE`，因为恢复会写入目标路径；如果目标已存在，SafeVault 会先保存当前版本。

## 6. 使用 Codex 前运行 safevault run

```bash
safevault run --project ~/Projects/myapp -- codex
```

## 7. 审查 sandbox diff

```bash
safevault sandboxes --latest
safevault apply <sandbox-id> --dry-run
```

## 8. apply

默认不会删除文件：

```bash
safevault apply <sandbox-id>
```

如果确实要应用删除，先确认 diff，再显式：

```bash
safevault apply <sandbox-id> --allow-delete
```

## 9. 导出备份

```bash
safevault export --output /external/safevault-export.tar.gz --gzip
```

## 10. 导入备份

先 dry-run，再导入到新的 SAFEVAULT_HOME：

```bash
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --dry-run
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --confirm
```

## 11. 检查健康状态

```bash
safevault doctor --deep
safevault verify --deep
```

## 12. 清理 sandbox

```bash
safevault sandbox-clean --older-than 30d --status applied --dry-run
safevault sandbox-clean --older-than 30d --status applied --confirm
```

GUI 中确认清理 sandbox 必须输入 `CLEAN SANDBOXES`。

## 13. 取消保护 root

```bash
safevault unprotect ~/Projects/myapp --dry-run
safevault unprotect ~/Projects/myapp --confirm
```

其他 GUI 确认词包括：apply 删除输入 `ALLOW DELETE`，prune 输入 `PRUNE`，覆盖导出输入 `OVERWRITE EXPORT`，跳过导出校验输入 `SKIP VERIFY`，导入输入 `IMPORT`，覆盖导入目标输入 `OVERWRITE`。
