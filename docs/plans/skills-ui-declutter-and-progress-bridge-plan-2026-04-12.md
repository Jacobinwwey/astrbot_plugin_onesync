---
date: 2026-04-12
topic: skills-ui-declutter-and-progress-bridge
status: active
depends_on:
  - docs/plans/skills-management-roadmap-v2.md
  - docs/brainstorms/2026-04-11-skills-architecture-progress-and-next-direction-requirements.md
---

# OneSync Skills UI 减负与 Update-All 进度桥接实施计划

## Summary

当前 Skills 管理面板已经具备：

- package-first / aggregate-first 的主交互
- update-all 批量入口
- Source / Deploy / Utility 右侧检查器
- 执行历史与 install-atom 账本可观测性

但还存在两个明显体验缺口：

1. 主界面仍混入过多低频设置与诊断控件，影响 operator 首屏决策速度。
2. `update-all` 的反馈仍主要依赖单次请求完成后的 summary，前端只能做估算进度，缺少后端真实阶段语义。

本阶段目标是把 Skills 管理面板进一步推进到“**低噪声主工作台 + 后端可报告阶段进度**”。

## Goals

### G1. 主界面减负

- 把 `面板设置` 与一部分低频 controls 从主面板抽离到 Utility 抽屉/次级入口。
- 保持主界面只承载：
  - 宿主选择
  - 当前目标概览
  - 核心 command rail
  - skills list

### G2. Update-All 真实进度桥接

- 把当前前端估算进度升级为“后端可报告阶段 + 前端可视化”。
- 不追求伪精确百分比，而是保证阶段可解释、状态可消费、日志可回放。

## Non-Goals

- 不重写 WebUI 技术栈。
- 不引入 WebSocket / SSE 大改造，除非现有轮询模型无法满足阶段桥接。
- 不把所有细粒度 debug 信息重新搬回主界面。
- 不在本阶段做 leaf-level skill 管理回退。

## Workstream A: UI Declutter

### A1. 迁移对象

从主界面迁出的内容：

- `面板设置`
  - Source / Deploy card view mode
  - 字体大小
  - 卡片宽高
- 低频 Utility controls
  - Install Atom 筛选/刷新策略切换
  - 偏诊断型说明文案

保留在主界面的内容：

- `刷新资产 / 同步全部 Source / 更新全部聚合 / 导入 Source`
- 当前宿主速览
- 当前 deploy target hero
- 保存部署选择 / 快速选择按钮
- skills list

### A2. UI 结构原则

- 主界面只保留一个主 command rail。
- Utility 抽屉承担“设置 + 账本 + 长尾工具”。
- Source Inspector 承担“结构 + 执行细节”。
- 执行历史保持在 Utility Inspector，但不再与主 command rail 竞争视觉优先级。

### A3. 预期结果

- 首屏滚动前可完成主要选择与批量动作。
- operator 不需要先理解一堆诊断卡片，才知道“下一步该点哪个按钮”。
- 默认展开 Skills 面板时，信息密度仍高，但认知负担下降。

## Workstream B: Update-All Progress Bridge

### B1. 现实问题

当前 `POST /api/skills/aggregates/update-all` 是一个同步聚合请求：

- 请求开始后，前端只能进入 busy state。
- 请求结束后，才能拿到最终 summary。
- 前端现有 progress 只能按时间估算，缺乏后端真实阶段。

### B2. 目标状态

后端提供一个独立的 **progress snapshot contract**，至少包含：

- `run_id`
- `status`
  - `idle`
  - `planning`
  - `executing_command`
  - `executing_source_sync`
  - `refreshing_snapshot`
  - `completed`
  - `failed`
- `candidate_install_unit_total`
- `executed_install_unit_total`
- `command_install_unit_total`
- `source_sync_install_unit_total`
- `completed_command_install_unit_total`
- `completed_source_sync_install_unit_total`
- `skipped_install_unit_total`
- `failure_count`
- `started_at`
- `updated_at`
- `message`

### B3. API 方案

新增/扩展以下接口：

- `POST /api/skills/aggregates/update-all`
  - 保持现有 summary 返回
  - 额外返回 `run_id`
- `GET /api/skills/aggregates/update-all/progress`
  - 返回最近一次运行态 progress snapshot
  - 可选 `?run_id=...`

必要时支持：

- `GET /api/skills/aggregates/update-all/history`
  - 若后续需要更长的运行态历史，再加

### B4. 后端实现原则

- progress 状态存放于插件进程内存即可，不新增复杂状态文件。
- audit 仍负责最终结果留痕；progress 只负责运行态可见性。
- 运行态更新节点至少覆盖：
  - 计划生成完成
  - command 批次执行推进
  - source sync 批次执行推进
  - overview refresh 开始/完成
  - 最终 completed/failed

