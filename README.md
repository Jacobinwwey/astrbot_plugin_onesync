# astrbot_plugin_onesync

> 语言 / Language: [中文](./README.md) | [English](./README_en.md)

OneSync 是一个面向 AstrBot 的通用可扩展软件更新器插件。

- 支持定时检查、自动更新、手动触发。
- 支持多目标扩展（不仅是 `zeroclaw`）。
- 支持镜像/多远端回退（提高更新稳定性）。
- 支持更新前自动探测远端质量（连通性与延迟）并择优使用。
- 支持状态持久化与事件日志，便于排障与审计。
- 设置页支持“软件与版本总览（自动生成滚动列表）”，便于用户快速查看。
- 支持内置 WebUI 管理端（无需改 AstrBot Dashboard 源码），提供“立即更新（当前筛选）/立即全部更新”并带确认弹窗。

## 配置模式（重要）

OneSync 支持两种配置模式：

- `human`（默认）：面向用户的简洁配置，只保留常用基础项。
- `developer`：直接编辑 `targets_json` 的高级模式（镜像、超时、正则等）。

通过配置项 `target_config_mode` 切换。

## 软件总览（运维视图）

`software_overview` 是插件自动生成的软件版本总览，只读展示，不支持手动编辑。

为适配大规模运维场景，配置界面提供了多种切换能力：

1. 视图模式切换：
   - `表格`：适合高密度、多列对比（带粘性表头和滚动区）。
   - `卡片`：适合快速浏览单个软件状态。
   - `紧凑列表`：适合一次查看更多目标。
2. 主题模式切换：
   - `跟随系统`
   - `浅色`
   - `深色柔和`
   - `深色蓝灰`
   - `海军蓝`
   - `暖灰夜`
   - `高对比`
3. 密度模式切换：
   - `舒适`
   - `紧凑`
   - `极限紧凑`
4. 运维筛选能力：
   - 支持按关键字搜索（软件名/版本/策略）。
   - 支持按状态筛选（已最新/可更新/待检查/已停用）。

以上偏好会在浏览器本地保存，下次打开配置页会自动恢复。

## 内置 WebUI（推荐）

当你希望不修改 AstrBot Dashboard 源码但仍获得完整前端交互时，可启用 OneSync 内置 WebUI。

1. 在插件配置中打开 `web_admin.enabled=true`。
2. 设定 `web_admin.host` 与 `web_admin.port`（默认 `127.0.0.1:8099`）。
3. （可选）设置 `web_admin.password` 开启 API 登录保护。
4. 重启/热重载插件后，查看配置项 `web_admin_url`，浏览器打开即可。

WebUI 关键能力：

- 按关键字和状态筛选软件。
- `立即更新（当前筛选）`：只更新当前筛选结果中的启用目标。
- `立即全部更新（全部纳管）`：更新所有启用目标。
- 两个操作均有确认弹窗，防止误触。
- 内置 Debug 日志面板：支持多标签视图（运行/目标/调度/系统）、实时滚动、级别筛选、关键字过滤与一键清空。
- 内置 i18n：WebUI 支持中英文切换（界面文案、按钮、筛选项、日志面板标签同步切换）。

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
   - 基础：仓库/二进制路径或版本命令/更新命令。
5. 保存配置后，执行 `/updater check <name>` 验证目标可用。

说明：

- 条目数量不受固定槽位限制，可持续新增。
- 已存在目标会在列表里直接显示，可逐条修改或删除。
- 首次切换到 `human` 模式时，插件会自动把已有 `targets_json` 目标迁移到 `human_targets` 以便可视化管理。
- 镜像策略、超时、正则等高级项请切换 `developer` 模式配置。

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

- [安装与配置手册（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)
- [操作与同步手册（中文）](./docs/OPERATIONS_AND_SYNC_zh.md)
- [Operations and Sync Manual (English)](./docs/OPERATIONS_AND_SYNC_en.md)
