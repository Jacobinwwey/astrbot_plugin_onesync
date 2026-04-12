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

## 本轮已落地的中间态修正（2026-04-07）

为避免前端继续把大量 unresolved root leaf 平铺成“看似独立、实际上不可维护”的主卡片，本轮已经增加一层有限度的 `legacy_family` collection group：

- 仅作用于 `synthetic_single`
- 仅作用于 provenance 仍然停留在 `skills_root`
- 仅作用于 `legacy_root_only` 这类低置信度历史遗留条目
- 仅在同 scope、同 root label、同前缀家族达到 `2+` 成员时生效

当前运行态已可见的 `legacy_family` 例子包括：

- `Adversarial`
- `Agent`
- `CLI`
- `Data`
- `Git`
- `JavaScript`
- `Kieran`
- `Performance`
- `Security`
- `Test`
- `Todo`

这层修正的目标只有一个：

- 让 UI 从“噪声化 leaf 平铺”回到“可解释的家族压缩”

这层修正明确不代表：

- 已恢复真实 npm 包边界
- 已恢复可统一升级的真实 install unit
- 已恢复 package/source provenance ledger

因此接下来的工程方向仍然不变：

- `legacy_family` 只作为 honest compression layer 保留
- 真正需要继续推进的是 provenance recovery，而不是继续扩大家族命名规则

## 本轮新增的 provenance recovery 落点（2026-04-07）

在 `legacy_family` 之外，本轮已经补上第一批“真实 package 恢复”能力：

- 对 `npx_single` 增加 package cache mirror 恢复
- 仅在本机包缓存中找到同名 skill 目录且 `SKILL.md` 内容签名一致时才认定为候选来源
- 仅当候选最终收敛到唯一 package name 时才恢复 provenance
- 若命中 curated rule，则直接回归对应 install unit / collection group

当前这层恢复优先覆盖：

- `~/.bun/install/cache`
- `~/.npm/_npx`

它解决的问题是：

- 某些 leaf skill 明明来自真实 npm 包，但因为安装后只剩目标技能目录，原始 package provenance 丢失
- 系统现在可以借助“本机缓存镜像 + 内容签名”把这类 leaf 恢复到真实 npm install unit

当前运行态收益：

- `source_provenance_resolved_total` 已从 `8` 提升到 `23`
- `install_unit_total` 已从 `94` 降到 `79`
- `Compound Engineering` 现已恢复为包含 `17` 条 source、`24` 个成员的真实 package 聚合

## 本轮新增的第二阶段缓存匹配（2026-04-07）

在首批“内容签名严格一致”的 cache mirror 恢复之外，本轮进一步增加了第二阶段匹配：

- 仅在 strict match 失败后才进入
- 仍然要求候选 skill 名称一致
- 仍然要求最终只收敛到唯一 package name
- 仅当 `SKILL.md` 文本相似度达到高阈值时才接受

这层匹配是为了解决一个真实运行态问题：

- 本地已安装 skill 与缓存里的包内 skill 往往只差少量文案修订、命令别名调整、路径示例修正
- 严格内容签名会把这些“明显同源”的技能错误留在 unresolved

因此这层近似匹配明确采用保守约束：

- 不接受低相似度候选
- 不接受多 package 同时命中的歧义场景
- 不会跳过 package root / package.json 的最终归属校验

当前运行态收益进一步提升为：

- `source_provenance_resolved_total` 已提升到 `37`
- `install_unit_total` 已降到 `65`
- `meaningful_collection_group_total` 已从 `16` 降到 `13`
- `Compound Engineering` 现已恢复为包含 `31` 条 source、`38` 个成员的真实 package 聚合

这一步的边界同样明确：

- 不会因为“仅同名”就认定来源
- 不会在多个候选 package 同时命中时强行归属
- 不会把本地源码仓库直接伪装成 npm registry package

因此下一步仍应继续：

- 引入更稳定的 installer/import ledger
- 扩展到非缓存镜像来源的 provenance 恢复
- 让更多 `legacy_family` 成员逐步晋升为真实 install unit

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

## Execution Log

### 2026-04-10 / Step 3

- 已新增 install-atom 证据账本内核（`skills_install_atoms_core.py`）：
  - `install_unit_rows -> install_atom_registry` 的持久化归一化
  - evidence level / resolution status / resolver path 推导
  - first seen / last seen / last changed 时间轴
