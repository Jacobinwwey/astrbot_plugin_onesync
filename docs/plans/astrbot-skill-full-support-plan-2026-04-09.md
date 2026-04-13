---
date: 2026-04-09
topic: astrbot-skill-full-support
status: active
depends_on:
  - docs/plans/skills-management-next-step-implementation-plan-2026-04-06.md
  - docs/plans/skills-management-reference-comparative-analysis-2026-04-06.md
references:
  - /home/jacob/ref/astrbot/astrbot/core/skills/skill_manager.py
  - /home/jacob/ref/astrbot/astrbot/core/skills/neo_skill_sync.py
  - /home/jacob/ref/astrbot/astrbot/core/computer/computer_client.py
  - /home/jacob/ref/astrbot/astrbot/dashboard/routes/skills.py
---

# AstrBot Skill 全量支持实施计划

## Summary

OneSync 当前已经把 AstrBot 识别为可管理宿主，但仍停留在“路径级宿主 + 通用 source/deploy 视图”层面，尚未进入 AstrBot 自身的 skill 状态机。

本计划将 AstrBot 从“普通 claw 宿主”升级为“具备本地 skill、sandbox cache、Neo release、runtime health 的一等宿主”，同时保持现有 package-first/source-first 管理主线不被破坏。

## 现状差距

AstrBot 的 skill 生命周期真实由四层状态构成：

- `data/skills/`：本地 skill 根目录
- `data/skills.json`：active flag
- `data/sandbox_skills_cache.json`：sandbox 运行态缓存
- `data/skills/neo_skill_map.json`：Neo release 到本地 skill 的映射

OneSync 当前只稳定覆盖了第一层的路径发现。

直接后果：

- 无法区分 `local_only / synced / sandbox_only / neo_managed`
- 无法判断 AstrBot 当前 runtime 状态是否健康
- 无法在 doctor 中准确暴露 AstrBot-specific drift
- 无法为后续 Neo / sandbox / ZIP import 管理建立可靠动作边界

## 目标模型

### Host Capability

AstrBot 宿主需要声明独立能力，而不是只复用 `supports_source_kinds`：

- `local_skill_scan`
- `local_skill_toggle`
- `local_skill_delete`
- `local_zip_import`
- `local_zip_export`
- `sandbox_cache_read`
- `sandbox_sync_trigger`
- `neo_release_read`
- `neo_release_sync`

### AstrBot State Classification

AstrBot 宿主视角下的 skill 需要最少区分为：

- `local_only`
- `synced`
- `sandbox_only`
- `neo_managed`
- `drifted`

其中：

- `local_only`：本地存在，sandbox cache 无对应项
- `synced`：本地与 sandbox cache 同时存在
- `sandbox_only`：只在 cache 中存在，禁止本地启停/删除
- `neo_managed`：本地 skill 名由 Neo map 管理
- `drifted`：active flag、cache、Neo map 或本地目录之间存在不一致

## 分阶段推进

### Phase 1：AstrBot State Adapter

目标：先把 AstrBot 真实状态读出来，并挂到现有 skills snapshot。

实现要求：

- 新增 `skills_astrbot_state_core.py`
- 从 AstrBot host 的 `target_path` 推导：
  - `astrbot_root`
  - `astrbot_data_dir`
  - `skills_root`
  - `skills.json`
  - `sandbox_skills_cache.json`
  - `neo_skill_map.json`
- 扫描本地 skill 目录并合并：
  - local skill
  - active flags
  - sandbox cache
  - neo map
- 输出：
  - 宿主级 summary
  - skill 级 runtime rows
  - warning 列表

本阶段不做：

- 不执行 sync / promote / rollback
- 不新增复杂 UI 操作入口
- 不改 install-unit / collection-group 更新逻辑

### Phase 2：Runtime Health Integration

目标：把 AstrBot-specific 健康检查并入现有 doctor。

实现要求：