### B5. 前端实现原则

- progress panel 只显示后端阶段，不再伪装为精确进度。
- 百分比由后端可推导字段计算：
  - `completed_command + completed_source_sync + skipped`
  - / `candidate_install_unit_total`
- 若后端未提供可精确计算值：
  - 只显示阶段标签与 counters
  - 不显示虚构百分比

## Data Contract Notes

### Freshness vs Sync

本阶段顺带固定一条关键语义：

- `freshness_status` 不应仅由本地目录 mtime 决定。
- 对 `sync_status = ok` 且 syncable 的 source，freshness anchor 应至少考虑：
  - `last_seen_at`
  - `sync_checked_at`
  - `last_refresh_at`
  - `last_synced_at`

这样 update/sync 成功后，前端不会再出现“结果显示 ok，但 freshness 仍 aging”的语义断裂。

## Implementation Order

1. 固化计划文档、README/roadmap/changelog。
2. Ship 当前 UI command rail + progress baseline 与 freshness 语义修复。
3. 把 `面板设置` 抽离到 Utility 抽屉。
4. 增加后端 `update-all` progress snapshot state。
5. 增加 `progress` API。
6. 前端改为消费后端阶段和 counters。
7. 删除/降级前端估算进度逻辑。
8. 增加端到端与静态测试。

## Execution Log

### 2026-04-13 / 已落地切片

- command rail、批量进度区与 Utility Inspector 更新报告面板已进入主线代码，不再只是计划项。
- `POST /api/skills/improve-all`、`GET /api/skills/aggregates/update-all/progress` 与 `.../history` 已接线，`一键完善 Skills` 与 `更新全部聚合` 共享同一套后端 progress/history contract。
- freshness 语义修复已从“规划中的 anchor 规则”进入实际写回逻辑：
  - install-unit / collection 命令更新成功后，会回写 `last_seen_at`、`last_refresh_at`、`source_age_days=0` 与 `freshness_status=fresh`
  - repo-metadata source 成功后仍显示 `AGING` 的假阳性已纳入回归覆盖
- authority boundary 也已同步收口一层：
  - `webui_update_inventory_bindings()` 不再依赖 inventory 重扫
  - deploy target mutation 现已复用 manifest-first 投影辅助逻辑
- Guide 弹窗已接入本地文档工作台：
  - 新增 `/api/docs/index`、`/api/docs/content`、`/api/docs/raw`，前端可在 WebUI 内直接浏览本地 Markdown 文档，不再依赖外链仓库页面
  - 支持按界面语言自动筛选（中文/英文）与手动切换 `auto/zh/en/all`，并保持文档列表与正文同屏可读
  - 文档路由增加路径白名单与 traversal 防护，仅暴露仓库根文档与 `docs/**/*.md`
- 当前完整回归基线：`pytest -q -> 191 passed`

## Test Plan

### Backend

- `update-all` progress snapshot 初始值、阶段推进、完成态
- completed/failed run 的 snapshot 收敛
- `run_id` 与 progress route 对齐
- freshness anchor 回归：
  - sync 成功后 source/install-unit/collection-group 从 `aging` 转 `fresh`

### Frontend

- 主界面不再直接暴露 `面板设置`
- Utility 抽屉内可编辑 Source/Deploy 显示偏好
- progress panel 可显示：
  - phase
  - counters
  - completed/failed state
- 若 progress API 不可用，前端必须优雅退化

### Live Verification

- `8099` 点击 `更新全部聚合` 后立即看到：
  - run state
  - phase
  - counters
- `nextlevelbuilder/ui-ux-pro-max-skill` 类 repo-metadata source 在 sync/update 后不再显示 `AGING`

## Risks

### R1. 前后端阶段定义不一致

- 规避：阶段枚举固定在后端，前端只消费，不自行发明。

### R2. 运行态 progress 丢失

- 规避：允许页面刷新后显示“最近一次已知 progress + 最终 audit”。

### R3. Utility 抽屉职责继续膨胀

- 规避：只迁移低频设置，不把核心动作再次塞回抽屉。

## Exit Criteria

- 主界面默认展开后，`面板设置` 不再占用主工作区。
- `update-all` 运行时能看到后端阶段，而不是仅靠时间估算。
- `一键完善 Skills` 改为后端统一编排：
  - install-atom 补齐阶段不再由前端循环驱动
  - 页面刷新后仍可通过 `workflow_kind=improve_all` 恢复正确进度语义
- sync 成功后的 repo-metadata source freshness 语义正确。