- 已在 `skills_core.py` 完成聚合主链路接入：
  - overview 输出 `install_atom_registry`
  - install unit 行新增 `aggregation_*` 证据字段
  - counts/doctor 新增 install atom 健康指标
- 已在 `main.py` 完成状态持久化接线：
  - 新增 `skills/install_atom_registry.json`
  - refresh/load/save/persist 全链路接入
  - 新增 API payload：`webui_get_install_atom_registry_payload`
- 已在 `webui_server.py` 增加接口：
  - `GET /api/skills/install-atoms`
- 新增与更新单测：
  - `tests/test_skills_install_atoms_core.py`
  - `tests/test_skills_core.py`
  - 调整 `tests/test_inventory_core.py` 的 freshness 断言以避免环境路径状态导致的非确定性失败

### 2026-04-10 / Step 4

- 已完成 WebUI install-atom 账本视图接入（基于 overview 的 `install_atom_registry`）：
  - Utility Inspector 新增 `Install Atom Ledger` 卡片
  - 新增账本摘要行：`total/resolved/partial/unresolved/explicit/strong/heuristic`
  - 新增按风险优先排序（`unresolved -> partial -> resolved`）的条目列表
  - 条目级展示：evidence / resolution / resolver path / last changed at
  - 列表默认仅展示前 8 条，其余条目显示隐藏计数
  - 新增 `/api/skills/install-atoms` 回退加载通道，避免 overview 精简载荷时 Utility 账本卡片失真
- 更新前端静态断言，补充 install-atom utility 视图关键字符串与 helper 函数覆盖：
  - `tests/test_webui_inventory_registry_hosts.py`

### 2026-04-10 / Step 5

- 已完成 install-atom -> Source/Bundle 的可操作联动：
  - install-atom 条目写入 `data-inventory-atom-install-unit-id`
  - 新增 `inventoryPrimarySourceKeyByInstallUnitId()`，将 install unit 映射到当前主列表可见聚合
  - 新增 `focusInventorySourceByInstallUnit()`，点击账本条目可自动切换到 Source Inspector 并加载对应 detail
  - 对定位失败场景增加结构化提示文案（`inventory_install_atom_locate_error`）
- 更新静态断言覆盖该联动路径：
  - `tests/test_webui_inventory_registry_hosts.py`

### 2026-04-10 / Step 6

- 已新增 install-atom 运维筛选与批量刷新闭环：
  - Utility 卡片新增账本筛选（`unresolved` / `all`）
  - 新增“刷新待补聚合”动作，按 install unit 串行调用 `/api/skills/install-units/{id}/refresh`
  - 刷新过程显示逐条运行态（基于 `inventoryRefreshingAtomInstallUnitIds`）
  - 完成后自动刷新 target/source detail，并输出 `success/failed/total` 结果摘要
  - 筛选状态已接入 WebUI preferences 持久化
- 更新静态断言覆盖：
  - `normalizeInventoryInstallAtomFilter`
  - `syncInventoryInstallAtomFilterTabs`
  - `refreshUnresolvedInstallAtomAggregates`
  - install-atom 筛选 tabs / 批量刷新按钮事件绑定

### 2026-04-11 / Step 7

- 已完成 install-atom 批量刷新策略与失败诊断扩展：
  - Utility 卡片新增刷新策略（`all` / `high_confidence`）
  - `high_confidence` 仅刷新 `explicit/strong` 且 `unresolved/partial` 的 install unit
  - 批量刷新入口新增候选计算器：`inventoryInstallAtomRefreshCandidates()`
  - 刷新按钮可用态改为按当前策略候选 install unit 数量判定
- 已完成刷新后失败分组报告面板：
  - 记录最近一次刷新策略、成功/失败/总数、完成时间
  - 失败项按 `resolver_path + evidence_level` 聚合分组
  - 分组内展示失败数量与 install unit 列表（长列表自动折叠预览）
- 已完成前端偏好与交互接入：
  - 新增 `inventoryInstallAtomRefreshStrategy` 本地持久化
  - 新增 `normalizeInventoryInstallAtomRefreshStrategy`
  - 新增 `syncInventoryInstallAtomRefreshStrategyTabs`
  - 新增刷新策略 tabs 事件绑定
- 更新静态断言覆盖：
  - `tests/test_webui_inventory_registry_hosts.py`

