# SafeVault 安全模型

安全提醒：SafeVault 不做裸盘恢复，不是恶意代码沙箱，只能恢复已经被 SafeVault 快照捕获的版本；导出备份应保存到离机位置。

## 1. 数据保护边界

SafeVault 保护已经初始化的项目目录，并把快照内容写入本地 BLAKE3 内容寻址对象库。

## 2. sandbox 不是安全容器

`safevault run` 在复制目录中运行命令，避免直接修改原项目。但它不是恶意代码沙箱，不能限制网络、凭据或系统文件访问。

## 3. symlink 策略

快照不跟随 symlink。sandbox 中指向 root 外部的 external symlink 会变成 placeholder，并通过 sidecar map 识别。

## 4. apply 策略

apply 验证 diff schema、路径、文件类型、hash、冲突和 unsafe entry。删除默认跳过，GUI 里应用删除也必须输入 `ALLOW DELETE`。

## 5. export/import 策略

export 使用 SQLite backup，并只导出被备份数据库引用的对象。导入 import 会校验 archive 成员、manifest、数据库完整性和对象 hash。

## 6. destructive operations 策略

unprotect、sandbox-clean、prune、import overwrite、apply delete、restore、export overwrite 和 export skip verify 都需要 dry-run 或显式 confirm。

## 7. threat model / non-goals

非目标包括裸盘恢复、SSD TRIM 后恢复、恶意代码隔离、远程管理控制台、OS/离机备份替代。
