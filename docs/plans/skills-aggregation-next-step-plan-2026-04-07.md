---
date: 2026-04-07
topic: skills-aggregation-next-step-plan
status: active
depends_on:
  - docs/plans/skills-aggregation-reference-analysis-2026-04-07.md
  - docs/plans/skills-management-next-step-implementation-plan-2026-04-06.md
---

# OneSync Skills 聚合管理下一步实施计划

## Summary

本计划只解决一个具体问题：

- 把 OneSync 从“少量 bundle 规则 + 大量 `npx_single` 回退”推进到“install-unit-first 的聚合管理”

本计划默认保持以下边界不变：

- 继续保留 WebUI 插件形态
- 继续保留 `/api/inventory/*` 兼容层
- 不恢复 root-directory synthetic bundle
- 不把主交互改成 leaf-first

本计划完成后，OneSync 需要达到的状态是：

- 默认管理对象是 install unit 或 collection group
- 叶子 skill 只在 detail 中展开
- refresh / update / doctor 都能围绕真实维护边界运行

## 运行态现实校正（2026-04-07）

截至本轮排查，运行态已经确认下面这些事实：

- 当前 registry 中共有 `98` 条 source rows
- 其中 `94` 条 install units 曾被前端直接当作“可读聚合包”
- 实际只有 `5` 个 meaningful collection groups：
  - `Compound Engineering`
  - `Design Review`
  - `DHH Rails`
  - `anthropics/skills`
  - `vercel-labs/skills`
- 剩余 `89` 条 `fallback_single` 全部来自 `/root/.codex/skills/*`
- 这些目录大多缺少：
  - `package.json`
  - `.skill-lock.json`
  - git/source provenance
  - 可恢复的安装 ledger

这意味着当前系统的主要问题已经不再是“前端没有折叠好”，而是：

- discovery 阶段没有把 provenance 当成一等状态持久化
- aggregation 只能在每次扫描时临时猜 package/source 边界
- UI 只能在错误粒度上继续做过滤，而不能依赖稳定 install-unit truth

所以从这个节点开始，下一步优先级必须改成：

- 先做 provenance-aware aggregation foundation
- 再把同一 install-unit 模型扩到 `manual_git` / `manual_local`

而不是继续把当前模糊聚合逻辑平移到更多来源。

## 目标状态

### 数据层

系统内部正式区分四类对象：

- `leaf_skill`
- `install_unit`
- `collection_group`
- `host_target`

### 交互层

前端默认只展示：

- 已安装的、支持 skills 的宿主
- install unit 或 collection group 卡片

前端默认不展示：

- 每个 leaf skill 单独一张主卡片

### 运维层

核心动作改为围绕 install unit：

- refresh install unit
- sync install unit metadata
- doctor install unit members and target projections
- deploy install unit to host target

## 核心架构决策

### 1. 不新增新的长期状态文件种类

继续坚持四层状态边界：

- `registry.json`
- `manifest.json`
- `lock.json`
- `audit.log.jsonl`

install unit 与 collection group 的长期信息进入 `registry.json`。

leaf membership、resolved package provenance、projection state 进入 `lock.json`。

### 2. 聚合规则分成两层

第一层是 install-unit resolution：

- 解决“哪些 leaf 来自同一个维护单元”

第二层是 collection-group resolution：

- 解决“前端应该如何把 install units 压缩成更可读对象”

### 3. install unit 优先于 collection group

所有 refresh、update、registry sync、doctor，都必须先基于 install unit。

collection group 只能提供：

- 显示聚合
- 批量筛选
- 可选的 group-level bulk action

collection group 不能替代 install unit 成为唯一真相。

## Phase A：聚合元数据内核

目标：让当前 source-first 模型正式拥有 install-unit 语义。

实现单元：

- 新增 `skills_aggregation_core.py`
  - 负责 leaf -> install_unit -> collection_group 的解析
- 更新 `skills_sources_core.py`
  - source registry 增加 install-unit 字段
- 更新 `skills_core.py`
  - overview 中增加 install unit 与 collection group 视图数据

新增字段：

- `install_unit_id`
- `install_unit_kind`
- `install_ref`
- `install_manager`
- `aggregation_strategy`
- `collection_group_id`
- `collection_group_name`
- `collection_group_kind`

