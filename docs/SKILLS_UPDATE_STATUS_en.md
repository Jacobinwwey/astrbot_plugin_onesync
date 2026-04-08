# OneSync Skills Source and Update Status

> Language / 语言: [English](./SKILLS_UPDATE_STATUS_en.md) | [中文](./SKILLS_UPDATE_STATUS_zh.md)

Audit date: `2026-04-08`  
Scope: current `main` branch, source-first Skills management model

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

- Supported only for npm-backed sources with both:
  - `registry_package_name`
  - `registry_package_manager == "npm"`
- The implementation currently fetches npm registry metadata only.
- GitHub/community/catalog/documented repo references are not metadata-syncable yet.

### 2.3 `Update Install Unit` / `Update Collection`

This executes a real update command derived from the install unit.

Current reality:

- Registry-backed install units can be updated through `bunx`, `npx`, `pnpm dlx`, or `npm install -g`.
- Git-backed install units can be updated with `git -C <source_path> pull --ff-only` when a local checkout path exists.
- Manual/local custom/repo-reference-only aggregates are still unsupported unless OneSync can derive a concrete executable update command.

## 3. Current Support Matrix

| Install/source shape | Example | `Sync Source` | `Update Install Unit` | Notes |
| --- | --- | --- | --- | --- |
| npm package-backed bundle/single | `npm:@every-env/compound-plugin` | Yes | Yes | Sync reads npm registry metadata. Update uses `management_hint` first, otherwise a registry command is built. |
| Git-backed local checkout / skill-lock entry | `skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills` | No | Yes, if local `source_path` exists | Update becomes `git -C <path> pull --ff-only`. This is update support, not source-sync support. |
| Documented/catalog/community repo reference without executable manager | `repo:https://github.com/...#skills/foo` | No | Usually no | These rows improve provenance and grouping, but they are not automatically updateable yet. |
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

Important nuance:

- A source row may still carry `update_policy=registry` because of how the source registry normalizes npx-discovered entries.
- That does **not** guarantee the install unit is updateable.
- The final truth is the install-unit-level `update_plan`.

This matters for local custom skills such as `doc`: they can be discovered from the same runtime inventory as npx-managed skills, but they remain manually maintained and therefore update-unsupported.

## 5. Current Verdict

If the question is "is the current skill update function complete?", the answer is:

- Discovery/import/provenance: largely complete for the current v1 scope.
- Install-unit update execution: partially complete.
- Source metadata sync: not complete yet.

More specifically:

- Complete enough today for package-backed npm updates and git-backed local checkouts.
- Not complete for repo-derived sources that only carry provenance/reference information.
- Not complete for local custom/manual skills.
- Not complete for non-npm upstream metadata refresh.

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
- `counts.source_syncable_total` only counts npm-backed sources today.
- Supported install units expose non-empty `update_plan.commands`.
- Local custom skills expose `update_plan.supported = false`.

## 7. Recommended Next Steps

To call the feature "complete", the next implementation steps should be:

1. Add repo-aware source sync adapters for git/GitHub-style sources.
2. Surface unsupported reasons more explicitly in the UI.
3. Separate "provenance origin" from "update mechanism" more clearly in panel copy.
4. Add more end-to-end tests around install-unit detail payloads and live sync/update behavior.
