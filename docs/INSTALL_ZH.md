# SafeVault 安装指南

SafeVault 1.0.0 提供稳定的本地连续文件保护。它继续使用
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

## 构建 SafeVaultSetup.exe

发布构建者可以用 PyInstaller 和 Inno Setup 生成一键 Windows 安装器：

```powershell
python -m pip install -e '.[installer,ui,tray]'
powershell -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

安装器定义在 `packaging/windows/SafeVaultSetup.iss`，输出
`dist/SafeVaultSetup.exe`。安装器默认注册当前用户的 daemon 和 tray 开机
启动项，立即启动本次会话的后台保护，并在安装完成后打开首次启动向导。
两个开机启动选项都可以在安装时取消。

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
