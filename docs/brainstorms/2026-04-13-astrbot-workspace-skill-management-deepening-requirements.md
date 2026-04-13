---
date: 2026-04-13
topic: astrbot-workspace-skill-management-deepening
status: active
references:
  - skills_hosts_core.py
  - skills_astrbot_state_core.py
  - skills_astrbot_actions_core.py
  - skills_core.py
  - main.py
  - tests/test_skills_hosts_core.py
  - tests/test_skills_astrbot_state_core.py
---

# AstrBot Workspace Skills 管理深化需求

## Problem Frame
当前 OneSync 已具备 AstrBot host 的基础 skill 管理能力（状态读取、启停、删除、ZIP 导入导出、sandbox sync、neo source）。
但 workspace 维度仍停留在 “global/workspace 二值 scope”：

- 缺少 workspace 实例级定位（具体是哪一个 `workspaces/{umo}`）。
- 缺少 workspace 枚举与选择能力。
- 缺少 workspace 级审计可观测性（仅有 `scope=workspace`，没有 `workspace_id`）。
- 与 AstrBot 上游 workspace 语义（`init_workspace`、`workspace/skills`）尚未完全对齐。

## Verified Reality（代码与运行态核验）

### 已完成修复（2026-04-13 本轮）

- AstrBot scope 路径判定已纠偏：
  - `skills_hosts_core.py`
  - `skills_astrbot_state_core.py`
  - `skills_core.py`
- 关键效果：
  - `/root/astrbot/data/skills` 不再被误判为 workspace。
  - 无真实 workspace root 时，`available_scopes` 仅返回 `["global"]`。
  - saved lock 历史脏值 `target_paths.workspace=global` 会被归一化清理。
- 回归测试：
  - `pytest -q`
  - `221 passed`
- 运行态验证（8099）：
  - `GET /api/skills/hosts/astrbot/astrbot`
  - `target_paths.workspace=""`
  - `available_scopes=["global"]`
  - `skills_root=/root/astrbot/data/skills`

### 与 ref/astrbot 最新对比（master + draft/workspace-skills-support）

- `ref/astrbot` 草案分支已引入：
  - `SkillManager(workspace_skills_root=...)`
  - workspace-local `list_skills` 合并扫描
  - `install_skill_from_zip(..., install_to_workspace=True)`
  - `init_workspace(umo)` 统一初始化 `EXTRA_PROMPT.md` 与 `workspace/skills`
- OneSync 当前状态：
  - 已有 scope-aware host/action 框架；
  - 但缺 workspace instance（`umo`）级数据模型与操作参数。

## Gap Map（尚未完成）

1. Workspace 实体缺失  
当前仅有 `scope=workspace`，没有 `workspace_id` / `workspace_root` / `umo`。

2. Workspace 枚举缺失  
未提供 AstrBot workspaces 列表接口，前端无法做 workspace 精确切换。

3. Action 维度不足  
AstrBot 动作仅支持 `scope`，无法明确作用到某个 workspace。

4. 状态语义不完整  
缺 workspace 粒度运行摘要（例如每 workspace 的 local/sandbox/drift 总量）。

5. 上游语义未完全对齐  
未引入 `init_workspace` contract；workspace/skills 生命周期仍由 OneSync 自定义路径推导主导。

## Decisions

1. 继续沿用 host/runtime capability 架构，不新增平行子系统。  
workspace 深化应在现有 `skills_astrbot_*` 与 `main.py` action context 上扩展。

2. 把 workspace 作为一等实体，而非 `scope=workspace` 的隐式别名。  
后续所有动作、审计、UI 展示都要可定位到 `workspace_id`。

3. 与上游优先做“语义对齐”，而非“代码搬运”。  
OneSync 保持聚合与运维编排职责，AstrBot 保持 runtime/workspace contract 语义来源。

## Requirements

### R1. Workspace Index

