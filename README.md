# astrbot_plugin_onesync

OneSync 是一个面向 AstrBot 的通用可扩展软件更新器插件。

- 支持定时检查、自动更新、手动触发。
- 支持多目标扩展（不仅是 `zeroclaw`）。
- 支持镜像/多远端回退（提高更新稳定性）。
- 支持状态持久化与事件日志，便于排障与审计。

## 快速设置同步时间（最短路径）

同步节奏由两个参数共同决定：

- `poll_interval_minutes`：后台轮询周期（分钟）。
- `targets_json.<目标>.check_interval_hours`：该目标的检查周期（小时，可用小数）。

建议这样设置：

1. 在 AstrBot 插件配置中把 `poll_interval_minutes` 设为 `5`（或 `10`）。
2. 在 `targets_json` 里把 `zeroclaw.check_interval_hours` 设为你想要的频率（例如 `6` 表示 6 小时）。
3. 保存配置后重启 AstrBot（修改 `poll_interval_minutes` 后建议重启）。
4. 用 `/updater status` 查看是否生效。

示例（每 6 小时检查一次）：

```json
{
  "zeroclaw": {
    "enabled": true,
    "strategy": "cargo_path_git",
    "check_interval_hours": 6,
    "repo_path": "/home/jacob/zeroclaw",
    "binary_path": "/root/.cargo/bin/zeroclaw",
    "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
    "mirror_prefixes": ["", "https://gh-proxy.com/", "https://ghfast.top/"],
    "build_commands": ["cargo install --path {repo_path}"],
    "verify_cmd": "{binary_path} --version"
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

- `/updater status`：查看插件状态和目标状态。
- `/updater check [target]`：立即检查版本，不执行更新。
- `/updater run [target]`：立即检查并在有新版本时更新。
- `/updater force [target]`：强制执行更新命令（忽略版本比较）。

`target` 可省略；省略时对所有已配置目标执行。

## 详细安装与配置文档

完整文档见：`docs/INSTALL_AND_CONFIG_zh.md`

包含内容：

- 安装与首次验证
- 同步时间配置原理与场景示例
- 全量配置字段说明（顶层 + 两类策略）
- 可扩展目标配置范式
- 稳定性与鲁棒性建议（镜像、超时、告警）
- 常见故障排查
- 插件上传信息与版本维护流程

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
