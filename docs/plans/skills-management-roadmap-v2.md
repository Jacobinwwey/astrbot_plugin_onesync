---
date: 2026-04-06
topic: skills-management-roadmap-v2
status: active
---

# OneSync Skills 管理路线图

## 阶段 1.5：Source-First 过渡层
- 保留 `inventory_core.py`
- 引入 `skills_core.py`
- 新增 `/api/skills/*`
- `manifest.json` 可写，作为 deploy intent 主存储
- 新增 `POST /api/skills/deploy-targets/{target_id}`
- 在插件数据目录落地：
  - `skills/manifest.json`
  - `skills/lock.json`
  - `skills/sources/*.json`
  - `skills/generated/*.json`

## 阶段 2：独立 Manifest/Lock 状态
- 把当前 inventory 派生状态升级为独立可写状态
- 增加 source import/sync/deploy/repair 明确动作
- 让 deploy target 不再只依赖 `skill_bindings`

## 阶段 3：完整运维视图
- 增加 drift diff
- 增加 repair / redeploy
- 增加 source update available / stale age
- 增加更清晰的 target path / projection 健康诊断

## 阶段 4：更广宿主生态
- 扩更多 CLI / GUI / claw 家族
- 增加 git source / registry source
- 视需要再讨论跨主机统一管理
