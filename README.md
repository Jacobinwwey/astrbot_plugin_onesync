# astrbot_plugin_onesync

OneSync 是一个面向 AstrBot 的通用可扩展软件更新器插件。

- 支持定时检查、自动更新、手动触发。
- 支持多目标扩展（不仅是 `zeroclaw`）。
- 支持镜像/多远端回退（提高更新稳定性）。
- 支持更新前自动探测远端质量（连通性与延迟）并择优使用。
- 支持状态持久化与事件日志，便于排障与审计。

## 配置模式（重要）

OneSync 现在支持两种配置模式：

- `human`（默认）：可视化“软件目标列表”，支持无限新增条目。
  - 前端通过 `template_list` 渲染，每个软件一张配置卡片。
  - 适合人类交互配置。
- `developer`：`targets_json` 高级模式。
  - 直接编辑 JSON，适合 AI/脚本批量生成配置。

通过配置项 `target_config_mode` 切换。

## 快速设置同步时间（最短路径）

同步节奏由两个参数共同决定：

- `poll_interval_minutes`：后台轮询周期（分钟）。
- `check_interval_hours`：每个软件目标自己的检查周期（小时，可用小数）。

推荐设置：

1. 把 `poll_interval_minutes` 设为 `5`（或 `10`）。
2. 在目标配置里把 `check_interval_hours` 设为期望频率（如 `6` 表示每 6 小时）。
3. 保存后重启 AstrBot（修改 `poll_interval_minutes` 后建议重启）。
4. 发送 `/updater status` 验证。

## 新增软件配置指南（人类方案）

适用场景：运维/普通用户在 WebUI 手工配置。

1. 在插件配置页把 `target_config_mode` 设为 `human`。
2. 进入 `软件目标列表（human_targets）`。
3. 点击“添加条目”，选择模板：
   - `Cargo/Git 软件`：本地 git 仓库 + `cargo install --path` 类型。
   - `命令型软件`：通过命令读版本 + 执行更新脚本类型。
4. 填写条目参数：
   - 必填：`name`（唯一名称）。
   - 调度：`check_interval_hours`。
   - 稳定性：`append_default_mirror_prefixes`、`probe_remotes`、`probe_timeout_s`、`probe_parallelism`、`probe_cache_ttl_minutes`。
5. 保存配置后，执行 `/updater check <name>` 验证目标可用。

说明：

- 条目数量不受固定槽位限制，可持续新增。
- 已存在目标会在列表里直接显示，可逐条修改或删除。
- 首次切换到 `human` 模式时，插件会自动把已有 `targets_json` 目标迁移到 `human_targets` 以便可视化管理。

## 新增软件配置指南（AI/开发者方案）

适用场景：让 AI 生成配置、或你批量维护多目标。

1. 把 `target_config_mode` 设为 `developer`。
2. 在 `targets_json` 中粘贴完整 JSON。
3. 保存后执行 `/updater check` 或 `/updater run` 验证。

建议给 AI 的提示词模板：

```text
你是 OneSync 配置助手。请输出合法 JSON（不要 Markdown），目标用于 astrbot_plugin_onesync 的 targets_json。
要求：
1) 保留已有目标，不覆盖。
2) 新增目标名为 <TARGET_NAME>。
3) 根据 <STRATEGY=command|cargo_path_git> 生成最小可用配置。
4) 填写 check_interval_hours、超时、verify_cmd。
5) 若是 GitHub 源，加入 mirror_prefixes 和 probe_remotes 相关字段。
```

`developer` 示例（简化）：

```json
{
  "zeroclaw": {
    "enabled": true,
    "strategy": "cargo_path_git",
    "check_interval_hours": 12,
    "repo_path": "/home/jacob/zeroclaw",
    "binary_path": "/root/.cargo/bin/zeroclaw",
    "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
    "mirror_prefixes": [
      "",
      "https://edgeone.gh-proxy.com/",
      "https://hk.gh-proxy.com/",
      "https://gh-proxy.com/",
      "https://gh.llkk.cc/",
      "https://ghfast.top/"
    ],
    "probe_remotes": true,
    "probe_timeout_s": 15,
    "probe_parallelism": 4,
    "probe_cache_ttl_minutes": 30,
    "build_commands": ["cargo install --path {repo_path}"],
    "verify_cmd": "{binary_path} --version",
    "check_timeout_s": 120,
    "update_timeout_s": 1800,
    "verify_timeout_s": 120,
    "current_version_pattern": "(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.\\-]+)?)"
  },
  "mytool": {
    "enabled": true,
    "strategy": "command",
    "check_interval_hours": 6,
    "current_version_cmd": "/usr/local/bin/mytool --version",
    "current_version_pattern": "(\\d+\\.\\d+\\.\\d+)",
    "latest_version_cmd": "curl -fsSL https://example.com/mytool/latest.txt",
    "latest_version_pattern": "(\\d+\\.\\d+\\.\\d+)",
    "update_commands": ["curl -fsSL https://example.com/mytool/install.sh | bash"],
    "verify_cmd": "/usr/local/bin/mytool --version",
    "check_timeout_s": 120,
    "update_timeout_s": 900,
    "verify_timeout_s": 120
  }
}
```

## 安装

推荐安装路径：`<ASTRBOT_ROOT>/data/plugins/astrbot_plugin_onesync`

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
```

如果 AstrBot 以服务方式运行：

```bash
systemctl restart astrbot.service
```

验证：

- 管理员发送 `/updater status`。
- 出现 `Software Updater Status` 且目标列表正常，即插件加载成功。

## 管理命令

- `/updater status`：查看插件状态和目标状态（含最近一次 `best_remote`）。
- `/updater check [target]`：立即检查版本，不执行更新。
- `/updater run [target]`：立即检查并在有新版本时更新。
- `/updater force [target]`：强制执行更新命令（忽略版本比较）。

`target` 可省略；省略时对所有已配置目标执行。

## 详细安装与配置文档

完整文档见：`docs/INSTALL_AND_CONFIG_zh.md`

## GitHub About 配置

可直接复制到 GitHub 仓库 `About` 的文案见：

- `docs/GITHUB_ABOUT.md`

## 插件上传信息

上传平台可直接使用 `plugin_upload_info.json`，关键字段如下：

- `[Plugin]`：`astrbot_plugin_onesync`
- JSON：

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

## 版本维护

版本由 `metadata.yaml` 和 `CHANGELOG.md` 共同维护。

快速发版：

```bash
cd /root/astrbot/data/plugins/astrbot_plugin_onesync
./scripts/release.sh v0.1.1
```

本地演练（不推送）：

```bash
NO_PUSH=1 ./scripts/release.sh v0.1.1
```
