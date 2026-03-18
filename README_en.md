# astrbot_plugin_onesync

> Language / 语言: [English](./README_en.md) | [中文](./README.md)

OneSync is an extensible software update manager plugin for AstrBot.

- Scheduled checks, optional auto-update, and manual run support.
- Multi-target architecture (not limited to `zeroclaw`).
- Mirror and multi-remote fallback for stable updates.
- Remote probe and selection before update execution.
- Persistent state and event logs for audit/troubleshooting.
- Built-in WebUI (no AstrBot Dashboard source patch required).
- Auto-generated software/version overview for operations.
- Built-in debug log panel with tabs (`All/Run/Target/Scheduler/System`).
- WebUI config center can now read/write plugin config and sync Human/Developer target models.
- Native `system_package` strategy for `apt_get/yum/dnf/pacman/zypper/choco/winget/brew`.

## Configuration Modes

- `human` (default): cleaner UI settings for normal users.
- `developer`: advanced `targets_json` mode for full control.

Switch via `target_config_mode`.

## Embedded WebUI

Enable with:

1. `web_admin.enabled=true`
2. Configure `web_admin.host` and `web_admin.port` (default `127.0.0.1:8099`)
3. Optional `web_admin.password`
4. Reload plugin and open `web_admin_url`

WebUI capabilities:

- Filter targets by status and keyword.
- `Run Update (Filtered)` with confirmation dialog.
- `Run Update (All Managed)` with confirmation dialog.
- `Config Center`: edit plugin settings and target definitions directly in WebUI.
- `AI Assistant`: generate copy-ready prompts for bootstrap/add/diagnose/full-suite workflows.
- `Guide`: built-in user and developer operation flows, plus direct doc links.
- Recent job panel and real-time debug logs.
- UI i18n toggle (Chinese/English).

### Embedded AI Assistant and Guide

Entry points:

- Top buttons: `AI Assistant` and `Guide`
- Shortcuts:
  - `Alt+A` open AI assistant
  - `Alt+H` open guide
  - `Esc` close top-most modal (AI / Guide / Config Center)

Recommended user flow:

1. Open `AI Assistant` and click `User Preset`.
2. Pick a scenario (bootstrap/add/diagnose/suite) and fill minimal target fields.
3. Click `Generate Prompt`, then `Copy Output`, and send it to your AI tool.
4. Apply returned JSON/script via Config Center or API.
5. Verify from `Latest Job` and `Debug Logs`.

Recommended developer flow:

1. Open `AI Assistant` and click `Developer Preset`.
2. Use `Full Suite` to generate a multi-scenario prompt package.
3. Ask AI to output `targets_json` or one-click API scripts.
4. Switch Config Center to `developer` mode and apply the config.
5. Validate with `/updater env` and `/updater check`.

### WebUI Troubleshooting: `Failed to load config (404)`

If you see `Failed to load config: 404 Not Found`, the running plugin process is usually still serving an older route set.

Use this sequence:

1. Restart AstrBot:
   `systemctl restart astrbot.service`
2. Confirm you opened OneSync `web_admin_url` (default `http://127.0.0.1:8099`) instead of the AstrBot Dashboard URL.
3. Hard refresh browser cache (`Ctrl+F5`).
4. Verify endpoint on host:
   - `curl -i http://127.0.0.1:8099/api/config`
   - `curl -s http://127.0.0.1:8099/openapi.json | jq -r '.paths | keys[]'`

## AI One-Click Prompt (Copy Ready)

If you do not want to fill a large prompt manually, generate it first with the built-in helper:

```bash
# Interactive mode (recommended): answer a few questions
python3 scripts/onesync_prompt_builder.py --interactive --lang en --scenario suite --output /tmp/onesync_prompt_en.txt

# Non-interactive mode (example: Ubuntu + system_package)
python3 scripts/onesync_prompt_builder.py \
  --lang en \
  --scenario suite \
  --os-profile ubuntu \
  --software-name curl \
  --strategy system_package \
  --output /tmp/onesync_prompt_en.txt
```

Then send the full generated file content (`/tmp/onesync_prompt_en.txt`) to your AI tool.

The prompt below is designed for ChatGPT/Codex/Claude to produce a full OneSync setup in one pass: generate config, apply it through API, and validate result.

```text
You are my OneSync (astrbot_plugin_onesync) configuration execution assistant.
Goal: generate a valid OneSync config payload, then provide one-click shell commands to apply and verify it.

Follow these rules strictly:
1) First output a valid JSON payload in this exact shape:
   {
     "config": {
       ...OneSync config...
     }
   }
2) Then output a bash script that performs:
   - write onesync_config.json
   - optional login via POST /api/login when WEBUI_PASSWORD is not empty
   - POST /api/config to apply
   - GET /api/config and /api/overview to verify
3) If required fields are missing, use safe defaults and list them under assumptions.
4) Output must contain exactly these three sections:
   - `JSON_PAYLOAD`
   - `BASH_ONE_CLICK`
   - `ASSUMPTIONS`
5) No comments or trailing commas in JSON.

Input values:
WEBUI_URL=http://127.0.0.1:8099
WEBUI_PASSWORD=
TARGET_CONFIG_MODE=human
POLL_INTERVAL_MINUTES=10
DEFAULT_CHECK_INTERVAL_HOURS=12
AUTO_UPDATE_ON_SCHEDULE=true
NOTIFY_ADMIN_ON_SCHEDULE=true
NOTIFY_ON_SCHEDULE_NOOP=false
ADMIN_SID_LIST=
TARGETS_YAML:
- name: zeroclaw
  strategy: cargo_path_git
  enabled: true
  check_interval_hours: 12
  repo_path: /home/jacob/zeroclaw
  binary_path: /root/.cargo/bin/zeroclaw
  upstream_repo: https://github.com/zeroclaw-labs/zeroclaw.git
  build_commands:
    - cargo install --path {repo_path}
  verify_cmd: "{binary_path} --version"
- name: curl
  strategy: system_package
  enabled: true
  check_interval_hours: 24
  manager: apt_get
  package_name: curl
  require_sudo: true
```

For a full prompt suite (bootstrap, incremental target add, diagnose/repair), see:
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)
- [安装与配置手册（中文）](./docs/INSTALL_AND_CONFIG_zh.md)

## Quick Interval Setup

Sync cadence is controlled by:

- `poll_interval_minutes` (scheduler loop frequency)
- `check_interval_hours` (per target)

Recommended:

1. `poll_interval_minutes = 5` (or `10`)
2. Set per-target `check_interval_hours`
3. Restart AstrBot
4. Verify via `/updater status` and `/updater env <target>`

## Install

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
systemctl restart astrbot.service
```

Verification:

- Send `/updater status` as admin.

## Commands

- `/updater status`
- `/updater check [target]`
- `/updater run [target]`
- `/updater force [target]`
- `/updater env [target]`

## Docs

- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)
- [安装与配置手册（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Operations and Sync Manual (English)](./docs/OPERATIONS_AND_SYNC_en.md)
- [操作与同步手册（中文）](./docs/OPERATIONS_AND_SYNC_zh.md)
