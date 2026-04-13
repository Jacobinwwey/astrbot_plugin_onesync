# OneSync Developer Guide (English)

> Language / 语言: [English](./DEVELOPER_GUIDE_en.md) | [中文](./DEVELOPER_GUIDE_zh.md)

This guide is for maintainers, contributors, and extension authors. It focuses on:

- repository structure and responsibility boundaries
- local development and verification workflow
- Skills control-plane state files
- extension points and maintenance discipline

For user install/usage, operations, and API details, use:

- [README_en.md](../README_en.md)
- [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md)
- [Operations and Sync Manual (English)](./OPERATIONS_AND_SYNC_en.md)
- [API Reference (English)](./API_REFERENCE_en.md)

## 1. Repository layout

Important files and directories:

- `main.py`
  - plugin entrypoint
  - orchestration for WebUI actions, scheduling, persistence, and Skills control-plane mutations
- `webui_server.py`
  - embedded FastAPI server
  - publishes `/api/*` routes and optional login auth
- `webui/index.html`
  - single-file operations console
  - holds runtime dashboard, config center, Skills management, progress UI, and inspector flows
- `updater_core.py`
  - software-update execution core
- `inventory_core.py`
  - compatibility/discovery layer for software and skills
- `skills_core.py`
  - Skills overview assembly and aggregation entrypoint
- `skills_aggregation_core.py`
  - install-unit / collection-group / provenance aggregation logic
- `skills_sources_core.py`
  - source-registry normalization and merge helpers
- `skills_hosts_core.py`
  - host capability and host-row assembly logic
- `tests/`
  - regression tests
- `docs/`
  - user, ops, developer, API, and planning docs

## 2. Current state model

The Skills control plane is centered around:

- `manifest`
  - operator intent
  - deploy-target selection, source selection, scope, and related declarative state
- `lock`
  - resolved runtime state
  - aggregation, freshness, projection, and doctor output
- `registry`
  - source truth
  - locator, manager, sync metadata, managed checkout metadata
- `install_atom_registry`
  - install-atom / evidence ledger
- `inventory_snapshot`
  - discovery and compatibility input
  - still present, but increasingly being narrowed away from authority duties

Important current boundary:

- `webui_update_inventory_bindings()` is now manifest-first.
- deploy-target mutations reuse the same manifest-first projection helpers.
- `skill_bindings` remains as compatibility projection, not long-term authority.

## 3. Runtime files

The plugin writes runtime state under AstrBot `plugin_data`, including:

- `skills/manifest.json`
- `skills/lock.json`
- `skills/registry.json`
- `skills/install_atom_registry.json`
- `skills/audit.log.jsonl`
- `skills/sources/*.json`
- `skills/generated/*.json`
- `state.json`
- `events.jsonl`

When debugging, first identify whether the problem is in:

- operator intent (`manifest`)
- source metadata (`registry`)
- resolved aggregation (`lock/overview`)
- or frontend presentation

## 4. Local development workflow

### 4.1 Suggested prerequisites

- working Python 3 environment
- runnable AstrBot dev environment
- local access to `127.0.0.1:8099` for WebUI verification

### 4.2 Common commands

Syntax check:

```bash
python3 -m py_compile main.py skills_core.py webui_server.py
```

Full regression:

```bash
pytest -q
```

Focused Skills slice:

```bash
pytest -q tests/test_main_git_checkout_runtime.py tests/test_skills_core.py tests/test_webui_server.py
```

### 4.3 After frontend changes

- verify `webui/index.html` does not have obvious syntax issues
- verify the 8099 WebUI still renders
- at minimum, re-check:
  - Skills panel expand/collapse
  - Source / Bundle detail
  - Deploy Target detail
  - aggregate progress strip
  - right-side inspector

## 5. Extension points

### 5.1 Update strategies

Current primary strategies:

- `cargo_path_git`
- `command`
- `system_package`

When adding a new strategy, review:

- schema support
- execution support in `updater_core.py`
- whether the WebUI needs new user-facing fields

### 5.2 Skills source / host support

Source-related extensions usually touch:

- `skills_sources_core.py`
- `skills_core.py`
- `main.py`
- `webui_server.py`
- `webui/index.html`
- related tests

Host-related extensions usually touch:

- `skills_hosts_core.py`
- `skills_core.py`
- and `skills_astrbot_*` for AstrBot-specific runtime support

Recommended order:

1. define capability and normalized row shape
2. add API surface
3. wire UI
4. add tests and docs

### 5.3 WebUI API changes

When adding or changing routes:

1. update `webui_server.py`
2. add/update the matching `webui_*` method in `main.py`
3. update [API Reference (English)](./API_REFERENCE_en.md) and [接口参考（中文）](./API_REFERENCE_zh.md)
4. add regression coverage in `tests/test_webui_server.py`

## 6. Current risk areas

The mainline risk is not “missing aggregation models”. It is:

- authority boundary is still not fully detached from inventory
- runtime reliability is still sensitive to manager availability, checkout quality, and sync stability
- semantics for `manual_only`, repo-metadata, and git-backed sources need to stay consistent across UI and execution

Avoid:

- turning temporary UI heuristics into new truth sources
- pushing inventory back into authority duties it should no longer own
- adding one-off host/manager branches that cannot generalize

## 7. Documentation boundaries

Recommended doc ownership:

- `README.md` / `README_en.md`
  - project homepage, core value, install entry, quick usage, doc navigation
- `docs/INSTALL_AND_CONFIG_*`
  - full install/config detail
- `docs/OPERATIONS_AND_SYNC_*`
  - release, sync, maintainer operations
- `docs/DEVELOPER_GUIDE_*`
  - code structure, extension points, verification workflow
- `docs/API_REFERENCE_*`
  - `/api/*` interface documentation
- `docs/plans/*` / `docs/brainstorms/*`
  - plans, roadmap, analysis, historical decisions

Do not keep re-expanding README with:

- long route inventories
- maintainer release flow
- architecture retrospectives
- detailed roadmap history

## 8. Related documents

- [README_en.md](../README_en.md)
- [Installation & Config Guide (English)](./INSTALL_AND_CONFIG_en.md)
- [Operations and Sync Manual (English)](./OPERATIONS_AND_SYNC_en.md)
- [API Reference (English)](./API_REFERENCE_en.md)
- [开发指南（中文）](./DEVELOPER_GUIDE_zh.md)
