# SafeVault 自动保护模式开发方案（交给 Codex 执行版）

> 目标：把 SafeVault 从“工程师主动使用的安全工具箱”，升级为“普通用户长期打开、自动保护、误删后直接找回”的本地恢复软件。  
> 原则：不削弱现有 CLI 安全边界；先做 Windows 优先的可用 RC，再逐步扩展 macOS/Linux。

---

## 0. 给 Codex 的总指令

把本文件放到 SafeVault 仓库根目录，然后对 Codex 说：

```text
Read SAFEVAULT_AUTO_PROTECTION_PRODUCTIZATION_CODEX_PLAN.md and implement it from beginning to end in small, tested phases.

Do not rewrite the existing snapshot/restore/apply/export/import core unless necessary.
Preserve all current safety guarantees.
Focus on automatic protection, daemon/tray operation, onboarding, recent-deleted recovery UX, and automatic export.

Before finishing every phase, run:
ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
bash scripts/release_check.sh when available on the platform
```

---

## 1. 产品目标

当前 SafeVault 的核心能力已经较强：

```text
init
snapshot
restore
run sandbox
apply
doctor / verify
export / import
local GUI
Chinese docs
```

但它仍然要求用户主动记住：

```text
先 init
再 snapshot
定期 verify
定期 export
需要时打开 GUI
手动搜索版本和删除记录
```

下一阶段目标是让用户只完成一次配置，之后 SafeVault 自动工作：

```text
首次启动向导 -> 自动保护目录 -> 后台守护进程持续运行 -> 文件变化自动快照
-> 误删后 GUI 首页直接显示最近删除 -> 一键恢复
-> 定期自动导出备份 -> 定期健康检查
```

最终体验应当是：

```text
用户不需要记得 snapshot。
用户不需要知道对象库细节。
用户不需要每天手动 verify/export。
用户误删后打开 GUI 就能看到“最近删除”，点击恢复。
```

---

## 2. 本阶段范围

### 必须实现

1. `safevault daemon`
2. `safevault tray`
3. GUI 首次启动向导
4. 自动保护常见目录
5. 自动快照策略
6. 最近删除/最近修改首页
7. GUI 一键恢复
8. 自动导出备份
9. 后台健康检查
10. 中文文档更新
11. 测试与 smoke 脚本

### 不要实现

1. 裸盘恢复
2. 绕过权限
3. 恶意代码强隔离沙箱
4. 云端同步
5. 自动删除用户文件
6. 自动应用 Codex 删除
7. 未确认的 destructive operation

---

## 3. 用户故事

### 用户故事 1：首次使用

用户安装后执行：

```powershell
safevault ui --open
```

GUI 检测到尚未完成 onboarding，自动进入向导：

```text
第 1 步：选择保护目录
第 2 步：选择备份导出目录
第 3 步：设置保留策略
第 4 步：是否开机自启
第 5 步：确认安全说明
```

完成后：

```text
SafeVault 自动创建 roots
自动创建初始快照
启动 daemon
可选启动 tray
```

### 用户故事 2：误删恢复

用户误删文件后：

```text
打开 SafeVault GUI
首页显示“最近删除”
点击文件
选择“恢复到原位置”或“另存为”
确认弹窗
恢复完成
```

普通恢复不需要输入 `RESTORE`；只需要 GUI 确认弹窗。  
高级模式仍可保留确认词。

### 用户故事 3：Codex 自动保护

用户运行 Codex 前仍推荐：

```powershell
safevault run --project <project> -- codex
```

但如果用户直接在项目目录运行 Codex，daemon 也会监控到文件变化：

```text
大量修改自动分组
删除立即记录
批量删除触发告警
```

### 用户故事 4：自动导出

用户选择备份目录后：

```text
SafeVault 每天或每周自动 export
GUI 显示最近一次成功备份时间
失败时提醒用户
备份目录不可位于 SAFEVAULT_HOME 内部
```

---

## 4. 新增 CLI 命令

### 4.1 daemon 命令

```bash
safevault daemon run
safevault daemon status
safevault daemon stop
safevault daemon install
safevault daemon uninstall
```

语义：

