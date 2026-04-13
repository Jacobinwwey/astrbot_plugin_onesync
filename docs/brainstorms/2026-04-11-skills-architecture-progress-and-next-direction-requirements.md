---
date: 2026-04-11
topic: skills-architecture-progress-and-next-direction
---

# OneSync Skills 架构推进基线复盘与下一阶段需求

## Problem Frame
当前代码已经明显超出早期路线图对 “聚合管理” 的设想阶段，但文档认知仍有滞后，导致后续推进方向容易失焦。

真实现状不是“还没做出 install-unit / collection-group 模型”，而是：

- install-unit / collection-group / provenance / install-atom / update-all / improve-all / AstrBot runtime 已经进入可用状态。
- `docs/plans/skills-management-roadmap-v2.md` 中 Phase 2A、2A.1、3、3A 的大量内容已经落地。
- 当前剩余问题主要转移到：
  - authority boundary 仍未彻底收口
  - runtime reliability 仍不足
  - host/source extensibility 仍偏静态
  - UI 还有减负空间，但已不再是主阻塞项

因此，这一轮 brainstorm 的目的不是继续定义“如何把 skills 聚合起来”，而是重新定义：

1. 现在到底已经做到了哪一段
2. 哪些路线图条目已经被实现或部分实现
3. 下一阶段到底应该先补架构、补运行时，还是继续补 UI

## Roadmap Comparison Matrix

| 路线图阶段 | 原始意图 | 当前实现现实 | 结论 |
| --- | --- | --- | --- |
| Phase 1.5 | 引入 `skills_core.py`、`/api/skills/*`、`manifest/lock/sources/generated` 状态层 | `skills_core.py`、`webui_server.py` 中 `/api/skills/overview`、`/api/skills/registry`、`/api/skills/install-atoms`、`/api/skills/*` 系列接口均已存在；`main.py` 已落地 `manifest.json`、`lock.json`、`registry.json`、`audit.log.jsonl` | 已完成 |
| Phase 2A | Source Registry 与 Host Adapter 拆分 | `skills_sources_core.py`、`skills_hosts_core.py` 已存在；source register / refresh / remove / sync API 已存在；但 host/source 仍主要由 inventory 与静态 provider 定义驱动 | 部分完成 |
| Phase 2A.1 | 聚合管理内核、npx provenance、install-unit / collection-group 主模型 | `skills_aggregation_core.py`、install-unit、collection-group、provenance、install-atom 全部已进入 overview / UI / tests；主界面已按 aggregate-first 消费 | 大部分完成 |
| Phase 2B | Manifest/Lock 独立化，inventory 降级为 discovery input | `build_skills_overview()` 仍以 `inventory_snapshot` 为根输入；`main.py` 仍会把 manifest 反投影回 `skill_bindings` 并重建 inventory | 部分完成，且是当前关键缺口 |
| Phase 2C | manual source / custom host / package-first UI 稳定扩展 | `manual_local`、`manual_git` 已落地；package-first UI 已保留；AstrBot runtime / neo source 已进入 overview 与 UI；但 custom host registry 还不是独立扩展层 | 部分完成 |
| Phase 3 | drift diff / repair / redeploy / stale age / projection health | deploy diff、repair、doctor、freshness、projection health、rollback audit 已在后端与 UI 中存在 | 大部分完成 |
| Phase 3A | 主界面减负与 Update-All Progress Bridge | command rail、Utility Inspector、批量 progress、history、freshness anchor 修正、improve-all 与 update-all 统一进度已落地 | 大部分完成，剩余为尾声收口 |
| Phase 4 | 更广宿主生态 | `skills_hosts_core.py` 已预置大量 provider defaults，但“可识别”不等于“可受管更新”； capability 深度仍不均匀 | 刚起步 |

## Superseded Conclusions

- “继续追加聚合规则”不再是主线。
  - 当前已有 install-unit / collection-group / curated pack / legacy family / synthetic single 等分层模型，再继续堆规则只会放大维护成本。
