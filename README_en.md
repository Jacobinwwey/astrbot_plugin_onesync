# astrbot_plugin_onesync

> Language / 语言: [English](./README_en.md) | [中文](./README.md)

<div align="center">
  <img src="./logo_256.png" alt="OneSync Logo" width="132">
</div>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.2.1-2563eb" alt="version v0.2.1">
  <img src="https://img.shields.io/badge/AstrBot-%3E%3D4.16-16a34a" alt="AstrBot >=4.16">
  <img src="https://img.shields.io/badge/WebUI-127.0.0.1%3A8099-f59e0b" alt="WebUI 127.0.0.1:8099">
  <img src="https://img.shields.io/badge/Skills-aggregate--first-7c3aed" alt="aggregate-first skills">
</p>

OneSync is a general-purpose software update plugin for AstrBot, built around one practical goal:

- keep multiple software targets under one update workflow
- expose a dedicated WebUI without patching AstrBot Dashboard source
- manage software hosts, source bundles, deploy targets, and Skills operations inside one control plane

Use this project if you want:

- scheduled and manual maintenance for more than one software target
- a built-in operations console at `127.0.0.1:8099`
- aggregate-first Skills management instead of leaf-level UI noise

## Quick Navigation

1. [Core Highlights](#core-highlights)
2. [Good Fit](#good-fit)
3. [Quick Start](#quick-start)
4. [Common Commands](#common-commands)
5. [WebUI Highlights](#webui-highlights)
6. [Skills Management Highlights](#skills-management-highlights)
7. [FAQ](#faq)
8. [Documentation Map](#documentation-map)

## Core Highlights

### 1. Software updates as an actual workflow

- scheduled checks, manual checks, manual updates, and forced updates
- multi-target architecture instead of a single-tool updater
- three primary strategies:
  - `cargo_path_git`
  - `command`
  - `system_package`
- post-update verification, persisted state, and event logs

### 2. Embedded WebUI without dashboard patching

- embedded WebUI at `127.0.0.1:8099`
- config center, runtime overview, recent jobs, debug logs
- Chinese/English UI toggle
- filtering by keyword, status, and strategy

### 3. Built for operations, not only for “it runs”

- mirror and multi-remote support
- runtime health and structured diagnostics
- batch update flows and audit replay
- unified batch workflows such as `Improve All Skills` and `Update All Aggregates`

### 4. Aggregate-first Skills management

- no primary UI based on flat leaf-skill explosion
- install units and collection groups are the main maintenance objects
- package/source bundles are preferred when a real maintenance boundary exists
- `manual_only`, git-backed, repo-metadata, and registry-backed paths stay explicitly separated

## Good Fit

- you maintain multiple CLI / GUI / Skills-capable hosts on one AstrBot machine
- you want software updates and Skills maintenance in one panel
- you need a plugin that is user-operable, developer-extensible, and ops-auditable
- you do not want README to carry user guidance, ops process, architecture notes, and API inventory all at once

## Quick Start

### 1. Install the plugin

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
```

### 2. Restart AstrBot

```bash
systemctl restart astrbot.service
```

### 3. Run the minimal verification

Send as admin:

```text
/updater status
```

If you see the status summary, the plugin is loaded correctly.

### 4. Open the embedded WebUI

Enable these config fields:

- `web_admin.enabled = true`
- `web_admin.host = 127.0.0.1`
- `web_admin.port = 8099`

Then open:

```text
http://127.0.0.1:8099
```

### 5. Follow the recommended path

1. choose `human` or `developer` mode in Config Center
2. define or import software targets
3. run `/updater env` or `Run Update (Filtered)` first
4. validate one target before moving to batch operations

For full install and config detail:

- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)
- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md)

## Common Commands

| Command | Purpose |
| --- | --- |
| `/updater status` | show plugin and target status |
| `/updater check [target]` | check versions without updating |
| `/updater run [target]` | check and update if needed |
| `/updater force [target]` | force update execution |
| `/updater env [target]` | verify runtime commands, paths, and versions |

Notes:

- `target` is optional; when omitted, all configured targets are used
- running `/updater env` before wider rollout is strongly recommended

## WebUI Highlights

The WebUI is not just “commands with buttons”. It is structured for actual operations:

- `Config Center`
  - read/write plugin config
  - `human` / `developer` dual-mode support
- `AI Assistant`
  - prompt generation for bootstrap, incremental add, diagnosis, and full-suite flows
- `Latest Job`
  - recent software-update execution summary
- `Debug Logs`
  - tabs, level filter, keyword filter, clear action
- `Guide`
  - user flow and developer flow help

If your immediate goal is “get software update working safely”, the practical order is:

1. `Config Center`
2. `AI Assistant` if needed
3. `Run Update (Filtered)`
4. `Latest Job`
5. `Debug Logs`

## Skills Management Highlights

OneSync does not treat Skills management as a raw `npx skills ls` dump. It is built around maintenance boundaries:

- installed, skill-capable hosts are shown first by default
- uninstalled candidates can still be revealed explicitly
- `global / workspace` binding scope is first-class
- the right-side inspector focuses on the current source / install unit / deploy target
- long information zones such as `Structure & Members` and `Execution Preview & Audit` are collapsible
- in the current UI, `Structure & Members` is collapsed by default so the primary operations stay visually dominant

Update support is intentionally explicit:

- npm / registry-backed aggregates: updateable
- git-backed `skill_lock` aggregates: updateable after managed checkout bootstrap
- repo-metadata sources: source-sync fallback
- `local_custom` / `synthetic_single` / `derived`: explicitly `manual_only`

The point is not to make everything look updateable. The point is to make it obvious:

- what can be updated automatically
- what can only refresh metadata
- what still requires manual maintenance

## FAQ

### 1. The page shows `Failed to load config: 404 Not Found`

Use this order first:

1. `systemctl restart astrbot.service`
2. make sure you opened OneSync `web_admin_url`
3. hard refresh the browser with `Ctrl+F5`
4. verify:
   - `curl -i http://127.0.0.1:8099/api/config`
   - `curl -s http://127.0.0.1:8099/openapi.json | jq -r '.paths | keys[]'`

### 2. An update succeeded, but the Skills panel still looks stale

The current mainline already fixes two common false positives:

- binding saves no longer depend on an inventory rescan to become visible
- successful install-unit / collection command updates now stamp freshness anchors immediately, so false `AGING` state should clear on the next rebuild

If the panel still looks wrong, check:

- whether the source is actually `manual_only`
- whether the path used `source sync fallback` instead of command update
- whether `Debug Logs` or `doctor` show a structured error

### 3. Should I use `human` or `developer` mode?

- normal users: start with `human`
- advanced operators needing mirrors, regex, timeout tuning, or larger target sets: use `developer`

## Documentation Map

The documentation is now intentionally separated by audience:

### User docs

- [README_en.md](./README_en.md)
- [README.md](./README.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)
- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md)

### Operations / release docs

- [Operations and Sync Manual (English)](./docs/OPERATIONS_AND_SYNC_en.md)
- [操作与同步手册（中文）](./docs/OPERATIONS_AND_SYNC_zh.md)

### Developer docs

- [Developer Guide (English)](./docs/DEVELOPER_GUIDE_en.md)
- [开发指南（中文）](./docs/DEVELOPER_GUIDE_zh.md)

### API docs

- [API Reference (English)](./docs/API_REFERENCE_en.md)
- [接口参考（中文）](./docs/API_REFERENCE_zh.md)

### Status and planning docs

- [Skills Update Status (English)](./docs/SKILLS_UPDATE_STATUS_en.md)
- [Skills 更新能力现状（中文）](./docs/SKILLS_UPDATE_STATUS_zh.md)
- [Skills Management Roadmap](./docs/plans/skills-management-roadmap-v2.md)

---

If this project helps with real AstrBot maintenance work, a Star is appreciated.
