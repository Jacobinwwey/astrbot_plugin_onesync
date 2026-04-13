# OneSync 接口参考（中文）

> 语言 / Language: [中文](./API_REFERENCE_zh.md) | [English](./API_REFERENCE_en.md)

| 当前版本 | 最后更新 | 适用对象 | 建议先读 |
| --- | --- | --- | --- |
| `v0.2.3` | `2026-04-13` | 脚本调用者、前端联调者、二次集成者 | [README.md](../README.md) |

这份文档只做一件事：把 OneSync 内置 WebUI 的 `/api/*` 面整理清楚。你如果只是安装和使用插件，不需要从这里开始。

| 什么时候看这份文档 | 入口 |
| --- | --- |
| 想确认鉴权和 token 传法 | [2. 鉴权规则](#2-鉴权规则) |
| 想查系统和总览接口 | [4. 系统与总览接口](#4-系统与总览接口) |
| 想查 Skills 读写接口 | [6. Skills 只读接口](#6-skills-只读接口) / [7. Skills 变更接口](#7-skills-变更接口) |
| 想知道实际调用顺序 | [11. 推荐调用顺序](#11-推荐调用顺序) |

| 相关文档 | 用途 |
| --- | --- |
| [README.md](../README.md) | 项目定位与快速开始 |
| [安装与配置指南（中文）](./INSTALL_AND_CONFIG_zh.md) | 用户安装与日常使用 |
| [开发指南（中文）](./DEVELOPER_GUIDE_zh.md) | 代码结构与扩展点 |

## 1. 基本信息

- 默认地址：`http://127.0.0.1:8099`
- API 根路径：`/api`
- OpenAPI：`/openapi.json`
- 健康检查：`/api/health`

## 2. 鉴权规则

当 `web_admin.password` 为空时：

- 所有 `/api/*` 路由默认可直接访问。

当 `web_admin.password` 已配置时：

- 放行：
  - `GET /api/auth-info`
  - `POST /api/login`
- 其余 `/api/*` 路由需要 token。

可用两种方式携带 token：

- 查询参数：`?token=...`
- 请求头：`Authorization: Bearer <token>`

相关接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/auth-info` | 返回是否开启登录保护 |
| POST | `/api/login` | 提交密码并获取 token |

## 3. 通用约定

- 大多数响应都会带：
  - `ok`
  - `message`
- 只读接口通常返回 `200`
- 资源不存在通常返回 `404`
- 参数错误或执行失败通常返回 `400`

说明：

- `install_unit_id`、`collection_group_id`、`source_id` 可能包含 `:`、`/`、`@` 等字符，调用时应做 URL 编码。

## 4. 系统与总览接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 基础健康检查 |
| GET | `/api/overview` | 软件更新总览 |
| GET | `/api/jobs/latest` | 最近一次运行任务 |
| GET | `/api/jobs/{job_id}` | 单个任务详情 |
| GET | `/api/debug/logs` | Debug 日志 |
| POST | `/api/debug/clear` | 清空 Debug 日志 |
| POST | `/api/run` | 触发软件更新执行 |
| GET | `/api/docs/index` | Guide 弹窗本地文档索引（Markdown） |
| GET | `/api/docs/content` | 单个本地 Markdown 文档正文（JSON） |
| GET | `/api/docs/raw` | 单个本地 Markdown 文档正文（纯文本） |

文档路由说明：

- `path` 必须是仓库内相对路径，且为 Markdown 文件。
- 当前允许范围：
  - 根文档（`README*.md`、`CHANGELOG.md`、`TODO.md`、`TEST_REPORT.md`）
  - `docs/**/*.md`
- `../../...` 这类 traversal 路径会被拒绝并返回 `404`。

## 5. Inventory 兼容层接口

这些接口仍保留，用于兼容旧的 inventory 工作流。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/inventory/overview` | inventory 总览 |
| GET | `/api/inventory/software` | 软件资产明细 |
| GET | `/api/inventory/skills` | skill 资产明细 |
| GET | `/api/inventory/bindings` | 绑定明细 |
| POST | `/api/inventory/scan` | 重扫 inventory |
| POST | `/api/inventory/bindings` | 保存软件与 source 绑定 |

当前注意事项：

- `POST /api/inventory/bindings` 现已直接基于 persisted `manifest` 与最新 skills snapshot 生成兼容投影。
- 也就是说，“保存绑定”不再要求 inventory 重扫才能反映结果。

## 6. Skills 只读接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/skills/overview` | source-first 总览 |
| GET | `/api/skills/registry` | source registry |
| GET | `/api/skills/install-atoms` | install atom 账本 |
| GET | `/api/skills/audit` | 审计记录 |
| GET | `/api/skills/hosts` | host rows |
| GET | `/api/skills/sources` | source rows 列表 |
| GET | `/api/skills/sources/{source_id}` | 单个 source 详情 |
| GET | `/api/skills/install-units/{install_unit_id}` | install unit 详情 |
| GET | `/api/skills/collections/{collection_group_id}` | collection group 详情 |
| GET | `/api/skills/deploy-targets/{target_id}` | deploy target 详情 |
| GET | `/api/skills/astrbot-neo-sources` | AstrBot Neo source 列表 |
| GET | `/api/skills/astrbot-neo-sources/{source_id}` | 单个 AstrBot Neo source 详情 |
| GET | `/api/skills/hosts/{host_id}/astrbot` | AstrBot 宿主运行态详情 |
| GET | `/api/skills/hosts/{host_id}/astrbot/workspaces` | AstrBot workspace 索引详情 |

## 7. Skills 变更接口

### 7.1 Source / registry

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/skills/import` | 重建 skills snapshot |
| POST | `/api/skills/sources/register` | 新增 source |
| POST | `/api/skills/sources/{source_id}/refresh` | 刷新 source registry 元数据 |
| POST | `/api/skills/sources/{source_id}/remove` | 删除 source |
| POST | `/api/skills/sources/{source_id}/sync` | 同步单个 source |
| POST | `/api/skills/sources/sync-all` | 同步全部可同步 source |
| POST | `/api/skills/sources/{source_id}/deploy` | 直接部署单个 source |

### 7.2 Install unit / collection group

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/skills/install-units/{install_unit_id}/refresh` | 刷新 install unit 视图相关元数据 |
| POST | `/api/skills/install-units/{install_unit_id}/sync` | 同步 install unit 下所有 source |
| POST | `/api/skills/install-units/{install_unit_id}/update` | 执行 install unit 更新 |
| POST | `/api/skills/install-units/{install_unit_id}/rollback` | install unit 回滚 |
| POST | `/api/skills/install-units/{install_unit_id}/deploy` | 部署 install unit |
| POST | `/api/skills/install-units/{install_unit_id}/repair` | 修复 install unit |
| POST | `/api/skills/collections/{collection_group_id}/refresh` | 刷新 collection group 元数据 |
| POST | `/api/skills/collections/{collection_group_id}/sync` | 同步 collection group 下所有 source |
| POST | `/api/skills/collections/{collection_group_id}/update` | 更新 collection group |
| POST | `/api/skills/collections/{collection_group_id}/rollback` | collection group 回滚 |
| POST | `/api/skills/collections/{collection_group_id}/deploy` | 部署 collection group |
| POST | `/api/skills/collections/{collection_group_id}/repair` | 修复 collection group |

### 7.3 Deploy target / doctor

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/skills/deploy-targets/{target_id}` | 保存 target 选中的 source |
| POST | `/api/skills/deploy-targets/{target_id}/repair` | 修复单个 deploy target |
| POST | `/api/skills/deploy-targets/{target_id}/reproject` | 重建单个 deploy target projection |
| POST | `/api/skills/deploy-targets/repair-all` | 批量修复 deploy target |
| POST | `/api/skills/doctor` | 执行 Skills 健康检查 |

## 8. 批量运行与进度接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/skills/aggregates/update-all` | 批量更新所有可执行聚合 |
| GET | `/api/skills/aggregates/update-all/progress` | 最近一次批量更新进度快照 |
| GET | `/api/skills/aggregates/update-all/history` | 最近批量更新历史 |
| POST | `/api/skills/improve-all` | 一键完善 Skills（install-atom + aggregate update） |

当前建议：

- 若要做 UI 进度展示，优先依赖 `progress` / `history`，不要自行估算。
- `POST /api/skills/improve-all` 也会写入同一条进度通道；前端应通过 `progress.workflow_kind = "improve_all"` 以及 `atom_*` 计数字段区分“原子刷新 + 聚合更新”的复合流程。

## 9. AstrBot 运行态接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/toggle` | 启停本地 AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/delete` | 删除本地 AstrBot skill |
| POST | `/api/skills/hosts/{host_id}/astrbot/skills/import-zip` | 导入本地 AstrBot skill ZIP 包 |
| GET | `/api/skills/hosts/{host_id}/astrbot/skills/export-zip` | 导出本地 AstrBot skill ZIP 包 |
| POST | `/api/skills/hosts/{host_id}/astrbot/sandbox/sync` | 触发 sandbox 同步 |
| POST | `/api/skills/hosts/{host_id}/astrbot/workspaces/init` | 初始化单个 AstrBot workspace 骨架 |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/sync` | 同步 AstrBot Neo source |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/promote` | 提升 AstrBot Neo candidate |
| POST | `/api/skills/astrbot-neo-sources/{source_id}/rollback` | 回滚 AstrBot Neo release |

### 9.1 宿主详情响应结构

`GET /api/skills/hosts/{host_id}/astrbot` 的响应重点字段：

- `host`
  - 当前 host row。
- `layout.available_scopes`
  - 当前宿主可用的 `global / workspace` 范围。
- `layout.selected_scope`
  - 默认读取范围。
- `layout.scoped_layouts.{scope}`
  - 每个 scope 下的 `skills_root`、`skills_config_path`、`sandbox_cache_path`、`neo_map_path`、`state_available`。
- `runtime_state.summary.available_scopes`
  - 运行态层再次暴露可用范围，便于前端不依赖 layout 推断。
- `runtime_state.summary.scope_summaries.{scope}`
  - 每个范围各自的 `local_skill_total`、`active_skill_total`、`sandbox_cache_exists`、`sandbox_cache_ready` 等摘要。
- `runtime_state.state_rows[]`
  - 逐 skill 状态行，包含 `scope`、`skill_name`、`state_classification`、`local_exists`、`sandbox_exists`、`active`。

### 9.1.1 Neo source detail 补充字段

`GET /api/skills/astrbot-neo-sources/{source_id}` 额外返回：

- `neo_state`
  - 当前 source 的 `host_id`、`skill_key`、`local_skill_name`、`release_id`、`candidate_id`、`payload_ref`、`updated_at`
- `neo_capabilities`
  - 当前详情下 `sync_supported`、`promote_supported`、`rollback_supported`
- `neo_defaults`
  - 前端可直接复用的默认动作参数：`candidate_id`、`release_id`、`stage`、`sync_to_local`、`require_stable`
  - 当远端可读时，会优先对齐到远端当前 `latest_candidate_id` / `active_stable_release_id`
- `neo_remote_state`
  - Neo 远端只读状态快照：`configured`、`endpoint`、`fetched_at`、`reason_code`、`message`
  - `current` 下包含 `active_stable_release_id`、`active_canary_release_id`、`latest_release_id`、`latest_candidate_id`、`latest_candidate_status`
  - `releases.items[]` 与 `candidates.items[]` 已按 `updated_at -> created_at` 的时间优先级倒序整理
- `neo_activity`
  - 当前 Neo source 的最近审计轨迹：`counts.total`、`items[]`、`warnings[]`
  - 审计过滤会按标准化后的 `source_id` 匹配，因此 `astrneo:*` 这类带分隔符的 source id 也能稳定返回历史

### 9.2 AstrBot 变更请求 payload

建议显式传递 `scope`，不要让前端隐式假设默认范围。
当 `scope=workspace` 时必须传 `workspace_id`，否则会返回
`reason_code=workspace_required` 或 `reason_code=workspace_not_found`。

- `POST /api/skills/hosts/{host_id}/astrbot/workspaces/init`

```json
{
  "workspace_id": "session_alpha",
  "workspace_root": "/root/astrbot/data/workspaces/session-alpha"
}
```

`workspace_root` 为可选项。若传入，必须位于
`{astrbot_data_dir}/workspaces` 目录下，且其 basename 归一化后需与
`workspace_id` 一致。

- `POST /api/skills/hosts/{host_id}/astrbot/skills/toggle`

```json
{
  "skill_name": "demo",
  "active": false,
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/hosts/{host_id}/astrbot/skills/delete`

```json
{
  "skill_name": "demo",
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/hosts/{host_id}/astrbot/skills/import-zip`
  - `multipart/form-data`
  - 字段：
    - `file`: `.zip` 文件
    - `scope`: `global` / `workspace`
    - `workspace_id`: 当 `scope=workspace` 时必填
    - `overwrite`: 可选，默认 `false`
    - `skill_name_hint`: 可选，单 skill root archive 时可作为目标目录名提示

- `GET /api/skills/hosts/{host_id}/astrbot/skills/export-zip`
  - query:
    - `skill_name=demo`
    - `scope=workspace`
    - `workspace_id=session_alpha`

- `POST /api/skills/hosts/{host_id}/astrbot/sandbox/sync`

```json
{
  "scope": "workspace",
  "workspace_id": "session_alpha"
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/sync`

```json
{
  "release_id": "rel-2"
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/promote`

```json
{
  "candidate_id": "cand-3",
  "stage": "stable",
  "sync_to_local": true
}
```

- `POST /api/skills/astrbot-neo-sources/{source_id}/rollback`

```json
{
  "release_id": "rel-3"
}
```

注意：

- `scope` 可取 `global` 或 `workspace`。
- 若请求了当前宿主未暴露的范围，会返回 `reason_code = "scope_unavailable"`。
- ZIP 导入当前只接受 `.zip` 文件；无文件时返回 `reason_code = "zip_path_required"`。
- ZIP 导出会返回 `application/zip` 文件流；若 skill 仅存在于 sandbox cache，会返回 `reason_code = "sandbox_only_skill"`。
- Neo sync 可省略 `release_id`，省略时按当前后端默认 candidate/release 选择执行。
- Neo promote 若未显式传入 `candidate_id`，后端会优先回退到当前 source detail 的 `neo_defaults.candidate_id`。
- Neo rollback 若未显式传入 `release_id`，后端会优先回退到当前 source detail 的 `neo_defaults.release_id`。

## 10. 配置接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/config` | 读取插件配置 |
| POST | `/api/config` | 更新插件配置 |

注意：

- `web_admin.password` 不会再明文返回。
- 更新密码时应通过显式模式语义处理：
  - `keep`
  - `set`
  - `clear`

## 11. 推荐调用顺序

### 11.1 用户配置与软件更新

1. `GET /api/config`
2. `POST /api/config`
3. `GET /api/overview`
4. `POST /api/run`

### 11.2 Skills 导入与绑定

1. `POST /api/skills/import`
2. `GET /api/skills/overview`
3. `POST /api/inventory/bindings`
4. `GET /api/skills/deploy-targets/{target_id}`

### 11.3 批量聚合更新

1. `POST /api/skills/aggregates/update-all`
2. `GET /api/skills/aggregates/update-all/progress`
3. `GET /api/skills/aggregates/update-all/history`

### 11.4 AstrBot 本地 skill 管理

1. `GET /api/skills/hosts`
2. `GET /api/skills/hosts/{host_id}/astrbot`
3. 按显式 `scope` 调用 toggle / delete / import-zip / export-zip / sandbox sync
4. `GET /api/skills/hosts/{host_id}/astrbot`

## 12. 相关文档

- [README.md](../README.md)
- [安装与配置指南（中文）](./INSTALL_AND_CONFIG_zh.md)
- [开发指南（中文）](./DEVELOPER_GUIDE_zh.md)
- [操作与同步手册（中文）](./OPERATIONS_AND_SYNC_zh.md)