- 新增 AstrBot workspace 索引模型（最少字段）：
  - `workspace_id`（稳定 ID，建议采用 `umo` 规范化值）
  - `workspace_root`
  - `skills_root`
  - `extra_prompt_path`
  - `exists`
  - `skill_count`
  - `last_seen_at`
- 数据来源优先级：
  1. 显式 `target_paths.workspace`
  2. `data/workspaces/*/skills` 自动发现
  3. 历史 persisted lock 映射

### R2. Scope -> Workspace 解耦

- 保留 `scope`，但动作入口新增 `workspace_id`（可选）：
  - `scope=global`：忽略 `workspace_id`
  - `scope=workspace`：必须可解析到具体 workspace
- 若请求 `scope=workspace` 且缺有效 workspace：
  - 返回结构化错误码：`workspace_not_found` / `workspace_required`

### R3. Action Contract 扩展

- 扩展以下动作签名与审计：
  - toggle / delete / import_zip / export_zip / sandbox_sync
- 每条审计事件补齐：
  - `scope`
  - `workspace_id`
  - `workspace_root`（可选）

### R4. Runtime State 扩展

- `build_astrbot_host_runtime_state` 增加 workspace 粒度摘要：
  - `workspace_summaries`（按 workspace_id）
  - `selected_workspace_id`
- 与现有 `scope_summaries` 保持兼容，不破坏前端已上线字段。

### R5. API & UI 能力

- 新增接口：
  - `GET /api/skills/hosts/{host_id}/astrbot/workspaces`
- 扩展现有 host detail payload：
  - `workspace_profiles`
  - `selected_workspace_id`
- 前端：
  - AstrBot runtime panel 增加 workspace 选择器（默认折叠状态保持不变）。
  - 所有 AstrBot 动作请求携带 `workspace_id`（当 `scope=workspace`）。

### R6. Upstream 对齐

- 在 OneSync 文档中明确与 `ref/astrbot` 的 contract 对齐项：
  - `workspace/skills`
  - `EXTRA_PROMPT.md`
  - `install_to_workspace` 语义
- 明确不对齐项（若有）及原因，避免后续漂移。

## Non-Goals（本阶段不做）

- 不改写 OneSync 聚合更新主链路（install-unit / collection-group）。
- 不引入跨主机 workspace 统一调度。
- 不把用户自建 `docs/` 等非技能目录纳入 workspace skills。

## Phase Plan

### Phase A（最小可用，建议先落地）

- 引入 workspace index（只读）
- 新增 workspace list API
- Host payload 暴露 `workspace_profiles`
- 测试覆盖：
  - 单 workspace
  - 多 workspace
  - 无 workspace
  - 历史 lock 脏值修复

### Phase B（动作闭环）

- AstrBot 动作增加 `workspace_id`
- action context 解析与校验收口
- audit payload 补齐 workspace 维度
- UI 增加 workspace 选择器与失败文案

### Phase C（上游语义对齐）

- 引入 `init_workspace` 语义兼容层（OneSync 侧）
- 明确 workspace ZIP 安装策略与 active flag 策略
- 完成文档与 operator 操作手册收口

## Risks & Pitfalls

1. 历史锁文件脏值回流  
风险：旧 `target_paths.workspace` 污染新逻辑。  
应对：在 host merge 阶段强制 normalize（本轮已做第一步）。

2. 多 workspace 选择歧义  
风险：默认 workspace 不可预测导致误操作。  
应对：`scope=workspace` 默认必须携带 `workspace_id`；否则拒绝执行。

3. 上游语义漂移  
风险：OneSync 与 AstrBot workspace contract 再次分叉。  
应对：每个阶段都保留 ref 对照锚点并在 PR 中显式记录差异。

## Success Criteria

- S1. AstrBot host payload 能稳定列出 workspace 实例。
- S2. `scope=workspace` 操作可精确命中指定 workspace。
- S3. 审计日志可追溯到具体 workspace。
- S4. 8099 面板中 workspace 选择与执行结果一致，无“看起来更新了但未命中目标 workspace”现象。
