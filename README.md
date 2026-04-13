# astrbot_plugin_onesync

> 语言 / Language: [中文](./README.md) | [English](./README_en.md)

<div align="center">
  <img src="./logo_256.png" alt="OneSync Logo" width="132">
</div>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.2.1-2563eb" alt="version v0.2.1">
  <img src="https://img.shields.io/badge/AstrBot-%3E%3D4.16-16a34a" alt="AstrBot >=4.16">
  <img src="https://img.shields.io/badge/WebUI-127.0.0.1%3A8099-f59e0b" alt="WebUI 127.0.0.1:8099">
  <img src="https://img.shields.io/badge/Skills-aggregate--first-7c3aed" alt="aggregate-first skills">
</p>

OneSync 是一个面向 AstrBot 的通用可扩展软件更新器插件，目标很明确：

- 让多个软件目标的检查、更新、验证、审计进入同一个工作流
- 给运维侧一个不用改 AstrBot Dashboard 源码就能用的独立 WebUI
- 把技能包、source bundle、deploy target 和 host 软件放进同一套 Skills 管理控制面

如果你要找的是：

- 一个能定时检查与更新多个软件的软件维护插件
- 一个自带 `8099` 运维面板的 AstrBot 插件
- 一个强调聚合管理而不是叶子平铺的 Skills 管理方案

那本项目就是为这个场景设计的。

## 快速导航

