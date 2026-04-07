---
date: 2026-04-06
topic: skills-management-next-step-implementation-plan
status: active
depends_on:
  - docs/plans/skills-management-reference-comparative-analysis-2026-04-06.md
---

# OneSync Skills 管理下一步实施计划

## Summary

下一阶段不再继续堆叠 UI 控件，而是把 OneSync 从“inventory 派生的 skills 面板”推进到“可持续演进的 source/host 运维内核”。

本阶段默认目标：

- 保持 package-first / bundle-first 交互，不回退到逐条 skill 平铺
- 保持 WebUI 插件形态，不引入桌面壳
- 保持本地优先，不把 WSL/SSH 远端同步放进本阶段主线

阶段结果定义：

- source 成为独立注册资产
- host 成为独立适配目标
- `manifest / lock / doctor / deploy` 都基于同一套 source/host 语义工作

## 阶段划分

### Phase 2A：Source Registry 与 Host Adapter 基础层

目标：把当前混在 `inventory_core.py` 中的两类职责拆开。

实现要求：

- 新增 `skills_sources_core.py`
  - 负责 source registry 的读取、规范化、ID 生成和生命周期状态
  - source kind 先支持：`npx_bundle`、`npx_single`、`manual_local`、`manual_git`
- 新增 `skills_hosts_core.py`
  - 负责宿主适配器定义、runtime path 解析、skill root 发现、installed/managed/status 计算
  - built-in host 从当前 `PROVIDER_DEFAULTS / DEFAULT_SOFTWARE_CATALOG` 迁移而来
- `inventory_core.py` 继续保留，但职责收缩为“兼容层和聚合入口”
  - 软件自动发现仍可保留在这里
  - 兼容旧 `/api/inventory/*`
  - 不再承载 source registry 真相

状态文件新增：

- `plugin_data/.../skills/registry.json`
  - 保存 source 注册信息、kind、locator、bundle policy、update policy、source scope、管理提示
- `plugin_data/.../skills/audit.log.jsonl`
  - 记录 source register / refresh / deploy / repair / remove 事件

接口新增：

- `GET /api/skills/registry`
- `POST /api/skills/sources/register`
- `POST /api/skills/sources/{source_id}/refresh`
- `POST /api/skills/sources/{source_id}/remove`
- `GET /api/skills/hosts`

本阶段前端要求：

- Skills 面板新增“Source Registry”只读/轻写入口
- 允许查看 source kind、locator、managed_by、last_refresh_at、update_policy
- UI 仍以 bundle/source 为主，不做 leaf-level 选择树

### Phase 2B：Manifest/Lock 独立化

目标：停止让 `skills_core.py` 完全从 inventory 快照派生。

实现要求：

- `skills_core.py` 改为基于：
  - `registry.json`
  - `manifest.json`
  - `lock.json`
  - host adapter runtime observation
- inventory 只作为 discovery input，不再是 manifest 真相
- `manifest.json` 只存用户意图：
  - source enabled state
  - deploy target selection
  - scope
  - source policy
- `lock.json` 只存解析结果：
  - resolved source snapshot
  - deployed targets
  - freshness
  - drift
  - projection hashes

兼容策略：

- `skill_bindings` 继续保留，但明确降级为 compatibility projection
- `/api/inventory/*` 读取仍可用，但必须从独立 manifest/lock 投影而来

本阶段前端要求：

- Source 面板新增 source policy / source state 展示
- Deploy Target 面板继续保留 repair / reproject
- 新增最近一次 source refresh、deploy apply、doctor run 的摘要状态

### Phase 2C：受管导入与可扩展宿主

目标：让当前 bundle-first 模型不仅能读 `npx skills ls`，还能纳管外部来源。

实现要求：

- `manual_local`：登记本地 source 根目录
- `manual_git`：登记 git repo + optional subpath，不要求第一版做复杂缓存策略
- host registry 支持 `custom host`
  - 字段：`key`、`display_name`、`software_kind`、`detect_paths`、`detect_commands`、`skill_roots`
- 只在这个阶段引入“导入 source”向导

明确不做：

- 不做桌面端 central repo
- 不做 WSL/SSH 同步主线
- 不做默认 leaf-level 细粒度部署器

## 关键架构决策

### 1. OneSync 继续坚持 package-first，而不是 leaf-first

默认部署单元保持 source / bundle。

只有在 source detail 中才允许看到成员预览和诊断，不在主面板平铺每个 leaf。

### 2. host adapter 是下一阶段最重要的扩展点

适配器字段至少统一为：

- `host_id`
- `family`
- `kind`
- `display_name`
- `installed`
- `managed`
- `resolved_skill_roots`
- `declared_skill_roots`
- `target_path(scope)`
- `supports_source_kind[]`

doctor / deploy / repair / reproject 都只能依赖 adapter contract，不再依赖分散常量。

### 3. registry/manifest/lock/audit 四层状态固定下来

- `registry`：有哪些 source 被纳管
- `manifest`：用户希望如何部署
- `lock`：系统当前解析到了什么
- `audit`：最近做过哪些动作

当前阶段不再新增更多并列状态文件。

## 文档与代码落地顺序

先改文档与边界，再改实现：

1. 更新 `docs/plans/skills-management-roadmap-v2.md`
   - 增加 Phase 2A / 2B / 2C
2. 更新 `docs/plans/software-skill-unified-management-plan.md`
   - 补上 registry 与 adapter 拆分目标
3. 实现后端基础层
   - `skills_sources_core.py`
   - `skills_hosts_core.py`
   - `skills_core.py` 适配
4. 暴露新 API
   - `main.py`
   - `webui_server.py`
5. 最后改前端
   - 先接只读 registry / hosts
   - 再接 register / refresh / remove 操作

## Test Plan

### 后端单测

- source registry 规范化
  - source id 稳定
  - kind/locator 解析正确
  - 重复 source 拒绝或合并策略稳定
- host adapter 解析
  - built-in host 生成正确
  - target path(scope) 正确
  - custom host 参数校验正确
- skills_core 独立状态
  - registry + manifest + lock -> overview 稳定
  - inventory 缺席时只读状态仍可展示
  - `skill_bindings` 兼容投影正确
- source refresh / remove
  - registry 更新
  - audit 记录落地
  - manifest/lock 联动不破坏已有 deploy target

### WebUI 验证

- registry 面板能列出 source kind、locator、scope、last refresh
- host 面板能列出 built-in/custom host 与 runtime path
- source register / refresh / remove 有明确结果反馈
- package-first 视图不被新 source 类型打散
- 现有 deploy target repair / reproject 不回归

### 回归要求

- 现有 `npx` bundle 管理保持可用
- `ce:* -> Compound Engineering` 聚合保持不变
- `GET /api/skills/*` 继续 cache-first
- 现有 inventory 面板筛选、layout、deploy filter 不回归

## Assumptions

- 本阶段默认继续以本地单机为核心，不引入远端同步主线
- git source 第一版先支持登记与刷新，不要求复杂凭证管理 UI
- 自定义宿主先支持配置文件级接入，不做复杂 runtime installer
- 叶子级选择不是下一阶段主目标，只保留为 source detail 能力预留