- “plan/execute contract parity 仍是第一矛盾”这个结论已经过时。
  - `main.py` 已具备 `plan_contract_health` 检查、`partial` / `manual_only` 模式校验，以及 collection-group detail/update 统一计划逻辑。
- “AstrBot 支持仍在规划中”这个结论也已经过时。
  - AstrBot runtime、neo source、sandbox sync、skill toggle/delete 都已经在 API、overview、UI、tests 中存在。

## Architecture Reality Snapshot

### 已经稳定形成的层

- `skills_aggregation_core.py`
  - 已承担聚合规则、provenance、install-unit / collection-group 生成。
- `skills_sources_core.py`
  - 已承担 source registry 归一化与 CRUD 合并逻辑。
- `skills_core.py`
  - 已能从 registry / manifest / lock 生成 skills overview，并补上 install-atom、AstrBot runtime、doctor counters。
- `main.py`
  - 已承担 skills state 持久化、aggregate update / improve-all 编排、rollback、repair、doctor、history、progress snapshot。
- `webui_server.py`
  - 已暴露 aggregate-first 的 API 面。
- `webui/index.html`
  - 已形成主 command rail、progress、utility inspector、source/install-unit/collection drilldown。

### 仍然存在的结构性耦合

- `skills_core.py` 的 `build_skills_overview()` 仍然以 `inventory_snapshot` 为根输入，而不是以 persisted registry / manifest / lock 为根输入。
- `main.py` 的 `_refresh_inventory_snapshot()` 仍然是先建 inventory，再建 skills，然后把 manifest 反投影回 `skill_bindings` 再重建 inventory。
- `skill_bindings` 虽已被弱化为 compatibility projection，但目前仍然处在真相链路里，而不只是兼容输出。
- host registry 目前主要由 `skills_hosts_core.py` 中的静态 `PROVIDER_DEFAULTS` / `DEFAULT_SOFTWARE_CATALOG` 驱动，不是独立、可插拔、可声明式扩展的 registry。

### 已经收口的一层 authority boundary

- `webui_update_inventory_bindings()` 现已直接基于 persisted `manifest` 与最新 skills snapshot 做绑定投影，不再要求 inventory 重扫才能让保存结果可见。
- deploy target 的保存/修复相关 mutation 也已复用同一套 manifest-first 投影辅助逻辑。
- 这说明 authority boundary 已经开始从 “inventory 回流” 向 “persisted state 主真相” 收口，但 `overview` 构建主入口仍未彻底完成反转。

### 这意味着什么

当前的主要问题已经不是“有没有聚合模型”，而是“真相边界还不够干净”。

这会直接带来三个后果：

1. 新宿主 / 新 source 形态的接入仍容易跨多个模块落地，扩展成本偏高。
2. skills update 能力的不足，很多并不是单点执行 bug，而是 authority boundary 不清导致的语义回流。
3. runtime reliability 的优化虽然能继续做，但如果不先收口 authority boundary，后续可靠性修复会越来越依赖特殊分支。

## Evidence Anchors

后续 planning 应优先围绕以下代码与测试做事实核对，而不是再按旧文档假设推进：

- `skills_aggregation_core.py`
  - 聚合、provenance、curated pack、install-unit / collection-group 归并逻辑
- `skills_sources_core.py`
  - source registry normalization、register / refresh / remove 语义
- `skills_core.py`
  - overview 构建入口、install-atom、AstrBot runtime、doctor counters
- `main.py`
  - persisted state、`skill_bindings` projection、aggregate update / improve-all、plan contract health
- `webui_server.py`
  - `/api/skills/*` control plane API 面
- `webui/index.html`
  - aggregate-first UI、progress bridge、utility inspector、AstrBot runtime controls
- `tests/test_skills_core.py`
  - manual source、AstrBot runtime、freshness anchor、provenance、aggregate rows 的核心行为回归
