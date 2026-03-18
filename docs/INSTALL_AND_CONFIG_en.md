# OneSync Installation and Configuration Guide (English)

> Language / 语言: [English](./INSTALL_AND_CONFIG_en.md) | [中文](./INSTALL_AND_CONFIG_zh.md)

This guide covers:

- How to install OneSync and verify it is working.
- How to quickly set sync/update intervals.
- How to configure additional software targets (human and developer modes).
- How to troubleshoot common runtime/update failures.

## 1. Plugin Positioning

OneSync is an extensible software updater plugin for AstrBot.

Core capabilities:

- Scheduled checks + optional auto-update.
- Manual operations (`/updater check`, `/updater run`, `/updater force`).
- Multi-target architecture (not limited to `zeroclaw`).
- Native strategy set: `cargo_path_git`, `command`, `system_package`.
- Mirror probing and fallback for GitHub connectivity stability.
- Persistent runtime state and events log for operations/audit.
- Built-in WebUI (without modifying AstrBot Dashboard source).
- Auto-generated software/version overview for large-scale operations.

## 2. Requirements

- AstrBot version: `>=4.16` (see `metadata.yaml`).
- Runtime user must have permissions required by update commands.
  - Example: `cargo install --path` requires executable `cargo` and write permission to install location.
- For `cargo_path_git` strategy:
  - Local git repo path exists (for example `/path/to/zeroclaw`).
  - Upstream repo/mirror is reachable.
- For `system_package` strategy:
  - The host must provide one of the native package managers:
    `apt_get/yum/dnf/pacman/zypper/choco/winget/brew`.
  - The runtime user must have proper update permission (sudo is commonly needed on Linux).

Recommended first check after installation:

- Run `/updater env` once, so OneSync can check command availability and versions before runtime updates.

## 3. Installation

### 3.1 Manual install (recommended)

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
```

Directory layout (simplified):

```text
astrbot_plugin_onesync/
├── main.py
├── updater_core.py
├── _conf_schema.json
├── metadata.yaml
├── README.md
├── docs/
│   ├── INSTALL_AND_CONFIG_en.md
│   └── INSTALL_AND_CONFIG_zh.md
└── webui/
```

### 3.2 Restart AstrBot

```bash
systemctl restart astrbot.service
```

### 3.3 First verification

- Send `/updater status` as admin.
- If you see status summary + target list, plugin load is successful.

## 4. Software Overview View (Large-Scale Ops)

OneSync maintains `software_overview` automatically.

Design goals:

- Dense and scannable version/status view.
- Fast filtering and search.
- Ready for many maintained software targets.

Recommended interactions:

- Search by software name/version/strategy.
- Filter by status (`up_to_date`, `outdated`, `unknown`, `disabled`).
- Use compact density for high-target operations.

## 4.1 Built-in WebUI (no AstrBot Dashboard source patch)

OneSync provides an embedded WebUI for runtime operation.

Enable steps:

1. Configure in plugin settings:
   - `web_admin.enabled = true`
   - `web_admin.host = 127.0.0.1` (recommended)
   - `web_admin.port = 8099` (customizable)
   - `web_admin.password = ...` (optional)
2. Save config and reload/restart plugin.
3. Open `web_admin_url` (generated automatically).

WebUI features:

- Filter targets by keyword and status.
- `Run Update (Filtered)` with confirmation dialog.
- `Run Update (All Managed)` with confirmation dialog.
- Config Center: sync/read/write plugin config directly from WebUI.
- Recent job panel (queued/running/success/partial/error).
- Debug log panel with i18n-ready layout:
  - Tabs: `All / Run / Target / Scheduler / System`
  - Level filter: `ALL/INFO/WARN/ERROR/DEBUG`
  - Keyword filter + auto-scroll + clear logs
- Built-in UI language switch: Chinese / English (labels, filters, buttons, tab names).

If you see `Failed to load config: 404 Not Found`, do this first:

1. `systemctl restart astrbot.service`
2. Open OneSync `web_admin_url` (default `http://127.0.0.1:8099`), not the AstrBot Dashboard URL.
3. Hard refresh browser cache (`Ctrl+F5`).