```text
run       前台运行 daemon，适合调试
status    查看 daemon 是否运行、最后 heartbeat、当前 roots
stop      请求 daemon 停止
install   安装开机自启，Windows 优先实现
uninstall 移除开机自启
```

Windows v1 推荐实现方式：

```text
优先：用户级启动项 / Startup shortcut
后续：计划任务 Task Scheduler
暂不做：Windows Service
```

### 4.2 tray 命令

```bash
safevault tray
safevault tray --open-ui
```

托盘菜单：

```text
Open SafeVault
Recent Deleted
Run Snapshot Now
Run Verify
Backup Now
Pause Protection 30 min
Resume Protection
Quit
```

实现建议：

```text
使用 pystray + pillow，放在 optional dependency [tray]
没有 GUI 环境时优雅失败
```

### 4.3 protect 命令

```bash
safevault protect list
safevault protect add <path> [--profile documents|coding|downloads|desktop]
safevault protect remove <path> [--confirm]
safevault protect auto-detect
safevault protect pause <path>
safevault protect resume <path>
```

### 4.4 recent 命令

```bash
safevault recent deleted [--since 24h]
safevault recent modified [--since 24h]
safevault recent activity [--since 24h]
```

### 4.5 backup 命令

```bash
safevault backup configure --target <path> [--schedule daily|weekly|manual]
safevault backup status
safevault backup run
safevault backup disable
```

---

## 5. 配置设计

新增或扩展：

```text
~/.safevault/config.toml
```

示例：

```toml
[app]
onboarding_completed = true
advanced_mode = false
language = "zh-CN"

[daemon]
enabled = true
heartbeat_interval_seconds = 30
watch_debounce_seconds = 3
batch_window_seconds = 20
bulk_delete_threshold = 20
bulk_delete_window_seconds = 30
hourly_snapshot_enabled = true
daily_snapshot_enabled = true
idle_verify_enabled = true
idle_verify_after_minutes = 15

[protection]
auto_protect_desktop = true
auto_protect_documents = true
auto_protect_downloads = false
auto_protect_dev_projects = true

[backup]
enabled = true
target = "D:/SafeVaultBackups"
schedule = "daily"
time = "21:00"
gzip = true
overwrite_latest = true
keep_last = 7
skip_verify = false

[retention]
max_vault_size_gb = 100
keep_days = 90
conservative_prune_only = true

[ui]
host = "127.0.0.1"
port = 8765
show_advanced_actions = false
```

要求：

```text
1. 所有配置读写集中在 config.py。
2. 配置变更必须原子写入。
3. 旧配置自动迁移。
4. 所有路径保存为绝对路径。
5. 禁止 backup target 位于 SAFEVAULT_HOME 内部。
6. 禁止 backup target 位于受保护 root 内部，除非高级模式显式允许。
```

---

## 6. 数据库扩展

在现有 SQLite schema 基础上新增表。必须使用 migration，不要直接破坏旧数据库。

### 6.1 schema_migrations

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### 6.2 protection_policies

```sql
CREATE TABLE IF NOT EXISTS protection_policies (
    id INTEGER PRIMARY KEY,
    root_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    profile TEXT NOT NULL,
    auto_snapshot INTEGER NOT NULL DEFAULT 1,
    watch_enabled INTEGER NOT NULL DEFAULT 1,
    hourly_snapshot INTEGER NOT NULL DEFAULT 1,
    daily_snapshot INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(root_id) REFERENCES roots(id)
);
```

### 6.3 daemon_state

```sql
CREATE TABLE IF NOT EXISTS daemon_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pid INTEGER,
    status TEXT NOT NULL,
    started_at TEXT,
    last_heartbeat_at TEXT,
    message TEXT
);
```

### 6.4 change_batches

```sql
CREATE TABLE IF NOT EXISTS change_batches (
    id TEXT PRIMARY KEY,
    root_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    last_event_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_count INTEGER NOT NULL DEFAULT 0,
    modified_count INTEGER NOT NULL DEFAULT 0,
    deleted_count INTEGER NOT NULL DEFAULT 0,
    snapshot_id INTEGER,
    FOREIGN KEY(root_id) REFERENCES roots(id),
    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
);
```

