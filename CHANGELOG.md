# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added
- Placeholder for upcoming changes.

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

