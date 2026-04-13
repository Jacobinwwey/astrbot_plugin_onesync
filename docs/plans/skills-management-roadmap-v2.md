---
date: 2026-04-06
topic: skills-management-roadmap-v2
status: active
---

# OneSync Skills 管理路线图

## 参考分析入口
- `docs/plans/skills-management-reference-comparative-analysis-2026-04-06.md`
- `docs/plans/skills-management-next-step-implementation-plan-2026-04-06.md`
- `docs/plans/skills-aggregation-reference-analysis-2026-04-07.md`
- `docs/plans/skills-aggregation-next-step-plan-2026-04-07.md`

## 阶段 1.5：Source-First 过渡层
- 保留 `inventory_core.py`
- 引入 `skills_core.py`
- 新增 `/api/skills/*`
- `manifest.json` 可写，作为 deploy intent 主存储
- 新增 `POST /api/skills/deploy-targets/{target_id}`
- 新增 `GET /api/skills/deploy-targets/{target_id}`
- 新增 target 级 `generated projection diff`
- 新增 `POST /api/skills/deploy-targets/{target_id}/reproject`
- 在插件数据目录落地：
  - `skills/manifest.json`
  - `skills/lock.json`
  - `skills/sources/*.json`
  - `skills/generated/*.json`

## 阶段 2：独立 Manifest/Lock 状态
- 把当前 inventory 派生状态升级为独立可写状态
- 增加 source import/sync/deploy/repair 明确动作
- 让 deploy target 不再只依赖 `skill_bindings`

### 阶段 2A：Source Registry 与 Host Adapter
- 把 source registry 从 inventory 派生逻辑中拆出
- 把 built-in host / future custom host 抽象为统一 adapter contract
- 新增 `registry.json` 与 `audit.log.jsonl`
- 新增 source register / refresh / remove API
- 引入 install-unit metadata，停止只靠 namespace bundle 规则表达聚合
- 聚合策略升级为：
  - install unit 负责真实维护边界
  - collection group 负责主面板压缩显示

### 阶段 2A.1：聚合管理内核
- 新增 `skills_aggregation_core.py`
- 为 `npx` 结果补齐 package provenance
- 把 legacy root bundle 逐步迁移为真实 install units
- 默认不恢复 root-directory synthetic bundle
- 让 WebUI 主列表逐步从 source-only 过渡到 install unit / collection group

### 阶段 2B：Manifest/Lock 独立化
- `skills_core.py` 改为基于 registry + manifest + lock 生成 overview
- inventory 降级为 discovery input 与兼容层
- `skill_bindings` 继续保留，但明确为 compatibility projection

### 阶段 2C：受管导入
- 增加 `manual_local` source
- 增加 `manual_git` source
- 增加 custom host registry
- package-first UI 保持不变，不回退到默认 leaf-first

## 阶段 3：完整运维视图
- 增加 drift diff
- 增加 repair / redeploy
- 增加 source update available / stale age
- 增加更清晰的 target path / projection 健康诊断

### 阶段 3A：主界面减负与 Update-All Progress Bridge
- 把 `面板设置` 与低频 controls 抽到 Utility 抽屉，降低 Skills 主界面噪声
- 主工作区仅保留宿主选择、当前目标、核心 command rail、skills list
- `update-all` 从前端估算进度升级为后端阶段桥接
- freshness 语义从“仅本地 mtime”升级为“本地 last_seen + 最近成功 sync/refresh 锚点”

### 2026-04-06 已落地增量
- Source freshness / stale age 诊断
- npm-backed source sync 与 sync-all
- canonical compatible source list（source_rows 真相源）
- compatible source list inline sync action
- segmented scope tabs（global/workspace）
- source/deploy subpanel view mode + card typography/size preferences
- deploy target 当前目标 repair
- deploy target repair-all 批量修复
- deploy target generated projection diff
- deploy target reproject
- WebUI drift detail 面板
- WebUI projection detail 面板
- runtime state / projection doctor 诊断
- skills/inventory GET cache-first 读取，避免只读访问覆盖 generated 状态

### 2026-04-12 已落地增量
- Utility Inspector `执行历史` 统一入口（batch/current/rollback）
- Skills 主界面 command rail 与批量更新进度区
- Skills 列表精简为主信息 + 可展开细节
- Source Inspector 改为折叠式“结构与成员 / 执行预览与审计”
- sync 成功后 freshness anchor 修复，避免 `sync_status=ok` 但仍显示 `aging`
- `一键完善 Skills` 已打通连续进度条：
  - install-atom 补齐阶段与 aggregate update 阶段都已切到后端统一编排
  - 两个阶段复用同一条 progress snapshot / polling contract
  - progress payload 已携带 `workflow_kind` 与 atom 改善计数，页面刷新后仍可恢复 improve-all 语义
- 新阶段实施计划已固化：
  - `docs/plans/skills-ui-declutter-and-progress-bridge-plan-2026-04-12.md`

### 2026-04-13 已落地增量
- `webui_update_inventory_bindings()` 已切到 manifest-first 投影：
  - 保存绑定时不再要求 inventory 重扫
  - full replace 会清理 omitted manifest targets，并直接回写兼容投影
- deploy target 相关 mutation 已复用同一套 manifest-first 投影辅助逻辑，authority boundary 从“inventory 回流”进一步收口到 persisted state
- install-unit / collection 的命令更新成功后，会立即回写 freshness anchor，修复成功后仍显示 `aging` 的假阳性
- `build_skills_overview()` 新增 manifest authority 投影层：
  - `binding_rows / binding_map / binding_map_by_scope / compatibility` 由 manifest + registry + host/source 关系主导生成，不再直接回传 inventory 快照字段
  - counts 新增 `bindings_total / bindings_valid / bindings_invalid` 的 authority 侧统计，避免 inventory 旧值污染诊断
- `build_skills_manifest()` 收口优先级：
  - source 的显式兼容约束（`compatible_software_ids / compatible_software_families`）优先于 inventory compatibility
  - target 选择回退链升级为 `saved_manifest -> saved_lock -> inventory_binding_projection`
- manifest authority 投影进一步收紧：
  - 无显式兼容约束的 source，优先使用 `selected_source_ids` 作为宿主提示，避免 `available_source_ids` 扩散导致的跨宿主误判
  - 移除 inventory-only compatibility key 的回流，overview compatibility 不再携带无 host/target 依据的残留宿主键
- 当前完整回归基线：`pytest -q -> 204 passed`

## 阶段 4：更广宿主生态
- 扩更多 CLI / GUI / claw 家族
- 增加 git source / registry source
- 视需要再讨论跨主机统一管理

## 当前判断
- 下一步主线不是继续堆 UI，也不是继续增加聚合命名规则，而是推进 Phase 2B/2C authority boundary completion。
- `skill-flow` 主要借鉴 source state / planner / doctor。
- `ai-toolbox` 主要借鉴 host registry / custom tool / sync trigger 思路。
- 两者都不应直接改变 OneSync 当前的 package-first 主交互。
- 聚合管理专项的主线已从“继续补 Phase 2A.1 聚合规则”切到“Phase 2B/2C authority boundary + runtime reliability 收口”。
- Phase 3A 继续保留，但仅作为 authority/runtime 收口的支持性 UI 工作，不再独立扩 scope。
