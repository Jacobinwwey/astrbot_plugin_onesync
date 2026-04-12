---
date: 2026-04-11
topic: skills-architecture-progress-and-next-direction
---

# OneSync Skills 架构推进现状与下一步需求

## Problem Frame
当前 OneSync 已从“leaf 平铺管理”推进到 install-unit-first 与 collection-group 展示模型，核心数据面（`registry/manifest/lock/audit`）与 WebUI 运维面已经具备可用基础。

但运行态反馈“聚合更新仍不顺利”并非单点 bug，而是一个**语义一致性缺口**：

- 预览详情中的 `update_plan`（含 `update_mode/actionable/fallback_mode`）与实际执行入口（`/update`）仍存在路径分叉。
- collection group 在“部分可执行（部分 install unit 可 sync/更新）”时，缺少统一 contract，导致前端与后端对“可执行”判断不一致。
- provenance 与 install-atom 账本已引入，但“更新边界可执行性”还没有形成从 detail 预览到执行编排的闭环真相。

换言之，当前阶段的主要目标不再是“继续增加聚合规则”，而是将**可执行性语义**统一为单一真相并可被 UI 稳定消费。

## Current Progress Matrix

| 规划阶段 | 目标 | 当前进展 | 结论 |
| --- | --- | --- | --- |
| Phase A | install-unit / collection-group 基础建模 | `skills_aggregation_core.py`、`skills_sources_core.py`、`skills_core.py` 已贯通 | 已完成 |
| Phase B | npx provenance resolver | provenance 字段、legacy family 压缩、cache mirror 恢复已落地 | 已完成（仍需持续提升命中率） |
| Phase C | 聚合视图 API 与 WebUI 切换 | `/api/skills/overview` 与 install-unit / collection-group detail 已稳定 | 已完成 |
| Phase D | install-unit-first 运维动作 | refresh/sync/deploy/update/doctor 已具备 install-unit 与 collection-group 路由 | 已完成（语义一致性待补） |
| Phase E | provenance foundation | provenance 计数、告警、install-atom ledger、doctor 指标已接线 | 已完成（可观测面） |
| Phase F | manual_git / manual_local 扩展 | source locator + subpath 边界已进入聚合模型与 UI 展示 | 已完成（更新策略仍分层） |
| Step 23/24 | update 可执行性与 fallback | install-unit 级 `command/source_sync/manual_only` 已可用 | 部分完成（collection 级仍有一致性缺口） |
| Step 25 | aggregate update-all | backend route + WebUI action + live deployment 已完成 | 已完成 |
| Step 26 | synthetic single 收口 | 无真实包边界的 `synthetic_single` 已稳定降级为 `manual_only` | 已完成 |
| Step 27 | git checkout bootstrap | `skill_lock` / git-backed source 已可自动补齐受管 checkout | 已完成（远端稳定性仍需继续增强） |

## Architecture Reality Snapshot

基于当前代码与 8099 运行态，现状应更新为：

- `candidate_install_unit_total = 20`
- 最近一次 `update-all` 实际执行：
  - `executed_install_unit_total = 14`
  - `command_install_unit_total = 3`
  - `source_sync_install_unit_total = 11`
  - `skipped_install_unit_total = 6`
  - `success_count = 8`
  - `failure_count = 2`
  - `precheck_failure_count = 0`
- `manual_only` 当前稳定收口为 6 个 install unit，主要集中在：
  - `synthetic_single:*`
  - `local_custom:*`
  - `derived:*`

这说明当前主问题已经从“可执行性契约大面积漂移”收敛到两个更具体的层面：

1. 仍有少量 command 型聚合在执行期失败，主要属于 manager/runtime 级问题，而不是 plan contract 问题。
2. git-backed source 虽已能自动补齐 checkout，但 checkout bootstrap 仍受远端网络质量与 mirror 策略影响。

也就是说，当前阶段的核心矛盾已经不再是“前端与后端是否认同某个聚合能不能执行”，而是“执行路径已经统一后，如何进一步提升 git / registry 命令的成功率与首轮延迟表现”。

## User Flow（当前缺口）
```mermaid
flowchart TB
  A[读取 collection group detail] --> B[前端按 update_plan 判断按钮可用态]
  B --> C{是否 actionable}
  C -->|否| D[按钮禁用/提示 manual-only]
  C -->|是| E[触发 POST /collections/{id}/update]
  E --> F{后端计划是否 supported}
  F -->|否| G[返回 unsupported]
  F -->|是| H[执行 update 或 source sync fallback]
  G --> I[用户感知: 预览与执行结果不一致]
```

## Requirements

**可执行性契约统一**
- R1. 后端必须提供单一 `effective_update_plan` 生成路径，detail 预览与 update 执行必须复用同一决策函数。
- R2. `update_mode` 必须支持 `command`、`source_sync`、`manual_only` 之外的 `partial` 语义，覆盖“部分 install unit 可执行”的 collection group。
- R3. `actionable` 判定必须与执行入口完全一致：若后端会执行任一子单元，则 UI 不得禁用更新按钮。
- R4. `unsupported_install_units` 与 `blocked_reasons` 必须在 detail 与 update response 中结构一致，避免两套文案分叉。