### 2026-04-11 / Step 8

- 已补 install-atom 刷新失败闭环（report -> action）：
  - Utility 卡片新增“重试失败项”按钮（`inventoryRetryFailedAtomsBtn`）
  - 新增 `retryFailedInstallAtomAggregates()`，可基于最近一次 report 的失败 install units 发起重试
  - 重试与普通刷新复用执行内核 `runInstallAtomAggregateRefresh()`，避免两套逻辑漂移
- 已补失败报告交互联动：
  - 失败分组行新增 `data-inventory-atom-report-install-unit-id`
  - 点击失败分组可直接定位到对应 Source/Bundle 明细（复用 `focusInventorySourceByInstallUnit`）
- 已补状态与文案：
  - 新增 `inventoryRetryingFailedInstallAtoms` 运行态
  - 新增 retry 相关中英文 i18n 文案（idle/running/noop/done）
- 更新静态断言覆盖：
  - `tests/test_webui_inventory_registry_hosts.py`

### 2026-04-11 / Step 9

- 已完成 source-sync adapter 从 npm-only 扩展到 npm + git：
  - `source_sync_core.py` 新增统一判定：`is_source_syncable()`
  - 新增 git sync 分支：
    - git remote/head：`git ls-remote <locator> HEAD`
    - git checkout 元数据：本地 `rev-parse/status` 快照
- 已完成统计口径升级：
  - `skills_core.py` 的 `source/install_unit/collection_group` syncable/pending 统计改为统一能力判定，不再硬编码 npm-only
- 已完成批量入口接线：
  - `main.py -> webui_sync_all_skill_sources` 改为复用 `is_source_syncable()`，支持批量 sync git-backed sources
- 已补单测与回归：
  - `tests/test_source_sync_core.py` 新增 git remote sync 与 syncable 判定测试
  - `tests/test_skills_core.py` 新增 git source 纳入 syncable 统计测试

### 2026-04-11 / Step 10

- 已完成 source-sync 结构化元数据升级（为 source-lock 化做准备）：
  - 新增并贯通字段：
    - `sync_local_revision`
    - `sync_remote_revision`
    - `sync_resolved_revision`
    - `sync_branch`
    - `sync_dirty`
    - `sync_error_code`
  - npm sync 与 git sync 均输出统一 revision 元数据
  - `skills_sources_core.py`、`skills_core.py`、`main.py` 的 registry/manifest/lock 路径已接入
- 已补回归验证：
  - `tests/test_source_sync_core.py` 新增 git checkout 元数据路径测试
  - `tests/test_skills_core.py` 新增 sync revision 字段透传断言

### 2026-04-11 / Step 11

- 已完成 sync 元数据到运维指标的第一段接线：
  - `counts` 新增：
    - `source_sync_dirty_total`
    - `source_sync_revision_drift_total`
  - `doctor.source_sync` 新增：
    - `dirty`
    - `revision_drift`
- 已补回归验证：
  - `tests/test_skills_core.py` 新增 dirty + revision drift 计数断言

### 2026-04-11 / Step 12

- 已完成 install-unit update pipeline 的 git precheck 安全闸：
  - `skills_update_core.py`：
    - git install unit 更新计划新增 `precheck_commands`
    - collection group 级计划新增 precheck 聚合透传
  - `main.py::_execute_install_unit_update_plans`：
    - 执行顺序改为 `precheck -> update`
    - precheck 失败会跳过 update 命令并返回结构化失败原因（`precheck_failed`）
    - command result 新增 `phase`（`precheck` / `update`）
    - 执行摘要新增分相统计：
      - `precheck_success_count`
      - `precheck_failure_count`
      - `update_success_count`
      - `update_failure_count`
- 已补回归验证：
  - `tests/test_skills_update_core.py` 新增 git precheck 计划断言与 collection group precheck 聚合断言

### 2026-04-11 / Step 13

- 已完成 update 执行链路的 revision capture 落地（git install unit）：
  - `main.py::_execute_install_unit_update_plans` 新增 before/after 采样
  - 执行器对 git source 做本地 checkout 级 revision 采样（避免远端网络抖动干扰）
  - 每个 install unit 结果新增 `revision_capture`：
    - `before`
    - `after`
    - `changed/unchanged/unknown` 统计
