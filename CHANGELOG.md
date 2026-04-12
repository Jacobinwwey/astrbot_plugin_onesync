# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added
- New helper script `scripts/onesync_prompt_builder.py` for zero-fill AI prompt generation (interactive and CLI modes).
- Supports prompt scenarios: bootstrap apply, incremental target merge, and diagnose/repair.
- Added aggregate-wide skills update route `POST /api/skills/aggregates/update-all` and matching WebUI action `Update All Aggregates`.
- Added managed git checkout bootstrap for git-backed `skill_lock` / repo-derived skill sources under `plugin_data/.../skills/git_repos`.
- Added background managed git checkout prewarm after snapshot refresh so git-backed sources can bootstrap before the first operator-triggered sync/update call.
- Added structured `update-all` failure taxonomy and top-level summary fields so operators can consume major failed/blocking reasons without parsing the nested `update` object.
- Added batch-local source-sync cache keys so repeated repo metadata lookups inside one aggregate update run are reused instead of hitting the same upstream repo multiple times.
- Added a specialized Compound Engineering registry update command so `npm:@every-env/compound-plugin` now runs a real Codex install/update action instead of invoking the package CLI without a subcommand.
- Added cache-aware aggregate update reporting in the WebUI summary so `source_sync_cache_hit_total` is surfaced to operators instead of staying backend-only.

### Fixed
- WebUI API request fallback now retries relative path when absolute `/api/...` returns `404`, reducing route-mount mismatch issues.
- `synthetic_single:*` skill aggregates without a real package boundary are now stabilized as `manual_only` instead of generating bogus `npx npx_global_*` update commands.
- Git-backed skill updates no longer require the leaf skill directory itself to be a git worktree; OneSync now bootstraps and reuses a managed checkout.
- Sync metadata writeback now treats saved registry sync fields as authoritative, preventing stale `sync_error_code` values from surviving after a successful sync/update.
- Existing managed git checkouts are now re-aligned before runtime detail/sync/update flows, and the live 8099 runtime was restored after syncing the missing AstrBot skill adapter modules needed by the new mainline.
- Managed checkout remote selection is now probe-based and mirror-aware instead of only preserving the current reachable origin, and `update-all` taxonomy now keeps failed install-unit reasons instead of collapsing them to `unknown`.
- Repeated repo-metadata fallback sources in `update-all` now reuse batch-local sync records, which reduced live fallback churn and brought the latest live batch back to `source_sync_failed = 0`.
- Compound Engineering update plans no longer execute the invalid bare command `bunx @every-env/compound-plugin`; they now run the explicit `install compound-engineering --to codex --codexHome ...` flow, and fallback attempts no longer count as failures once a later registry runner succeeds.
- After the Compound Engineering command fix, the latest live `update-all` run has converged to `failure_count = 0`, leaving only explicit `manual_managed` blocked units in the aggregate summary.

### Documentation
- Added troubleshooting steps for `Failed to load config: 404 Not Found` in both Chinese and English docs.
- Clarified WebUI access path and hard-refresh guidance for stale frontend cache.
- Added copy-ready AI prompt templates in README and install/config docs for one-click config bootstrap, incremental target merge, and diagnostics.
- Updated status/docs/changelog to reflect the 2026-04-12 live runtime state (`update-all`, cache-aware aggregate UI summary, Compound Engineering specialized update command, `8099` recovery, and `pytest -q -> 177 passed`).

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
