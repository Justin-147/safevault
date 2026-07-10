# SafeVault FAQ

## How far back can SafeVault restore a file?

SafeVault can restore any version that is still referenced by its SQLite
metadata and present in the BLAKE3 object store. v1.0.1 does not automatically
delete version history: smart retention is planning/dry-run only. Available
history therefore depends on when protection started, captured changes, manual
maintenance, and available disk space.

## Can it recover a file that was never protected?

No. SafeVault is not raw-disk recovery and cannot recover content that was never
captured by a snapshot or watcher-triggered save.

## Does SafeVault start with Windows?

The Windows installer enables current-user daemon and tray Startup tasks by
default. Both can be disabled during setup or removed later. Quitting SafeVault
from the tray stops background protection for the current session; the Startup
choice controls the next sign-in.

## Which folders are protected?

Only folders selected during onboarding or added later are protected. SafeVault
recommends Desktop, Documents, and Pictures. Large project workspaces are shown
but not selected by default. Custom folders can be added during onboarding or
later, and an entire filesystem root is never protected by default.

## Can I close the browser after setup?

Yes. The browser is only the local Recovery Home. The daemon continues the
initial scan and watches protected folders in the background. Choosing Quit from
the tray stops background protection, Recovery Home, and the tray for the current
session.

## Why did the first scan use a lot of disk space?

A top-level folder containing many projects, media files, datasets, or generated
artifacts can create a large first version. Prefer specific personal and project
folders over a whole drive or large workspace. Unprotecting a folder does not
automatically erase its history; do not manually delete `.safevault` unless that
history is no longer needed.

## How do I restore a deleted file?

Open Recovery Home, find the file under recent deletions, and choose Restore.
SafeVault preserves an existing target before overwrite. Use the history view to
restore a specific point or provide an alternate output path.

## Is SafeVault a malware sandbox or full backup system?

No. The command sandbox reduces accidental project changes but does not isolate
credentials, the network, or the rest of the user account. Keep an off-machine
backup for disk failure, theft, or destruction of the local vault.

## What does mass-change protection do?

SafeVault records important recovery points and warnings for high-volume changes
and suspicious encrypted-file extensions. It preserves immutable prior objects;
it does not claim to detect or stop every ransomware technique.

## How is SafeVault different from Git?

Git primarily protects committed project history. SafeVault protects local
versions in selected folders, including uncommitted files and non-code documents.
They can be used together.

## Does SafeVault replace Time Machine, File History, or cloud backup?

No. SafeVault focuses on continuous versioning and accidental-change recovery
for selected folders. It does not provide whole-machine, volume-level, or cloud
protection. Keep system backups and store SafeVault exports on another device.

## Why are sandbox deletions skipped by default?

Deletion is high risk. `safevault apply` applies creations and modifications by
default. It applies deletions only after review with `--allow-delete`, or after
the matching `ALLOW DELETE` confirmation in the GUI.

## Why must backups stay outside SAFEVAULT_HOME?

A disk failure or accidental deletion could otherwise destroy both the object
store and its backup. Backup targets are also rejected inside protected folders
to prevent recursive protection and unbounded growth.

## Can the GUI be exposed to a LAN or the internet?

No. The GUI binds to `127.0.0.1` and uses a random token. It is a local recovery
interface, not a remote administration console. Do not expose it publicly.

## Why do some operations require typed confirmation words?

Normal restore uses a local confirmation dialog. High-risk deletion, overwrite,
import, and cleanup actions require words such as `ALLOW DELETE`, `PRUNE`, or
`IMPORT` to reduce irreversible mistakes.

## Will SafeVault keep using more disk space?

Identical content is stored once, but new versions still grow the object store.
Recovery Home shows object-store use and the configured budget. Smart retention
in v1.0.1 is planning/dry-run only, so it never removes history automatically.
