# OneSync Skills 来源与更新能力现状

> 语言 / Language: [中文](./SKILLS_UPDATE_STATUS_zh.md) | [English](./SKILLS_UPDATE_STATUS_en.md)

审计日期：`2026-04-12`  
适用范围：当前 `main` 分支、source-first Skills 管理模型

## 1. 当前已经完成的部分

目前 Skills 管理链路在以下方面已经比较完整：

- source-first 快照生成（`manifest / lock / sources / generated`）已经可用。
- Skills 来源归因不再局限于 npm 包。
- install unit 与 collection group 详情接口已经暴露有效的 `update_plan`。
- Deploy Target 投影、漂移检测和 doctor 健康检查都已经接入同一套 source-first 模型。

当前已经能识别的来源/安装单元类型包括：

- `registry_package`
- `skill_lock_source`
- `documented_source_repo`
- `catalog_source_repo`
- `community_source_repo`
- `local_custom_skill`

例如：像 `doc` 这类用户自建 skill，现已可以被建模为 `local_custom_skill`，而不是继续被当成未解析的外部包。

## 2. 三种操作必须分开理解

### 2.1 `POST /api/skills/import`

这个动作会重建本地 inventory 与 Skills snapshot。它是导入/重投影动作，不是上游更新动作。

### 2.2 `Sync Source`

这个动作用于从上游刷新 source 的元数据。

当前真实情况：

- 支持 npm-backed 与 git-backed 两类 source sync。
- npm-backed 仍要求：
  - `registry_package_name` 非空
  - `registry_package_manager == "npm"`
- git-backed 支持以下任一判定路径：
  - manager 为 `git/github`，且有 `source_path` 或 git locator
  - `source_kind == "manual_git"` 且有 `source_path` 或 git locator
  - `update_policy == "source_sync"` 且有 `source_path` 或 git locator
- npm 走 registry metadata；git 走 remote/head + local checkout metadata。
- `repo:` / `documented:` / `catalog:` / `community:` 这类来源，现已支持 GitHub / GitLab / Bitbucket 的 repo metadata sync（更新时间、默认分支、描述等）。
- 自建私有 GitHub/GitLab/Bitbucket 实例现可通过 `sync_api_base + sync_auth_header/sync_auth_token` 做 metadata sync；完全未知 provider 仍需额外适配。

### 2.3 `Update Install Unit` / `Update Collection`

这个动作会执行真实的更新命令，由 install unit 推导得出。

当前真实情况：

- registry-backed install unit 支持通过 `bunx`、`npx`、`pnpm dlx` 或 `npm install -g` 更新。
- git-backed install unit 现已支持“受管 checkout 自动补齐”：
  - 若原始 `source_path` 本身就是 git worktree，则直接复用。
  - 若叶子 skill 目录不是 git 仓库，但 locator/provenance 仍能解析出上游 git repo，则 OneSync 会在 `plugin_data/.../skills/git_repos/` 下自动物化受管 checkout。
  - 后续 sync/update 会优先走 `git_checkout_path`，而不是继续对 leaf skill 目录执行 git 命令。
- git-backed install unit 在存在可用 checkout 路径时，支持执行 `git -C <checkout_path> pull --ff-only`，并在执行前自动跑 precheck：
  - `git -C <source_path> rev-parse --is-inside-work-tree`
  - `test -z "$(git -C <source_path> status --porcelain)"`
- git-backed install unit 的更新执行结果会附带 before/after revision capture，并输出 changed/no-change/unknown 统计。
- git-backed install unit 的更新执行结果会附带 rollback preview（仅命令预览，不自动执行），用于回退演练。
- 已提供可执行 rollback API（install unit / collection group），并要求显式确认：
  - `payload.execute = true`
  - `payload.confirm = "ROLLBACK_ACCEPT_RISK"`
- WebUI 已接入基础 rollback 流程：
  - 从最新 update 响应缓存 before-revision 快照
  - 按当前聚合触发回滚确认并调用 rollback API
  - 回滚后展示 restored/not-restored/failed 摘要
- manual / local custom / 仅 repo 引用聚合这几类来源，如果无法推导出明确可执行命令，当前仍属于不支持更新。

## 3. 当前支持矩阵

