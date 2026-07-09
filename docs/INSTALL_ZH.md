# SafeVault 安装指南

SafeVault 0.2.0rc1 是本地连续文件保护的 release candidate。它继续使用
BLAKE3 对象库和 SQLite 元数据，不会安装内核驱动，也不会开放远程管理端口。

## 安装

```bash
python -m pip install -e '.[dev,ui]'
safevault ui --open
```

Windows 用户可以使用用户级安装脚本，把 daemon 加入当前用户的开机启动项，
也可以选择启动 tray：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_user.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_windows_user.ps1 -WithTray -OpenUi
```

脚本内部调用 `safevault daemon install`，只写入当前用户 Startup 文件夹。
它不会删除文件，不会创建系统级服务，也不会改变 SafeVault 的 CLI 安全确认。

## 第一次启动

```bash
safevault ui --open
```

首次向导会让用户选择 Documents、Desktop、Projects、Pictures 或其他目录。
完成后 SafeVault 会创建初始快照，并可选配置外部备份目录。

## 移除开机启动项

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_user.ps1
```

卸载脚本只移除 Startup 文件夹中的 SafeVault 启动项，不删除快照、对象库、
保护 root 元数据或备份。

## 安全限制

SafeVault 不是裸盘恢复工具，只能恢复已经被快照或 watcher 捕获的版本。
如果担心本机磁盘损坏，请把 export/backup 放在外置硬盘、NAS 或其他机器上。
