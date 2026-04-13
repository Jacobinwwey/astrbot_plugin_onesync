# OneSync API Reference (English)

> Language / 语言: [English](./API_REFERENCE_en.md) | [中文](./API_REFERENCE_zh.md)

| Current version | Updated | Audience | Start here |
| --- | --- | --- | --- |
| `v0.2.3` | `2026-04-13` | script callers, frontend integrators, extension authors | [README_en.md](../README_en.md) |

This document does one job: it maps the embedded WebUI `/api/*` surface cleanly. If you are installing or operating the plugin, start elsewhere.

| When should you read this? | Go to |
| --- | --- |
| auth rules and token transport | [2. Authentication](#2-authentication) |
| system and overview endpoints | [4. System and overview routes](#4-system-and-overview-routes) |
| Skills read/write endpoints | [6. Skills read routes](#6-skills-read-routes) / [7. Skills mutation routes](#7-skills-mutation-routes) |
| practical call order | [11. Recommended call sequences](#11-recommended-call-sequences) |

| Related doc | Purpose |
| --- | --- |
| [README_en.md](../README_en.md) | project overview and quick start |
| [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md) | installation and daily usage |
| [Developer Guide (English)](./DEVELOPER_GUIDE_en.md) | code structure and extension points |

## 1. Basics

- default URL: `http://127.0.0.1:8099`
- API root: `/api`
- OpenAPI: `/openapi.json`
- health check: `/api/health`

## 2. Authentication

When `web_admin.password` is empty:

- all `/api/*` routes are directly accessible

When `web_admin.password` is configured:

- these remain public:
  - `GET /api/auth-info`
  - `POST /api/login`
- all other `/api/*` routes require a token

Accepted token transports:

- query parameter: `?token=...`
- header: `Authorization: Bearer <token>`

Auth routes:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/auth-info` | report whether login protection is enabled |
| POST | `/api/login` | submit password and receive token |

## 3. General conventions

- most responses include:
  - `ok`
  - `message`
- read routes usually return `200`
- missing resources usually return `404`
- invalid payloads or execution failures usually return `400`

Important note:

- `install_unit_id`, `collection_group_id`, and `source_id` may contain `:`, `/`, `@`, and similar characters, so they should be URL-encoded by callers.

## 4. System and overview routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | base health check |
| GET | `/api/overview` | software-update overview |
| GET | `/api/jobs/latest` | latest job |
| GET | `/api/jobs/{job_id}` | one job detail |
| GET | `/api/debug/logs` | debug logs |
| POST | `/api/debug/clear` | clear debug logs |
| POST | `/api/run` | trigger software update execution |
| GET | `/api/docs/index` | local Markdown document index for the Guide modal |
| GET | `/api/docs/content` | one local Markdown document payload (JSON) |
| GET | `/api/docs/raw` | one local Markdown document payload (raw text) |

Docs route notes:

- `path` must be a repository-relative Markdown path.
- current allow scope:
  - root docs (`README*.md`, `CHANGELOG.md`, `TODO.md`, `TEST_REPORT.md`)
  - all `docs/**/*.md`
- traversal paths such as `../../...` are rejected with `404`.

## 5. Inventory compatibility layer

These routes remain for compatibility with the older inventory-driven flow.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/inventory/overview` | inventory overview |
| GET | `/api/inventory/software` | software asset detail |
| GET | `/api/inventory/skills` | skill asset detail |
| GET | `/api/inventory/bindings` | binding detail |
| POST | `/api/inventory/scan` | rescan inventory |
| POST | `/api/inventory/bindings` | save software-to-source bindings |

Current note:

- `POST /api/inventory/bindings` now projects from persisted `manifest` plus the latest skills snapshot, so binding saves no longer need an inventory rescan to converge.

## 6. Skills read routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/skills/overview` | source-first overview |
| GET | `/api/skills/registry` | source registry |
| GET | `/api/skills/install-atoms` | install-atom ledger |
| GET | `/api/skills/audit` | audit records |
| GET | `/api/skills/hosts` | host rows |
| GET | `/api/skills/sources` | source list |
| GET | `/api/skills/sources/{source_id}` | one source detail |
| GET | `/api/skills/install-units/{install_unit_id}` | install-unit detail |
| GET | `/api/skills/collections/{collection_group_id}` | collection-group detail |
| GET | `/api/skills/deploy-targets/{target_id}` | deploy-target detail |
| GET | `/api/skills/astrbot-neo-sources` | AstrBot Neo source list |
| GET | `/api/skills/astrbot-neo-sources/{source_id}` | one AstrBot Neo source detail |
| GET | `/api/skills/hosts/{host_id}/astrbot` | AstrBot host runtime detail |
| GET | `/api/skills/hosts/{host_id}/astrbot/workspaces` | AstrBot workspace index detail |

## 7. Skills mutation routes

### 7.1 Source / registry

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/import` | rebuild skills snapshot |
| POST | `/api/skills/sources/register` | register a source |
| POST | `/api/skills/sources/{source_id}/refresh` | refresh source-registry metadata |
| POST | `/api/skills/sources/{source_id}/remove` | remove a source |
| POST | `/api/skills/sources/{source_id}/sync` | sync one source |
| POST | `/api/skills/sources/sync-all` | sync all syncable sources |
| POST | `/api/skills/sources/{source_id}/deploy` | deploy one source directly |

### 7.2 Install unit / collection group

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/install-units/{install_unit_id}/refresh` | refresh install-unit related metadata |
| POST | `/api/skills/install-units/{install_unit_id}/sync` | sync all sources under one install unit |
| POST | `/api/skills/install-units/{install_unit_id}/update` | execute install-unit update |
| POST | `/api/skills/install-units/{install_unit_id}/rollback` | rollback one install unit |
| POST | `/api/skills/install-units/{install_unit_id}/deploy` | deploy one install unit |
| POST | `/api/skills/install-units/{install_unit_id}/repair` | repair one install unit |
| POST | `/api/skills/collections/{collection_group_id}/refresh` | refresh collection-group metadata |
| POST | `/api/skills/collections/{collection_group_id}/sync` | sync all sources in one collection group |
| POST | `/api/skills/collections/{collection_group_id}/update` | update one collection group |
| POST | `/api/skills/collections/{collection_group_id}/rollback` | rollback one collection group |
| POST | `/api/skills/collections/{collection_group_id}/deploy` | deploy one collection group |
| POST | `/api/skills/collections/{collection_group_id}/repair` | repair one collection group |

### 7.3 Deploy target / doctor

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/deploy-targets/{target_id}` | save selected sources for one target |
| POST | `/api/skills/deploy-targets/{target_id}/repair` | repair one deploy target |
| POST | `/api/skills/deploy-targets/{target_id}/reproject` | rebuild one deploy-target projection |
| POST | `/api/skills/deploy-targets/repair-all` | repair all repairable deploy targets |
| POST | `/api/skills/doctor` | run Skills doctor |

## 8. Batch and progress routes

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/aggregates/update-all` | batch-update all actionable aggregates |
| GET | `/api/skills/aggregates/update-all/progress` | fetch latest aggregate-update progress snapshot |
| GET | `/api/skills/aggregates/update-all/history` | fetch recent aggregate-update history |
| POST | `/api/skills/improve-all` | run the full Improve All Skills workflow |

Recommendation:

- for progress UI, prefer `progress` / `history` instead of inventing client-side progress estimates
- `POST /api/skills/improve-all` writes to the same progress channel; distinguish the combined atom-refresh + aggregate-update workflow through `progress.workflow_kind = "improve_all"` and the `atom_*` counters.

## 9. AstrBot runtime routes

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/toggle` | enable/disable a local AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/delete` | delete a local AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/import-zip` | import a local AstrBot skill ZIP |
| GET | `/api/skills/hosts/{host_id}/astrbot/skills/export-zip` | export a local AstrBot skill ZIP |
| POST | `/api/skills/hosts/{host_id}/astrbot/sandbox/sync` | trigger sandbox sync |
| POST | `/api/skills/hosts/{host_id}/astrbot/workspaces/init` | initialize one AstrBot workspace scaffold |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/sync` | sync one AstrBot Neo source |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/promote` | promote one AstrBot Neo candidate |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/rollback` | roll back one AstrBot Neo release |

### 9.1 Host detail response shape

Key fields returned by `GET /api/skills/hosts/{host_id}/astrbot`:

- `host`
  - the current host row
- `layout.available_scopes`
  - the scopes currently exposed by the host (`global / workspace`)
- `layout.selected_scope`
  - the default read scope
- `layout.selected_workspace_id`
  - populated only when the host provides an explicit `target_paths.workspace` mapping; discovered workspace candidates are intentionally not auto-selected
- `layout.scoped_layouts.{scope}`
  - per-scope paths and availability such as `skills_root`, `skills_config_path`, `sandbox_cache_path`, `neo_map_path`, and `state_available`
- `runtime_state.summary.available_scopes`
  - the runtime layer re-exposes usable scopes so the client does not need to infer from layout only
- `runtime_state.summary.scope_summaries.{scope}`
  - per-scope summaries such as `local_skill_total`, `active_skill_total`, `sandbox_cache_exists`, and `sandbox_cache_ready`
- `runtime_state.summary.selected_workspace_id`
  - follows the same explicit-target semantics as `layout.selected_workspace_id`
  - when empty and `scope_summaries.workspace` exists, that workspace scope summary is an aggregate (`workspace_aggregate=true`) instead of an implicit first-workspace fallback
- `runtime_state.state_rows[]`
  - per-skill rows carrying `scope`, `skill_name`, `state_classification`, `local_exists`, `sandbox_exists`, and `active`

### 9.1.1 Neo source detail extras

`GET /api/skills/astrbot-neo-sources/{source_id}` also returns:

- `neo_state`
  - `host_id`, `skill_key`, `local_skill_name`, `release_id`, `candidate_id`, `payload_ref`, `updated_at`
- `neo_capabilities`
  - action-level booleans for `sync_supported`, `promote_supported`, and `rollback_supported`
- `neo_defaults`
  - frontend-ready default action parameters: `candidate_id`, `release_id`, `stage`, `sync_to_local`, `require_stable`
  - when remote state is available, these defaults are aligned to the remote `latest_candidate_id` / `active_stable_release_id`
- `neo_remote_state`
  - read-only Neo remote snapshot with `configured`, `endpoint`, `fetched_at`, `reason_code`, and `message`
  - `current` includes `active_stable_release_id`, `active_canary_release_id`, `latest_release_id`, `latest_candidate_id`, and `latest_candidate_status`
  - `releases.items[]` and `candidates.items[]` are normalized in descending recency order using `updated_at -> created_at`
- `neo_activity`
  - recent audit history for the current Neo source: `counts.total`, `items[]`, and `warnings[]`
  - audit filtering matches normalized `source_id` values, so `astrneo:*` identifiers with separators still resolve their history correctly

### 9.2 AstrBot mutation payloads

Pass `scope` explicitly whenever the caller already knows which root it wants.
When `scope=workspace`, `workspace_id` is required; otherwise the API returns
`reason_code=workspace_required` or `reason_code=workspace_not_found`.

- `POST /api/skills/hosts/{host_id}/astrbot/workspaces/init`

```json
{
  "workspace_id": "session_alpha",
  "workspace_root": "/root/astrbot/data/workspaces/session-alpha"
}
```

`workspace_root` is optional. If provided, it must be under
`{astrbot_data_dir}/workspaces` and its basename must normalize to the same
`workspace_id`.

- `POST /api/skills/hosts/{host_id}/astrbot/skills/toggle`

```json
{
  "skill_name": "demo",
  "active": false,
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/hosts/{host_id}/astrbot/skills/delete`

```json
{
  "skill_name": "demo",
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/hosts/{host_id}/astrbot/skills/import-zip`
  - `multipart/form-data`
  - fields:
    - `file`: `.zip` archive
    - `scope`: `global` / `workspace`
    - `workspace_id`: required when `scope=workspace`
    - `overwrite`: optional, default `false`
    - `skill_name_hint`: optional target directory hint for single-skill root archives

- `GET /api/skills/hosts/{host_id}/astrbot/skills/export-zip`
  - query:
    - `skill_name=demo`
    - `scope=workspace`
    - `workspace_id=session_alpha`

- `POST /api/skills/hosts/{host_id}/astrbot/sandbox/sync`

```json
{
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/sync`

```json
{
  "release_id": "rel-2"
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/promote`

```json
{
  "candidate_id": "cand-3",
  "stage": "stable",
  "sync_to_local": true
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/rollback`

```json
{
  "release_id": "rel-3"
}
```

Notes:

- `scope` should be `global` or `workspace`.
- Requesting an unavailable scope returns `reason_code = "scope_unavailable"`.
- ZIP import only accepts `.zip`; missing upload content returns `reason_code = "zip_path_required"`.
- ZIP export returns an `application/zip` stream; sandbox-only skills return `reason_code = "sandbox_only_skill"`.
- Neo sync may omit `release_id`; when omitted, backend default candidate/release selection is used.
- Neo promote falls back to the current source detail `neo_defaults.candidate_id` when `candidate_id` is omitted.
- Neo rollback falls back to the current source detail `neo_defaults.release_id` when `release_id` is omitted.

## 10. Config routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/config` | read plugin config |
| POST | `/api/config` | update plugin config |

Important note:

- `web_admin.password` is no longer returned in plaintext
- password updates should use explicit mode semantics:
  - `keep`
  - `set`
  - `clear`

## 11. Recommended call sequences

### 11.1 User config and software update

1. `GET /api/config`
2. `POST /api/config`
3. `GET /api/overview`
4. `POST /api/run`

### 11.2 Skills import and binding

1. `POST /api/skills/import`
2. `GET /api/skills/overview`
3. `POST /api/inventory/bindings`
4. `GET /api/skills/deploy-targets/{target_id}`

### 11.3 Batch aggregate update

1. `POST /api/skills/aggregates/update-all`
2. `GET /api/skills/aggregates/update-all/progress`
3. `GET /api/skills/aggregates/update-all/history`

### 11.4 AstrBot local skill flow

1. `GET /api/skills/hosts`
2. `GET /api/skills/hosts/{host_id}/astrbot`
3. call toggle / delete / import-zip / export-zip / sandbox sync with explicit `scope`
4. `GET /api/skills/hosts/{host_id}/astrbot`

## 12. Related documents

- [README_en.md](../README_en.md)
- [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md)
- [Developer Guide (English)](./DEVELOPER_GUIDE_en.md)
- [Operations and Sync Manual (English)](./OPERATIONS_AND_SYNC_en.md)