**聚合边界与 provenance 真相**
- R5. install-unit / collection-group 的 `supported` 语义必须区分：
  - `aggregate_supported`（至少一个可执行子单元）
  - `fully_supported`（全部子单元可执行）
- R6. provenance/ledger 只能表达“归因置信度”，不得被误用为“可更新性”推断；更新能力必须由 manager/policy/syncable 判定导出。
- R7. 对 `manual_only` install unit，必须稳定暴露机器可读的 `reason_code`，替代纯文本 message。

**运行与运维可观测性**
- R8. update 执行审计必须新增“partial 执行统计”，至少包含：
  - executed install units
  - skipped manual-only install units
  - fallback sync install units
- R9. doctor 必须新增“plan/execute contract drift”检查项，检测 preview 与执行口径不一致。

**前端交互一致性**
- R10. UI 更新按钮可用态仅依赖后端 `actionable`，不再在前端二次推导“猜测可执行性”。
- R11. 运维计划卡片必须明确显示：
  - `Execution Mode`（含 `Partial`）
  - `Supported Units / Unsupported Units`
  - `Will Execute` 与 `Will Skip` 列表摘要
- R12. Skills 管理面板默认收起能力应保持（当前已落地），但展开后更新动作反馈要与后端结构化结果一一对应。

## Success Criteria

- S1. 任意 collection group 满足：detail `actionable` 与 `/update` 执行决策一致，不出现“detail 可执行但 update 直接 unsupported”或反向情况。
- S2. 运行态 `supported=true && actionable=false` 的 collection group 数量收敛到 `0`。
- S3. 对 mixed group（可执行 + manual-only）执行更新时，返回成功结果中明确给出 executed/skipped 分层统计，而非整体失败。
- S4. 回归测试覆盖以下断言：
  - detail/update contract parity
  - partial mode 端到端
  - fallback sync 与 manual-only 混合场景

## Scope Boundaries

- 不在本阶段引入新的状态文件类型，继续沿用 `registry/manifest/lock/audit`。
- 不在本阶段重写前端技术栈或迁移到独立前端工程。
- 不在本阶段引入远端集中管控（多机/SSH/WSL 分发）。
- 不在本阶段把 local custom/manual source 强行自动化更新。

## Key Decisions

- 决策 1：将“可执行性”作为独立架构层（plan contract），不再让 UI 或执行入口各自推导。
  - 原因：当前问题本质是契约漂移，不是单纯聚合准确率不足。
- 决策 2：collection group 支持 `partial` 模式，而不是二元 supported/unsupported。
  - 原因：真实运行态天然存在混合来源，二元模型会放大误判。
- 决策 3：manual-only 明确保留为一等状态，不追求“全自动更新覆盖率”。
  - 原因：对本地自建 skills 强行自动更新会引入更高风险和更差可解释性。

## Dependencies / Assumptions

- 假设当前 install-unit 聚合结果总体可信，问题主要集中在 update contract 层。
- 假设 8099 运维台继续作为主验证入口，API contract 为先、UI 逻辑最小化。
- 假设现有测试框架可承载新增 contract parity 与 partial mode 回归。

## 2026-04-12 现实结论

- `find-skills` 与 `frontend-design` 这两条先前失败的 `skill_lock` 更新链路已经在 8099 live 环境修复：
  - 受管 checkout 已生成到 `plugin_data/.../skills/git_repos/`
  - install-unit detail 已切换到受管 checkout 路径生成 precheck 与 `git pull --ff-only`
  - 单项 update 实测均为 `success_count = 3`, `failure_count = 0`
- 先前错误地被当成可更新聚合的 `synthetic_single:*` 已全部退出执行队列，避免“伪失败”污染 `update-all` 统计。
- 当前仍然失败的 command 型聚合主要不是聚合模型错误，而是具体 manager/runtime 级失败，这说明 contract 层的目标已经基本达成。

## Outstanding Questions

### Resolve Before Planning
- 无。当前可直接进入下一轮规划，重点不再是 contract 收敛，而是 runtime success rate 与 checkout bootstrap latency。

### Deferred to Planning
- [Affects runtime stability][Technical] 如何把 git checkout bootstrap 从同步请求链路中拆成后台预热/作业队列，降低首轮 update 延迟。
- [Affects runtime stability][Technical] GitHub 类 managed checkout 的 remote strategy 是否要从“单 origin”提升为 mirror-aware remote probe / preferred remote 选择。
- [Affects observability][Technical] `update-all` 是否需要把 command 失败进一步按 manager / reason_code 聚类，避免 operators 只看到总失败数。
- [Affects UI clarity][Needs research] 是否需要在 Source / Bundle 详情中直接暴露 `git_checkout_path`、bootstrap 状态和 managed/unmanaged 区分。

## Next Steps
→ 下一轮规划应转向“managed checkout queue + mirror-aware git runtime + update-all failure taxonomy”，而不是继续追加更多聚合命名规则或 UI 折叠逻辑。
