# SafeVault 故障排除

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. doctor unhealthy

运行 `safevault doctor --deep`，查看 ERROR 项。缺失 root、缺失对象、损坏对象都需要优先处理。

## 2. verify corrupted object

对象 hash 与文件名不一致。尝试从离机导出备份恢复。

## 3. missing referenced object

数据库引用了对象库中不存在的内容。检查是否误删了 `objects/`。

## 4. sandbox apply conflict

原项目在 run 后发生变化。重新审查 diff，必要时重新创建 sandbox。

## 5. unsafe diff entry

diff 里有受保护路径、外部 symlink、缺失 hash 或特殊文件。SafeVault 会拒绝应用。

## 6. import archive rejected

archive 路径、manifest、SQLite 完整性或对象 hash 不符合要求。只导入你信任的 archive。

GUI import 默认 dry-run。如果你已经输入 `IMPORT` 但目标没有生成，请确认是否仍然勾选了 dry-run。真正导入需要取消 dry-run、勾选 confirm，并输入 `IMPORT`；覆盖目标还需要 `OVERWRITE`。

## 6.1 GUI confirmation rejected

确认词必须完全匹配，例如 `RESTORE`、`CLEAN SANDBOXES`、`OVERWRITE EXPORT`、`SKIP VERIFY`、`IMPORT`、`OVERWRITE`。大小写或空格不一致都会被拒绝。

## 7. Windows symlink 权限问题

启用 Developer Mode 或使用管理员权限创建 symlink；否则相关测试会跳过或使用 fallback。

## 8. macOS 权限问题

确认终端有访问项目目录的权限，尤其是 Desktop、Documents、Downloads。

## 9. SQLite database locked

关闭正在运行的 SafeVault 进程后重试。SafeVault 使用 WAL 和 busy timeout，但外部锁仍可能阻塞。

## 10. SAFEVAULT_HOME 设置错误

确认环境变量指向预期目录：

```bash
echo "$SAFEVAULT_HOME"
safevault doctor
```
