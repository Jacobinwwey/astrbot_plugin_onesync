# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added
- New helper script `scripts/onesync_prompt_builder.py` for zero-fill AI prompt generation (interactive and CLI modes).
- Supports prompt scenarios: bootstrap apply, incremental target merge, and diagnose/repair.
- Added aggregate-wide skills update route `POST /api/skills/aggregates/update-all` and matching WebUI action `Update All Aggregates`.
- Added managed git checkout bootstrap for git-backed `skill_lock` / repo-derived skill sources under `plugin_data/.../skills/git_repos`.

### Fixed
- WebUI API request fallback now retries relative path when absolute `/api/...` returns `404`, reducing route-mount mismatch issues.
- `synthetic_single:*` skill aggregates without a real package boundary are now stabilized as `manual_only` instead of generating bogus `npx npx_global_*` update commands.
- Git-backed skill updates no longer require the leaf skill directory itself to be a git worktree; OneSync now bootstraps and reuses a managed checkout.
- Sync metadata writeback now treats saved registry sync fields as authoritative, preventing stale `sync_error_code` values from surviving after a successful sync/update.

### Documentation
- Added troubleshooting steps for `Failed to load config: 404 Not Found` in both Chinese and English docs.
- Clarified WebUI access path and hard-refresh guidance for stale frontend cache.
- Added copy-ready AI prompt templates in README and install/config docs for one-click config bootstrap, incremental target merge, and diagnostics.
- Updated README, status docs, operations docs, and implementation logs to reflect the 2026-04-12 live runtime state (`update-all`, managed git checkout bootstrap, and current support boundaries).

## [v0.2.0] - 2026-03-17

### Added
- WebUI config center:
  - Added `/api/config` GET/POST endpoints for config sync and persistence.
  - WebUI can now load, edit, and save plugin config directly.
  - Human/developer target models are synchronized (`human_targets` <-> `targets_json`).
- New native `system_package` strategy:
  - Built-in manager support: `apt_get`, `yum`, `dnf`, `pacman`, `zypper`, `choco`, `winget`, `brew`.
  - Native check/update command defaults with customizable overrides.
  - Added manager-aware environment check integration.

### Changed
- `CommandRunner` now supports cross-platform shell execution (`/bin/bash` on Unix, `cmd /C` on Windows) and PATH enrichment for common package manager binary locations.
- Human target normalization and schema now include `system_package` template.
- Docs and README updated for config center and new strategy coverage.

## [v0.1.0] - 2026-03-16

### Added
- Initial release of `astrbot_plugin_onesync`.
- Extensible updater engine with two strategies:
  - `cargo_path_git`
  - `command`
- Scheduled check/update loop with lock protection.
- Persistent updater state and events logging under plugin data directory.
- Admin command group:
  - `/updater status`
  - `/updater check [target]`
  - `/updater run [target]`
  - `/updater force [target]`
- Default target configuration for `zeroclaw` with mirror fallback support.