## 5. Quick Sync Interval Setup

Sync cadence is controlled by two layers:

- `poll_interval_minutes`: scheduler polling loop interval.
- `check_interval_hours`: per-target check interval.

Recommended quick setup:

1. Set `poll_interval_minutes` to `5` or `10`.
2. Set each target `check_interval_hours` as needed (for example `6`).
3. Restart AstrBot if polling interval changed.
4. Run `/updater status` and `/updater env <target>`.

### 5.1 3-minute setup for `zeroclaw`

- Keep target in `human_targets`.
- Ensure:
  - `strategy = cargo_path_git`
  - `repo_path` points to local repo
  - `binary_path` points to installed binary
- Set `check_interval_hours = 12` (or your desired value).

### 5.2 Interval examples

- Every 30 minutes: `check_interval_hours = 0.5`
- Every 2 hours: `check_interval_hours = 2`
- Every 1 day: `check_interval_hours = 24`

### 5.3 AI One-Click Prompt Suite (Recommended)

Use the following prompts directly with AI tools (ChatGPT/Codex/Claude).  
Goal: reduce manual steps and complete setup in one interaction whenever possible.

#### Prompt A: Bootstrap and apply in one shot

```text
You are my OneSync configuration execution assistant.
Please bootstrap and apply OneSync configuration end-to-end.

Goal:
1) Generate valid JSON payload for POST /api/config (outer shape must be {"config": {...}}).
2) Generate a bash one-click script that:
   - writes onesync_config.json
   - logs in via /api/login if WEBUI_PASSWORD is not empty
   - POSTs /api/config
   - verifies with GET /api/config and GET /api/overview
3) Output exactly 3 sections:
   - JSON_PAYLOAD
   - BASH_ONE_CLICK
   - ASSUMPTIONS
4) No extra commentary; JSON must have no comments/trailing commas.

Input:
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

#### Prompt B: Incrementally add one target without overwriting existing config

```text
You are my OneSync config merge assistant.
Add one new software target while preserving all existing settings and targets.

Execution rules:
1) Read current config from GET {WEBUI_URL}/api/config.
2) Merge my new target incrementally (do not wipe unrelated targets).
3) Output:
   - UPDATED_JSON_PAYLOAD (for POST /api/config)
   - BASH_APPLY_PATCH (one-click script)
   - CHANGE_SUMMARY (what changed)
4) If target name already exists, update that target in place instead of duplicating.

Input:
WEBUI_URL=http://127.0.0.1:8099
WEBUI_PASSWORD=
NEW_TARGET:
  name: mytool
  strategy: command
  enabled: true
  check_interval_hours: 12
  current_version_cmd: /usr/local/bin/mytool --version
  latest_version_cmd: curl -fsSL https://example.com/mytool/latest.txt
  latest_version_pattern: (\d+\.\d+\.\d+)
  update_commands:
    - bash /opt/scripts/update-mytool.sh
  verify_cmd: /usr/local/bin/mytool --version
```

#### Prompt C: Diagnose and repair config failures (including 404)

```text
You are my OneSync troubleshooting assistant.
Output a runnable plan in order: diagnose -> fix -> verify.

Required diagnostics:
1) GET {WEBUI_URL}/api/health
2) GET {WEBUI_URL}/openapi.json and confirm `/api/config` exists
3) GET {WEBUI_URL}/api/config
4) If /api/config is 404, provide minimum fix sequence (restart service, confirm web_admin_url, Ctrl+F5)

Output format:
- DIAGNOSIS
- FIX_COMMANDS
- VERIFY_COMMANDS
- ROLLBACK_PLAN