| 安装/来源形态 | 示例 | `Sync Source` | `Update Install Unit` | 说明 |
| --- | --- | --- | --- | --- |
| npm 包支撑的 bundle/single | `npm:@every-env/compound-plugin` | 支持 | 支持 | Sync 读取 npm registry 元数据；Update 优先使用 `management_hint`，否则构造 registry 更新命令。 |
| git 本地 checkout / skill-lock 条目 | `skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills` | 支持（git remote/head、受管 checkout 或本地 checkout） | 支持 | 若原始 skill 路径不是 git worktree，OneSync 会自动在 `plugin_data/.../skills/git_repos/` 下补齐受管 checkout，再执行 `git pull --ff-only`。 |
| 只有 repo 引用的 documented/catalog/community 来源 | `repo:https://github.com/...#skills/foo` | 部分支持（仅 metadata） | 通常不支持 | Source Sync 可刷新 GitHub/GitLab/Bitbucket 仓库元数据（如更新时间），但 update 执行仍不支持。 |
| 手工本地路径 / 用户自建 local custom skill | `local_custom:/path/to/skill` | 不支持 | 不支持 | OneSync 可以纳管、归类、部署，但无法安全推导更新命令。 |
| 已登记但没有可用本地 checkout 的 `manual_git` | `manual_git` 远端 | 不支持 | 不支持 | 只有远端 locator 不够，还需要能解析到本地 checkout 路径。 |

## 4. 如何正确判断“是否支持”

不要只看 `source_kind`。

应以以下字段为准：

- `update_plan.supported`
- `update_plan.commands`
- `update_plan.message`
- `registry_package_name`
- `registry_package_manager`
- `sync_status`
- `sync_local_revision` / `sync_remote_revision` / `sync_resolved_revision`

一个需要特别说明的细节：

- 某些 source 行可能因为 npx 发现链路的归一化规则，仍然带着 `update_policy=registry`。
- 这 **不等于** 对应 install unit 一定可以更新。
- 最终真相应以 install unit 级别的 `update_plan` 为准。

这点对 `doc` 这类本地自建 skill 尤其重要：它虽然可能和 npx 管理的 skills 一起被发现，但本质上仍是手工维护，因此当前仍不支持自动更新。

## 5. 当前结论

如果问题是“当前 skill 更新功能是否已经完善”，结论现在应更新为：

- 发现 / 导入 / 来源归因：对当前 v1 范围来说已经比较完整。
- install unit / collection group 更新执行：核心路径已可用。
- source 元数据同步：核心路径已可用，但 provider 扩展和远端稳定性仍有提升空间。

更具体地说：

- 对 npm 包驱动的 skills 更新，以及 git-backed `skill_lock` 来源更新，已经足够可用。
- 对只有来源归因意义的 repo 派生 source，已部分完善：GitHub/GitLab/Bitbucket locator 可做 metadata sync，但 update 执行仍不支持。
- 对 local custom / manual skills，还不算完善。
- 对 git 来源（remote/head、本地 checkout）已支持 metadata sync；对 GitHub/GitLab/Bitbucket repo 引用来源已支持 metadata sync（含自建实例鉴权/自定义 API Base）；完全未知 provider 仍未完善。
- 对没有真实包边界的 `synthetic_single` / `derived` install unit，系统现已明确降级到 `manual_only`，不会再伪造 `npx npx_global_*` 这类错误更新命令。

## 6. 维护者验证方式

建议执行：

```bash
python3 -m pytest tests -q
curl -s http://127.0.0.1:8099/api/health
curl -s http://127.0.0.1:8099/api/skills/sources
curl -s http://127.0.0.1:8099/api/skills/install-units/npm%3A%40every-env%2Fcompound-plugin
```

建议确认：