- 已完成 revision delta 纯函数化：
  - `skills_update_core.py` 新增 `summarize_revision_capture_delta()`
  - 支持按 `source_id` 对齐比较并输出 changed/no-change/unknown
- 已完成执行摘要与审计接线：
  - execution summary 新增：
    - `revision_changed_source_total`
    - `revision_unchanged_source_total`
    - `revision_unknown_source_total`
    - `revision_changed_install_unit_ids`
  - `install_unit_update` / `collection_group_update` 审计事件新增 revision 统计字段
- 已补回归验证：
  - `tests/test_skills_update_core.py` 新增 revision delta 统计测试

### 2026-04-11 / Step 14

- 已新增 git rollback preview（仅预览，不执行）：
  - `skills_update_core.py` 新增 `build_git_rollback_preview()`
  - 基于 before revision + source path 生成候选回滚命令：
    - `git -C <path> reset --hard <before_revision>`
  - 输出结构化 `candidates/skipped_sources/warning`
- 已在 update 执行结果接线：
  - install unit 结果新增 `rollback_preview`
  - execution summary 新增：
    - `rollback_preview_install_unit_total`
    - `rollback_preview_candidate_total`
  - 审计事件新增 `rollback_preview_candidate_total`
- 已补回归验证：
  - `tests/test_skills_update_core.py` 新增 rollback preview 命令生成与缺失条件断言

### 2026-04-11 / Step 15

- 已完成可执行 rollback API（基于 Step 14 preview）：
  - `main.py` 新增：
    - `webui_rollback_install_unit()`
    - `webui_rollback_collection_group()`
  - rollback 执行要求显式确认：
    - `payload.execute = true`
    - `payload.confirm = "ROLLBACK_ACCEPT_RISK"`
  - rollback 执行链路包含：
    - precheck
    - rollback command 执行
    - after-capture 与恢复结果判定（restored/not-restored）
    - audit + debug log
- 已完成 Web API 接线：
  - `webui_server.py` 新增：
    - `POST /api/skills/install-units/{id}/rollback`
    - `POST /api/skills/collections/{id}/rollback`
- 已补回归验证：
  - `tests/test_webui_server.py` 新增 rollback 路由成功/失败/404 覆盖
- 已完成 WebUI rollback 基础闭环：
  - `webui/index.html` 新增按聚合缓存 rollback before-revision 快照
  - update 成功后自动提取 `update.install_unit_results[].revision_capture.before`
  - 新增 `Rollback Aggregate` 按钮状态机（空快照禁用、执行中互斥）
  - 新增 rollback 确认与 API 调用（`execute + confirm + before_revisions`）
  - 成功后展示 `restored/not-restored/failed` 摘要
- 已补前端静态断言：
  - `tests/test_webui_inventory_registry_hosts.py` 新增 rollback 按钮/函数/路由字符串覆盖

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
  - WebUI hero/detail 已新增 `边界 / 扇出` 说明区，并把 collection-group 动作文案明确为 fan-out 到 install units / subpaths
  - WebUI 已支持在 collection group detail 内下钻到 install unit，hero 与动作栏会随 drilldown 同步切换

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

## 执行日志（2026-04-11）

- Step 15（baseline rollback flow）已完成：
  - 前端回滚入口已接线到 install-unit / collection-group rollback API。
  - 回滚前快照缓存（before_revisions）已随 update 响应持久到前端状态。
- Step 16（rollback hardening）已完成：
  - 新增 `/api/skills/audit` 回滚审计读取能力并接入 WebUI。
  - 回滚支持按 source_id 选择子集执行，降低误操作范围。
  - 回滚失败支持一次定向重试（仅重试未恢复 source）。
  - 审计面板支持“当前聚合优先，否则最近全局”显示策略。
- Step 17（update 可解释性增强）已完成：
  - 运维计划卡片新增 `Prechecks` 可视化（显示 precheck 命令预览与数量）。
  - collection 级卡片新增 `Blocked Reasons` 汇总，直接呈现受阻 install unit 的失败原因。
  - update 不可执行时，前端弹窗会附带结构化 `message`，不再只给泛化 unsupported 提示。
