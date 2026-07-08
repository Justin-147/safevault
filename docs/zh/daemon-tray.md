# 守护进程和托盘

daemon 是 SafeVault 自动保护模式的核心：

```bash
safevault daemon run
safevault daemon status
safevault daemon stop
safevault daemon install
safevault daemon uninstall
```

daemon 会：

- 保持单实例运行。
- 写入 heartbeat。
- 启动时对启用 root 做 startup scan。
- 对 created/modified/moved 事件做 debounce 后快照。
- 对已跟踪文件的 deleted 事件立即写入 deleted marker。
- 对批量删除写 warning notification。
- 在空闲时运行轻量 verify。

托盘程序是可选功能：

```bash
pip install -e '.[tray]'
safevault tray
safevault tray --open-ui
```

托盘菜单可以打开本地 GUI、运行快照、运行 verify、触发 backup、暂停保护 30
分钟和恢复保护。托盘不会绕过 CLI 的安全边界，也不会自动执行 destructive
operation。