- 扩展 `skills_runtime_health.py`
- 在现有 state/projection 健康之外新增 `astrbot_runtime_health`
- 重点覆盖：
  - `skills.json` 缺失或脏数据
  - `sandbox_skills_cache.json` 缺失/空/过期
  - `sandbox_only` 与本地投影冲突
  - `neo_skill_map.json` 指向缺失 skill
  - 本地 skill 缺 `SKILL.md`

### Phase 3：AstrBot Action Adapter

目标：在已有状态模型上接入 AstrBot-native 写操作。

实现要求：

- 封装本地动作：
  - enable / disable
  - delete
  - ZIP import / export
- 封装 runtime 动作：
  - sync active sandboxes
  - refresh sandbox cache
- 明确 mutate 与 update 的边界

### Phase 4：Neo Lifecycle

目标：把 Neo release 变成可运维 source，而不是隐藏的附加功能。

实现要求：

- `astrneo:<skill_key>` 形式的稳定 source id
- source detail 中展示：
  - `skill_key`
  - `local_skill_name`
  - `latest_release_id`
  - `latest_candidate_id`
  - `payload_ref`
- 后续再接 promote / sync / rollback

## 本轮实现范围

本轮只做 Phase 1 + Phase 2 的基础部分：

1. 新增 AstrBot state adapter
2. 在 host rows / skills overview 中暴露 AstrBot runtime state
3. 在 runtime health 中加入 AstrBot-specific 健康摘要
4. 新增对应单测

## Execution Log

### 2026-04-09 / Step 1

- `Phase 1` 已验证并并入 `main`
- 主干提交：`789d7eb feat(skills): add astrbot runtime state model`
- 已落地：
  - AstrBot runtime state adapter
  - host row runtime summary
  - doctor 中的 AstrBot runtime health
  - 对应后端单测

### 2026-04-09 / Step 2

- 从更新后的 `main` 新建干净工作树继续推进：
  - branch: `feat/astrbot-webui-phase2`
- 当前切片聚焦：
  - 在 WebUI Inspector 中暴露 AstrBot runtime summary
  - 在 Doctor 摘要中拼接 AstrBot-specific health
  - 保持 action adapter 仍未开放，避免在读模型稳定前提前引入写路径

### 2026-04-11 / Step 3

- 已完成 Phase 3 的最小可用动作适配器（后端 + API）：
  - 新增 `skills_astrbot_actions_core.py`：
    - `set_astrbot_skill_active`：本地 skill 启停写入 `skills.json`
    - `delete_astrbot_local_skill`：本地 skill 删除并同步清理 `skills.json` 与 `sandbox_skills_cache.json`
    - `sandbox_only` 风险防护：对仅 sandbox 存在的 skill 阻断本地启停/删除
    - 输入与状态错误统一 reason code（`invalid_skill_name` / `sandbox_only_skill` / `invalid_skills_config` 等）
  - `skills_astrbot_state_core.py` 抽出公共布局解析：
    - `resolve_astrbot_host_layout`，供 read-model 与 action adapter 共享路径真相
- 已完成 OneSync 主流程接线：
  - `main.py` 新增 AstrBot host action context 解析
  - 新增 API 语义方法：
    - `webui_get_astrbot_host_payload`
    - `webui_set_astrbot_skill_active`
    - `webui_delete_astrbot_skill`
    - `webui_sync_astrbot_sandbox`
  - sandbox 同步触发通过运行时适配：
    - 动态导入 `sync_skills_to_active_sandboxes`
    - 不可用/失败场景返回结构化 reason code（`sandbox_sync_unavailable` / `sandbox_sync_failed`）
  - 动作已纳入既有审计链路（audit + debug log）
- `webui_server.py` 新增路由：
  - `GET /api/skills/hosts/{host_id}/astrbot`
  - `POST /api/skills/hosts/{host_id}/astrbot/skills/toggle`
  - `POST /api/skills/hosts/{host_id}/astrbot/skills/delete`
  - `POST /api/skills/hosts/{host_id}/astrbot/sandbox/sync`