- Step 18（repo metadata sync adapter）已完成：
  - `source_sync_core.py` 新增 repo metadata 适配器（当前支持 GitHub）。
  - 支持解析 `repo:`/`documented:`/`catalog:`/`community:` 前缀 locator 并拉取仓库元数据。
  - 对 repo-prefix locator 增加 git-adapter 分流规则，避免被误判为可执行 git remote/head sync。
  - 新增单测覆盖：
    - GitHub repo metadata 成功路径
    - repo metadata 请求失败路径
    - `is_source_syncable` 对 repo locator 的判定路径
  - `skills_core` 回归测试已覆盖 repo-metadata source 计入 syncable 统计。
- Step 19（repo metadata provider 扩展）已完成：
  - `source_sync_core.py` 的 repo metadata 适配器已从 GitHub 扩展到 GitLab / Bitbucket。
  - 新增 provider 级 locator 解析逻辑（host/namespace/workspace/repo 归一化）。
  - 新增单测覆盖：
    - GitLab repo metadata 成功路径
    - Bitbucket repo metadata 成功路径
    - 多 provider 下 `is_source_syncable` 判定
- Step 20（repo metadata 鉴权与错误可观测性）已完成：
  - `source_sync_core.py` 已支持 `sync_auth_token` / `sync_auth_header` / `sync_api_base`：
    - 支持 GitHub/GitLab/Bitbucket 的自建实例 API Base 覆盖。
    - 支持 provider 默认鉴权头与显式 Header 模板（含 `{token}` 模板替换）。
    - `repo:` locator 在 `managed_by=github` 场景下不再误路由到 git remote 适配器。
  - repo metadata 错误码已分层：
    - `repo_metadata_auth_failed`
    - `repo_metadata_rate_limited`
    - `repo_metadata_provider_unreachable`
    - `repo_metadata_auth_config_invalid`
    - `repo_metadata_api_base_invalid`
  - source 鉴权字段已打通持久化链路（registry -> manifest/lock -> overview -> sync 执行）。
  - WebUI 已新增 source sync 错误码可视化与修复提示：
    - source 卡片 / 选择列表 / hero 面板展示 `sync_error_code` 标签与 hint。
    - Source 导入弹窗新增 `sync_api_base` / `sync_auth_header` / `sync_auth_token` 配置项。
  - 回归验证：
    - `python3 -m py_compile source_sync_core.py skills_sources_core.py skills_core.py main.py webui_server.py`
    - `python3 -m pytest tests -q` -> `150 passed`
- Step 21（WebUI payload 鉴权字段脱敏）已完成：
  - `main.py` 新增 `webui_redact_sensitive_payload` 与 `_redact_sync_auth_header`：
    - 递归脱敏 `sync_auth_token`（返回空字符串）并补齐 `sync_auth_token_configured`。
    - 对 `sync_auth_header` 执行掩码（`Header: <redacted>`）并补齐 `sync_auth_header_configured`。
  - `webui_server.py` 在 `/api/skills/*` 响应出口统一走 `_public(...)` 脱敏封装：
    - 覆盖 success 与 error `JSONResponse` 路径，避免敏感字段在异常分支泄露。
  - `webui_server.py` 的 `/api/inventory/bindings` 与 `/api/inventory/scan` 也已接入 `_public(...)`：
    - 防止 inventory 相关接口返回的 `skills` 快照旁路暴露鉴权字段。
  - `tests/test_webui_server.py` 新增路由级回归测试：
    - 验证 overview/sources 以及 inventory bindings 响应中的 token/header 被正确脱敏。
    - 验证 header-only（无值）场景保持可读（不误掩码策略名）。
  - 回归验证：
    - `python3 -m py_compile main.py webui_server.py`
    - `python3 -m pytest tests -q` -> `151 passed`
- Step 22（配置面板密码字段安全收口）已完成：
  - `main.py` 的 `/api/config` 载荷不再回传明文 `web_admin.password`：
    - 固定返回空字符串。
    - 通过 `web_admin.password_configured` 与 `meta.web_admin_password_configured` 暴露是否已配置。
  - `main.py` 的配置保存新增 `web_admin.password_mode` 语义：
    - `keep`：保持现有密码不变
    - `set`：使用新密码覆盖
    - `clear`：清空当前密码
    - 未传 mode 时兼容旧语义（若传了 `password` 字段则按其值更新）。
  - `webui/index.html` 配置面板改为安全输入语义：
    - `cfgWebPassword` 改为 `type=password`，不再回填明文。
    - 新增“清除已配置密码”复选与动态 hint/placeholder。
    - 保存时按输入状态自动发送 `password_mode`，避免“留空误清空”。
  - `webui_server.py` 的 `/api/config` GET/POST 也接入 `_public(...)` 统一出口，避免后续扩展字段时出现脱敏旁路。
  - 测试覆盖：
    - `tests/test_webui_server.py` 新增 config 路由密码语义断言（redacted + keep/set/clear）。
    - `tests/test_webui_inventory_registry_hosts.py` 新增前端密码模式控件与脚本断言。
  - 回归验证：
    - `python3 -m py_compile main.py webui_server.py`
    - `python3 -m pytest tests -q` -> `153 passed`