### 6.5 backup_jobs

```sql
CREATE TABLE IF NOT EXISTS backup_jobs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    target_path TEXT NOT NULL,
    archive_path TEXT,
    object_count INTEGER,
    error TEXT
);
```

### 6.6 notifications

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);
```

---

## 7. 自动保护默认目录

### 7.1 默认候选目录

Windows：

```text
%USERPROFILE%\Desktop
%USERPROFILE%\Documents
%USERPROFILE%\Downloads
D:\CodexWork
%USERPROFILE%\source
%USERPROFILE%\Projects
```

但首次向导中不要强制全部启用。推荐默认：

```text
Desktop: 建议启用
Documents: 建议启用
Downloads: 默认不启用，只提示可选
CodexWork / Projects: 如果存在，建议启用
```

### 7.2 自动检测规则

```text
1. 目录存在才显示。
2. 目录不可为系统根目录。
3. 目录不可为 SAFEVAULT_HOME。
4. 目录不可包含 SAFEVAULT_HOME。
5. 目录不可是 backup target。
6. 大于一定规模时提示用户确认，例如超过 100GB 或 100000 文件。
```

---

## 8. 自动快照策略

### 8.1 文件变化 debounce

当 watcher 检测到 created/modified/moved：

```text
记录事件
等待 debounce_seconds
如果没有继续变化，触发局部 snapshot 或 root snapshot
```

MVP 可先全 root snapshot，但要避免频繁执行：

```text
同一 root 30 秒内最多一次 snapshot
如果正在 snapshot，则合并到下一批
```

### 8.2 删除事件立即记录

当 watcher 检测到 deleted：

```text
如果该文件已被跟踪：
  立即标记 deleted
  插入 deleted marker
  写 events
  写 notifications
```

不要等下一次完整 snapshot 才记录删除。

### 8.3 批量变更分组

连续 20 秒内的文件变更归为一个 batch：

```text
batch reason:
- watcher-change
- bulk-delete
- scheduled-hourly
- scheduled-daily
- pre-daemon-start
```

批量删除超过阈值：

```text
生成 warning notification
托盘弹通知
GUI 首页高亮
```

### 8.4 保底快照

```text
每小时：对活跃 root 做轻量 snapshot
每天：对所有 root 做完整 snapshot
daemon 启动时：对所有 enabled roots 做 startup scan
```

### 8.5 空闲 verify

空闲判定：

```text
过去 N 分钟没有 watcher event
没有 snapshot/export 正在运行
```

空闲任务：

```text
fast verify 每天一次
deep verify 每周一次或用户配置
```

不要在用户频繁改文件时深度 hash 大对象。

---

## 9. GUI 产品化改造

### 9.1 首页改为 Recovery Home

默认首页不要先显示技术状态，而是显示用户最关心的：

```text
最近删除
最近修改
搜索文件
一键恢复
保护状态
备份状态
健康状态
```

页面布局：

```text
顶部状态卡：
- Protected roots: N
- Daemon: Running / Stopped
- Last snapshot: time
- Last backup: time
- Health: OK / Warning / Error

主区域：
- 最近删除
- 最近修改
- 搜索文件

右侧：
- 快捷操作
  - Add folder
  - Run snapshot now
  - Backup now
  - Open settings
```

### 9.2 最近删除页面

字段：

```text
文件名
原路径
删除时间
所属 root
最近可恢复版本时间
大小
操作：恢复 / 另存为 / 查看版本
```

### 9.3 一键恢复

普通恢复：

```text
点击 Restore
弹窗显示：
  文件名
  原路径
  恢复版本时间
  如果目标存在，SafeVault 会先保存当前版本
按钮：
  恢复到原位置
  另存为