1. [核心特色](#核心特色)
2. [适用场景](#适用场景)
3. [快速开始](#快速开始)
4. [常用命令](#常用命令)
5. [WebUI 亮点](#webui-亮点)
6. [Skills 管理亮点](#skills-管理亮点)
7. [常见问题](#常见问题)
8. [文档导航](#文档导航)

## 核心特色

### 1. 软件更新不是单点脚本，而是一套完整闭环

- 支持定时检查、手动检查、手动更新、强制更新
- 支持多目标软件并行维护，不局限于单一工具
- 支持 `cargo_path_git`、`command`、`system_package` 三类更新策略
- 支持更新后验证、状态持久化、事件日志记录

### 2. 内置独立 WebUI，不必改 AstrBot Dashboard

- 内置 WebUI 默认运行在 `127.0.0.1:8099`
- 支持配置中心、运行概览、最近任务、Debug 日志
- 支持中英文切换
- 支持按关键字、状态、策略快速筛选

### 3. 面向真实运维，而不是只做“能跑”

- 支持镜像/多远端候选与远端探测
- 支持运行态健康检查与错误定位
- 支持批量更新和审计回放
- 支持 `Improve All Skills` / `Update All Aggregates` 这类批量流程

### 4. Skills 管理坚持聚合优先

- 不是把所有 leaf skill 平铺成主界面噪声
- install unit / collection group 是主管理对象
- 默认优先展示可统一维护的 bundle/source
- `manual_only`、git-backed、repo-metadata、registry-backed 边界会被明确区分

## 适用场景

- 你在一台 AstrBot 主机上同时维护多个 CLI / GUI / Skills 宿主
- 你希望把软件更新与技能包维护收敛到一个面板
- 你需要一个用户可操作、开发者可扩展、运维可审计的更新插件
- 你不想把“配置说明、运维说明、开发说明、接口说明”都揉在一个首页里

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

如果能看到状态摘要，说明插件已经正常加载。

### 4. 打开内置 WebUI

在插件配置中启用：

- `web_admin.enabled = true`
- `web_admin.host = 127.0.0.1`
- `web_admin.port = 8099`

然后打开：

```text
http://127.0.0.1:8099
```

### 5. 进入推荐使用路径

1. 在 WebUI 配置中心确认 `human` 或 `developer` 模式
2. 配置或导入你的软件目标
3. 先跑一次 `/updater env` 或 `立即更新（当前筛选）`
4. 确认单目标没问题后，再使用批量更新能力

完整安装与配置细节请看：

- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `/updater status` | 查看插件与目标状态 |
| `/updater check [target]` | 立即检查版本，不执行更新 |
| `/updater run [target]` | 检查并在需要时更新 |
| `/updater force [target]` | 忽略版本比较，强制执行更新 |
| `/updater env [target]` | 检查运行环境、命令路径与版本 |

说明：

- `target` 可省略；省略时会按所有已配置目标执行
- 推荐先跑 `/updater env`，再做批量更新

## WebUI 亮点

OneSync 的 WebUI 不是“只把命令换成按钮”，而是面向运维场景做了几件实用的事：

- `配置中心`
  - 直接读写插件配置
  - 支持 `human` / `developer` 双模式
- `AI 配置助手`
  - 生成初始化、增量新增、诊断修复、完整套件 Prompt
- `最近任务`
  - 查看软件更新执行结果
- `Debug 日志`
  - 多标签、级别过滤、关键字过滤、清空日志
- `Guide`
  - 用户流程与开发者流程说明

如果你主要是“先把软件更新跑通”，那 WebUI 的推荐顺序是：

1. `配置中心`
2. `AI 配置助手`（可选）
3. `立即更新（当前筛选）`
4. `最近任务`
5. `Debug 日志`

## Skills 管理亮点

本项目的 Skills 管理不是简单把 `npx skills ls` 的结果照单全收，而是围绕“可维护边界”来组织：

- 默认只显示已安装、且可调用 skills 的宿主软件
- 支持切换显示未安装候选
- `global / workspace` 作为绑定作用域显式切换
- 右侧 Inspector 聚焦当前 source / install unit / deploy target
- `结构与成员`、`执行预览与审计` 等长信息区块采用折叠式展示
- 当前版本下，`结构与成员` 默认收起，优先把注意力让给核心运维动作

在更新支持上，当前边界是清晰的：

- npm / registry-backed 聚合：支持更新
- git-backed `skill_lock` 聚合：支持受管 checkout 后更新
- repo-metadata source：支持 source sync fallback
- `local_custom` / `synthetic_single` / `derived`：显式归类为 `manual_only`

这套设计的重点不是“让所有东西都看起来能更新”，而是让用户一眼看懂：

- 哪些可以自动维护
- 哪些只能同步元数据
- 哪些必须手工维护

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

当前主线已经修复两类常见假阳性：

- 绑定保存不再依赖 inventory 重扫才能收敛
- install-unit / collection 命令更新成功后，会立即回写 freshness anchor，避免成功后仍显示 `AGING`

如果你仍然看到异常状态，优先检查：

- 当前 source 是否属于 `manual_only`
- 是否实际走的是 `source sync fallback` 而不是命令更新
- `Debug 日志` 与 `doctor` 是否有结构化错误提示

### 3. 我应该用 `human` 还是 `developer` 模式

- 普通用户：优先 `human`
- 需要镜像、超时、正则、复杂 target 管理：用 `developer`

## 文档导航

当前文档边界已经拆开，建议按角色阅读：

### 用户文档

- [README.md](./README.md)
- [README_en.md](./README_en.md)
- [安装与配置指南（中文）](./docs/INSTALL_AND_CONFIG_zh.md)
- [Installation & Config Guide (English)](./docs/INSTALL_AND_CONFIG_en.md)

### 运维/发布文档

- [操作与同步手册（中文）](./docs/OPERATIONS_AND_SYNC_zh.md)
- [Operations and Sync Manual (English)](./docs/OPERATIONS_AND_SYNC_en.md)

### 开发文档

- [开发指南（中文）](./docs/DEVELOPER_GUIDE_zh.md)
- [Developer Guide (English)](./docs/DEVELOPER_GUIDE_en.md)

### 接口文档

- [接口参考（中文）](./docs/API_REFERENCE_zh.md)
- [API Reference (English)](./docs/API_REFERENCE_en.md)

### 状态与规划文档

- [Skills 更新能力现状（中文）](./docs/SKILLS_UPDATE_STATUS_zh.md)
- [Skills Update Status (English)](./docs/SKILLS_UPDATE_STATUS_en.md)
- [Skills 管理路线图](./docs/plans/skills-management-roadmap-v2.md)

---

如果这个项目解决了你在 AstrBot 运维中的真实问题，欢迎点个 Star。
