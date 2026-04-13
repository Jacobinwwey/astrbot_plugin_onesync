# OneSync Skills Source and Update Status

> Language / 语言: [English](./SKILLS_UPDATE_STATUS_en.md) | [中文](./SKILLS_UPDATE_STATUS_zh.md)

| Current version | Audit date | Scope | Start here |
| --- | --- | --- | --- |
| `v0.2.3` | `2026-04-13` | current `main` branch, source-first Skills management model | [README_en.md](../README_en.md) |

This is not product marketing. It is a capability audit. If you need to answer “what is actually updateable today, what only syncs metadata, and what is still manual,” start here.

| Read this section first | Use it for |
| --- | --- |
| [3. Current Support Matrix](#3-current-support-matrix) | what each source/install shape can actually do |
| [4. How To Judge Support Correctly](#4-how-to-judge-support-correctly) | which fields matter when UI state and reality diverge |
| [5. Current Verdict](#5-current-verdict) | where the current mainline is solid and where it is still incomplete |

## 1. What Is Actually Complete Today

The current Skills management stack is already solid in these areas:

- Source-first snapshot generation (`manifest / lock / sources / generated`) is working.
- Skills provenance is now resolved beyond plain npm packages.
- Install-unit and collection-group detail payloads expose effective `update_plan`.
- Deploy target projection, drift detection, and doctor checks are wired into the same source-first model.

The currently recognized provenance/install-unit families include:

- `registry_package`
- `skill_lock_source`
- `documented_source_repo`
- `catalog_source_repo`
- `community_source_repo`
- `local_custom_skill`

Example: a self-authored skill such as `doc` can now be modeled as `local_custom_skill` instead of being treated as an unresolved external package.

## 2. Three Different Operations That Must Not Be Confused

### 2.1 `POST /api/skills/import`

This rebuilds the local inventory and Skills snapshot. It is an import/reprojection step, not an upstream update step.

### 2.2 `Sync Source`

This refreshes saved source metadata from an upstream source.

Current reality:

- Supports two sync adapters today: npm-backed and git-backed sources.
- npm-backed still requires both:
  - `registry_package_name`
  - `registry_package_manager == "npm"`
- git-backed is considered syncable when any of these paths applies:
  - manager is `git/github` with `source_path` or a git locator
  - `source_kind == "manual_git"` with `source_path` or a git locator
  - `update_policy == "source_sync"` with `source_path` or a git locator
- npm sync uses registry metadata; git sync uses remote/head plus local checkout metadata.
- Repo-reference sources (`repo:` / `documented:` / `catalog:` / `community:`) can now sync repository metadata for GitHub, GitLab, and Bitbucket locators.
- Self-hosted GitHub/GitLab/Bitbucket instances are now syncable through `sync_api_base + sync_auth_header/sync_auth_token`; unknown providers still require dedicated adapters.

### 2.3 `Update Install Unit` / `Update Collection`

This executes a real update command derived from the install unit.

Current reality:

- Registry-backed install units can be updated through `bunx`, `npx`, `pnpm dlx`, or `npm install -g`.
- Git-backed install units now support managed checkout bootstrap:
  - If the original `source_path` is already a git worktree, OneSync reuses it directly.
  - If the leaf skill directory is not a git repository but locator/provenance still resolve to an upstream git repo, OneSync now materializes a managed checkout under `plugin_data/.../skills/git_repos/`.
  - Sync and update now prefer `git_checkout_path` over the leaf skill directory.
- Git-backed install units can be updated with `git -C <checkout_path> pull --ff-only` when a usable checkout path exists, and now run prechecks first:
  - `git -C <source_path> rev-parse --is-inside-work-tree`
  - `test -z "$(git -C <source_path> status --porcelain)"`
- Git-backed update execution now includes before/after revision capture with changed/no-change/unknown summaries.
- Git-backed update execution now includes rollback preview candidates (preview only, not auto-executed).
- Executable rollback APIs are now available (install unit / collection group) with explicit confirmation requirements:
  - `payload.execute = true`
  - `payload.confirm = "ROLLBACK_ACCEPT_RISK"`
- WebUI now includes a baseline rollback flow:
  - cache before-revision snapshots from the latest update response
  - run aggregate-level rollback confirmation and call rollback APIs
  - display restored/not-restored/failed summary after rollback
- Manual/local custom/repo-reference-only aggregates are still unsupported unless OneSync can derive a concrete executable update command.

## 3. Current Support Matrix

| Install/source shape | Example | `Sync Source` | `Update Install Unit` | Notes |
| --- | --- | --- | --- | --- |
| npm package-backed bundle/single | `npm:@every-env/compound-plugin` | Yes | Yes | Sync reads npm registry metadata. Update uses `management_hint` first, otherwise a registry command is built. |
| Git-backed local checkout / skill-lock entry | `skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills` | Yes (git remote/head, managed checkout, or local checkout metadata) | Yes | If the original skill path is not a git worktree, OneSync now bootstraps a managed checkout under `plugin_data/.../skills/git_repos/` and executes `git pull --ff-only` from there. |
| Documented/catalog/community repo reference without executable manager | `repo:https://github.com/...#skills/foo` | Partial (repo metadata only) | Usually no | Source Sync can refresh metadata from GitHub/GitLab/Bitbucket (for example pushed/updated timestamp), but update execution is still unsupported. |
| Manual local path / self-authored local custom skill | `local_custom:/path/to/skill` | No | No | OneSync can inventory, classify, and deploy them, but cannot infer a safe update command. |
| Manual git source registered without a usable local checkout | `manual_git` remote | No | No | A remote locator alone is not enough; a resolvable local checkout path is required for git update execution. |

## 4. How To Judge Support Correctly

Do not decide capability from `source_kind` alone.

The authoritative fields are:

- `update_plan.supported`
- `update_plan.commands`
- `update_plan.message`
- `registry_package_name`
- `registry_package_manager`
- `sync_status`
- `sync_local_revision` / `sync_remote_revision` / `sync_resolved_revision`

Important nuance:

- A source row may still carry `update_policy=registry` because of how the source registry normalizes npx-discovered entries.
- That does **not** guarantee the install unit is updateable.
- The final truth is the install-unit-level `update_plan`.

This matters for local custom skills such as `doc`: they can be discovered from the same runtime inventory as npx-managed skills, but they remain manually maintained and therefore update-unsupported.

## 5. Current Verdict

If the question is "is the current skill update function complete?", the answer now needs to be refined to:

- Discovery/import/provenance: largely complete for the current v1 scope.
- Install-unit / collection-group update execution: core paths are now usable.
- Source metadata sync: core paths are now usable, while provider breadth and remote stability still need work.

More specifically:

- Complete enough today for package-backed npm updates and git-backed `skill_lock` sources.
- Partially complete for repo-derived sources: GitHub/GitLab/Bitbucket locators support metadata sync; update execution remains unsupported.
- Not complete for local custom/manual skills.
- Git-backed metadata refresh (remote/head + local checkout) is supported; repo-reference metadata sync is supported for GitHub/GitLab/Bitbucket (including self-hosted instances with auth/api-base overrides); unknown providers remain incomplete.
- `synthetic_single` / `derived` aggregates without a real package boundary are now explicitly downgraded to `manual_only` instead of pretending to be updateable.

## 6. Maintainer Verification Procedure

Recommended checks:

```bash
python3 -m pytest tests -q
curl -s http://127.0.0.1:8099/api/health
curl -s http://127.0.0.1:8099/api/skills/sources
curl -s http://127.0.0.1:8099/api/skills/install-units/npm%3A%40every-env%2Fcompound-plugin
```

What to confirm:

- `counts.source_provenance_unresolved_total == 0` for the current runtime snapshot.
- `counts.source_syncable_total` now counts npm-backed, git-backed, and repo-metadata-backed sources (GitHub/GitLab/Bitbucket).
- Supported install units expose non-empty `update_plan.commands`.
- Git-backed install units expose `update_plan.precheck_commands`.
- Git-backed `skill_lock` install units expose `git_checkout_path` on source rows after the first sync/update bootstrap.
- Git-backed update responses expose `revision_capture` (before/after/delta).
- When revisions changed, update responses also expose `rollback_preview.candidates`.
- Rollback API responses expose structured restore metrics (`restored_source_total`, `not_restored_source_total`, `failed_sources`).
- Local custom skills expose `update_plan.supported = false`.
- Git-backed source sync emits structured revision fields (`sync_*revision`).
- Overview counts expose `source_sync_dirty_total` and `source_sync_revision_drift_total`.

## 7. Recommended Next Steps

To call the feature "complete", the next implementation steps should be:

1. Add adapters for unknown/non-GitHub/GitLab/Bitbucket providers and unify auth strategy across adapters.
2. Harden the UI rollback workflow on top of the current rollback API (candidate selection, retry handling, visible audit trails, and rollback history).
3. Surface unsupported/precheck-failure reasons more explicitly in the UI.
4. Separate "provenance origin" from "update mechanism" more clearly in panel copy.
5. Add more end-to-end tests around install-unit detail payloads and live sync/update behavior.

## 8. Recent Implementation Progress (2026-04-12)

- Batch aggregate update is now wired in both backend and WebUI:
  - `POST /api/skills/aggregates/update-all`
  - Frontend action: `Update All Aggregates`
  - Response now returns executed/skipped/source-sync/deduplicated breakdown instead of a generic aggregate success/failure shell.
- Managed git checkout bootstrap is now live:
  - `find-skills` and `frontend-design` now bootstrap managed checkouts in the live 8099 environment and update successfully instead of failing with `git_source_unresolved`.
  - Current managed checkout directories include:
    - `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-55d42a13a220`
    - `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-7d7c7a8d88f1`
- Managed git checkout prewarm queue is now live:
  - `_refresh_inventory_snapshot()` now schedules background prewarm for git-backed sources after the latest skills snapshot is built, so the first sync/update request no longer absorbs checkout bootstrap latency on the critical path.
  - The live 8099 debug log now shows prewarm completion entries such as:
    - `git checkout prewarm finished: source=npx_global_find_skills ...`
    - `git checkout prewarm finished: source=npx_global_frontend_design ...`
- Existing managed checkout remote alignment is now hardened:
  - When a `git_checkout_path` already exists, OneSync now re-aligns the checkout remote before detail/sync/update flows instead of only setting `origin` during the first clone.
  - If the current remote becomes unreachable, OneSync falls back to a reachable candidate; if the current remote is still healthy, it is preserved to avoid unnecessary churn.
- Managed checkout remote selection has now been upgraded to mirror-aware preferred-remote probing:
  - OneSync now probes candidate remotes and picks a healthy preferred remote instead of only keeping the current reachable origin forever.
  - In live runtime verification, the managed checkout for `frontend-design` was automatically reselected to:
    - `https://gh.llkk.cc/https://github.com/anthropics/skills.git`
- Sync metadata writeback is now authoritative:
  - `saved_registry` is treated as the authority for sync fields, so successful sync/update no longer leaves stale error codes behind.
- Batch-local repo metadata dedupe is now live for source-sync fallback:
  - When multiple fallback sources in one `update-all` run point at the same upstream repo, OneSync now reuses a single repo metadata sync record instead of repeatedly querying the same upstream.
  - In the current runtime, the 5 fallback sources pointing at `sickn33/antigravity-awesome-skills` can now share one batch sync result.
- `synthetic_single:*` no-package-boundary aggregates are now stabilized as `manual_only`:
  - bogus commands like `npx npx_global_*` are no longer generated
  - the stable skipped set now includes:
    - `synthetic_single:npx_global_awesome_design_md`
    - `synthetic_single:npx_global_clone_website`
    - `synthetic_single:npx_global_impeccable`
    - `synthetic_single:npx_global_terminal_dialog_style`
    - `local_custom:/root/.codex/skills/doc`
    - `derived:npx_global_playwright_interactive`
- Latest live 8099 verification for `POST /api/skills/aggregates/update-all`:
  - `candidate_install_unit_total = 20`
  - `executed_install_unit_total = 14`
  - `command_install_unit_total = 3`
  - `source_sync_install_unit_total = 11`
  - `skipped_install_unit_total = 6`
  - `success_count = 8`
  - `failure_count = 2`
  - `precheck_failure_count = 0`
- Current live 8099 startup and verification status:
  - WebUI is listening again at `http://127.0.0.1:8099`
  - Single install-unit update for `find-skills` succeeded again:
    - `success_count = 3`
    - `failure_count = 0`
    - `precheck_failure_count = 0`
  - `find-skills` update is now stably executed through the managed checkout path:
    - `git -C /root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-55d42a13a220 pull --ff-only`
  - `update-all` now exposes top-level summary fields directly:
    - `candidate_install_unit_total`
    - `planned_install_unit_total`
    - `executed_install_unit_total`
    - `success_count`
    - `failure_count`
    - `precheck_failure_count`
    - `skipped_install_unit_total`
  - `update-all` structured failure taxonomy is now directly consumable:
    - `failure_taxonomy.failed_install_unit_reason_groups[0] = update_failed:1`
    - `failure_taxonomy.blocked_reason_groups[0] = non_syncable_sources_present:6`
  - Debug logs now include failed/blocking reason tails:
    - `failed_reasons=[update_failed:1] blocked_reasons=[non_syncable_sources_present:6]`
  - After introducing repo metadata batch dedupe, the latest live `update-all` is back to:
    - `success_count = 19`
    - `failure_count = 2`
    - `failure_taxonomy.failed_source_total = 0`
    - `update.source_sync_cache_hit_total = 4`
  - Compound Engineering install-unit update now uses a semantically correct install command:
    - `bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex`
  - Current live verification for the Compound Engineering single install-unit update:
    - `success_count = 2`
    - `failure_count = 0`
    - `failed_install_units = []`
  - After fixing the CE update command, the latest live `update-all` has further converged to:
    - `success_count = 19`
    - `failure_count = 0`
    - `skipped_install_unit_total = 7`
    - `failure_taxonomy.failed_install_unit_total = 0`
    - `failure_taxonomy.blocked_reason_groups[0] = manual_managed:7`
  - `source_sync_cache_hit_total` is now surfaced in the frontend summary instead of remaining backend-only:
    - the current “Update All Aggregates” summary now shows `Source sync cache reuses: {count}`
    - the matching debug log line now includes `sync_cache_hits=...`
  - The Utility Inspector now includes a dedicated “Aggregate Update Report” panel:
    - it prefers the latest in-session `update-all` result
    - it falls back to `aggregates_update_all` audit history when no live session result is cached
    - blocked / failed groups can be clicked to focus the related install-unit/source detail
- Inventory binding saves and deploy-target projection mutations now narrow the authority boundary:
  - `webui_update_inventory_bindings()` now projects from persisted `manifest` plus the latest skills snapshot instead of forcing an inventory rescan.
  - The same manifest-first projection helpers are now reused by deploy-target mutation paths, so operator intent no longer has to round-trip through inventory just to become visible again.
- Runtime freshness writeback is now authoritative after command updates:
  - successful install-unit command execution now stamps `last_seen_at`, `last_refresh_at`, `source_age_days=0`, and `freshness_status=fresh` back into saved registry rows
  - this removes the false `AGING` badge that could remain after a successful repo-metadata-backed or registry-backed update path
- Full regression result is now:
  - `pytest -q` -> `191 passed`

- WebUI now renders a rollback audit trail panel backed by `/api/skills/audit?action=rollback`, with automatic switching between current-aggregate scope and global recent records.
- Rollback flow now supports selective rollback by `source_id`, so operators can scope blast radius instead of always rolling back the full aggregate.
- Rollback flow now supports a retry pass: unresolved sources from the first rollback response are extracted and retried as a targeted second run.
- After rollback execution, the panel refreshes rollback audit records and aggregate details to keep recovery state observable.
- Operation-plan preview now surfaces precheck commands and blocked-unit reasons, so unsupported updates are actionable instead of generic.
- Source Sync now includes a repo-metadata adapter for `repo:`/`documented:`-style GitHub locators, so provenance-only sources can still refresh upstream metadata.
- Source Sync repo-metadata adapter now also supports GitLab and Bitbucket locators.
- Source Sync now supports authenticated repo-metadata sync with `sync_auth_token` / `sync_auth_header` / `sync_api_base` flowing through registry -> overview -> sync adapter.
- Repo-metadata errors are now layered (`auth_failed`, `rate_limited`, `provider_unreachable`, `auth_config_invalid`, `api_base_invalid`) for actionable diagnostics.
- WebUI source panels now expose structured sync errors (`sync_error_code`) with label + remediation hints.
- WebUI `/api/skills/*` responses now redact auth-sensitive sync fields: `sync_auth_token` is always blanked and paired with `sync_auth_token_configured`; `sync_auth_header` is masked as `Header: <redacted>` when provided in `Header: value` form (header strategy remains visible, secret value is hidden).
- Inventory routes that can carry embedded `skills` snapshots (`/api/inventory/bindings`, `/api/inventory/scan`) now use the same redaction boundary to prevent non-skills route bypass.
- Redaction is applied on both success and error response paths, and route-level regression tests were added; current regression result: `python3 -m pytest tests -q` -> `151 passed`.
- `/api/config` no longer returns plaintext `web_admin.password`; config reads now return an empty password plus `password_configured` (also surfaced via `meta.web_admin_password_configured`).
- Config updates now support `web_admin.password_mode` (`keep`/`set`/`clear`), and the frontend now emits explicit mode semantics to prevent accidental password clearing on blank input.
- The config panel password field is now `type=password`, no longer prefilled with secrets, and includes explicit clear-password controls with dynamic hints.
- Skills update execution is now hardened:
  - Registry-backed updates now include runner prechecks (`bunx`/`npx`/`pnpm`/`npm`) so missing runtime tools surface before update execution.
  - When the primary registry command fails with `command not found`, OneSync now auto-tries fallback manager commands for the same install_ref.
  - When `update_plan.supported=false` but all sources remain syncable, update now auto-degrades to source sync (`fallback_mode=source_sync`) instead of hard unsupported.
- Aggregate update preview and frontend action gating are now aligned on one executable model:
  - Detail-level `update_plan` now exposes `update_mode` (`command`/`source_sync`/`manual_only`) and `actionable`.
  - The frontend update button no longer depends only on `command_count`; it uses `actionable` first and still supports `source_sync` fallback.
  - Operation-plan cards now render an explicit execution mode so `manual_only` units are not mistaken for auto-updateable units.
- Latest runtime verification on `8099`:
  - Total install units: `18`
  - Actionable preview: `16` (`command=5`, `source_sync=11`)
  - `manual_only=2`: `local_custom:/root/.codex/skills/doc`, `derived:npx_global_playwright_interactive`
- Current regression result is now: `python3 -m pytest tests -q` -> `153 passed`.
- AstrBot Phase 3 minimal action adapter is now wired:
  - New API surface: `/api/skills/hosts/{host_id}/astrbot`, `/skills/toggle`, `/skills/delete`, `/sandbox/sync`.
  - Local skill toggle now writes `skills.json`; delete now removes local skill directory and cleans both `skills.json` and `sandbox_skills_cache.json`.
  - `sandbox_only` skills are now explicitly guarded against local toggle/delete to avoid runtime preset corruption.
- AstrBot Phase 4 read-model baseline is now wired:
  - Added stable Neo source ids in the form `astrneo:{host_id}:{skill_key}`.
  - Added read-only API routes: `GET /api/skills/astrbot-neo-sources` and `GET /api/skills/astrbot-neo-sources/{source_id}`.
  - Neo source rows now expose release/candidate/payload references for upcoming promote/sync/rollback write paths.
- Added AstrBot action adapter regression coverage in `tests/test_skills_astrbot_actions_core.py`; full suite is now `160 passed`.
- AstrBot Phase 4 Neo write path is now wired: added `POST /api/skills/astrbot-neo-sources/{source_id}/sync` with Neo release sync execution and audit trail writeback (`astrbot_neo_source_sync`).
- Full regression is now: `python3 -m pytest tests -q` -> `161 passed`.
- WebUI Source / Bundle now surfaces and operates `astrneo:*` rows: Neo standalone sources are visible, detail loading auto-routes to `/api/skills/astrbot-neo-sources/{source_id}`, and the sync button auto-switches to the Neo sync API.
- AstrBot Neo lifecycle now covers promote / rollback as well:
  - added `POST /api/skills/astrbot-neo-sources/{source_id}/promote` and `POST /api/skills/astrbot-neo-sources/{source_id}/rollback`
  - Neo source detail now exposes `neo_state`, `neo_capabilities`, and `neo_defaults`
  - the focused source-detail inspector now shows `Sync Stable / Promote Stable / Rollback Release` only for `astrneo:*` sources
  - new audit events: `astrbot_neo_source_promote` and `astrbot_neo_source_rollback`
- AstrBot Neo source detail observability is now closed:
  - `GET /api/skills/astrbot-neo-sources/{source_id}` now also returns `neo_remote_state` and `neo_activity`
  - remote `releases / candidates` are normalized by recency using `updated_at -> created_at`, so latest candidate/release selection no longer drifts to older rows
  - audit filtering now matches normalized `source_id` values, which fixes missing history for separator-heavy ids such as `astrneo:*`
  - the focused WebUI inspector now shows Neo remote state and recent activity inline instead of forcing another ops surface
- Aggregate update report and operation-plan failures are now more readable:
  - added a unified reason mapping layer (`inventoryAggregateReasonLabel`) that translates internal `reason_code/failure_reason` into operator-facing labels
  - update-all completion summary, execution-history groups, and operation-plan blocked reasons now all use this mapping
  - aggregate update report now surfaces `precheck_failure_count` plus dedicated guidance for `precheck_failed` and `source_sync_failed`
- Source detail now explicitly separates provenance from update mechanics:
  - provenance (origin/package/evidence/confidence) is rendered in its own section
  - update mechanism (manager/policy/mode/sync/latest/check) is rendered in its own section
  - deploy notes are no longer mixed with provenance diagnosis

## 9. Follow-up Progress (2026-04-13)

- AstrBot local skill management now has a scope-aware contract end to end:
  - `GET /api/skills/hosts/{host_id}/astrbot` now reliably exposes `available_scopes`, `selected_scope`, and `scoped_layouts`
  - `runtime_state.summary.scope_summaries` carries separate `global / workspace` local-skill summaries
  - toggle / delete / ZIP import / ZIP export / sandbox sync all accept explicit `scope`
  - unavailable scopes now fail explicitly with `reason_code = "scope_unavailable"` instead of silently drifting to another root
  - ZIP import/export is now wired into the existing audit trail and WebUI Inspector instead of remaining a capability-only declaration
- The frontend primary action is now converged on `Improve All Skills`:
  - refresh improve-able install atoms first
  - then execute all actionable aggregates
  - progress bar, latest report, and history all read from the same progress channel
- This closes precision and observability gaps; it does not magically turn `manual_only` units into updateable ones:
  - `local_custom`, `synthetic_single`, and `derived` units remain non-auto-update targets
  - scope-aware AstrBot local actions do not change the updateability classification of those units
