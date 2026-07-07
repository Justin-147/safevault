# Changelog

## 0.1.0rc1

SafeVault is a local project protection and recovery tool built around
versioned snapshots, a BLAKE3-addressed object store, restore, sandboxed command
runs, and conservative apply flows.

Safety guarantees:
- `safevault run` operates on a copied working tree and does not mutate the
  original project.
- `safevault apply` skips deletions unless `--allow-delete` is passed.
- Object-store reads and restores verify BLAKE3 content hashes.
- External symlink placeholders are tracked by sandbox sidecar metadata.
- `unprotect` and `sandbox-clean` require explicit confirmation for destructive
  metadata or sandbox cleanup.

Known limitations:
- No raw disk recovery.
- Not a hardened malware sandbox.
- No continuous cross-machine sync.
- Retention is planning-only in this release candidate.
- Export/import exists, but archives should still be stored off-machine.
- Import requires a trusted export archive and an empty target home unless
  `--overwrite` is explicitly passed.

Upgrade notes:
- Run `safevault doctor --deep` and `safevault verify --deep` after upgrading.
- Create an off-machine export with `safevault export --output <path> --gzip`.