```

普通恢复不要求输入 `RESTORE`。  
高级模式可继续显示确认词。

### 9.4 搜索

新增 GUI 搜索：

```text
按文件名搜索
按路径搜索
按后缀过滤
按 root 过滤
按 deleted/active 过滤
```

对应 CLI：

```bash
safevault search <query> [--deleted] [--root <path>]
```

### 9.5 设置页面

设置：

```text
保护目录
自动快照
备份目录
备份频率
开机自启
高级模式
语言
保留策略
```

### 9.6 高级模式

默认隐藏：

```text
raw diff JSON
confirm words
unsafe/conflict technical details
manual prune
import overwrite
public bind
```

高级模式开启后再显示完整技术细节。

---

## 10. 自动导出备份

### 10.1 备份目标设置

GUI onboarding 要求用户选择 backup target，可跳过，但要持续提醒：

```text
You have not configured off-machine backup.
```

中文提示：

```text
你还没有设置外部备份目录。如果本机磁盘损坏或 SafeVault 目录被删除，可能无法恢复。
```

### 10.2 自动备份策略

支持：

```text
manual
daily
weekly
```

默认建议：

```text
daily at 21:00
keep_last = 7
gzip = true
verify before export = true
```

### 10.3 导出文件命名

```text
safevault-backup-YYYYMMDD-HHMMSS.tar.gz
safevault-latest.tar.gz
```

如果 overwrite_latest：

```text
先写临时文件
校验完成后 atomic rename 到 latest
```

### 10.4 备份健康状态

显示：

```text
最近一次成功备份时间
最近一次失败原因
下次备份时间
备份目录可用空间
最近导出对象数量
```

---

## 11. 守护进程设计

### 11.1 单实例

daemon 必须单实例：

```text
启动时检查 lock file
检查 daemon_state
若已有进程存活，退出并提示
若 stale lock，清理
```

建议文件：

```text
~/.safevault/daemon.lock
```

### 11.2 主循环

伪代码：

```python
def run_daemon():
    acquire_single_instance_lock()
    write_daemon_state(status="running")
    load_config()
    ensure_roots()
    start_watchers()
    schedule_startup_scan()

    while not stopping:
        update_heartbeat()
        process_event_queue()
        flush_due_batches()
        run_due_hourly_snapshots()
        run_due_daily_snapshots()
        run_due_backup()
        run_idle_verify_if_due()
        sleep(1)

    stop_watchers()
    write_daemon_state(status="stopped")
```

### 11.3 崩溃恢复

daemon 启动时：

```text
检查上次状态是否 running 但 heartbeat 过期
写 notification：上次 daemon 非正常退出
对 roots 做 startup scan
```

### 11.4 暂停保护

支持：

```bash
safevault protect pause <path> --duration 30m
safevault protect resume <path>
```

GUI：

```text
Pause protection for 30 minutes
```

暂停期间：

```text
不处理 watcher event
但 scheduled daily snapshot 可以跳过
GUI 显示黄色警告
```

---

## 12. 托盘程序设计

### 12.1 命令

```bash
safevault tray
```

### 12.2 行为

```text
启动时确保 daemon 正在运行
显示托盘图标
右键菜单
可打开 GUI
可显示最近删除
可触发 backup
可暂停保护
```

### 12.3 通知

Windows 初版可简单实现：

```text
托盘 balloon notification
或 GUI notification center
```

通知类型：

```text
批量删除
备份失败
verify 发现问题
daemon 停止
保护目录不可访问
```

---

## 13. Codex 运行保护增强

保留现有：

```bash
safevault run --project <path> -- codex
```

新增 GUI 入口：

```text
选择项目 -> Run command in sandbox -> 输入 codex -> Start
```

同时 daemon 识别：

```text
如果 root 下 30 秒内出现大量修改或删除，生成 batch
如果检测到 .codex 或类似日志，可标记为 possible-ai-edit
```

不要自动阻止用户直接运行 Codex，但要提醒：

```text
建议使用 SafeVault sandbox 运行 Codex。
```

---

## 14. 测试要求

### 14.1 单元测试

新增：

```text
tests/test_auto_protect.py
tests/test_daemon.py
tests/test_daemon_scheduler.py
tests/test_recent.py
tests/test_backup_scheduler.py
tests/test_onboarding.py
tests/test_tray_optional.py
tests/test_ui_recovery_home.py
tests/test_search.py
```

### 14.2 必测场景

1. auto-detect 能识别 Desktop/Documents/Projects。
2. auto-detect 不会加入 SAFEVAULT_HOME。
3. daemon 单实例。
4. daemon heartbeat 更新。
5. watcher created/modified 会触发 debounced snapshot。
6. watcher deleted 会立即插入 deleted marker。
7. 批量删除超过阈值产生 warning。
8. hourly snapshot 不会重复过度触发。
9. backup scheduler 到点执行 export。
10. backup target 在 SAFEVAULT_HOME 内部时被拒绝。
11. GUI 首页展示最近删除。
12. GUI 普通 restore 不要求 RESTORE 确认词，但必须有弹窗确认参数。
13. search 能搜索 active/deleted 文件。
14. onboarding 完成后写 config。
15. onboarding 创建初始 snapshot。
16. pause/resume 生效。
17. daemon 崩溃后重启会 startup scan。
18. 旧数据库 migration 成功。

### 14.3 集成 smoke

新增：

```text
scripts/daemon_smoke.ps1
scripts/auto_protect_smoke.ps1
scripts/onboarding_smoke.py
```

Windows smoke 示例：

```powershell
$env:SAFEVAULT_HOME = "$env:TEMP\safevault-daemon-smoke"
$project = "$env:TEMP\safevault-project-smoke"
mkdir $project
"hello" | Set-Content "$project\a.txt"

