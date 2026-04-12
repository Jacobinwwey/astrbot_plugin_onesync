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
- WebUI 现已支持读取与修改插件配置（含 Human/Developer 双模式目标编辑与 `targets_json` 互相同步）。
- 原生支持 `system_package` 策略：`apt_get/yum/dnf/pacman/zypper/choco/winget/brew`。
- v1 新增“Skills管理”资产面板：支持 npx-based Skills 发现、CLI 资产自动发现、兼容性过滤、Deploy Target projection diff 和 Skill 绑定保存。
- Skills 管理链路现已支持 install-unit / collection-group 级运维，而不是只对 leaf skill 做平铺操作。
- WebUI 已支持“一键更新全部聚合”，会统一执行可更新聚合并自动跳过 `manual_only` 边界。
- git-backed skill source 现已支持“受管 checkout 自动补齐”：当叶子 skill 目录不是 git 仓库时，OneSync 会在插件数据目录下自动物化 repo checkout，再执行 git update。

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
- `配置中心`：在 WebUI 内直接修改插件配置、目标模式、软件列表与目标参数。
- `AI 配置助手`：在 WebUI 内生成可直接发送给 AI 的 Prompt（初始化/增量新增/诊断/完整套件）。
- `使用指引`：内置用户流程与开发者流程，并提供文档直达链接。
- `Skills管理`：查看本地软件资产、基于 `npx skills ls` 汇总 Skills、按软件类型筛选可兼容 Skill 并保存绑定。
- 软件列表默认只显示已安装且可调用 Skills 的软件；可在面板中切换显示未安装候选。
- 统一管理面板支持绑定作用域切换（`global/workspace`）与快速选择（全选兼容 / 仅已发现 / 清空选择）。
- `global/workspace` 现已改为分段切换按钮，减少顶部控制区占用。
- 软件速览区支持按 `CLI/GUI/CLAW/OTHER` 过滤并点击卡片快速切换当前软件。
- Skills 面板现已提供 `导入 Source` 向导，可登记 `manual_local` 与 `manual_git` 来源，并支持为 git source 填写可选 `subpath`。
- Deploy Targets 支持展示当前 drift 明细、generated projection diff，并可执行“重建当前投影 / 修复当前目标 / 批量修复全部漂移目标”。
- 右侧可部署 Source package 列表现已直接使用 source-first `source_rows` 真相源，显示与下方 Source / Bundle 视图一致的 freshness、registry、sync 状态，并支持就地 `Sync Source`。
- Source / Bundle 视图与 Deploy Targets 现已支持 `单列卡片 / 双列卡片 / 紧凑列表` 视图切换，并可在面板设置中调整字体、卡片宽度与卡片高度；这些偏好会保存在浏览器本地。
- `健康检查` 现已额外覆盖 `manifest.json / lock.json / sources/*.json / generated/*.json` 与 `skill_bindings` 投影一致性。
- 两个操作均有确认弹窗，防止误触。
- 内置 Debug 日志面板：支持多标签视图（运行/目标/调度/系统）、实时滚动、级别筛选、关键字过滤与一键清空。
- 内置 i18n：WebUI 支持中英文切换（界面文案、按钮、筛选项、日志面板标签同步切换）。

### Skills管理（v1）

配置新增三组字段：

- `software_catalog`：基础软件资产清单（可选手工补充，系统会额外自动发现 PATH 中 CLI）。
- `skill_catalog`：可选手工 skill 清单（`filesystem/hybrid` 模式下参与合并）。
- `skill_bindings`：软件与 skill 绑定关系（支持 `global/workspace` scope）。
- `skill_management_mode`：`npx / filesystem / hybrid`，默认 `npx`。
- `npx_skills_*`：`npx skills ls` 探测命令、范围和超时。
- `auto_discover_cli*`：CLI 自动发现开关、数量上限与包含/排除列表。

WebUI 与 API：

