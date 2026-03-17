# astrbot_plugin_onesync

OneSync is an extensible software updater plugin for AstrBot.

It supports:
- Periodic checks and optional automatic updates.
- Pluggable update strategies (currently `cargo_path_git` and `command`).
- Retry/fallback style remote source selection via `remote_candidates` and `mirror_prefixes`.
- Persistent state and event logs under `data/plugin_data/astrbot_plugin_onesync/`.
- Admin commands for manual check/update/force-update.

## Commands

- `/updater status`: show plugin status and each target's last check result.
- `/updater check [target]`: run immediate version check only.
- `/updater run [target]`: run check and update when needed.
- `/updater force [target]`: force update command execution.

`target` is optional. If omitted, all configured targets are processed.

## Strategy Overview

### 1) `cargo_path_git`

Recommended for locally cloned Rust projects installed via `cargo install --path`.

Core fields:
- `repo_path`
- `binary_path`
- `upstream_repo` and/or `remote_candidates`
- `mirror_prefixes`
- `build_commands`

How it works:
1. Read current version from binary command.
2. Resolve latest semantic version from remote tags (mirror fallback supported).
3. Pull latest code with fast-forward only.
4. Rebuild/reinstall using configured build commands.
5. Re-check current version.

### 2) `command`

Generic strategy for arbitrary software.

Core fields:
- `current_version_cmd`
- `latest_version_cmd`
- `update_commands`
- optional regex fields `current_version_pattern` / `latest_version_pattern`

## Add Another Software Target

Edit `targets_json` and add one more target object. Example:

```json
{
  "mytool": {
    "enabled": true,
    "strategy": "command",
    "check_interval_hours": 6,
    "current_version_cmd": "/usr/local/bin/mytool --version",
    "current_version_pattern": "(\\d+\\.\\d+\\.\\d+)",
    "latest_version_cmd": "curl -fsSL https://example.com/mytool/latest.txt",
    "latest_version_pattern": "(\\d+\\.\\d+\\.\\d+)",
    "update_commands": [
      "curl -fsSL https://example.com/mytool/install.sh | bash"
    ],
    "verify_cmd": "/usr/local/bin/mytool --version",
    "check_timeout_s": 120,
    "update_timeout_s": 900,
    "verify_timeout_s": 120
  }
}
```

## Data Files

- State: `data/plugin_data/astrbot_plugin_onesync/state.json`
- Event log: `data/plugin_data/astrbot_plugin_onesync/events.jsonl`

## Release Workflow

Version is managed in `metadata.yaml` and changelog is tracked in `CHANGELOG.md`.

Quick release:

```bash
cd /root/astrbot/data/plugins/astrbot_plugin_onesync
./scripts/release.sh v0.1.1
```

What the script does:
1. Validates version format (`vMAJOR.MINOR.PATCH`).
2. Updates `metadata.yaml` `version`.
3. Appends a changelog section when missing.
4. Commits release changes.
5. Creates an annotated git tag.
6. Pushes branch and tag to `origin`.

Dry run for local check (no push):

```bash
NO_PUSH=1 ./scripts/release.sh v0.1.1
```
