# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Fixed
- WebUI API request fallback now retries relative path when absolute `/api/...` returns `404`, reducing route-mount mismatch issues.

### Documentation
- Added troubleshooting steps for `Failed to load config: 404 Not Found` in both Chinese and English docs.
- Clarified WebUI access path and hard-refresh guidance for stale frontend cache.

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
