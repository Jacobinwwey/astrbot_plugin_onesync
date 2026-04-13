# OneSync API Reference (English)

> Language / 语言: [English](./API_REFERENCE_en.md) | [中文](./API_REFERENCE_zh.md)

This document centralizes the embedded WebUI `/api/*` surface for:

- automation scripts
- frontend integration
- secondary integrations around the plugin

For user install and day-to-day usage, see:

- [README_en.md](../README_en.md)
- [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md)

For code structure and extension points, see:

- [Developer Guide (English)](./DEVELOPER_GUIDE_en.md)

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

## 9. AstrBot runtime routes

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/toggle` | enable/disable a local AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/delete` | delete a local AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/sandbox/sync` | trigger sandbox sync |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/sync` | sync one AstrBot Neo source |

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

## 12. Related documents

- [README_en.md](../README_en.md)
- [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md)
- [Developer Guide (English)](./DEVELOPER_GUIDE_en.md)
- [Operations and Sync Manual (English)](./OPERATIONS_AND_SYNC_en.md)
