# astrbot_plugin_onesync

> 语言 / Language: [中文](./README.md) | [English](./README_en.md)

<div align="center">
  <img src="./logo_256.png" alt="OneSync Logo" width="132">
</div>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.2.3-2563eb" alt="version v0.2.3">
  <img src="https://img.shields.io/badge/AstrBot-%3E%3D4.16-16a34a" alt="AstrBot >=4.16">
  <img src="https://img.shields.io/badge/WebUI-127.0.0.1%3A8099-f59e0b" alt="WebUI 127.0.0.1:8099">
  <img src="https://img.shields.io/badge/Skills-aggregate--first-7c3aed" alt="aggregate-first skills">
</p>

OneSync 把 AstrBot 环境里的软件更新和 Skills 运维收进同一个控制面。

它解决的是很实际的一类问题：你手上不止一个软件目标，不想靠散落脚本和临时命令去维护，也不想为了一个运维台再去改 AstrBot Dashboard 源码。于是 OneSync 给出一条完整链路：检查、更新、验证、审计，再加上一个独立 WebUI。

## 快速导航

| 现在要做什么 | 入口 |
| --- | --- |
| 先判断项目是不是适合你 | [核心特色](#核心特色) / [适用场景](#适用场景) |
| 先把插件装起来 | [快速开始](#快速开始) |
| 想直接让 AI 帮你生成配置 | [Prompt 模板](#prompt-模板) |
| 想看常用命令 | [常用命令](#常用命令) |
| 想快速理解 WebUI | [WebUI 亮点](#webui-亮点) |
| 想看 Skills 管理思路 | [Skills 管理亮点](#skills-管理亮点) |
| 遇到常见问题 | [常见问题](#常见问题) |

| 用户安装 | Prompt 套件 | 运维发布 | 开发扩展 | 接口参考 | 状态/路线 |
| --- | --- | --- | --- | --- | --- |
| [安装与配置（中文）](./docs/INSTALL_AND_CONFIG_zh.md)<br>[Installation & Config (EN)](./docs/INSTALL_AND_CONFIG_en.md) | [安装文档中的完整 Prompt 套件](./docs/INSTALL_AND_CONFIG_zh.md#53-ai-一键配置-prompt-套件推荐)<br>[Prompt suite (EN)](./docs/INSTALL_AND_CONFIG_en.md#53-ai-one-click-prompt-suite-recommended) | [运维与发布（中文）](./docs/OPERATIONS_AND_SYNC_zh.md)<br>[Ops & Release (EN)](./docs/OPERATIONS_AND_SYNC_en.md) | [开发指南（中文）](./docs/DEVELOPER_GUIDE_zh.md)<br>[Developer Guide (EN)](./docs/DEVELOPER_GUIDE_en.md) | [接口参考（中文）](./docs/API_REFERENCE_zh.md)<br>[API Reference (EN)](./docs/API_REFERENCE_en.md) | [Skills 状态（中文）](./docs/SKILLS_UPDATE_STATUS_zh.md)<br>[Skills Status (EN)](./docs/SKILLS_UPDATE_STATUS_en.md) |

## 核心特色

### 1. 软件更新不是单点命令，而是一条完整链路

- 支持定时检查、手动检查、手动更新、强制更新。
- 支持多目标软件并行维护，不局限于单一工具。
- 支持 `cargo_path_git`、`command`、`system_package` 三类主更新策略。
- 支持更新后验证、状态持久化、事件日志与审计回放。

### 2. 内置独立 WebUI，不需要改 AstrBot Dashboard

- 内置 WebUI 默认运行在 `127.0.0.1:8099`。
- 设置中心改成摘要卡 + 分组表单，配置、运行概览、最近任务、Debug 日志在同一控制面内分层呈现。
- 高频动作尽量收进抽屉与 Utility，不让主工作区被低频设置长期占用。
- 支持中英文切换。
- 支持按关键字、状态、策略快速筛选。

### 3. Skills 管理按“可维护边界”组织，而不是按叶子数量堆满界面

- install unit / collection group 是主管理对象。
- source bundle、deploy target、host 软件一起进入同一个控制面。
- `global / workspace` 是一级绑定作用域，AstrBot 本地 skill 已支持按 scope 管理。
- `一键完善 Skills` 会先刷新待补 install atom，再推进全部可执行聚合，并提供进度与历史回放。
- `manual_only`、git-backed、repo-metadata、registry-backed 等边界会显式区分。
- `结构与成员` 默认收起，首屏优先让给高频运维动作。

### 4. 面向真实运维，不是“能跑就算”

- 支持镜像、多远端候选与探测。
- 支持运行态健康检查、doctor、结构化错误提示。
- 支持批量更新、聚合进度、执行结果回放。
- 支持把 source sync 和真实 update 分开判断，不再伪装“看起来都能更新”。

## 适用场景

- 你在一台 AstrBot 主机上同时维护多个 CLI / GUI / Skills 宿主。
- 你希望把软件更新和 Skills 管理收敛到一个运维台。
- 你需要一个普通用户能用、开发者能扩展、运维能审计的插件。
- 你不想把安装说明、开发说明、接口清单、发布流程混在同一页里。

## 快速开始

### 1. 安装插件

```bash
cd <ASTRBOT_ROOT>/data/plugins
git clone https://github.com/Jacobinwwey/astrbot_plugin_onesync.git
```

### 2. 重启 AstrBot

```bash
systemctl restart astrbot.service
```

### 3. 先做最小验证

管理员发送：

```text
/updater status
```

能看到状态摘要，说明插件已经正常加载。

### 4. 打开内置 WebUI

在插件配置中启用：

- `web_admin.enabled = true`
- `web_admin.host = 127.0.0.1`
- `web_admin.port = 8099`

然后打开：

```text
http://127.0.0.1:8099
```

### 5. 推荐使用顺序

1. 在配置中心确认 `human` 或 `developer` 模式。
2. 配置或导入软件目标。
3. 先跑一次 `/updater env` 或 `立即更新（当前筛选）`。
4. 单目标验证通过后，再做批量更新。

更完整的安装、配置和排障说明见：

- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)

## Prompt 模板

如果你不想从零写配置，直接把下面模板丢给 Codex、Claude 或 ChatGPT 即可。

如果参数很多，优先用本地生成器：

```bash
python3 scripts/onesync_prompt_builder.py \
  --interactive \
  --lang zh \
  --scenario suite \
  --output /tmp/onesync_prompt_zh.txt
```

### Prompt A：初始化并一键下发

适合第一次配置 OneSync，或者准备把一组软件目标一次性导入 WebUI。

```text
你是 OneSync 配置执行助手。请帮我完成 OneSync 的初始化配置与下发。

目标：
1) 生成可直接 POST 到 /api/config 的 JSON，外层必须是 {"config": {...}}。
2) 生成一段 bash 一键脚本，自动：
   - 写入 onesync_config.json
   - 如果 WEBUI_PASSWORD 非空则调用 /api/login 获取 token
   - 调用 /api/config 提交配置
   - 调用 /api/config 与 /api/overview 验证是否生效
3) 输出分为 3 个区块：
   - JSON_PAYLOAD
   - BASH_ONE_CLICK
   - ASSUMPTIONS
4) 不要输出多余解释；JSON 不允许注释和尾逗号。

输入参数：
WEBUI_URL=http://127.0.0.1:8099
WEBUI_PASSWORD=
TARGET_CONFIG_MODE=human
POLL_INTERVAL_MINUTES=10
DEFAULT_CHECK_INTERVAL_HOURS=12
AUTO_UPDATE_ON_SCHEDULE=true
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
```

### Prompt B：在现有配置上增量新增一个软件目标

适合当前配置已经能用，只想补一个新软件，不想把旧配置覆盖掉。

```text
你是 OneSync 配置助手。请在“保留现有配置不丢失”的前提下，为 OneSync 新增一个软件目标。

执行规则：
1) 先通过 GET {WEBUI_URL}/api/config 读取现有配置。
2) 按我的目标参数进行增量合并，不要覆盖无关目标。
3) 输出：
   - UPDATED_JSON_PAYLOAD
   - BASH_APPLY_PATCH
   - CHANGE_SUMMARY
4) 如果检测到同名目标，按“更新该目标”处理，不新增重复条目。

输入参数：
WEBUI_URL=http://127.0.0.1:8099
WEBUI_PASSWORD=
NEW_TARGET:
  name: mytool
  strategy: command
  enabled: true
  check_interval_hours: 12
  current_version_cmd: /usr/local/bin/mytool --version
  latest_version_cmd: curl -fsSL https://example.com/mytool/latest.txt
  latest_version_pattern: (\\d+\\.\\d+\\.\\d+)
  update_commands:
    - bash /opt/scripts/update-mytool.sh
  verify_cmd: /usr/local/bin/mytool --version
```

### Prompt C：诊断并修复配置异常

适合 `404`、配置下发失败、接口路径不一致这类问题。

```text
你是 OneSync 故障诊断助手。请按“先诊断、后修复、再验证”的顺序输出可执行方案。

必须执行的诊断检查：
1) GET {WEBUI_URL}/api/health
2) GET {WEBUI_URL}/openapi.json 并确认是否存在 /api/config
3) GET {WEBUI_URL}/api/config
4) 如果 /api/config 返回 404，给出最小修复步骤：
   - 重启服务
   - 确认 web_admin_url
   - 浏览器 Ctrl+F5

输出格式：
- DIAGNOSIS
- FIX_COMMANDS
- VERIFY_COMMANDS
- ROLLBACK_PLAN

环境参数：
WEBUI_URL=http://127.0.0.1:8099
SERVICE_NAME=astrbot.service
```

更完整的 Prompt 套件与脚本用法见：

- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md#53-ai-一键配置-prompt-套件推荐)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md#53-ai-one-click-prompt-suite-recommended)

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `/updater status` | 查看插件与目标状态 |
| `/updater check [target]` | 立即检查版本，不执行更新 |
| `/updater run [target]` | 检查并在需要时更新 |
| `/updater force [target]` | 忽略版本比较，强制执行更新 |
| `/updater env [target]` | 检查运行环境、命令路径与版本 |

补充说明：

- `target` 可省略；省略时按所有已配置目标执行。
- 推荐先跑 `/updater env`，再做批量更新。

## WebUI 亮点

WebUI 不是“把命令换成按钮”那么简单。它主要解决三件事：先把配置写对，再把执行过程看清，再把问题定位下来。

- `配置中心`
  - 摘要卡先展示当前模式、轮询、端口与口令状态。
  - 直接读写插件配置，并支持 `human` / `developer` 双模式。
- `AI 配置助手`
  - 生成初始化、增量新增、诊断修复、完整套件 Prompt。
- `一键完善 Skills`
  - 先刷新待补 install atom，再批量执行可行动聚合更新。
  - 进度条、最近报告与历史回放共用同一后端进度契约。
- `AstrBot 本地 Skills`
  - 对 AstrBot host 按 `global / workspace` 范围启停、删除与执行 sandbox sync。
- `最近任务`
  - 查看软件更新执行结果。
- `Debug 日志`
  - 多标签、级别过滤、关键字过滤、清空日志。
- `Guide`
  - 用户流程与开发者流程说明。

如果你只是想先把软件更新安全跑通，推荐顺序是：

1. `配置中心`
2. `AI 配置助手`
3. `立即更新（当前筛选）`
4. `最近任务`
5. `Debug 日志`

## Skills 管理亮点

OneSync 的 Skills 管理不照搬 `npx skills ls` 的原始输出，而是按“谁可以被统一维护”来组织界面。

- 默认先显示已安装、且具备 skills 能力的宿主软件。
- 支持显式切换显示未安装候选。
- `global / workspace` 是一级绑定作用域，不藏在细节里；AstrBot 本地动作会显式带上 scope。
- `一键完善 Skills` 把 install-atom 刷新与批量聚合更新收敛成一个主按钮，并保留可回看的执行报告。
- 右侧 Inspector 聚焦当前 source / install unit / deploy target。
- `结构与成员`、`执行预览与审计` 这类低频长内容区块采用折叠式展示。

当前更新边界也保持明确：

- npm / registry-backed 聚合：支持更新。
- git-backed `skill_lock` 聚合：支持受管 checkout 后更新。
- repo-metadata source：支持 source sync fallback。
- `local_custom` / `synthetic_single` / `derived`：显式归类为 `manual_only`。

重点不是把所有东西都说成“可更新”，而是让用户很快看懂：

- 哪些可以自动维护。
- 哪些只能同步元数据。
- 哪些还必须手工维护。

## 常见问题

### 1. 页面报 `加载配置失败: 404 Not Found`

优先按这个顺序处理：

1. `systemctl restart astrbot.service`
2. 确认访问的是 OneSync 自己的 `web_admin_url`
3. 浏览器强制刷新 `Ctrl+F5`
4. 验证：
   - `curl -i http://127.0.0.1:8099/api/config`
   - `curl -s http://127.0.0.1:8099/openapi.json | jq -r '.paths | keys[]'`

### 2. 更新成功了，但 Skills 面板还显示旧状态

当前主线已经修过两类常见假阳性：

- 绑定保存不再依赖 inventory 重扫才能收敛。
- install unit / collection 命令更新成功后，会立即回写 freshness anchor，避免成功后仍显示 `AGING`。

如果你仍然看到异常状态，优先检查：

- 当前 source 是否属于 `manual_only`
- 实际走的是命令更新，还是 `source sync fallback`
- 如果是 AstrBot 本地 skill，确认当前操作 scope 是否选对，`workspace` 不会回写到 `global`
- `Debug 日志` 与 `doctor` 是否给出了结构化错误提示

### 3. 我应该用 `human` 还是 `developer` 模式

- 普通用户：优先 `human`
- 需要镜像、超时、正则、复杂 target 管理：用 `developer`

## 文档分层说明

文档已经按角色拆开，不再试图让 README 承担所有职责。

| 你现在要解决什么问题 | 先读哪份文档 |
| --- | --- |
| 安装、配置、排障 | [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md) |
| 发布、同步、双语 release | [操作与同步手册（中文）](./docs/OPERATIONS_AND_SYNC_zh.md) |
| 看代码结构和扩展点 | [开发指南（中文）](./docs/DEVELOPER_GUIDE_zh.md) |
| 写脚本或联调前端接口 | [接口参考（中文）](./docs/API_REFERENCE_zh.md) |
| 判断 Skills 更新当前到底支持到哪一步 | [Skills 更新能力现状（中文）](./docs/SKILLS_UPDATE_STATUS_zh.md) |

如果这个项目正好解决了你在 AstrBot 运维里的实际问题，欢迎点个 Star。