Environment:
WEBUI_URL=http://127.0.0.1:8099
SERVICE_NAME=astrbot.service
```

## 6. Commands

- `/updater status`
  - Show plugin and target status summary.
- `/updater check [target]`
  - Check versions immediately, no update execution.
- `/updater run [target]`
  - Check and update if newer version is available.
- `/updater force [target]`
  - Force update command execution.
- `/updater env [target]`
  - Run environment checks (commands, paths, versions).

`target` is optional. If omitted, operation applies to all configured targets.

## 7. Configuration Overview

### 7.1 Top-level configuration keys

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable or disable plugin runtime. |
| `target_config_mode` | enum | `human` | `human` for UI-friendly config, `developer` for raw JSON config. |
| `human_targets` | list | `[]` | UI-friendly target entries, extensible without slot limit. |
| `targets_json` | string/object | `{}` | Developer mode advanced target config. |
| `software_overview` | template_list | `[]` | Auto-generated software/version summary (read-only intent). |
| `poll_interval_minutes` | int | `30` | Scheduler loop interval in minutes. |
| `default_check_interval_hours` | float | `24` | Default per-target check interval. |
| `auto_update_on_schedule` | bool | `true` | Update automatically during scheduled tick. |
| `notify_admin_on_schedule` | bool | `true` | Notify admins on scheduled update events. |
| `notify_on_schedule_noop` | bool | `false` | Notify even when no actual update happened. |
| `dry_run` | bool | `false` | Simulation mode (no real update command execution). |
| `env_check_timeout_s` | int | `8` | Timeout for per-command env check. |
| `admin_sid_list` | list | `[]` | Admin SIDs for notifications. |
| `web_admin` | object | schema default | Embedded WebUI config (`enabled/host/port/password`). |
| `web_admin_url` | string | `""` | Auto-generated URL for embedded WebUI. |

### 7.2 Shared target fields (`human_targets` and `targets_json`)

| Field | Required | Description |
|---|---|---|
| `name` | yes (human mode) | Unique target identifier. |
| `enabled` | no | Enable/disable this target. |
| `strategy` | yes | `cargo_path_git`, `command`, or `system_package`. |
| `check_interval_hours` | no | Per-target check interval. |
| `check_timeout_s` | no | Timeout for version checks. |
| `update_timeout_s` | no | Timeout for update execution. |
| `verify_timeout_s` | no | Timeout for post-update verify command. |
| `verify_cmd` | no | Verification command after update. |
| `current_version_pattern` | no | Regex for current version extraction. |
| `required_commands` | no | Additional command prerequisites for env checks. |

### 7.3 `cargo_path_git` strategy fields

| Field | Required | Description |
|---|---|---|
| `repo_path` | yes | Local git repository path. |
| `binary_path` | yes | Installed binary path (for version check). |
| `branch` | no | Preferred branch. Empty means auto-detect/fallback. |
| `upstream_repo` | recommended | Upstream repository URL. |
| `mirror_prefixes` | no | GitHub mirror prefixes. |
| `remote_candidates` | no | Explicit remotes for probe/pull fallback. |
| `probe_remotes` | no | Enable remote probe before update. |
| `probe_timeout_s` | no | Remote probe timeout. |
| `probe_parallelism` | no | Probe concurrency. |
| `probe_cache_ttl_minutes` | no | Probe result cache TTL. |
| `build_commands` | no | Build/install commands (supports templates). |
| `current_version_cmd` | no | Optional custom current version command. |
| `auto_add_safe_directory` | no | Auto add git safe.directory for repo path. |
| `clone_build_fallback` | no | Use temp clone build when local pull path cannot proceed. |
| `pull_rebase_fallback` | no | Optional ff-only -> rebase fallback. |

### 7.4 `command` strategy fields

| Field | Required | Description |
|---|---|---|
| `current_version_cmd` | yes | Command to get current version. |
| `latest_version_cmd` | recommended | Command to get latest version. |
| `update_commands` | yes | Commands to execute update. |
| `latest_version_pattern` | no | Regex for latest version extraction. |
| `current_version_pattern` | no | Regex for current version extraction. |

### 7.5 `system_package` strategy fields

| Field | Required | Description |
|---|---|---|
| `manager` | recommended | Manager id: `apt_get/yum/dnf/pacman/zypper/choco/winget/brew`. |
| `package_name` | recommended | Package identifier; defaults to target `name` when omitted. |
| `require_sudo` | no | Auto prepend sudo for built-in update commands. |
| `sudo_prefix` | no | Custom sudo prefix command, default `sudo`. |
| `current_version_cmd` | no | Override built-in current version command. |
| `latest_version_cmd` | no | Override built-in latest version command. |
| `check_update_cmd` | no | Fallback command for managers where latest version is not directly queryable. |
| `update_commands` | no | Override built-in update command list. |

## 8. Extensibility Examples

### 8.1 Add another software target (command strategy)

```json
{
  "mytool": {
    "enabled": true,
    "strategy": "command",
    "check_interval_hours": 6,
    "current_version_cmd": "mytool --version",
    "latest_version_cmd": "curl -s https://example.com/releases/latest | jq -r .version",
    "latest_version_pattern": "(\\d+\\.\\d+\\.\\d+)",
    "update_commands": ["bash /opt/scripts/update-mytool.sh"],
    "verify_cmd": "mytool --version"
  }
}
```

### 8.2 Template variables

Supported command template variables include (not limited to):

- `{target_name}`
- `{repo_path}`
- `{binary_path}`
- `{branch}`
- `{plugin_data_dir}`
- `{state_path}`
- `{events_path}`

## 9. Stability and Robustness Recommendations

- Keep at least 2-3 mirror prefixes for GitHub-hosted projects.
- Use `/updater env` in CI or after host changes.
- Keep per-target timeout values realistic for your machine/network.
- Use `clone_build_fallback=true` for safer updates on diverged local branches.
- Use `dry_run=true` for workflow rehearsal before production rollout.

## 10. Data and Logs

Plugin runtime data directory:

```text
<ASTRBOT_DATA>/plugin_data/astrbot_plugin_onesync/
```

Key files:

- `state.json`: current target states (versions/check timestamps).
- `events.jsonl`: append-only execution event stream.

## 11. Troubleshooting

### 11.1 `git` reports dubious ownership / safe.directory

- Enable `auto_add_safe_directory` for `cargo_path_git` targets.
- Or run manually:

```bash
git config --global --add safe.directory /path/to/repo
```

### 11.2 Cannot resolve latest version

- Verify remotes are reachable.
- Verify semantic version tags exist (`v1.2.3` style).
- Check mirror probe result and fallback order.

### 11.3 Version extraction fails

- Fix `current_version_pattern` and/or `latest_version_pattern`.
- Test regex against real command output.

### 11.4 Update command fails

- Run `/updater env <target>` to verify runtime dependencies.
- Increase `update_timeout_s` for heavy build/install tasks.
- Check stderr in events/debug logs for exact cause.

### 11.5 WebUI shows `Failed to load config: 404 Not Found`

- Restart service and wait until port is ready:
  - `systemctl restart astrbot.service`
- Verify endpoint availability:
  - `curl -i http://127.0.0.1:8099/api/config`
  - `curl -s http://127.0.0.1:8099/openapi.json | jq -r '.paths | keys[]'`
- If `/api/config` exists in OpenAPI but UI still fails, hard refresh (`Ctrl+F5`) and retry.

## 12. Maintainer Docs

For release workflow, upload metadata, GitHub About, and sync operations, see:

- [Operations and Sync Manual (English)](./OPERATIONS_AND_SYNC_en.md)
- [GitHub About Template (English)](./GITHUB_ABOUT_en.md)
- [操作与同步手册（中文）](./OPERATIONS_AND_SYNC_zh.md)
- [GitHub About 模板（中文）](./GITHUB_ABOUT_zh.md)