- `GET /api/inventory/overview`：获取最新库存总览（软件行、skill 行、兼容矩阵、绑定摘要、按 `scope` 分组绑定映射、告警）。
- `GET /api/inventory/software`：只读软件资产明细（适合外部脚本快速拉取本机软件状态）。
- `GET /api/inventory/skills`：只读 Skill 资产明细（含发现状态与来源路径）。
- `GET /api/inventory/bindings`：只读绑定明细（含 `binding_map` 与 `binding_map_by_scope`）。
- `POST /api/inventory/scan`：触发重新扫描并刷新 inventory 快照。
- `POST /api/inventory/bindings`：保存绑定；会执行软件-技能兼容性校验。
- `GET /api/skills/overview`：读取当前 source-first overview 快照，包含 `manifest / lock / source_rows / deploy_rows / doctor`。
- `GET /api/skills/install-units/{install_unit_id}`：读取 install unit 明细，包含有效 `update_plan` 与 source 成员。
- `GET /api/skills/collections/{collection_group_id}`：读取 collection group 明细，包含聚合后的 `update_plan`。
- `GET /api/skills/deploy-targets/{target_id}`：读取单个 Deploy Target 明细，附带 `generated_projection.path / exists / payload / diff`。
- `POST /api/skills/import`：显式刷新 inventory + skills 快照，并重建 `manifest / lock / sources / generated`。
- `POST /api/skills/sources/register`：登记新的 source；支持 `manual_local` 路径和带可选 `source_subpath` 的 `manual_git` 仓库。
- `POST /api/skills/sources/{source_id}/sync`：同步单个 source 的上游元数据。
- `POST /api/skills/install-units/{install_unit_id}/sync`：同步 install unit 下全部 source 的上游元数据。
- `POST /api/skills/install-units/{install_unit_id}/update`：执行 install unit 的真实更新命令。
- `POST /api/skills/collections/{collection_group_id}/sync`：同步 collection group 下全部 source 的上游元数据。
- `POST /api/skills/collections/{collection_group_id}/update`：执行 collection group 中所有受支持 install unit 的真实更新命令。
- `POST /api/skills/aggregates/update-all`：批量执行当前所有可执行聚合的更新计划，并返回 executed/skipped/source-sync 分层统计。
- `POST /api/skills/sources/sync-all`：批量同步当前所有可同步 source。
- `POST /api/skills/deploy-targets/{target_id}`：保存当前 target 的 selected sources。
- `POST /api/skills/deploy-targets/{target_id}/reproject`：重建单个 target 的 generated projection，用于消除缓存与落盘状态漂移。
- `POST /api/skills/deploy-targets/repair-all`：按当前 snapshot 批量修复 repairable targets。
- `POST /api/skills/doctor`：运行 runtime/projection 健康检查。

说明：

- v1 资产层是增量能力，不替代现有更新执行链路（`/api/run`、调度器、`/updater` 命令保持不变）。
- 默认模式使用 `npx skills ls --json`（项目级）与 `npx skills ls -g --json`（全局级）构建 Skills 资产。
- npx 模式下会优先按“可统一维护的技能包”聚合展示，而不是逐条展开所有 skill。比如 `ce:*` 会折叠成 `Compound Engineering`，并提示统一维护命令。
- `filesystem/hybrid` 模式下，仍支持从 `skill_roots` 扫描 `SKILL.md` 并与手工 `skill_catalog` 合并去重。
- `GET /api/skills/*` 当前采用 cache-first 读取，不会在每次页面访问时强制重写 `generated/*.json`；如需刷新真相源，请显式调用 `POST /api/skills/import` 或 target 级 `reproject`。
- 当前来源归因已可区分 `registry_package / skill_lock_source / documented_source_repo / catalog_source_repo / community_source_repo / local_custom_skill`；例如用户自建的 `doc` skill 会被归类为 `local_custom_skill`。
- `Sync Source` 与 `Update Install Unit` 不是同一件事：前者负责刷新 source 元数据，后者负责执行 install unit / collection group 的真实更新计划。
- git-backed `skill_lock` / repo 来源现在不再强依赖用户手工准备本地 git repo。若叶子 skill 目录不是 git worktree，OneSync 会在 `plugin_data/.../skills/git_repos/` 下创建受管 checkout，并让 sync/update 都走这份 checkout。
- 当前“更新功能”已从“部分可用”推进到“核心路径可用”：
  - npm / registry-backed 聚合可更新
  - git-backed `skill_lock` 聚合现已可自动补齐 checkout 后更新
  - repo-metadata-backed 聚合可执行 source sync fallback
  - `local_custom` / `synthetic_single` / `derived` 等无真实包边界来源会被显式收敛到 `manual_only`
- 维护者可参考 [Skills 更新能力现状（中文）](./docs/SKILLS_UPDATE_STATUS_zh.md) 与 [Skills Update Status (English)](./docs/SKILLS_UPDATE_STATUS_en.md) 了解完整支持矩阵。

### 最新进展（2026-04-12）

- 8099 live 运维台已部署“更新全部聚合”入口，并完成真实执行验证。
- `find-skills` 与 `frontend-design` 这两类原本因“叶子目录不是 git repo”而失败的 `skill_lock` 聚合，现已能自动补齐受管 checkout 并更新成功。
- `synthetic_single:*` 这类没有真实包边界的 npx leaf 不再伪装成可更新聚合，而是稳定落入 `manual_only`。
- 当前 live `POST /api/skills/aggregates/update-all` 最近一次验证结果：
  - `candidate_install_unit_total = 20`
  - `executed_install_unit_total = 14`
  - `command_install_unit_total = 3`
  - `source_sync_install_unit_total = 11`
  - `skipped_install_unit_total = 6`
  - `success_count = 8`
  - `failure_count = 2`
  - `precheck_failure_count = 0`

### Stitch MCP 基线脚本（前端校正）

仓库提供 `scripts/stitch_mcp_runner.py`，用于在 Stitch 链路不稳定时做“单次生成 + 轮询读取 + 资源下载”。

快速示例：