- 当前 runtime snapshot 中 `counts.source_provenance_unresolved_total == 0`
- `counts.source_syncable_total` 现在会统计 npm、git-backed、以及 repo-metadata-backed source（GitHub/GitLab/Bitbucket）
- 支持更新的 install unit 会暴露非空 `update_plan.commands`
- git-backed install unit 会暴露 `update_plan.precheck_commands`
- git-backed `skill_lock` install unit 在首次 update/sync 后，会在 source row 中暴露 `git_checkout_path`
- git-backed install unit 的 update 响应会附带 `revision_capture`（before/after/delta）
- 若检测到 revision 变化，响应会附带 `rollback_preview.candidates`
- rollback API 会返回结构化执行结果（`restored_source_total` / `not_restored_source_total` / `failed_sources`）
- local custom skill 会显示 `update_plan.supported = false`
- git 来源在 source sync 后会暴露结构化 revision 字段（`sync_*revision`）
- 概览统计会暴露 `source_sync_dirty_total` 与 `source_sync_revision_drift_total`

## 7. 下一步建议

如果要把这个能力称为“完善”，下一步建议是：

1. 为未知/非 GitHub/GitLab/Bitbucket 的 provider 补齐 metadata sync 适配器，并统一鉴权策略。
2. 在现有 rollback API 基础上继续强化前端交互流（候选勾选、失败重试、可视化审计与历史追踪）。
3. 在 UI 中更明确展示 unsupported / precheck 失败原因。
4. 在面板文案中进一步区分“来源归因”和“更新机制”。
5. 增加更多 install-unit 详情与 live sync/update 行为的端到端测试。

## 8. 最近实现进展（2026-04-12）

- WebUI 与后端现已新增批量聚合更新入口：
  - `POST /api/skills/aggregates/update-all`
  - 前端按钮：`更新全部聚合`
  - 响应会返回 `executed / skipped / source_sync / deduplicated` 分层统计，而不是只给一个模糊成功/失败。
- 受管 git checkout 自动补齐已落地：
  - `find-skills` 与 `frontend-design` 这类 `skill_lock` 来源在 8099 live 环境中，已从 `git_source_unresolved` 修复为自动补齐 checkout 后成功更新。
  - 当前受管 checkout 目录形态：
    - `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-55d42a13a220`
    - `/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-7d7c7a8d88f1`
- 受管 git checkout 预热队列已落地：
  - `_refresh_inventory_snapshot()` 在生成最新 skills snapshot 后，会后台调度 git-backed source 的 checkout prewarm，不再要求首个 sync/update 请求同步承担 bootstrap 延迟。
  - 当前 8099 live debug log 已可见预热完成记录：
    - `git checkout prewarm finished: source=npx_global_find_skills ...`
    - `git checkout prewarm finished: source=npx_global_frontend_design ...`
- 已有受管 checkout 的 remote 对齐已增强：
  - 对已经存在的 `git_checkout_path`，系统现在会在 detail/sync/update 前执行一次 remote 对齐，不再只在首次 clone 后设置 `origin`。
  - 若当前 remote 不可达，会自动回退到可达 candidate；若当前 remote 仍可用，则保持当前 origin，避免无谓切换。
- 受管 checkout remote 选择已进一步升级为 mirror-aware preferred remote：
  - 现在会对 candidate remotes 做 probe，并在健康候选中择优，而不是只沿用“当前 origin 只要可达就一直保留”的策略。
  - live 实测中，`frontend-design` 的 managed checkout remote 已发生自动重选，当前已切换到：
    - `https://gh.llkk.cc/https://github.com/anthropics/skills.git`
- sync 元数据写回已修正：
  - `saved_registry` 现在是 sync 字段的权威来源，成功 update 后不会再残留旧的 `sync_error_code`。
- source-sync fallback 的批次内 repo metadata 去重已落地：
  - 对同一轮 `update-all` 中多个指向同一 upstream repo 的 fallback source，不再重复请求同一份 repo metadata。
  - 当前运行态中，5 条 `sickn33/antigravity-awesome-skills` fallback source 已可复用同一批次 sync 结果。
- `synthetic_single:*` 无真实包边界聚合已收敛为 `manual_only`：
  - 不再生成伪命令 `npx npx_global_*`
  - 当前 stable skipped 集合包括：
    - `synthetic_single:npx_global_awesome_design_md`
    - `synthetic_single:npx_global_clone_website`
    - `synthetic_single:npx_global_impeccable`
    - `synthetic_single:npx_global_terminal_dialog_style`
    - `local_custom:/root/.codex/skills/doc`
    - `derived:npx_global_playwright_interactive`
