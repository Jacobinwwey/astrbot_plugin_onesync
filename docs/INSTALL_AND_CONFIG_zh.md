# OneSync 安装与配置指南（中文）

本文档面向 OneSync 最终使用者和运维者，重点覆盖：

- 如何安装并验证插件可用。
- 如何快速设置同步时间（核心诉求）。
- 如何扩展到多个软件目标并提升更新稳定性。
- 如何进行插件上传和版本维护。

## 1. 插件定位

`astrbot_plugin_onesync` 是一个 AstrBot 插件，负责按计划检查并更新软件。

核心特性：

- 支持多个目标软件（`targets_json` 中按名称扩展）。
- 支持两种更新策略：`cargo_path_git` 与 `command`。
- 支持自动更新、手动检查、强制更新。
- 支持镜像回退、多远端候选，提高更新可用性。
- 支持状态持久化与事件日志，便于排障与审计。

## 2. 环境要求

- AstrBot 版本：`>=4.16`（见 `metadata.yaml`）。
- 运行用户需具备目标软件更新所需权限。
  - 例如 `cargo install --path` 需要可执行 `cargo` 且有写入安装路径权限。
- 若使用 `cargo_path_git` 策略，需要：
  - 本地已有 git 仓库目录（如 `/home/jacob/zeroclaw`）。
  - 可访问上游仓库或镜像。

## 3. 安装

### 3.1 手动安装（推荐）

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
```

目录结构示例：

```text
<ASTRBOT_ROOT>/data/plugins/
└── astrbot_plugin_onesync/
    ├── main.py
    ├── updater_core.py
    ├── metadata.yaml
    ├── _conf_schema.json
    └── docs/INSTALL_AND_CONFIG_zh.md
```

### 3.2 重启 AstrBot

若 AstrBot 以 systemd 运行：

```bash
systemctl restart astrbot.service
```

### 3.3 首次验证

管理员在聊天里执行：

```text
/updater status
```

正常输出应包含：

- `Software Updater Status`
- `targets=...`
- 每个目标的 `strategy/interval_h/last_checked/status`

## 4. 快速设置同步时间（重点）

OneSync 的“同步时间”不是单一参数，而是由以下两层控制：

- `poll_interval_minutes`：后台轮询周期（分钟，最小 1）。
- `check_interval_hours`：每个目标自己的检查间隔（小时，支持小数）。

实际效果：

- 目标在“到期”后，会在下一次轮询时执行。
- 因此时间精度受 `poll_interval_minutes` 影响。

### 4.1 3 分钟配置法（zeroclaw）

1. 插件配置页设置：`poll_interval_minutes = 5`。
2. 在 `targets_json` 把 `zeroclaw.check_interval_hours` 改为目标值。
3. 保存配置，建议重启 AstrBot（尤其改了 `poll_interval_minutes` 时）。
4. 执行 `/updater status` 验证。

示例：每 6 小时检查一次。

```json
{
  "zeroclaw": {
    "enabled": true,
    "strategy": "cargo_path_git",
    "check_interval_hours": 6,
    "repo_path": "/home/jacob/zeroclaw",
    "binary_path": "/root/.cargo/bin/zeroclaw",
    "branch": "",
    "auto_add_safe_directory": true,
    "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
    "mirror_prefixes": ["", "https://gh-proxy.com/", "https://ghfast.top/"],
    "remote_candidates": [],
    "build_commands": ["cargo install --path {repo_path}"],
    "verify_cmd": "{binary_path} --version",
    "check_timeout_s": 120,
    "update_timeout_s": 1800,
    "verify_timeout_s": 120,
    "current_version_pattern": "(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.\\-]+)?)"
  }
}
```

### 4.2 常见频率换算

- 每 1 小时：`check_interval_hours = 1`
- 每 30 分钟：`check_interval_hours = 0.5`
- 每 15 分钟：`check_interval_hours = 0.25`

建议同时把 `poll_interval_minutes` 调到 `5` 或更小于期望精度的值。

## 5. 命令使用

仅管理员可用。

- `/updater status`
  - 查看全局状态、定时参数和各目标最近状态。
- `/updater check [target]`
  - 立即检查版本，不执行更新。
- `/updater run [target]`
  - 立即检查并在需要时更新。
- `/updater force [target]`
  - 强制执行更新命令，忽略版本比较。

示例：

```text
/updater check zeroclaw
/updater run zeroclaw
/updater force zeroclaw
```

## 6. 配置总览

### 6.1 顶层配置项

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 是否启用插件。 |
| `poll_interval_minutes` | int | `30` | 后台轮询间隔（分钟）。 |
| `default_check_interval_hours` | float | `24` | 目标未设置 `check_interval_hours` 时的默认值。 |
| `auto_update_on_schedule` | bool | `true` | 定时发现新版本后是否自动更新。 |
| `notify_admin_on_schedule` | bool | `true` | 定时任务后是否通知管理员。 |
| `notify_on_schedule_noop` | bool | `false` | 无更新/无异常时是否也通知。 |
| `dry_run` | bool | `false` | 演练模式，不真正执行更新命令。 |
| `admin_sid_list` | list | `[]` | 接收定时通知的管理员 SID 列表。 |
| `targets_json` | text(json) | 内置 zeroclaw 示例 | 多目标配置入口。 |

### 6.2 `targets_json` 通用字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 是否启用该目标。 |
| `strategy` | string | 更新策略：`cargo_path_git` 或 `command`。 |
| `check_interval_hours` | float | 该目标检查周期（小时，`<=0` 视为不参与定时）。 |
| `check_timeout_s` | int | 检查相关命令超时时间。 |
| `update_timeout_s` | int | 更新相关命令超时时间。 |
| `verify_timeout_s` | int | 验证命令超时时间。 |
| `verify_cmd` | string | 更新后验证命令，可选。 |
| `current_version_pattern` | string | 当前版本提取正则，可选。 |

### 6.3 `cargo_path_git` 策略字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `repo_path` | 是 | 本地 git 仓库路径。 |
| `binary_path` | 是 | 可执行文件路径。 |
| `upstream_repo` | 建议 | 上游仓库 URL（与镜像前缀组合）。 |
| `mirror_prefixes` | 否 | 镜像前缀列表，如 `https://gh-proxy.com/`。 |
| `remote_candidates` | 否 | 远端候选 URL 列表。 |
| `branch` | 否 | 分支；不填则自动检测当前分支。 |
| `auto_add_safe_directory` | 否 | 自动执行 git safe.directory 配置。 |
| `build_commands` | 否 | 更新后构建命令，默认 `cargo install --path {repo_path}`。 |
| `current_version_cmd` | 否 | 默认 `{binary_path} --version`。 |