字段语义：

- `install_unit_id`
  - 稳定主键，例如 `npm:@every-env/compound-plugin`
- `install_unit_kind`
  - 例如 `npm_package`、`git_source`、`local_source`、`synthetic_single`
- `install_ref`
  - 真实维护引用，例如 npm 包名或 git locator
- `aggregation_strategy`
  - 记录该 install unit 如何被识别，例如 `explicit_rule`、`package_json`、`path_heuristic`、`fallback_single`

本阶段不做：

- 不改动 deploy 逻辑
- 不改动主界面默认布局
- 不新增 collection group 编辑器

## Phase B：NPX provenance resolver

目标：解决同包 leafs 被错误平铺的问题。

实现单元：

- 更新 `inventory_core.py`
  - discovery 阶段尽量为每个 `npx` leaf 补足 package provenance hint
- 更新 `skills_aggregation_core.py`
  - 把 hint 归并为 install unit
- 更新 `skills_sources_core.py`
  - registry 中持久化 resolved package metadata

解析顺序：

1. 显式规则
   - 继续支持 `ce:*` 这类稳定 namespace 规则
2. 近邻 package 元数据
   - 尝试从 leaf path 附近的 `package.json` 读取包名
3. 路径启发式
   - 尝试从 `node_modules/<package>`、缓存目录或标准命名片段回推 package
4. curated override
   - 对已知高频聚合包建立显式映射
5. fallback single
   - 真无法确认时保留单 leaf install unit

本阶段重点迁移：

- 清理 legacy root bundle 兼容对象
- 让历史 `Codex Skill Pack` 这类伪大包尽可能拆解回真实 install units
- 让 `dhh-rails-*`、`design-*` 这类同包成员尽可能回归同一 install unit

本阶段验收标准：

- 不再新增 root-based synthetic bundle
- 对高频 npx 包可以得到稳定 `install_unit_id`
- 一个 install unit 可显示成员 preview 和统一管理命令

## Phase C：Collection group 解析与前端落地

目标：既不平铺 leaf，也不把 UI 压成无法解释的大包。

实现单元：

- 更新 `skills_core.py`
  - 产出 `install_unit_rows`
  - 产出 `collection_group_rows`
- 更新 `main.py`
  - `/api/skills/overview` 返回聚合视图
- 更新 `webui_server.py`
  - 暴露 install unit / collection group 详情路由
- 更新 `webui/index.html`
  - 主列表切到 install unit 或 collection group

推荐 API 形态：

- `GET /api/skills/overview`
  - 增加 `install_unit_rows`
  - 增加 `collection_group_rows`
- `GET /api/skills/install-units/{install_unit_id}`
- `GET /api/skills/collections/{collection_group_id}`

推荐前端行为：

- 默认视图：collection group
- 次级视图：install unit
- detail 视图：leaf members
- leaf 只作为 detail 数据，不再进入主列表

本阶段不做：

- 不做 leaf drag-sort
- 不做复杂 collection editor
- 不做 root-level auto bundle 恢复

## Phase D：install-unit-first 运维动作

目标：让 refresh、doctor、deploy 都围绕真实维护边界运行。

实现单元：

- 更新 `skills_core.py`
  - doctor 结果增加 install unit 汇总
- 更新 `main.py`
  - install-unit 级 refresh / sync / update 动作
- 更新 `webui/index.html`
  - install-unit 级操作入口

推荐动作：

- `POST /api/skills/install-units/{install_unit_id}/refresh`
- `POST /api/skills/install-units/{install_unit_id}/sync`
- `POST /api/skills/install-units/{install_unit_id}/deploy`

动作语义：

- refresh
  - 重新解析 source 与 package provenance
- sync
  - 重新同步 registry metadata 与 registry version
- deploy
  - 将 install unit 下当前生效 leaf members 投影到指定 target

当前进度（2026-04-07）：