- 回归验证：
  - `pytest -q` → `160 passed`
  - `python3 -m py_compile main.py webui_server.py skills_astrbot_state_core.py skills_astrbot_actions_core.py`

### 2026-04-11 / Step 4

- 已完成 Phase 4 的读模型基线（Neo lifecycle data surface）：
  - `skills_core.py` 新增 `build_astrbot_neo_source_rows(...)`
  - 基于 AstrBot runtime state 生成稳定 `astrneo:{host_id}:{skill_key}` source id
  - 每条 Neo source 暴露：
    - `astrneo_skill_key`
    - `astrneo_skill_name`
    - `astrneo_release_id`
    - `astrneo_candidate_id`
    - `astrneo_payload_ref`
    - `astrneo_updated_at`
  - 不影响现有 install-unit/update 主链路（先并行为独立读面，避免对既有聚合执行语义引入回归）
- OneSync API 已新增 Neo source 只读接口：
  - `GET /api/skills/astrbot-neo-sources`
  - `GET /api/skills/astrbot-neo-sources/{source_id}`
- 概览统计已新增 Neo source 指标：
  - `counts.astrbot_neo_source_total`
  - `counts.astrbot_neo_source_ready_total`
  - `counts.astrbot_neo_source_missing_total`
- 回归验证：
  - `pytest -q tests/test_skills_core.py tests/test_webui_server.py` → `40 passed`


### 2026-04-11 / Step 5

- 已完成 Phase 4 的 Neo 写路径最小闭环（sync action + API）：
  - `main.py` 新增 `webui_sync_astrbot_neo_source(source_id, payload)`：
    - 解析 `astrneo:{host_id}:{skill_key}` source
    - 读取 `provider_settings.sandbox.shipyard_neo_endpoint/access_token`
    - 动态导入 `shipyard_neo.BayClient` 与 `NeoSkillSyncManager`
    - 调用 `sync_release(release_id|skill_key)` 执行同步
    - 成功后刷新 snapshot，并写入审计事件 `astrbot_neo_source_sync`
  - `webui_server.py` 新增路由：
    - `POST /api/skills/astrbot-neo-sources/{source_id}/sync`
    - 错误码约定：`not found -> 404`，其他失败 `-> 400`
- 回归测试已覆盖 Neo sync 路由：
  - 成功路径（200）
  - 同步失败路径（400）
  - source 缺失路径（404）
- 回归验证：
  - `pytest -q tests/test_webui_server.py tests/test_skills_core.py` -> `40 passed`
  - `pytest -q` -> `161 passed`


### 2026-04-11 / Step 6

- 已完成 Neo source 在 WebUI 的可见与可操作接入（前端）：
  - Source / Bundle 面板现在会合并展示 `astrbot_neo_source_rows`（以 standalone source 形态附加，不覆盖 install-unit 主链路）。

### 2026-04-13 / Step 7

- 已补齐 AstrBot ZIP import / export 的最小闭环：
  - `skills_astrbot_actions_core.py` 新增：
    - `import_astrbot_skill_zip(...)`
    - `export_astrbot_skill_zip(...)`
  - 约束对齐 AstrBot 上游语义：
    - 只接受合法 `.zip`
    - 阻断绝对路径 / `..` 路径穿越
    - root archive 与 top-level skill folder 两种形态都可处理
    - `overwrite=false` 时会在冲突前提前失败
    - `sandbox_only` skill 禁止本地导出
  - `main.py` 已新增：
    - `webui_import_astrbot_skill_zip(...)`
    - `webui_export_astrbot_skill_zip(...)`
    - 两条写路径都已接入 audit + debug log
  - `webui_server.py` 已新增：
    - `POST /api/skills/hosts/{host_id}/astrbot/skills/import-zip`
    - `GET /api/skills/hosts/{host_id}/astrbot/skills/export-zip`
  - `webui/index.html` 的 AstrBot runtime 区已新增：
    - `导入 ZIP`
    - `导出 ZIP`
    - 对应 busy state 与成功/失败提示