- Step 23（聚合更新“可执行性”与降级策略增强）已完成：
  - `skills_update_core.py` 的 registry update plan 新增运行器 precheck：
    - registry 类更新（`bunx`/`npx`/`pnpm dlx`/`npm`）现在会生成统一 precheck 命令，避免直接执行后才暴露“命令不存在”。
  - `main.py` 的 install-unit update 执行器新增 registry 运行器回退链路：
    - 当首选命令因 `command not found` 失败时，会自动尝试同一 install_ref 的替代命令（`bunx -> npx -> pnpm dlx -> npm install -g`）。
    - 回退探测失败结果标记为 `ignored`，不再污染最终 success/failure 统计。
  - `main.py` 新增 update->sync fallback：
    - 当 install-unit / collection-group 的 `update_plan.supported=false`，但其 source 全部 `is_source_syncable=true` 时，`update` 动作会自动降级执行 source sync，而不是直接返回 unsupported。
    - 响应新增 `fallback_mode=source_sync`、`syncable_source_ids` 与 `non_syncable_source_ids`，便于前端提示“这是 sync 降级，不是命令更新”。
  - 运行态问题复盘（基于 8099 实测样本）：
    - install units 总计 `18`，原始 `supported=5`，`unsupported=13`。
    - `unsupported` 中有 `11` 个 install unit 实际具备 source sync 能力，现可通过 update->sync fallback 获得“可执行更新路径”。
  - 回归验证：
    - `python3 -m py_compile main.py skills_update_core.py`
    - `python3 -m pytest tests -q` -> `153 passed`
- Step 24（manual-only 收口与前端可执行态一致性）已完成：
  - `main.py` 新增 update plan 预览增强字段（detail 级）：
    - `update_mode`: `command` / `source_sync` / `manual_only`
    - `actionable`: 是否可执行（前端按钮门禁可直接使用）
    - `manual_only`: 明确标记“仅手工维护” install unit
  - install-unit / collection-group 详情接口在返回 `update_plan` 时统一补齐：
    - `syncable_source_ids` / `non_syncable_source_ids`
    - 对可 source sync 降级的计划提前标记 `fallback_mode=source_sync`，避免“点更新前显示 unsupported”。
  - `webui/index.html` 更新按钮门禁从“只认 command_count”升级为：
    - 认 `actionable=true`
    - 或自动识别 `source_sync` fallback
  - 运维计划卡片新增 `Execution Mode` 展示：
    - `Command Update` / `Source Sync Fallback` / `Manual-only`
  - 运行态回归（8099）：
    - install units `18`
    - 预览可执行 `16`（`command=5`, `source_sync=11`）
    - `manual_only=2`（`local_custom:/root/.codex/skills/doc`, `derived:npx_global_playwright_interactive`）
  - 测试与验证：
    - `python3 -m pytest tests -q` -> `153 passed`
    - 前端脚本回归：`tests/test_webui_inventory_registry_hosts.py` -> `18 passed`
- Step 25（collection update contract 统一 + partial 执行模式）已完成：
  - 已新增 collection-group 的统一有效计划构建器：
    - detail 预览与 update 执行均复用同一套 effective plan 语义，不再“双路径推导”。
    - 统一产出：
      - `actionable`
      - `update_mode`（新增 `partial`）
      - `supported_install_unit_total` / `unsupported_install_unit_total`
      - `actionable_install_unit_ids`
      - `blocked_reasons`
      - `aggregate_supported` / `fully_supported` / `partial_supported`
  - 已完成 mixed collection（部分可执行 + 部分 manual-only）的执行链路打通：
    - command 型 install unit 继续走 `_execute_install_unit_update_plans`。
    - source-sync 型 install unit 新增专用执行分支（phase=`source_sync`）并纳入同一执行汇总。
    - collection update 响应与审计现已附带 source-sync 成功/失败统计，避免“detail 显示可执行但 update 直接 unsupported”。
  - 前端已补 `partial` 执行模式渲染：
    - 新增 `inventory_operation_plan_mode_partial`（中英文）。
    - `getInventoryOperationPlanMode` / `inventoryOperationPlanModeLabel` 已识别并显示 `partial`。
  - 回归验证：
    - `python3 -m pytest tests -q` -> `153 passed`