- 已完成 install-unit 级 `refresh` / `sync` / `deploy`
- 已补 collection-group 级批量 `refresh` / `sync` / `deploy`
- 已补 install-unit / collection-group 级 repair orchestration
- 前端动作栏已从 “单 install unit” 升级为 “按当前 aggregate 自动路由”
- 已补 install unit / collection group 级 doctor 汇总
- 前端 doctor summary 已切到 aggregate-aware 统计
- 已补 install-unit / collection-group 级 `update` 编排
- `update` 当前已支持 registry-managed（`bunx` / `npx` / `pnpm dlx` / `npm`）与 git-managed 聚合
- manual / filesystem 聚合当前返回 structured unsupported，避免伪更新
- 下一步应推进 Phase E，把同一 install-unit-first 模型扩到 `manual_git` / `manual_local`
- 已完成 provenance foundation，并把 doctor / aggregate row / WebUI summary 全部接到后端 provenance truth
- 已开始推进 Phase F：
  - `manual_git` 现在按 `repo#subpath` 形成 install unit
  - 同一 Git repo 下多个 subpath 会归到同一个 `source_repo` collection group
  - `manual_local` 现在按 `root#subpath` 形成 install unit，并归到稳定的 `source_root` collection group
  - install-unit / collection-group row contract 已补 `locator` 与 `source_subpaths`
  - WebUI 已能把 manual source 渲染成 `Source Repository` / `Source Root`，并显示 subpath boundary summary

## Phase E：Provenance foundation（新的第一优先级）

目标：让 aggregation 不再依赖“本轮临时猜中”，而是依赖可持久化、可迁移、可解释的 provenance state。

### E1. 状态模型

新增 source-level provenance 字段，统一进入 `registry.json`，并在 `lock.json` 中保留解析结果：

- `provenance_origin_kind`
- `provenance_origin_ref`
- `provenance_origin_label`
- `provenance_root_kind`
- `provenance_root_path`
- `provenance_package_name`
- `provenance_package_manager`
- `provenance_package_strategy`
- `provenance_confidence`

字段职责：

- `origin_*`
  - 描述 leaf 最初来自哪个 source/package/repo 语义边界
- `root_*`
  - 描述 leaf 当前落在哪个 skills root 下，便于 legacy recovery 与诊断
- `package_*`
  - 描述 discovery 已确认的 package 维护边界
- `provenance_confidence`
  - 显式区分 `high` / `medium` / `low`，避免把低可信猜测直接当成正式 install unit

### E2. Discovery capture

实现单元：

- `inventory_core.py`
  - 在 discovery 时补足 provenance 字段，而不是只补 `install_unit_id`
- `skills_sources_core.py`
  - registry normalize 时保留 provenance 字段，并对历史数据做无损回填
- `skills_core.py`
  - `lock.json` 从 registry overlay provenance，而不是要求 manifest 承担 runtime 解析状态

解析顺序：

1. 显式 bundle / curated rule
2. `.skill-lock.json` repo/subpath
3. 近邻 `package.json`
4. `node_modules/<package>` 路径启发式
5. skills root 分类（仅作 provenance，不直接视为 install unit）
6. unresolved fallback

### E3. Aggregation resolver 改写

`derive_source_aggregation_fields()` 改为优先使用持久 provenance：

1. 现有显式 install-unit 字段
2. `provenance_package_name`
3. `registry_package_name`
4. `manual_git` / `manual_local` locator
5. `npx_bundle`
6. unresolved fallback

原则：

- 可持久化 provenance 优先于运行时临时猜测
- skills root 只作为恢复与诊断依据，不能重新变成 root synthetic bundle
- unresolved source 必须保留“未解状态”，而不是伪装成真实聚合包

### E4. Legacy recovery 策略

对历史 `/root/.codex/skills/*` 这类目录，采用两段式策略：

- 第一段：先保留 leaf 级 install unit，但把 root/source provenance 固化下来
- 第二段：等 importer 或安装路径开始写入 ledger 后，再基于 provenance 做可信迁移

这比直接恢复“Codex Skill Pack”更安全，因为：

- 不会把无关技能错聚成一个大包
- 不会制造用户以为“可统一更新”但实际并不存在的维护边界
- 可以逐步把未来安装记录补回历史数据模型

### E5. UI / API contract

本阶段不强制重做主面板，但 API 需要开始暴露 provenance 状态，以便后续 UI 能区分：

