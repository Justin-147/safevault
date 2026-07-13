# SafeVault 安装指南

SafeVault 1.1.2 提供稳定的本地连续文件保护。它继续使用
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
两个开机启动选项都可以在安装时取消。后台保护、托盘和恢复首页均为隐藏启动，
正常情况下不会留下终端窗口。

安装器会单独询问“SafeVault data location”。这里保存数据库和可恢复文件内容，
不是程序安装目录。有 D 盘时默认建议 `D:\SafeVaultData`；用户可以改为其他非系统盘
空目录。检测到已有数据时，安装器会显示当前位置说明页，而不是提供可编辑的目录框；
这是为了避免在升级过程中直接搬动正在使用的对象库。安装完成后会自动打开 Recovery
Home 的“存储”页面。选择新的空目录后，SafeVault 会停止后台保护、复制并校验全部
数据，只有用户明确选择时才删除旧副本并释放原磁盘空间。

## 第一次启动

```bash
safevault ui --open
```

首次向导会推荐 Documents、Desktop、Pictures，并把较大的项目工作区作为可选项。
用户也可以输入多个自定义目录。完成后 SafeVault 立即进入恢复首页，daemon 在后台
创建初始恢复点；浏览器可以关闭，不会停止后台保护。

首次向导还会显示数据位置和默认 10GB 空间目标。10GB 是提醒与规划目标，不是硬
上限；如果所选文件本身超过 10GB，SafeVault 不会为了达标而删除唯一恢复副本。

不要为了省事保护整个磁盘或包含许多项目的顶层目录。优先添加具体项目和个人文件
目录，可以显著减少首次扫描时间和本地对象库占用。

## 移除开机启动项

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_user.ps1
```

卸载脚本只移除 Startup 文件夹中的 SafeVault 启动项，不删除快照、对象库、
保护 root 元数据或备份。

## 安全限制

SafeVault 不是裸盘恢复工具，只能恢复已经被快照或 watcher 捕获的版本。
如果担心本机磁盘损坏，请把 export/backup 放在外置硬盘、NAS 或其他机器上。