- Step 26（blocked reason code 合同强化 + 回归防漂移）已完成：
  - `skills_update_core.py` 已补齐 install-unit 阻塞原因编码：
    - `manual_managed`：手工/文件系统维护来源，不支持命令更新。
    - `unsupported_manager`：存在 manager 但无可执行更新策略。
    - install-unit update plan 现在统一返回 `reason_code`。
  - collection-group update plan 已补齐机器可读阻塞结构：
    - `unsupported_install_units[].reason_code`
    - `blocked_reasons[].reason_code`
    - manual-only 根状态新增顶层 `reason_code`（单一原因透传，混合原因标记 `mixed_blocked_reasons`）。
  - `main.py` 的 effective collection plan 与 fallback preview 已同步 reason code 贯通：
    - blocked install units / blocked_reasons 透传 `reason_code`。
    - `manual_only` 计划在缺省时自动归一 `reason_code`（例如 `non_syncable_sources_present` / `manual_only`）。
  - 回归测试新增并通过：
    - `tests/test_skills_update_core.py`：补 `reason_code` 断言与 manual-only / unsupported-manager 用例。
    - `tests/test_skills_core.py`：补 collection detail payload 的 `blocked_reasons.reason_code` 合同断言。
  - 回归验证：
    - `python3 -m py_compile main.py skills_update_core.py webui_server.py source_sync_core.py skills_core.py`
    - `python3 -m pytest -q` -> `156 passed`
- Step 27（partial 执行可观测性补全：executed/skipped/source-sync 分层）已完成：
  - `main.py` 的 effective collection plan 新增 install-unit 分层字段：
    - `command_install_unit_ids`
    - `source_sync_install_unit_ids`
    - `skipped_install_unit_ids`
    - `skipped_manual_only_install_unit_ids`
    - `skipped_other_install_unit_ids`
    - 以及对应 total 计数字段。
  - `main.py` 的 collection update 响应与审计已透传分层统计：
    - `executed_install_unit_total/ids`
    - `skipped_install_unit_total/ids`
    - `source_sync_install_unit_total/ids`
    - `command_install_unit_total/ids`
  - `webui/index.html` 的运维计划卡片已增强：
    - 新增 “Will Execute Units / Will Skip Units” 摘要行。
    - blocked reason 支持 `reason_code` 可视化（`{reason} + code`）。
  - `webui/index.html` 的更新完成提示已增强：
    - 在原有 success/failed/unsupported 摘要之外，补充 source-sync 单元数与 skipped 单元数提示，减少“成功但为什么没全量执行”的认知落差。
  - 回归验证：
    - `python3 -m py_compile main.py webui_server.py skills_update_core.py skills_core.py source_sync_core.py`
    - `python3 -m pytest -q tests/test_webui_inventory_registry_hosts.py tests/test_skills_update_core.py tests/test_skills_core.py` -> `62 passed`
    - `python3 -m pytest -q` -> `156 passed`
- Step 28（doctor 增加 plan/execute contract drift 检查）已完成：
  - `main.py` 新增 collection-group 计划契约检查器：
    - `_collection_group_plan_contract_issues`
    - `_compute_collection_group_plan_contract_health`
  - 已将检查结果接入 `skills_snapshot`：
    - `counts.collection_group_plan_checked_total`
    - `counts.collection_group_plan_contract_drift_total`
    - `doctor.plan_contract_health`
    - `collection_group_plan_contract_rows`
  - 该检查当前用于检测计划字段内部一致性回归（`update_mode/actionable/command/source_sync/skipped` 关系），避免后续改动出现“计划结构看似完整但执行语义自相矛盾”。
  - WebUI doctor 摘要已显示该指标：
    - `Plan Contract(checked/drift)`（中英文）
  - 回归验证：
    - `python3 -m py_compile main.py webui_server.py skills_update_core.py skills_core.py source_sync_core.py`
    - `python3 -m pytest -q tests/test_webui_inventory_registry_hosts.py tests/test_skills_update_core.py tests/test_skills_core.py tests/test_webui_server.py` -> `70 passed`
    - `python3 -m pytest -q` -> `156 passed`