- 8099 live 最近一次 `POST /api/skills/aggregates/update-all` 真实结果：
  - `candidate_install_unit_total = 20`
  - `executed_install_unit_total = 14`
  - `command_install_unit_total = 3`
  - `source_sync_install_unit_total = 11`
  - `skipped_install_unit_total = 6`
  - `success_count = 8`
  - `failure_count = 2`
  - `precheck_failure_count = 0`
- 8099 live 当前启动与校验结果：
  - WebUI 已恢复监听：`http://127.0.0.1:8099`
  - `find-skills` 单项 install-unit update 再次实测成功：
    - `success_count = 3`
    - `failure_count = 0`
    - `precheck_failure_count = 0`
  - `find-skills` 当前 update 已稳定走受管 checkout：
    - `git -C /root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-55d42a13a220 pull --ff-only`
  - `update-all` 顶层返回已补齐 summary 字段：
    - `candidate_install_unit_total`
    - `planned_install_unit_total`
    - `executed_install_unit_total`
    - `success_count`
    - `failure_count`
    - `precheck_failure_count`
    - `skipped_install_unit_total`
  - `update-all` 结构化失败分层已可直接读取：
    - `failure_taxonomy.failed_install_unit_reason_groups[0] = update_failed:1`
    - `failure_taxonomy.blocked_reason_groups[0] = non_syncable_sources_present:6`
  - debug log 也已带上失败/受阻摘要：
    - `failed_reasons=[update_failed:1] blocked_reasons=[non_syncable_sources_present:6]`
  - 在引入 repo metadata 批次去重后，最新 live `update-all` 已恢复为：
    - `success_count = 19`
    - `failure_count = 2`
    - `failure_taxonomy.failed_source_total = 0`
    - `update.source_sync_cache_hit_total = 4`
  - `Compound Engineering` install-unit update 已修正为语义正确的安装命令：
    - `bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex`
  - `Compound Engineering` 单项 update 当前 live 实测结果：
    - `success_count = 2`
    - `failure_count = 0`
    - `failed_install_units = []`
  - 在 CE update command 修正后，最新 live `update-all` 已进一步收敛为：
    - `success_count = 19`
    - `failure_count = 0`
    - `skipped_install_unit_total = 7`
    - `failure_taxonomy.failed_install_unit_total = 0`
    - `failure_taxonomy.blocked_reason_groups[0] = manual_managed:7`
  - `source_sync_cache_hit_total` 现已从后端指标提升到前端摘要可见项：
    - 当前 “更新全部聚合” 提示会显示 `Source Sync 结果复用 {count} 次`
    - 对应 debug log 也会显示 `sync_cache_hits=...`
  - Utility Inspector 现已新增“聚合更新报告”面板：
    - 优先显示当前会话内最近一次 `update-all` 结果
    - 若当前会话没有结果，则回退显示 `aggregates_update_all` 审计记录
    - blocked / failed group 可点击定位到对应 install-unit/source 详情
- 当前完整回归结果已更新：
  - `pytest -q` -> `178 passed`

