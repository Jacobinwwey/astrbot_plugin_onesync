# OneSync Operations and Sync Manual (Maintainers)

> Language / 语言: [English](./OPERATIONS_AND_SYNC_en.md) | [中文](./OPERATIONS_AND_SYNC_zh.md)

| Current version | Updated | Audience | Start here |
| --- | --- | --- | --- |
| `v0.2.2` | `2026-04-13` | maintainers and release operators | [README_en.md](../README_en.md) |

This manual is for the people who publish and maintain the repository. It is not usage documentation. It is the place to keep release flow, tags, remote sync, and published messaging clean.

| If you need to... | Go to |
| --- | --- |
| prepare plugin upload metadata | [2. Plugin Upload Metadata](#2-plugin-upload-metadata) |
| update GitHub About | [3. GitHub About Setup](#3-github-about-setup) |
| run the release flow | [4. Versioning and Releases](#4-versioning-and-releases) |
| sync code and tags upstream | [5. Code Sync Workflow](#5-code-sync-workflow-local---github) |
| verify current Skills maintenance reality | [6. Skills Update Maintenance Notes](#6-skills-update-maintenance-notes) |

## 1. Doc Navigation

| Doc | Purpose |
| --- | --- |
| [README_en.md](../README_en.md) | project overview, quick start, prompt entry points |
| [INSTALL_AND_CONFIG_en.md](./INSTALL_AND_CONFIG_en.md) | installation, config, troubleshooting |
| [DEVELOPER_GUIDE_en.md](./DEVELOPER_GUIDE_en.md) | code layout and extension points |
| [API_REFERENCE_en.md](./API_REFERENCE_en.md) | `/api/*` surface and call sequences |
| [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md) / [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md) | repository About templates |
| [SKILLS_UPDATE_STATUS_en.md](./SKILLS_UPDATE_STATUS_en.md) / [SKILLS_UPDATE_STATUS_zh.md](./SKILLS_UPDATE_STATUS_zh.md) | current Skills update capability status |

## 2. Plugin Upload Metadata

Suggested values when publishing the plugin:

1. `[Plugin]`: `astrbot_plugin_onesync`
2. Metadata JSON:

```json
{
  "name": "astrbot_plugin_onesync",
  "display_name": "OneSync",
  "desc": "Extensible software updater plugin for AstrBot with scheduling, auto-update, mirror fallback, and state tracking.",
  "author": "Jacobinwwey",
  "repo": "https://github.com/Jacobinwwey/astrbot_plugin_onesync",
  "tags": ["updater", "automation", "devops", "zeroclaw", "astrbot"],
  "social_link": "https://github.com/Jacobinwwey"
}
```

In-repo file reference:

- [plugin_upload_info.json](../plugin_upload_info.json)

## 3. GitHub About Setup

Direct templates:

- [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)
- [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md)

Recommendations:

- Keep description short and clear (within 160 chars).
- Include core topics like `astrbot-plugin`, `updater`, `github-mirror`.
- Use `logo_256.png` or `logo.png` as social preview.

## 4. Versioning and Releases

### 4.1 Recommended release command

Run in the plugin repository:

```bash
./scripts/release.sh v0.2.2
```

This script will:

- Update `metadata.yaml` version
- Add a missing section to `CHANGELOG.md`
- Commit, tag, and push automatically

### 4.2 Local dry run (no push)

```bash
NO_PUSH=1 ./scripts/release.sh v0.2.2
```

### 4.3 GitHub release notes requirement

GitHub releases should default to bilingual notes, not English-only notes.

Recommended sequence:

1. create or update `docs/releases/vX.Y.Z.md`
2. keep the file structured as “complete English + complete Chinese”
3. finish pre-release verification first, then publish or edit the GitHub release with `--notes-file`

Recommended command:

```bash
gh release edit v0.2.2 \
  --title "v0.2.2 · english title / 中文标题" \
  --notes-file docs/releases/v0.2.2.md
```

Template file:

- [docs/releases/RELEASE_TEMPLATE.md](./releases/RELEASE_TEMPLATE.md)

### 4.4 Versioning strategy

- New features: bump `MINOR` (for example `v0.2.0`)
- Bugfix/compatibility: bump `PATCH` (for example `v0.1.1`)

### 4.5 Current repository baseline

- `metadata.yaml` version: `v0.2.2`
- Embedded WebUI OpenAPI version: `0.2.2`
- Current full regression baseline: `pytest -q -> 191 passed`

## 5. Code Sync Workflow (Local -> GitHub)

### 5.1 Regular commit

```bash
git status
git add .
git commit -m "feat: xxx"
git push origin main
```

### 5.2 Push tags after release

```bash
git push origin main --tags
```

### 5.3 Pre-push checklist

Before pushing, verify:

- `README.md` keeps user-facing content only
- `docs/` includes maintainer documentation in both zh/en
- `_conf_schema.json` is valid JSON
- Python files pass syntax checks
- `pytest -q` passes before remote sync
- WebUI JavaScript has no syntax errors
- WebUI routes are reachable (`/api/health` and `/api/config`)

### 5.4 Documentation sync guidance

When a change affects both implementation and operator understanding, do not update only one status file.

At minimum, keep these entry documents aligned:

- `README.md` / `README_en.md`
- `docs/SKILLS_UPDATE_STATUS_zh.md` / `docs/SKILLS_UPDATE_STATUS_en.md`
- `docs/releases/vX.Y.Z.md`
- relevant `docs/plans/*` and `docs/brainstorms/*`

If a live plugin checkout exists beside the development repository, also verify:

- whether `/root/astrbot/data/plugins/astrbot_plugin_onesync/docs/*` should be synced to the running instance
- whether API paths, counters, and runtime validation notes still match the current 8099 service

## 6. Skills Update Maintenance Notes

When reviewing the Skills management stack, separate these operations clearly:

- `POST /api/skills/import`: rebuild local source-first snapshot
- `Sync Source`: refresh upstream metadata for a source
- `Update Install Unit` / `Update Collection`: execute real update commands

Current implementation status:

- Source sync now supports:
  - npm registry metadata
  - git remote/head or local checkout metadata
  - GitHub / GitLab / Bitbucket repo metadata
- Install-unit update is governed by the effective `update_plan`, not by `source_kind` labels alone.
- Inventory binding saves now project from persisted `manifest` plus the latest skills snapshot; maintainers should no longer assume that “save bindings” must trigger an inventory rescan to become visible.
- Successful command updates now write freshness anchors back to saved registry rows, so a completed update should immediately clear false `AGING` state on the next overview rebuild.
- Git-backed `skill_lock` / repo-derived sources now support managed checkout bootstrap:
  - if the leaf skill directory is not a git worktree, OneSync materializes a managed checkout under `plugin_data/.../skills/git_repos/`
  - later `sync/update` paths prefer that checkout
- `synthetic_single`, `derived`, and `local_custom` install units without a real package boundary are now explicitly treated as `manual_only` instead of generating bogus update commands.
- WebUI now exposes:
  - `POST /api/skills/aggregates/update-all`
  - `Update All Aggregates`
  - executed / skipped / source-sync breakdown in the result path

When diagnosing an update complaint, check the install-unit detail payload first and treat `update_plan` as the source of truth.

Latest live 8099 `update-all` verification:

- `candidate_install_unit_total = 20`
- `executed_install_unit_total = 14`
- `command_install_unit_total = 3`
- `source_sync_install_unit_total = 11`
- `skipped_install_unit_total = 6`
- `success_count = 8`
- `failure_count = 2`
- `precheck_failure_count = 0`
