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
- Recent job panel and real-time debug logs.
- UI i18n toggle (Chinese/English).

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
- [GitHub About Template (English)](./docs/GITHUB_ABOUT_en.md)
- [GitHub About 模板（中文）](./docs/GITHUB_ABOUT_zh.md)
