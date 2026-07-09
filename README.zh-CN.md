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
- 不是裸盘恢复工具。
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

连续保护模式的完整说明见 [中文安装指南](docs/INSTALL_ZH.md)、
[中文用户指南](docs/USER_GUIDE_ZH.md)、[Install Guide](docs/INSTALL_EN.md) 和
[User Guide](docs/USER_GUIDE_EN.md)。

Windows 发布构建者可以使用 `scripts/build_windows_installer.ps1` 和 Inno Setup
生成 `dist/SafeVaultSetup.exe`。

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

GUI 高风险操作需要输入确认词：`RESTORE`、`ALLOW DELETE`、`PRUNE`、
`CLEAN SANDBOXES`、`OVERWRITE EXPORT`、`SKIP VERIFY`、`IMPORT`、`OVERWRITE`。
GUI 导入默认是 dry-run。要在浏览器里真正导入，需要取消 dry-run 并输入
`IMPORT`；覆盖目标还必须输入 `OVERWRITE`。SafeVault 仍是 `0.2.0rc1`
release candidate，不是 stable/final。

## 6.1 自动保护模式

SafeVault 0.2.0rc1 新增自动保护模式。目标是让用户完成一次配置后，
后台守护进程自动记录文件变化，误删后打开 GUI 首页即可看到“最近删除”。

```bash
safevault protect auto-detect
safevault protect add ~/Documents --profile documents
safevault daemon run
safevault recent deleted --since 24h
safevault search report --deleted
```

`protect add` 会拒绝文件系统根目录、`SAFEVAULT_HOME`、包含
`SAFEVAULT_HOME` 的目录、重复 root，以及已配置的备份目录。`protect remove
--confirm` 只停用自动保护，不删除已有快照和对象库；再次对同一路径执行
`protect add` 会重新启用自动保护。

连续保护元数据会和现有快照模型一起记录：SafeVault 会写入文件事件日志、
版本时间线和快照恢复点，但文件内容仍然保存在 BLAKE3 地址化对象库中。
watcher 触发的自动保存会变成普通可恢复版本，用户不需要管理 snapshot 编号。
`safevault retention-plan --smart` 会生成非破坏性的智能保留计划，用于平衡
最近高频版本、小时/天级恢复点、最新版本和重要 checkpoint。
`safevault.retention_engine` 会做 dry-run 空间估算，但不会删除数据。

AI/Codex 保护模式会自动识别通过 `safevault run` 启动的 `codex`、`cursor`、
`aider`、`claude`、`windsurf` 等 AI 编程工具：AI 修改前记录
`before-ai-change` 恢复点，sandbox apply 后记录 `after-ai-change` 恢复点；
watcher 检测到大规模文件变化时也会记录 `after-large-change` 重要恢复点。

## 6.2 第一次启动向导

第一次打开：

```bash
safevault ui --open
```

GUI 会显示首次启动向导：选择保护目录、可选配置备份目录、确认安全边界。
完成后 SafeVault 会自动添加 root 并创建初始快照。详见
[首次启动向导](docs/zh/onboarding.md)。

## 6.3 误删后如何一键恢复

GUI 首页现在是 Recovery Home，会显示最近删除、最近修改、恢复时间线、搜索和快捷操作。
恢复中心的历史版本页面默认隐藏 snapshot ID、version ID 和对象 hash，只显示
恢复点名称和时间；技术编号只作为表单内部字段使用。
普通恢复不再要求输入 `RESTORE`，但仍由本地 UI 提交显式确认；高级模式和旧
流程仍兼容 `RESTORE`。详见 [一键恢复](docs/zh/one-click-restore.md)。

## 6.4 后台守护进程和托盘

```bash
safevault daemon run
safevault daemon status
safevault daemon stop
safevault tray
```

daemon 单实例运行，记录 heartbeat，启动时扫描启用 root，文件变化后自动快照。
删除事件会立即记录 deleted marker；批量删除和大规模文件变化会生成 warning。
如果短时间出现大量 `.locked`、`.encrypted`、`.crypt` 等疑似加密扩展名，
SafeVault 会记录 `emergency-mass-change` 重要恢复点并发出 error 通知，但仍
不会自动删除或回滚用户文件。
托盘是可选功能，需要安装：

```bash
pip install -e '.[tray]'
```

详见 [守护进程和托盘](docs/zh/daemon-tray.md)。

## 6.5 自动导出备份

```bash
safevault backup configure --target D:\SafeVaultBackups --schedule daily
safevault backup status
safevault backup run
safevault backup disable
```

自动备份复用现有 export 校验路径，备份文件名使用
`safevault-backup-YYYYMMDD-HHMMSS-ffffff.tar.gz`，备份目录不能位于
`SAFEVAULT_HOME` 或受保护 root 内。详见 [自动备份](docs/zh/automatic-backup.md)。

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

GUI 导入同样先 dry-run。确认导入时取消 dry-run，输入 `IMPORT`；如需覆盖目标，
还要输入 `OVERWRITE`。

## 10. 常见问题

见 [FAQ](docs/zh/FAQ.md)、[自动保护模式](docs/zh/auto-protection.md) 和
[故障排除](docs/zh/TROUBLESHOOTING.md)。

## 11. 安全限制

SafeVault 的安全模型见 [安全模型](docs/zh/SAFETY_MODEL.md)。核心原则是：
不信任 diff、导入 archive 和外部 symlink placeholder；破坏性操作需要 dry-run
或 confirm；对象内容在读取和恢复前校验 hash。

## 12. 版本状态

当前版本是 `0.2.0rc1`，是 release candidate，不是 stable/final。