- 本轮定向回归：
  - `pytest -q tests/test_skills_astrbot_actions_core.py` -> `9 passed`
  - `pytest -q tests/test_webui_server.py -k "astrbot or mutation_routes"` -> `1 passed`
  - `pytest -q tests/test_webui_inventory_registry_hosts.py -k astrbot` -> `2 passed`
  - 选中 `astrneo:*` 行时，详情加载会自动走：
    - `GET /api/skills/astrbot-neo-sources/{source_id}`
  - Source Sync 按钮已支持 Neo 模式分流：
    - 普通 source -> `POST /api/skills/sources/{source_id}/sync`
    - Neo source -> `POST /api/skills/astrbot-neo-sources/{source_id}/sync`
- 前端语法核验：
  - 提取 `webui/index.html` 内联脚本并执行 `node --check`，通过。

### 2026-04-13 / Step 8

- 已补齐 AstrBot Neo promote / rollback 最小运维闭环：
  - `main.py` 新增公共 Neo helper：
    - `_resolve_astrbot_neo_client_config()`：统一解析 endpoint / token，并支持 Bay credentials 自动发现回退
    - `_resolve_astrbot_neo_operation_context()`：统一 source 校验、client import、sync manager 初始化
    - `_build_astrbot_neo_mutation_response()`：统一动作后 snapshot 刷新与详情回填
  - `webui_get_astrbot_neo_source_payload(...)` 现在额外暴露：
    - `neo_state`
    - `neo_capabilities`
    - `neo_defaults`
    - 供前端在不离开 Source Detail 的情况下直接判断 `sync / promote / rollback` 可执行性
  - 新增写路径：
    - `webui_promote_astrbot_neo_source(...)`
    - `webui_rollback_astrbot_neo_source(...)`
  - 新增 API：
    - `POST /api/skills/astrbot-neo-sources/{source_id}/promote`
    - `POST /api/skills/astrbot-neo-sources/{source_id}/rollback`
  - 审计事件已纳入既有链路：
    - `astrbot_neo_source_promote`
    - `astrbot_neo_source_rollback`
- WebUI Source Detail 已新增 Neo 生命周期动作条：
  - `同步 Stable`
  - `提升到 Stable`
  - `回滚 Release`
  - 只在当前选中的 `astrneo:*` 详情区出现，不污染主 Source / Bundle 列表
  - 同时补充 Candidate / Release / Payload / Local 芯片，降低 promote / rollback 前的信息切换成本
- 本轮定向回归：
  - `pytest -q tests/test_webui_server.py tests/test_webui_inventory_registry_hosts.py` -> `37 passed`
  - `python3 -m py_compile main.py webui_server.py tests/test_webui_server.py tests/test_webui_inventory_registry_hosts.py`

### 2026-04-13 / Step 9

- 已补齐 AstrBot Neo 详情可观测性闭环：
  - `webui_get_astrbot_neo_source_payload(...)` 现额外回填：
    - `neo_remote_state`
    - `neo_activity`
  - 远端 `releases / candidates` 不再依赖 Neo 返回顺序，统一按 `updated_at -> created_at` 倒序整理
  - `neo_defaults.candidate_id / release_id` 会在远端可读时自动对齐到当前远端 stable/candidate，避免前端动作仍引用陈旧本地值
- 已修复一处跨领域基础缺陷：
  - `webui_get_skills_audit_payload(...)` 对 `source_id` 的过滤改为“规范化 source_id 比对”
  - 解决 `astrneo:astrbot:demo.skill` 这类带分隔符 source id 在审计轨迹中查不到历史的问题
- WebUI focused inspector 已在现有 source detail 中新增：
  - Neo 远端状态块
  - 最近 Neo 活动块
  - 不新增新的顶层面板，避免继续扩大运维界面噪声面
