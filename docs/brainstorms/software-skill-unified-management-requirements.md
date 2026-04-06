---
date: 2026-04-06
topic: software-skill-unified-management
---

# OneSync Skills 管理需求

## Problem Frame
OneSync 已经具备稳定的软件更新能力，但缺少“宿主软件 + skills/source bundles”统一管理面。

当前真实需求已经从“给每一条 skill 做 CRUD”转向：

- 统一管理支持 skills 的宿主软件
- 统一查看 source / bundle 的发现状态
- 用包级、来源级视图而不是逐条技能平铺
- 保留本地软件更新与本地 skills 管理在一个入口里完成

用户特别强调：

- 不需要把 `ce:brainstorm`、`ce:compound` 这样的成员逐条平铺管理
- `ce:*` 这类应聚合为一个 package/source 级对象
- `npx` 不只是安装方式，也应成为展示与维护抽象的一部分
- 软件列表默认应只显示已安装且有 skills 能力的宿主

## Requirements

### R1. Skills 管理以 source / bundle 为中心
- R1.1 系统必须支持把 `npx` 或本地 roots 发现到的 skills 聚合为 source/bundle 级对象。
- R1.2 UI 不应默认按每条 skill 成员平铺，而应优先展示 bundle/source。
- R1.3 `ce:*` 必须支持聚合显示为 `Compound Engineering`。

### R2. 保持现有 inventory 与 updater 兼容
- R2.1 现有 `/api/inventory/*`、`/api/run`、`/updater` 流程必须继续可用。
- R2.2 现有 `skill_bindings` 可继续作为过渡期 deploy intent 存储。
- R2.3 现有软件更新逻辑与 skill/source 管理逻辑必须职责分离。

### R3. 建立 source-first 状态模型
- R3.1 系统必须产出 `manifest` 和 `lock` 两类状态。
- R3.2 系统必须区分：
  - source 是否已发现
  - deploy target 是否 ready / stale / unavailable
  - 宿主软件是否已安装
- R3.3 系统必须把目标宿主目录视为 projection output，而不是 source truth。

### R4. WebUI 提供统一入口
- R4.1 WebUI 必须继续允许用户快速为某个宿主选择可部署 sources。
- R4.2 WebUI 必须增加 source/bundle 视图与 deploy target 视图。
- R4.3 WebUI 必须支持一键查看 doctor/health 结果。

### R5. 软件宿主筛选符合实际使用场景
- R5.1 默认只展示已安装的、支持 skills 的宿主软件。
- R5.2 用户可通过开关查看未安装候选宿主。
- R5.3 软件族兼容性应优先按 `software_family` 而不是仅按 `cli/gui/claw`。

## Success Criteria
- 用户能在一个页面内同时看到：
  - 可管理宿主软件
  - source/bundle 清单
  - deploy targets 与健康状态
- `ce:*`、Codex skill pack 等来源不再以海量成员平铺主界面。
- 保持当前 8099 管理台和旧 inventory 接口可用。
- 后端产出持久化的 `manifest.json` 与 `lock.json`。

## Scope Boundaries
- 当前阶段不做远程市场和多机集中纳管。
- 当前阶段不做完整 source 编辑器。
- 当前阶段不重写前端技术栈。
- 当前阶段 deploy 仍通过现有 `skill_bindings` 兼容层落地。

## Key Decisions
- 决策 1：以 source/bundle 为主对象，而非 per-skill 主对象。
- 决策 2：保留 inventory 兼容层，新增 source-first skills 核心。
- 决策 3：优先使用 `npx` 聚合结果作为真实用户可管理对象。
- 决策 4：前端主数据源切换到 `/api/skills/overview`，但保留现有操作流。