safevault init $project
safevault daemon run --test-once
safevault snapshot $project --reason smoke

Remove-Item "$project\a.txt"
safevault recent deleted --since 1h
safevault restore "$project\a.txt" --latest
```

---

## 15. 文档更新

### 15.1 README.md

新增章节：

```text
Automatic Protection Mode
Daemon and Tray
Recovery Home
Automatic Backup
Onboarding
What SafeVault protects automatically
What it still cannot protect
```

### 15.2 README.zh-CN.md

新增中文章节：

```text
自动保护模式
第一次启动向导
误删后如何一键恢复
后台守护进程
托盘程序
自动导出备份
常见问题
```

### 15.3 docs/zh

新增：

```text
docs/zh/auto-protection.md
docs/zh/daemon-tray.md
docs/zh/one-click-restore.md
docs/zh/automatic-backup.md
docs/zh/onboarding.md
```

---

## 16. 分阶段实施计划

### Phase 1：配置、migration、policy 基础

实现：

```text
config 扩展
schema_migrations
protection_policies
daemon_state
backup_jobs
notifications
protect list/add/remove
```

验收：

```bash
safevault protect add <path>
safevault protect list
safevault doctor
pytest tests/test_auto_protect.py -q
```

### Phase 2：recent 和 search

实现：

```text
safevault recent deleted
safevault recent modified
safevault recent activity
safevault search
GUI 最近删除数据接口
```

验收：

```bash
safevault recent deleted --since 24h
safevault search foo --deleted
```

### Phase 3：daemon MVP

实现：

```text
safevault daemon run
single instance lock
heartbeat
load roots
watcher event queue
debounced snapshot
delete immediate marker
```

验收：

```bash
safevault daemon run
修改文件后自动 snapshot
删除文件后 recent deleted 可见
```

### Phase 4：scheduler

实现：

```text
change batches
hourly snapshot
daily snapshot
idle verify
bulk delete notification
pause/resume
```

验收：

```text
批量删除产生 notification
pause 后不触发 watcher snapshot
resume 后恢复
```

### Phase 5：GUI Recovery Home

实现：

```text
首页改造
最近删除列表
最近修改列表
搜索
一键恢复弹窗
高级模式开关
```

验收：

```text
误删文件后 GUI 首页可见
点击恢复成功
```

### Phase 6：onboarding

实现：

```text
首次启动检测
目录选择
备份目录选择
保留策略
开机自启选择
初始 snapshot
```

验收：

```text
新 SAFEVAULT_HOME 打开 GUI 进入 onboarding
完成后 config.onboarding_completed=true
```

### Phase 7：automatic backup

实现：

```text
backup configure/status/run
daemon scheduled export
backup health
GUI backup status
```

验收：

```text
backup 到点执行
GUI 显示最近成功时间
```

### Phase 8：tray

实现：

```text
safevault tray
菜单
通知
打开 GUI
暂停/恢复
```

验收：

```text
Windows 上托盘可启动
无 GUI 环境测试跳过
```

### Phase 9：文档和发布检查

实现：

```text
README 更新
中文文档更新
smoke 脚本
CI 更新
```

验收：

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
```

