# astrbot_plugin_onesync

OneSync 是一个面向 AstrBot 的通用可扩展软件更新器插件。

- 支持定时检查、自动更新、手动触发。
- 支持多目标扩展（不仅是 `zeroclaw`）。
- 支持镜像/多远端回退（提高更新稳定性）。
- 支持更新前自动探测远端质量（连通性与延迟）并择优使用。
- 支持状态持久化与事件日志，便于排障与审计。
- 设置页支持“软件与版本总览（自动生成）”，便于用户快速查看。

## 配置模式（重要）

OneSync 支持两种配置模式：

- `human`（默认）：面向用户的简洁配置，只保留常用基础项。
- `developer`：直接编辑 `targets_json` 的高级模式（镜像、超时、正则等）。

通过配置项 `target_config_mode` 切换。

## 快速设置同步时间（最短路径）

同步节奏由两个参数共同决定：

- `poll_interval_minutes`：后台轮询周期（分钟）。
- `check_interval_hours`：每个软件目标自己的检查周期（小时，可用小数）。

推荐设置：

1. 把 `poll_interval_minutes` 设为 `5`（或 `10`）。
2. 在目标配置里把 `check_interval_hours` 设为期望频率（例如 `6` 表示每 6 小时）。
3. 保存后重启 AstrBot（修改 `poll_interval_minutes` 后建议重启）。
4. 发送 `/updater status` 验证。
5. 发送 `/updater env <name>` 做依赖环境检测（命令可用性与版本）。

## 新增软件配置指南（人类方案）

适用场景：运维/普通用户在 WebUI 手工配置。

1. 在插件配置页把 `target_config_mode` 设为 `human`。
2. 进入 `软件目标列表（human_targets）`。
3. 点击“添加条目”，选择模板：
   - `Cargo/Git 软件`
   - `命令型软件`
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
- `/updater env [target]`：检测目标依赖环境，显示命令路径与版本信息。

`target` 可省略；省略时对所有已配置目标执行。

## 文档导航

- [安装与配置手册（用户）](docs/INSTALL_AND_CONFIG_zh.md)