- 本轮定向回归：
  - `pytest -q tests/test_main_git_checkout_runtime.py -k astrbot_neo_source_payload_enriches_remote_state_and_activity` -> `1 passed`
  - `pytest -q tests/test_main_git_checkout_runtime.py` -> `13 passed`
  - `pytest -q tests/test_webui_server.py` -> `10 passed`
  - `node --check`（提取后的 `webui/index.html` 内联脚本）-> passed

### 2026-04-13 / Step 10

- 聚合更新失败/受阻原因在前端已从“原始 reason_code”升级为“人类可读标签 + reason_code”双轨展示：
  - 新增 `inventoryAggregateReasonLabel(...)`，统一映射：
    - `manual_only` / `manual_managed`
    - `non_syncable_sources_present`
    - `precheck_failed`
    - `update_failed`
    - `source_sync_failed`
    - `rollback_failed`
  - 适配范围：
    - update-all 完成弹窗摘要
    - 执行历史中的失败/受阻分组
    - operation plan 的 blocked reason 明细
- 聚合更新报告新增 precheck 可观测字段前端消费：
  - `normalizeInventoryAggregateUpdateReport(...)` 新增 `precheck_failure_count`
  - 报告摘要新增 `Precheck 失败 {count}` 行
  - guidance 新增 `precheck_failed` / `source_sync_failed` 的专属建议文案
- Source Detail 信息结构进一步去混杂：
  - 右侧详情将“来源归因（provenance）”与“更新机制（manager/policy/mode/sync）”拆分为独立板块
  - 避免此前把 provenance 与 deploy notes 混在同一块导致运维判断成本偏高
- 本轮验证：
  - `pytest -q` -> `209 passed`
  - `pytest -q tests/test_webui_inventory_registry_hosts.py` -> `27 passed`
  - `node --check`（提取后的 `webui/index.html` 内联脚本）-> passed

### 2026-04-13 / Step 11

- 已补齐 repo metadata sync 的 Gitea / Forgejo provider 适配：
  - `source_sync_core.py` 新增 provider 归一化与主机推断：
    - `gitea` / `forgejo` / `codeberg` 别名归并为 `gitea`
    - `repo:codeberg.org/<owner>/<repo>#...` 这类无 schema locator 会自动归一化
  - repo metadata target 现在可解析 `provider=gitea`：
    - 输出 `owner/repo/host/homepage`
    - 缓存键新增 `repo_metadata:gitea:<owner>/<repo>`
  - `fetch_repo_metadata_summary(...)` 新增 `repo_metadata_gitea` 分支：
    - 默认 API base：`https://{host}/api/v1`
    - 支持显式 `sync_api_base` 覆盖
    - 统一回填 `updated_at/pushed_at` 等 revision 字段
  - 鉴权默认策略补齐：
    - 当 provider 为 `gitea` 且仅给出 `sync_auth_token` 时，默认使用 `Authorization: token <token>`
    - 仍支持 `sync_auth_header` 显式覆盖
- 本轮定向回归：
  - `pytest -q tests/test_main_git_checkout_runtime.py -k "gitea_repo_metadata_sync_records"` -> passed
  - `pytest -q tests/test_source_sync_core.py` -> passed
  - `pytest -q` -> passed
  - `python3 -m py_compile source_sync_core.py tests/test_source_sync_core.py` -> passed

### 2026-04-13 / Step 12

- 已补齐 rollback 审计记录的“可执行重试”闭环（后端 + 前端）：
  - `main.py`：
    - install-unit rollback 审计 payload 现追加：
      - `failed_sources`
      - `not_restored_source_ids`
      - `retry_before_revisions`
    - collection-group rollback 审计 payload 同步追加上述字段，并按 install-unit 结果聚合去重
  - `webui/index.html`：
    - 回滚审计轨迹新增失败原因摘要（reason:count）
    - 每条可重试记录新增 `重试失败项 / Retry Failed` 按钮
    - 重试直接复用审计中的 `retry_before_revisions` 调用 rollback API，不再要求用户重新粘贴 source_id
    - 新增重试忙状态管理，避免与 update/sync/deploy 等聚合动作并发冲突
  - `tests/test_webui_inventory_registry_hosts.py`：
    - 新增回滚审计重试相关字符串、函数与 DOM hook 的静态断言
