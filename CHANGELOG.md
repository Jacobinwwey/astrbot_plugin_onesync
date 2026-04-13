# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [v0.2.2] - 2026-04-13

### Added
- Added dedicated bilingual developer and API reference docs so user onboarding, extension work, and interface lookup are no longer mixed into one long homepage.

### Changed
- Reframed both README files as user-facing landing pages that foreground core capabilities, deployment fit, quick start flow, WebUI highlights, and skills-management design.
- Tightened the docs boundary between install/config, operations, developer extension, and API reference so operators can find the right guidance faster.

### Fixed
- The Skills inventory `结构与成员` panel now defaults to collapsed, which reduces first-screen noise for operators who only need the primary management actions.
- Added a static regression test to keep the inventory source-structure panel from silently reverting to open-by-default.

## [v0.2.1] - 2026-04-13

### Added
- New helper script `scripts/onesync_prompt_builder.py` for zero-fill AI prompt generation (interactive and CLI modes).
- Supports prompt scenarios: bootstrap apply, incremental target merge, and diagnose/repair.
- Added aggregate-wide skills update route `POST /api/skills/aggregates/update-all` and matching WebUI action `Update All Aggregates`.
- Added `POST /api/skills/improve-all` plus shared aggregate progress/history routes so `improve-all` and `update-all` can reuse the same backend progress contract.
- Added managed git checkout bootstrap for git-backed `skill_lock` / repo-derived skill sources under `plugin_data/.../skills/git_repos`.
- Added background managed git checkout prewarm after snapshot refresh so git-backed sources can bootstrap before the first operator-triggered sync/update call.
- Added structured `update-all` failure taxonomy and top-level summary fields so operators can consume major failed/blocking reasons without parsing the nested `update` object.
- Added batch-local source-sync cache keys so repeated repo metadata lookups inside one aggregate update run are reused instead of hitting the same upstream repo multiple times.
- Added a specialized Compound Engineering registry update command so `npm:@every-env/compound-plugin` now runs a real Codex install/update action instead of invoking the package CLI without a subcommand.
- Added cache-aware aggregate update reporting in the WebUI summary so `source_sync_cache_hit_total` is surfaced to operators instead of staying backend-only.
- Added a persistent aggregate update report panel in the Utility Inspector that replays the latest live result first and falls back to `aggregates_update_all` audit history when the session cache is empty.
- Added a focused Skills command rail and a visible aggregate-update progress panel so `update-all` no longer reads as a fire-and-forget action.
- Added a dedicated next-phase execution plan for UI declutter and backend progress bridging: `docs/plans/skills-ui-declutter-and-progress-bridge-plan-2026-04-12.md`.

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
- Aggregate update execution is no longer only visible through transient alerts; the panel now retains a structured, clickable execution report in the Utility Inspector.
- Inventory binding saves and deploy-target projection mutations now reuse manifest-first projection helpers instead of requiring a fresh inventory rescan to keep the control plane consistent.
- Successful command updates now stamp saved registry freshness anchors (`last_seen_at`, `last_refresh_at`, `source_age_days`, `freshness_status`) so source cards stop showing false `AGING` state after a successful update.
- Skills list and Source Inspector no longer dump all secondary diagnostics at once; low-frequency detail is now folded behind collapsible sections.

### Documentation
- Added troubleshooting steps for `Failed to load config: 404 Not Found` in both Chinese and English docs.
- Clarified WebUI access path and hard-refresh guidance for stale frontend cache.
- Added copy-ready AI prompt templates in README and install/config docs for one-click config bootstrap, incremental target merge, and diagnostics.
- Updated status/docs/changelog to reflect the current mainline baseline (`v0.2.1`, manifest-first binding projection, freshness writeback, and `pytest -q -> 191 passed`).
- Updated roadmap/brainstorm docs to reflect the current Phase 3A direction: utility-drawer declutter, backend-reported update-all progress, and freshness-anchor correctness.

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
