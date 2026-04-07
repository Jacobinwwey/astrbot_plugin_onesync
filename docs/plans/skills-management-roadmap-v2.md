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

## 阶段 4：更广宿主生态
- 扩更多 CLI / GUI / claw 家族
- 增加 git source / registry source
- 视需要再讨论跨主机统一管理

## 当前判断
- 下一步主线不是继续堆 UI，而是先做 Phase 2A。
- `skill-flow` 主要借鉴 source state / planner / doctor。
- `ai-toolbox` 主要借鉴 host registry / custom tool / sync trigger 思路。
- 两者都不应直接改变 OneSync 当前的 package-first 主交互。
- 聚合管理专项的近期主线是 Phase 2A.1，而不是新增更多 bundle 命名规则。
