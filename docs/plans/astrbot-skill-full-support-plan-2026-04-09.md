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
