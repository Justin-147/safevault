# SafeVault 中文说明

[English README](README.md)

SafeVault 是一个本地项目目录保护和恢复工具。它通过快照记录文件历史，
把内容存入 BLAKE3 地址化对象库，并提供恢复、沙箱运行、保守 apply、
导出备份和导入校验能力。

## 1. SafeVault 是什么

SafeVault 适合在使用 Codex、脚本或批量重构工具前保护项目目录。它可以：

- 初始化受保护目录。
- 手动或自动记录快照。
- 查看文件版本历史。
- 恢复误删或被覆盖的文件。
- 在复制出来的 sandbox 中运行命令。
- 审查 sandbox diff 后再决定是否 apply。
- 导出备份并在新 SAFEVAULT_HOME 中导入。
- 通过本地 GUI 做常见操作。

## 2. SafeVault 不能做什么

安全边界必须说清楚：

- 不做裸盘恢复。
- 不是恶意代码沙箱。
- 只能恢复已经被 SafeVault 快照捕获的版本。
- 不保证 SSD TRIM 后恢复。
- 不是 OS 备份、Time Machine、云同步或离机备份的替代品。
- `safevault run` 保护原项目目录不被直接修改，但命令仍可能访问用户权限允许的系统资源。

## 3. 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ui]'
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -e .[dev,ui]
```

## 4. 快速开始

```bash
safevault init ~/Projects/myapp
safevault snapshot ~/Projects/myapp --reason initial
safevault versions ~/Projects/myapp/file.py
safevault restore ~/Projects/myapp/file.py --latest
safevault verify --deep
```

## 5. 常用命令

```bash
safevault roots
safevault status ~/Projects/myapp
safevault deleted --since 7d
safevault doctor --deep
safevault prune --dry-run
```

## 6. 可视化界面

启动本地 GUI：

```bash
safevault ui --open
```

GUI 默认只监听 `127.0.0.1`，启动时生成随机 token。不要把 GUI 暴露到公网。
详细说明见 [GUI 指南](docs/zh/GUI_GUIDE.md)。

## 7. Codex 安全工作流

```bash
safevault snapshot ~/Projects/myapp --reason before-codex
safevault run --project ~/Projects/myapp -- codex
safevault sandboxes --latest
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
```

默认 apply 不删除文件；删除必须显式 `--allow-delete`。详见
[Codex 工作流](docs/zh/CODEX_WORKFLOW.md)。

## 8. 误删恢复

误删后先查看最近删除记录，再恢复最新非删除版本：

```bash
safevault deleted --since 24h
safevault restore ~/Projects/myapp/file.py --latest
```

完整步骤见 [恢复手册](docs/zh/RECOVERY_PLAYBOOK.md)。

## 9. 导出/导入备份

导出备份应保存到离机位置：

```bash
safevault export --output /external/safevault-export.tar.gz --gzip
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --dry-run
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --confirm
```

## 10. 常见问题

见 [FAQ](docs/zh/FAQ.md) 和 [故障排除](docs/zh/TROUBLESHOOTING.md)。

## 11. 安全限制

SafeVault 的安全模型见 [安全模型](docs/zh/SAFETY_MODEL.md)。核心原则是：
不信任 diff、导入 archive 和外部 symlink placeholder；破坏性操作需要 dry-run
或 confirm；对象内容在读取和恢复前校验 hash。

## 12. 版本状态

当前版本是 `0.1.0rc1`，是 release candidate，不是 stable/final。