---

## 17. GUI 文案建议

### 首页标题

```text
SafeVault 正在保护你的文件
```

### 最近删除

```text
最近删除的文件
这些文件可以从 SafeVault 快照中恢复。
```

### 未设置自动备份

```text
还没有设置外部备份目录。
如果本机磁盘损坏，SafeVault 本地对象库也可能丢失。
建议选择外置硬盘、同步盘或其他安全目录。
```

### daemon 未运行

```text
后台保护未运行。
文件变化不会被自动快照。建议启动 SafeVault 后台保护。
```

### 普通恢复确认

```text
确认恢复此文件？
如果原位置已有文件，SafeVault 会先保存当前版本，再恢复所选版本。
```

---

## 18. 安全边界

必须保持：

```text
1. 不自动删除用户文件。
2. apply 删除仍需显式 allow_delete。
3. import overwrite 仍需确认。
4. backup overwrite 仍需确认或只覆盖 safevault-latest。
5. 不将 backup target 设置到 SAFEVAULT_HOME 内。
6. 不跟随外部 symlink。
7. 不读取或暴露用户文件内容，除非用户执行 restore/view metadata。
8. daemon 不绕过系统权限。
9. tray/GUI 默认只本地访问。
10. public bind 必须明确开启。
```

---

## 19. 版本建议

本阶段完成后版本建议：

```text
0.2.0rc1
```

不要直接 stable。  
README 写：

```text
SafeVault 0.2.0rc1 introduces automatic protection mode, daemon/tray operation, recovery home, onboarding, and automatic backup.
It remains a release candidate.
```

---

## 20. 最终验收清单

功能验收：

```text
[ ] 新 SAFEVAULT_HOME 首次打开 GUI 进入 onboarding
[ ] 选择保护目录后自动 init + initial snapshot
[ ] daemon 可启动、停止、查看状态
[ ] 文件修改后自动快照
[ ] 文件删除后 GUI 首页出现最近删除
[ ] 一键恢复成功
[ ] 批量删除有告警
[ ] 自动 backup 可配置
[ ] backup status 显示最近成功时间
[ ] tray 可打开 GUI
[ ] pause/resume 可用
[ ] verify/doctor 正常
```

安全验收：

```text
[ ] 不保护 SAFEVAULT_HOME
[ ] 不把 backup target 放进 SAFEVAULT_HOME
[ ] 不跟随外部 symlink
[ ] 不自动应用删除
[ ] 不自动覆盖 import target
[ ] destructive operations 仍需确认
```

工程验收：

```text
[ ] ruff check .
[ ] mypy src
[ ] pytest -q
[ ] release_check
[ ] Windows smoke
[ ] README 更新
[ ] README.zh-CN.md 更新
```

---

## 21. 给 Codex 的阶段 1 精确任务

首次让 Codex 只做 Phase 1，不要一次全做：

```text
Implement Phase 1 from SAFEVAULT_AUTO_PROTECTION_PRODUCTIZATION_CODEX_PLAN.md.

Scope:
1. Add schema migration support.
2. Add protection_policies, daemon_state, backup_jobs, notifications tables.
3. Extend config.toml read/write for app/daemon/protection/backup/retention/ui settings.
4. Add CLI commands:
   - safevault protect list
   - safevault protect add <path> [--profile ...]
   - safevault protect remove <path> --confirm
   - safevault protect auto-detect
5. Add safety checks:
   - cannot protect SAFEVAULT_HOME
   - cannot protect backup target
   - cannot add duplicate roots
   - cannot add filesystem root
6. Add tests.

Do not implement daemon runtime yet.
Do not implement GUI changes yet.
Do not rewrite snapshot/restore/export/import.

Run:
ruff check .
mypy src
pytest -q
```

后续再逐阶段推进。