### 6.4 `command` 策略字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `current_version_cmd` | 是 | 获取当前版本命令。 |
| `latest_version_cmd` | 建议 | 获取最新版本命令。 |
| `update_commands` | 更新时必填 | 执行更新的命令列表。 |
| `latest_version_pattern` | 否 | 提取最新版本的正则。 |
| `current_version_pattern` | 否 | 提取当前版本的正则。 |

## 7. 可扩展配置示例

### 7.1 增加第二个软件（command 策略）

```json
{
  "zeroclaw": {
    "enabled": true,
    "strategy": "cargo_path_git",
    "check_interval_hours": 6,
    "repo_path": "/home/jacob/zeroclaw",
    "binary_path": "/root/.cargo/bin/zeroclaw",
    "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
    "mirror_prefixes": ["", "https://gh-proxy.com/"],
    "build_commands": ["cargo install --path {repo_path}"]
  },
  "mytool": {
    "enabled": true,
    "strategy": "command",
    "check_interval_hours": 12,
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

### 7.2 命令模板变量

更新命令支持 `{变量}` 模板，来源包括：

- 目标配置中的所有字段（例如 `{repo_path}`、`{binary_path}`）。
- 运行时字段：`{target_name}`、`{plugin_name}`、`{plugin_data_dir}`、`{state_path}`、`{events_path}`。

## 8. 稳定性与鲁棒性建议

- 对 GitHub 类源使用 `mirror_prefixes` + `remote_candidates` 双保险。
- 把 `check_timeout_s`、`update_timeout_s` 调整到符合目标软件体量。
- 给关键目标配置 `verify_cmd`，避免“更新命令成功但实际不可用”。
- 使用 `admin_sid_list` 接收失败告警，建议开启 `notify_admin_on_schedule`。
- 首次上线可先开 `dry_run=true` 做流程演练，确认无误后再关闭。

## 9. 数据与日志

运行数据目录：

- `data/plugin_data/astrbot_plugin_onesync/state.json`
- `data/plugin_data/astrbot_plugin_onesync/events.jsonl`

建议定期备份这两个文件用于审计与问题复盘。

## 10. 常见问题排查

### 10.1 `git` 提示 dubious ownership / safe.directory

- 保持 `auto_add_safe_directory: true`（默认已开启）。
- 或手动执行：

```bash
git config --global --add safe.directory <repo_path>
```

### 10.2 无法获取最新版本

- 检查目标仓库是否存在语义化版本标签（如 `v1.2.3`）。
- 检查网络连通性并配置可用镜像前缀。
- 必要时在 `remote_candidates` 填入多个候选地址。

### 10.3 版本提取失败

- 调整 `current_version_pattern` / `latest_version_pattern` 正则。
- 先手工执行命令查看原始输出，再写正则。

### 10.4 更新命令执行失败

- 检查运行用户权限。
- 检查 `update_timeout_s` 是否过短。
- 在 shell 里单独执行 `update_commands` 验证。

## 11. 插件上传信息

平台上传时可直接使用以下信息：

- `[Plugin]`：`astrbot_plugin_onesync`

```json
{
  "name": "astrbot_plugin_onesync",
  "display_name": "OneSync",
  "desc": "通用可扩展的软件更新器插件，支持定时检查、自动更新、镜像回退与状态追踪。",
  "author": "Jacobinwwey",
  "repo": "https://github.com/Jacobinwwey/astrbot_plugin_onesync",
  "tags": ["updater", "automation", "devops", "zeroclaw", "astrbot"],
  "social_link": "https://github.com/Jacobinwwey"
}
```

对应文件：`plugin_upload_info.json`。

## 12. 版本维护

### 12.1 推荐流程

```bash
cd /root/astrbot/data/plugins/astrbot_plugin_onesync
./scripts/release.sh v0.1.1
```

该脚本会自动：

- 更新 `metadata.yaml` 版本号。
- 若缺失则补充 `CHANGELOG.md` 对应版本段。
- 执行 git commit、tag、push。

### 12.2 仅本地演练

```bash
NO_PUSH=1 ./scripts/release.sh v0.1.1
```

### 12.3 建议的版本策略

- 功能新增：`MINOR` 递增（如 `v0.2.0`）。
- 兼容性修复：`PATCH` 递增（如 `v0.1.1`）。
- 每次发布同步更新 `CHANGELOG.md`，保持可追溯。
