# 首次启动向导

首次打开 GUI：

```bash
safevault ui --open
```

如果还没有完成 onboarding，SafeVault 会显示首次启动向导：

1. 选择保护目录。
2. 可选配置自动备份目录。
3. 确认安全说明。
4. 创建 root。
5. 创建初始快照。

默认候选目录包括 Desktop、Documents、Projects、source 和 CodexWork 等常见
位置。SafeVault 只显示存在且通过安全检查的目录。

可以跳过备份目录，但 GUI 会继续提醒：如果本机磁盘损坏或 `SAFEVAULT_HOME`
丢失，本地对象库也可能丢失。建议尽早配置外部备份目录。