- `tests/test_webui_server.py`
  - WebUI API contract 覆盖
- `tests/test_webui_inventory_registry_hosts.py`
  - operator panel、progress/history/runtime 文案与挂点覆盖

## Approach Options

### Option A. 先完成 3A UI 尾声

继续把 Skills 管理面板做得更克制、更低噪声，把剩余设置、历史、报表进一步收进 Utility 抽屉，并继续优化批量反馈。

优点：
- 用户可见收益最快
- 对当前 8099 面板体验提升直接

缺点：
- 不能根治 update 能力不足
- 容易继续把注意力留在展示层，而不是 authority boundary 和 runtime

适用场景：
- 当前最大问题是 operator 迷路，而不是更新成功率与扩展能力

### Option B. 先完成 2B/2C 架构收口

把 registry / manifest / lock 真正提升为 skills control plane 的 authoritative state，inventory 降级为 discovery / compatibility input，彻底把 `skill_bindings` 收成投影层。

优点：
- 能正面解决 “为什么很多聚合仍不好更新”
- 能降低新 host / source 接入成本
- 为 runtime reliability 提供更稳定的真相边界

缺点：
- 需要触及主干数据流
- 这不是小修，会带来一轮明确的回归成本

适用场景：
- 当前问题核心是架构耦合，不是单纯 UI 或执行细节

### Option C. 先做 runtime reliability

优先把 git checkout bootstrap、mirror-aware pull/source sync、failure taxonomy、stale badge 收敛、队列化执行等运行期问题压下去。

优点：
- 能直接改善更新成功率
- 对实际运维价值高

缺点：
- 如果 authority boundary 不先收口，容易把 runtime patch 打在旧耦合结构上
- 之后做 2B/2C 时可能重复返工

适用场景：
- 当前最痛的是“已经能更新，但成功率和反馈差”

### Recommendation

推荐顺序是：

1. 先做 **Option B：Phase 2B/2C authority boundary completion**
2. 紧接着做 **Option C：runtime reliability**
3. 最后只保留必要的 **Option A：3A UI 尾声**

原因很直接：现在的根问题不是界面不够好看，而是 skills control plane 还没有真正独立成型。

## Requirements

**Authority Boundary**
- R1. `skills_core` 必须能够以 persisted `registry/manifest/lock/install_atom_registry` 作为 primary authority 构建 overview，inventory 只作为 discovery / compatibility enrichment 输入。
- R2. `skill_bindings` 必须降级为 compatibility projection；skills overview、update planning、progress、doctor 不能再依赖“先反写 bindings 再重扫 inventory”来维持一致性。
- R3. source registry 与 host registry 必须明确 authority boundary：
  - source registry 负责 source truth
  - manifest 负责 operator intent
  - lock 负责 resolved runtime state
  - inventory 负责 discovery / compatibility evidence
- R4. 新 host / source 形态的接入不应要求同时修改 `main.py`、`webui/index.html`、aggregation heuristics 才能获得基础支持；至少应先有 capability-first 的注册与降级机制。

**Runtime Reliability**
- R5. managed git checkout / bootstrap 必须从“请求链路内临时补齐”推进到“可观测的 staged runtime”，至少要支持预热、失败分类、可重试状态与稳定 checkout metadata。
- R6. aggregate update / improve-all 必须在成功后输出 authoritative freshness / atom resolution 结果，避免出现“执行成功但前端仍显示 AGING / ATOM 待补”的假阳性状态。
- R7. failure taxonomy 必须覆盖 manager、source kind、runtime category、reason code，且同时服务于 progress、history、doctor 与 operator guidance。
- R8. `manual_only`、`manual_git`、`manual_local`、repo-metadata source 等不同更新边界必须保持一等状态，不允许被强行塞进同一自动更新语义。