- Step 29（前端执行结果闭环：Last Update 面板 + reason_code 折叠分组）已完成：
  - `webui/index.html` 新增 Inspector 卡片：
    - `Latest Update Execution`（最近一次更新执行）
    - 展示 executed/source-sync/skipped 三类 install-unit 统计
    - 展示执行模式与完成时间
  - 更新结果本地缓存新增按聚合键（`kind:id`）存储：
    - `state.inventoryLastUpdateByAggregateId`
    - `rememberInventoryLastUpdateForAggregate`
    - `getInventoryLastUpdateForAggregate`
  - 更新动作完成后已自动写入该缓存并刷新面板：
    - 仍保留弹窗摘要，但执行明细不再只存在瞬时提示中。
  - 跳过项展示已支持按 `reason_code` 折叠分组：
    - 统一聚合 `unsupported_install_units` + `blocked_reasons`
    - 折叠展开后可查看 install unit -> reason 明细
  - 回归验证：
    - `python3 -m pytest -q tests/test_webui_inventory_registry_hosts.py tests/test_webui_server.py` -> `26 passed`
    - `python3 -m py_compile main.py webui_server.py skills_update_core.py skills_core.py source_sync_core.py`
    - `python3 -m pytest -q` -> `156 passed`

- Step 30（聚合一键更新 + live 部署验证）已完成：
  - 后端新增：
    - `POST /api/skills/aggregates/update-all`
    - install-unit update plan 去重键，避免同一真实边界被重复执行
  - 前端新增：
    - “更新全部聚合”按钮
    - executed / skipped / source-sync / deduplicated 结果摘要
  - 已完成 8099 live 部署验证，不再停留在开发仓库局部实现。

- Step 31（`synthetic_single` 边界收口）已完成：
  - 无真实包边界、无可信 management hint 的 `synthetic_single` 现已明确收敛为 `manual_only`
  - 不再生成伪命令：
    - `npx npx_global_awesome_design_md`
    - `npx npx_global_clone_website`
    - `npx npx_global_impeccable`
    - `npx npx_global_terminal_dialog_style`
  - 当前 skipped install unit 稳定集：
    - `synthetic_single:npx_global_awesome_design_md`
    - `synthetic_single:npx_global_clone_website`
    - `synthetic_single:npx_global_impeccable`
    - `synthetic_single:npx_global_terminal_dialog_style`
    - `local_custom:/root/.codex/skills/doc`
    - `derived:npx_global_playwright_interactive`

- Step 32（git-backed source 受管 checkout 自动补齐）已完成：
  - `main.py` 新增 managed git checkout bootstrap：
    - 当 `skill_lock` / git-backed source 的叶子目录不是 git worktree 时，自动在 `plugin_data/.../skills/git_repos/` 下 clone 一个受管 checkout
  - `source_sync_core.py` 与 `skills_update_core.py` 已改为优先使用 `git_checkout_path`
  - `skills_sources_core.py` / `skills_core.py` 已修正 sync 元数据权威来源，避免 update 成功后残留旧 `sync_error_code`
  - live 运行态已验证：
    - `find-skills` -> `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-55d42a13a220`
    - `frontend-design` -> `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-7d7c7a8d88f1`
    - 两条 install unit update 实测均为 `success_count = 3`, `failure_count = 0`, `precheck_failure_count = 0`

- Step 33（最新全量运行态结果）：
  - 8099 live 最近一次 `POST /api/skills/aggregates/update-all`：
    - `candidate_install_unit_total = 20`
    - `executed_install_unit_total = 14`
    - `command_install_unit_total = 3`
    - `source_sync_install_unit_total = 11`
    - `skipped_install_unit_total = 6`
    - `success_count = 8`
    - `failure_count = 2`
    - `precheck_failure_count = 0`
  - 说明：
    - contract / fallback / bootstrap 主链路已基本稳定
    - 剩余失败已收敛到少量 command manager/runtime 层问题，而不是聚合模型本身

- 当前完整回归：
  - `pytest -q` -> `164 passed`