- WebUI 已接入回滚审计轨迹面板：从 `/api/skills/audit?action=rollback` 拉取记录并在当前聚合与全局最近回滚之间自动切换展示。
- 回滚流程已支持“按 source_id 选择子集回滚”，避免对整个聚合盲目全量回滚。
- 回滚结果已支持失败重试链路：从首轮回滚结果中提取未恢复 source，再次执行定向重试。
- 回滚后会自动刷新审计轨迹与详情面板，方便运维追踪恢复效果与失败面。
- 运维计划预览已补齐 precheck 与受阻原因可视化：可直接看到 precheck 命令和 blocked install unit 的 message。
- Source Sync 已新增 repo metadata 适配器：`repo:`/`documented:` 等 GitHub locator 可以刷新上游仓库元数据。
- Source Sync 的 repo metadata 适配器已扩展到 GitLab 与 Bitbucket locator。
- Source Sync 已支持 repo metadata 鉴权与自定义 API Base：新增 `sync_auth_token` / `sync_auth_header` / `sync_api_base` 字段链路（registry -> overview -> sync adapter）。
- repo metadata 错误码已分层：`auth_failed` / `rate_limited` / `provider_unreachable` / `auth_config_invalid` / `api_base_invalid`，便于面板侧诊断。
- WebUI Source 面板已补齐 sync error 可视化：展示结构化 `sync_error_code`、错误标签和修复建议提示。
- WebUI `/api/skills/*` 响应已加入敏感鉴权字段脱敏：`sync_auth_token` 默认清空并暴露 `sync_auth_token_configured`，`sync_auth_header` 在 `Header: value` 形态下统一掩码为 `Header: <redacted>`（策略名可见，密钥值不可见）。
- `inventory` 侧返回 `skills` 快照的接口（`/api/inventory/bindings`、`/api/inventory/scan`）也已统一套用同一脱敏出口，避免非 skills 路由旁路泄露。
- 脱敏逻辑已覆盖 success 与 error 分支，并新增路由级回归测试验证；当前回归结果：`python3 -m pytest tests -q` -> `151 passed`。
- `/api/config` 现已移除 `web_admin.password` 明文回传：配置读取仅返回空字符串与 `password_configured` 标记（同时在 `meta.web_admin_password_configured` 暴露状态）。
- 配置保存新增 `web_admin.password_mode`（`keep`/`set`/`clear`），前端已接入“留空保持不变 / 显式清除 / 输入覆盖”语义，避免空输入误清空已配置密码。
- 配置面板密码输入已改为 `type=password` 且不再回填密文；新增清除选项与动态提示文案。
- skills update 执行链路已增强：
  - registry 更新增加 runner precheck（`bunx`/`npx`/`pnpm`/`npm`），减少“点击更新后才报命令不存在”。
  - 当首选 registry 命令 `command not found` 时，会自动尝试替代 manager 命令链路，避免单点 manager 缺失导致整次更新失败。
  - 当 `update_plan` 不支持但 source 全部可 sync 时，`update` 动作会自动降级到 source sync（`fallback_mode=source_sync`），不再直接 unsupported。
- 聚合更新预览与前端门禁现已统一到同一可执行模型：
  - detail 级 `update_plan` 新增 `update_mode`（`command`/`source_sync`/`manual_only`）与 `actionable` 字段。
  - 前端更新按钮不再只依赖 `command_count`，而是优先使用 `actionable`，并兼容 `source_sync` fallback 场景。
  - 运维计划卡片新增“执行模式”展示，避免把 `manual_only` 聚合误判为可自动更新。
- 8099 运行态最新核验：
  - install unit 总数 `18`
  - 可执行预览 `16`（`command=5`，`source_sync=11`）
  - `manual_only=2`：`local_custom:/root/.codex/skills/doc`、`derived:npx_global_playwright_interactive`
- 当前回归结果已更新：`python3 -m pytest tests -q` -> `153 passed`。
- AstrBot Phase 3 最小动作适配已接入：
  - 新增 API：`/api/skills/hosts/{host_id}/astrbot`、`/skills/toggle`、`/skills/delete`、`/sandbox/sync`。
  - 本地 skill 启停会写入 `skills.json`，删除会同步清理本地目录、`skills.json` 与 `sandbox_skills_cache.json`。
  - 对 `sandbox_only` skill 已加保护，不允许本地启停/删除，避免破坏 AstrBot 运行态预置技能。
- AstrBot Phase 4 读模型基线已接入：
  - 新增稳定 Neo source id：`astrneo:{host_id}:{skill_key}`。
  - 新增只读 API：`GET /api/skills/astrbot-neo-sources` 与 `GET /api/skills/astrbot-neo-sources/{source_id}`。
  - Neo source 行可读取 release/candidate/payload 关键字段，供后续 promote/sync/rollback 写路径复用。
- 新增 AstrBot action adapter 回归：`tests/test_skills_astrbot_actions_core.py`，全量回归更新为 `160 passed`。
- AstrBot Phase 4 Neo 写路径已接入：新增 `POST /api/skills/astrbot-neo-sources/{source_id}/sync`，已支持从 Neo release 同步并回写审计轨迹（`astrbot_neo_source_sync`）。
- 全量回归已更新：`python3 -m pytest tests -q` -> `161 passed`。
- WebUI Source / Bundle 面板现已可见并管理 `astrneo:*`：会展示 Neo standalone source，详情接口自动路由到 `/api/skills/astrbot-neo-sources/{source_id}`，同步按钮会自动切换 Neo sync API。