- 已确认 package/repo group
- curated group
- unresolved fallback single

推荐新增统计：

- `source_provenance_resolved_total`
- `source_provenance_unresolved_total`

本阶段仍保持：

- 默认主视图继续优先 `meaningful_collection_group_rows`
- unresolved fallback singles 不自动升级为“聚合包”

### E6. 验收标准

- registry 可持久化 provenance 字段
- lock 可在不污染 manifest 的前提下保留 provenance 解析结果
- aggregation 优先使用 provenance，而不是重复即席扫描
- 现有 UI 不再依赖“94 个伪聚合包”才能工作
- 对 `/root/.codex/skills/*` 这类 legacy roots，系统能明确标记“低置信未解”，而不是假装已经识别完毕

## Phase F：扩展到 manual_git 与 manual_local

目标：让 install-unit 模型不只服务 `npx`。

实现单元：

- 更新 `skills_sources_core.py`
  - `manual_git` 与 `manual_local` 也生成 install unit
- 更新 `skills_aggregation_core.py`
  - 非 npm source 使用 source locator 作为 install ref

结果要求：

- 一个 Git repo 子树可以是 install unit
- 一个 local source root 可以是 install unit
- collection group 仍然只作为展示层

## 推荐代码落点

后端：

- `inventory_core.py`
  - 补发现期 provenance hint
- `skills_aggregation_core.py`
  - 新模块，承接 install-unit 与 collection-group 解析
- `skills_sources_core.py`
  - registry 正规化与持久化
- `skills_core.py`
  - build overview / manifest / lock 时消费聚合模型
- `main.py`
  - 增加 install-unit API
- `webui_server.py`
  - 暴露对应路由

前端：

- `webui/index.html`
  - 用 install unit / collection group 替代当前 source-only 主列表

测试：

- `tests/test_inventory_core.py`
- `tests/test_skills_core.py`
- `tests/test_webui_server.py`
- 新增 `tests/test_skills_aggregation_core.py`

## 测试场景

### 聚合正确性

- `ce:*` 继续收敛为同一 install unit
- 同一 npm 包的多个 leaf skills 聚为一个 install unit
- 不同 npm 包但共享根目录时不会被误聚
- 无法识别 provenance 时回退为 `synthetic_single`

### 历史兼容

- legacy root bundle 不再出现在新 overview
- 旧 manifest 选择项可以迁移到新的 install unit 关系
- `/api/inventory/*` 继续可读

### 前端行为

- 默认只显示已安装 skills-capable 宿主
- 主列表默认不平铺 leaf
- detail 中可以看到成员 preview、member count、management hint
- global / workspace 切换仍然有效

### 运维动作

- install-unit refresh 不破坏 deploy selection
- doctor 可以同时指出 install unit 缺失与 leaf projection drift
- deploy target 仍然按 leaf 展开写入

## 边界情况

- 同一个包同时出现在 global 与 workspace scope
  - install unit 共享 package identity，但保留 scope 观察信息
- 同名 leaf 来自不同 install units
  - 继续使用 projection naming 策略解决冲突
- package metadata 缺失或路径不标准
  - fallback single，但保留 override 入口
- 一个 collection group 下包含多个 install units
  - bulk action 必须展开到 install units 执行

## 风险与取舍

主要风险：

- npx provenance 不是所有场景都能可靠自动推断
- 旧 bundle 选择迁移如果处理不好，会造成 UI 选择漂移
- install unit 与 collection group 同时引入，会增加状态设计复杂度

对应取舍：

- install unit 解析允许 fallback，不强求首轮全量准确
- collection group 先只做只读聚合，不做编辑器
- 不新增新的长期状态文件，避免状态面继续扩张

## 当前建议

下一步实现顺序应当是：

1. 先做 `skills_aggregation_core.py` 和数据字段扩展
2. 再做 npx provenance resolver 与 legacy root bundle 清理
3. 然后把 overview 和 WebUI 主列表切到 install unit / collection group
4. 最后再补 install-unit-first 的 refresh / sync / doctor / deploy

如果顺序反过来，前端会先出现更多“看起来更像聚合”的卡片，但后端仍然没有真实维护边界，后续成本会继续上升。