```bash
# 只读：列出项目
python3 scripts/stitch_mcp_runner.py projects --limit 10

# 基线流程：发起一次 variants 并轮询
python3 scripts/stitch_mcp_runner.py baseline \
  --project-id 13653968230990294035 \
  --mode variants \
  --base-screen-id 3ed0716291bf49c4ac5ff29285fe9a2d \
  --prompt "Refine unified software+skills dashboard hierarchy" \
  --download new
```

更多参数与稳定性策略见：
- [Stitch WebUI 基线记录](./docs/plans/stitch-webui-baseline-2026-04-06.md)
- [Skills 管理参考仓库对比分析](./docs/plans/skills-management-reference-comparative-analysis-2026-04-06.md)
- [Skills 管理下一步实施计划](./docs/plans/skills-management-next-step-implementation-plan-2026-04-06.md)

### WebUI 内嵌 AI 助手与使用指引

入口方式：

- 顶部按钮：`AI 配置助手`、`使用指引`
- 快捷键：
  - `Alt+A` 打开 AI 助手
  - `Alt+H` 打开使用指引
  - `Esc` 关闭当前最上层弹窗（AI/指引/配置中心）

用户流程（推荐）：

1. 点击 `AI 配置助手`，先点 `用户预设`。
2. 如已有配置，先点 `从当前配置自动填充`，自动回填模式、轮询参数和一个软件目标字段。
3. 可选：打开 `自动生成: 开` 开关，让“自动填充”完成后直接生成 Prompt。
4. 选择场景（初始化/增量新增/诊断/完整套件）并补齐必要参数。
5. 点击 `生成 Prompt`，再点击 `复制输出` 发送给 AI。
6. 拿到 AI 返回的 JSON/脚本后，在 `配置中心` 或 API 下发。
7. 在 `最近执行任务` 与 `Debug 日志` 中验证执行结果。

开发者流程（推荐）：

1. 打开 `AI 配置助手`，点击 `开发者预设`。
2. 选择 `完整套件` 生成多场景 Prompt（初始化 + 增量 + 诊断）。
3. 将输出给 AI 生成 `targets_json` 或 API 一键脚本。
4. 在配置中心切到 `developer` 模式，粘贴配置后保存。
5. 执行 `/updater env`、`/updater check` 做环境与策略验收。

### WebUI 常见问题：加载配置失败（404）

如果看到 `加载配置失败: 404 Not Found`，通常是运行中的插件实例还在使用旧版本前端/后端路由。

建议按以下顺序处理：

1. 重启 AstrBot 服务：
   `systemctl restart astrbot.service`
2. 确认访问的是 OneSync `web_admin_url`（默认 `http://127.0.0.1:8099`），而不是 AstrBot Dashboard 地址。
3. 浏览器强制刷新页面（`Ctrl+F5`）。
4. 在主机上验证接口：
   - `curl -i http://127.0.0.1:8099/api/config`
   - `curl -s http://127.0.0.1:8099/openapi.json | jq -r '.paths | keys[]'`

## AI 一键配置 Prompt（复制即用）

如果你不想手动填大段参数，先用内置生成器自动产出 Prompt：

```bash
# 交互式：按提示回答少量问题（推荐）
python3 scripts/onesync_prompt_builder.py --interactive --lang zh --scenario suite --output /tmp/onesync_prompt_zh.txt

# 非交互：直接按参数生成（示例：Ubuntu + system_package）
python3 scripts/onesync_prompt_builder.py \
  --lang zh \
  --scenario suite \
  --os-profile ubuntu \
  --software-name curl \
  --strategy system_package \
  --output /tmp/onesync_prompt_zh.txt
```

然后把 `/tmp/onesync_prompt_zh.txt` 内容整体发给 AI，即可得到可执行配置结果。

下面这段 Prompt 可以直接发给 AI（ChatGPT/Codex/Claude 等），用于“一次生成 + 一次下发 + 一次验证” OneSync 配置。

```text
你是 OneSync（astrbot_plugin_onesync）配置执行助手。目标：为我生成可直接提交到 OneSync WebUI API 的配置，并给出一键执行命令。

请严格执行：
1) 先根据我的输入，生成一个合法 JSON 文件内容，格式必须是：
   {
     "config": {
       ...OneSync 配置...
     }
   }
2) 再输出一段 bash 命令，完成：
   - 写入 onesync_config.json
   - （可选）如果 WEBUI_PASSWORD 非空，先 POST /api/login 获取 token
   - POST /api/config 下发配置
   - GET /api/config 与 /api/overview 做结果验证
3) 若有缺失字段，请使用稳妥默认值并在“假设说明”里列出。
4) 输出必须包含且仅包含以下 3 个部分：
   - `JSON_PAYLOAD`
   - `BASH_ONE_CLICK`
   - `ASSUMPTIONS`
5) 任何 JSON 不允许注释、尾逗号、伪代码。

我的输入如下（请按此生成）：
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

完整 Prompt 套件（初始化、增量新增、诊断修复）见安装配置手册：
- [安装与配置手册（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)

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