- 本轮定向回归：
  - `python3 -m py_compile main.py webui_server.py` -> passed
  - `pytest -q tests/test_webui_inventory_registry_hosts.py` -> passed
  - `pytest -q tests/test_webui_server.py` -> passed
  - `pytest -q tests/test_main_git_checkout_runtime.py` -> passed
  - `pytest -q` -> passed

### 2026-04-12 / Cross-Cutting Runtime Follow-up

- 虽然本计划主线聚焦 AstrBot runtime/Neo 生命周期，但本轮有一项跨领域改进已经反向增强 AstrBot 宿主管理的稳定性：
  - git-backed skills 来源现在支持“受管 checkout 自动补齐”
  - 对应 checkout 会被物化到 `plugin_data/.../skills/git_repos/`
  - sync/update 路径不再依赖叶子 skill 目录本身就是 git worktree
- 这项能力虽然最先用于 `skill_lock` / repo-backed skills 管理，但它同时为 AstrBot 后续引入更多 git/source 型 skill 生命周期动作提供了更稳的基础设施。
- 当前判断：
  - AstrBot Neo / local skill 主链路已基本成形
  - 下一步 AstrBot 方向更适合继续推进“runtime action 完整度”和“Neo promote/rollback 可观测性”，而不是重复实现一套独立的 git checkout 逻辑

## 数据结构约定

### Host Row 扩展字段

- `capabilities`
- `runtime_state_backend`
- `runtime_state_summary`
- `runtime_state_warning_count`

### Overview 扩展字段

- `astrbot_state_rows`
- `astrbot_state_by_host`
- `doctor.astrbot_runtime_health`
- `counts.astrbot_*`

## 风险与权衡

### 1. 不强行把 AstrBot 压进通用 `manual_local`

这是必须的。

如果继续把 AstrBot skill 当成普通本地 source：

- state 判断会持续失真
- sandbox cache 永远只能作为旁路数据
- Neo release 无法稳定进入主状态模型

### 2. 暂不直接调用 AstrBot 内部模块

当前阶段优先做文件级兼容读取，而不是强依赖运行时 import AstrBot 内部 Python 模块。

原因：

- OneSync 单测可以独立运行
- 减少 AstrBot 版本耦合
- 更利于后续 fallback 与故障诊断

代价：

- 需要复制一部分 AstrBot 的路径与状态推导语义
- 后续版本漂移时需要追踪 ref/astrbot 变化

### 3. 先做读模型，再做动作模型

这是为了避免“动作很多，但真相源不稳定”。

先把 read-model 做对，后面的 UI 和 action adapter 才不会继续叠 if-else。

## 测试计划

### 新增单测

- `tests/test_skills_astrbot_state_core.py`
  - 本地 skill + active flags + sandbox cache + Neo map 的合并
  - `sandbox_only` 分类
  - `neo_managed` 分类
  - 缺失文件与脏文件 fallback

### 扩展单测

- `tests/test_skills_hosts_core.py`
  - AstrBot host capability 暴露
- `tests/test_skills_core.py`
  - overview 包含 AstrBot runtime summary
- `tests/test_skills_runtime_health.py`
  - doctor 暴露 AstrBot runtime health

## 完成标准

达到以下条件即认为本轮完成：

- AstrBot host 不再只是路径宿主
- skills overview 中可读取 AstrBot runtime state
- doctor 能指出 AstrBot-specific 状态问题
- 相关单测通过
- 不影响现有 `npx`/manual source 主链路
