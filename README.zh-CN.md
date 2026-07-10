# SafeVault 中文说明

**[English](README.md) | [中文安装指南](docs/INSTALL_ZH.md) | [中文用户指南](docs/USER_GUIDE_ZH.md) | [文档中心](docs/README.md)**

SafeVault 是一款本地优先的文件保护和恢复工具。选择需要保护的文件夹后，它会在
后台记录可恢复版本，在恢复首页显示最近删除和修改，并把高风险 AI 编程操作放到
项目副本中执行。

## 从这里开始

- 第一次安装：[中文安装指南](docs/INSTALL_ZH.md)
- 日常保护和恢复：[中文用户指南](docs/USER_GUIDE_ZH.md)
- 误删或批量修改后的处理：[恢复手册](docs/zh/RECOVERY_PLAYBOOK.md)
- 常见疑问：[常见问题](docs/FAQ_ZH.md)

普通用户不需要理解 snapshot 编号、对象 hash 或 SQLite。安装后完成一次向导，平时
让 SafeVault 在后台运行，需要恢复时再打开恢复首页。

## SafeVault 能做什么

- 自动保护首次向导中选中的文件夹。
- 文件变化后记录版本，已跟踪文件消失后记录删除标记。
- 从“最近删除”、搜索或版本时间线一键恢复。
- 使用 BLAKE3 内容寻址对象库去重保存文件内容。
- 使用 SQLite 记录路径、版本、事件和恢复点。
- 通过 `safevault run` 为 Codex 等 AI 编程操作建立前后恢复点。
- 对异常的大批量变化和疑似加密扩展名发出警告。
- 把校验后的备份导出到外置硬盘、NAS 或其他位置。

## 安装

Windows 普通用户应运行 `SafeVaultSetup.exe`。安装器可以默认启用当前用户的后台
保护和托盘开机启动，也可以在安装时取消这些选项。安装结束后会打开首次启动向导。

源码安装面向开发者：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev,ui,tray]
safevault ui --open
```

完整步骤见 [中文安装指南](docs/INSTALL_ZH.md)。

## 第一次使用

首次向导会推荐当前电脑上实际存在的 Desktop、Documents 和 Pictures。较大的项目
工作区会列出但默认不勾选，也可以直接输入其他文件夹路径。只选择真正需要保护的
目录。提交设置后页面会立即返回，初始恢复点由后台建立，此时可以关闭浏览器。

以后打开恢复首页：

```bash
safevault ui --open
```

## 恢复误删文件

在恢复首页的“最近删除”或搜索结果中找到文件，选择恢复点并点击“恢复”。如果原位置
已经存在文件，SafeVault 会先保存当前内容再写回历史版本。

高级用户仍可使用 CLI：

```bash
safevault recent deleted --since 24h
safevault restore C:\path\to\file --latest
```

初始化和手动恢复命令仍然兼容：

```bash
safevault init C:\path\to\folder
safevault restore C:\path\to\file --latest
```

更多场景见 [恢复手册](docs/zh/RECOVERY_PLAYBOOK.md)。

## 保护 AI 编程操作

```bash
safevault run --project C:\path\to\project -- codex
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
```

命令只在项目副本中运行。应用结果时 SafeVault 会检查路径、类型、hash、symlink 和
冲突；默认跳过删除，只有显式传入 `--allow-delete` 才允许应用删除。

详细说明见 [Codex 安全工作流](docs/zh/CODEX_WORKFLOW.md)。

## 备份和恢复原理

SafeVault 把变化后的文件内容流式写入不可变的 BLAKE3 对象库，同一内容只保存一次。
SQLite 记录保护目录、版本、删除标记、事件和恢复点。恢复前会校验对象内容，并通过
临时文件和原子替换写回目标位置。

## 必须了解的限制

- SafeVault 不是裸盘恢复工具，只能恢复开始保护后已经捕获的内容。
- 无法恢复从未保存过的文件，也无法保证恢复 SSD TRIM 后的磁盘块。
- `safevault run` 防止命令直接改动原项目，但不是恶意代码沙箱。
- watcher 是尽力而为机制，已经完成的版本才是恢复依据。
- v1.0.1 的智能保留只做规划和 dry-run，不会静默删除历史版本。
- 本地对象库无法防止整块磁盘损坏，应把导出备份放到其他设备。

## 文档导航

不要逐个翻找文件名。进入 [文档中心](docs/README.md)，按“安装、日常使用、恢复、
常见问题、高级功能”查找即可。

## 开发与发布检查

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
bash scripts/release_check.sh
```

当前稳定版本为 `1.0.1`。版本变化见 [CHANGELOG.md](CHANGELOG.md) 和
[v1.0.1 发布说明](docs/releases/v1.0.1.md)。