**Host and Ecosystem Expansion**
- R9. Host 扩展必须以 capability score 为准，而不是“出现在 provider defaults 里就算支持”；检测、部署、同步、更新、运行态控制需要分层声明。
- R10. AstrBot 支持必须收敛到 capability-driven host/runtime contract，避免后续每加一个 runtime 动作都继续扩散特殊分支。

**Operator Experience**
- R11. Skills 管理面板继续保持“默认收起、按需展开、主动作优先”的方向，但后续 UI 变更只服务于 authority/runtime 收口，不再独立扩 scope。
- R12. `一键完善 Skills` 应持续作为主入口，phase、history、post-run summary 都基于后端统一 contract，不再引入新的前端估算语义。

## Success Criteria

- S1. 在 inventory scan 失败或降级时，系统仍能从 persisted `registry/manifest/lock` 构建可消费的 skills overview，而不是整体失去 control plane。
- S2. `skill_bindings` 改动不会再成为 skills overview 与 update behavior 的必要前置条件。
- S3. aggregate update / improve-all 的成功结果与 UI badge 状态一致，不再出现执行成功但仍显示 `AGING`、`ATOM 待补`、错误 blocked 状态等假阳性。
- S4. 新增一个 host 或 source 类型时，最小接入面主要集中在 registry / capability / adapter 层，而不是横切多个 UI 与 orchestration 分支。
- S5. operator 能从 history / progress / doctor 明确回答：
  - 哪些聚合被执行
  - 哪些被跳过
  - 为什么失败
  - 是否属于 runtime 问题还是 authority 问题
- S6. `doctor.plan_contract_health.drift_total` 持续收敛为 `0`，且不会因 Phase 2B/2C authority 收口而重新引入 collection-group plan drift。

## Scope Boundaries

- 不在本阶段重写 WebUI 技术栈。
- 不在本阶段回退到 leaf-first 的 skills 主交互。
- 不在本阶段把 `manual_local` 或用户自建本地 skills 强制自动化更新。
- 不在本阶段引入跨主机集中运维或远端 agent 分发。
- 不把“继续新增更多聚合命名规则”作为本阶段主线。

## Key Decisions

- 决策 1：下一主线切到 **Phase 2B/2C authority boundary completion**。
  - 原因：当前 update 能力不足的根因更偏 control plane 耦合，而不是聚合模型缺失。
- 决策 2：runtime reliability 紧跟在 authority boundary 之后，而不是继续并行堆 UI。
  - 原因：不先收口 authority，runtime patch 容易演化成特殊分支债务。
- 决策 3：UI 只做支持性收口，不再单独扩 scope。
  - 原因：3A 已经大部分落地，继续单做 UI 的边际收益明显下降。

## Dependencies / Assumptions

- 假设 `inventory_core.py` 在过渡期继续保留，承担 discovery / compatibility input。
- 假设现有 persisted state 文件可继续作为 authoritative state 的演进载体。
- 假设当前测试基线足以承接一次 authority boundary 收口，而不需要另起新子系统。

## Outstanding Questions

### Resolve Before Planning
- 无。

### Deferred to Planning
- [Affects R1][Technical] `build_skills_overview()` 的 authority inversion 应该一步切换，还是先做 dual-read / shadow-mode 过渡。
- [Affects R5][Technical] managed checkout queue 应放在 plugin 进程内内存态，还是需要轻量持久化 run queue。
- [Affects R7][Technical] failure taxonomy 的 canonical schema 应复用现有 audit payload 结构，还是独立成 runtime diagnostics schema。
- [Affects R9][Needs research] 当前 `skills_hosts_core.py` 里的 provider defaults 中，哪些宿主值得进入“真受管更新”名单，哪些只保留 detect-only。
- [Affects R10][Technical] AstrBot runtime contract 是继续作为特化 host adapter 扩展，还是抽象成更通用的 runtime action interface。

## Next Steps
-> `/ce:plan`，主题应切到“Phase 2B/2C authority boundary completion，随后接 runtime reliability 收口”，而不是继续围绕聚合规则或纯 UI 做增量规划。
