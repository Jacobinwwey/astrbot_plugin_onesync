---
date: 2026-04-06
topic: software-skill-unified-management
status: active
origin: docs/brainstorms/software-skill-unified-management-requirements.md
---

# OneSync Skills 管理实施方案

## Summary
OneSync 不再沿“软件表 + skill 表 + 绑定表”继续扩展，而是进入 source-first 过渡架构：

- `inventory_core.py` 保留为兼容层，继续负责本地软件探测、`npx` 聚合、兼容性计算和旧 `/api/inventory/*`。
- 新增 `skills_core.py` 作为 source-first 状态核心，把 inventory 结果提升为：
  - `manifest`
  - `lock`
  - `source_rows`
  - `deploy_rows`
- WebUI 主入口仍保留在 `webui/index.html`，但前端主数据源切到 `/api/skills/overview`。
- 当前 `npx` 聚合包管理方向继续保持，不回退到逐条 `ce:*` 级别管理。

## Key Changes

### 1. 状态模型升级
- 技能管理真相采用 source-first 投影模型：
  - `manifest`：当前宿主、source、deploy target 的声明性状态
  - `lock`：最近一次解析后的 source/deploy 健康与漂移结果
- 插件运行时在 `plugin_data/astrbot_plugin_onesync/skills/` 下持久化：
  - `manifest.json`
  - `lock.json`
  - `sources/*.json`
  - `generated/*.json`
- 这些文件在当前阶段由 inventory 快照派生生成，属于 v1.5 过渡实现；后续 v2 再演进为更强的独立可写状态。

### 2. API 过渡策略
- 保留兼容接口：
  - `GET /api/inventory/overview`
  - `GET /api/inventory/software`
  - `GET /api/inventory/skills`
  - `GET /api/inventory/bindings`
  - `POST /api/inventory/scan`
  - `POST /api/inventory/bindings`
- 新增正式技能接口：
  - `GET /api/skills/overview`
  - `GET /api/skills/sources`
  - `GET /api/skills/sources/{source_id}`
  - `GET /api/skills/deploy-targets/{target_id}`
  - `POST /api/skills/import`
  - `POST /api/skills/sources/{source_id}/sync`
  - `POST /api/skills/sources/{source_id}/deploy`
  - `POST /api/skills/deploy-targets/{target_id}`
  - `POST /api/skills/deploy-targets/{target_id}/reproject`
  - `POST /api/skills/deploy-targets/repair-all`
  - `POST /api/skills/doctor`

### 3. 前端视图升级
- 保留现有宿主选择 + 兼容 source 勾选的高效操作路径。
- 新增两块 source-first 视图：
  - `Source / Bundle 视图`
  - `Deploy Targets`
- `刷新资产` 触发 `/api/skills/import`，而不是只刷新旧 inventory。
- `健康检查` 使用 `/api/skills/doctor` 直接展示 source/deploy 健康摘要。

### 4. 兼容性与边界
- 软件列表默认只显示已安装、可调用 skills 的宿主软件。
- `Show Uninstalled` 继续支持查看未安装候选宿主。
- `ce:*` 继续聚合为 `Compound Engineering` source bundle。
- `Codex Skill Pack` 等 bundle 继续按包级展示，不在主界面平铺所有成员。

## Implementation Changes

### Backend
- 新增 `skills_core.py`
  - 将 inventory 快照转为 `manifest + lock + overview`
  - 计算 source 健康、deploy 健康、漂移状态
  - 合并已保存 manifest 与最新 inventory，保留 deploy intent
- 更新 `main.py`
  - 增加 `skills` 运行态 state
  - 增加 skills 持久化目录与 JSON 文件写入
  - 每次刷新 inventory 时同步刷新 skills snapshot
  - 让 `manifest.json` 成为 deploy intent 的主存储
  - 将 manifest 反向投影到 `skill_bindings` 以维持 inventory 兼容
  - `GET /api/skills/*` 的读取改为 cache-first，避免在只读访问时覆盖 `generated/*.json`
  - Deploy Target detail 增加 `generated_projection.path / exists / payload / diff`
  - 增加 target 级 `reproject`，用于显式重建单个 generated projection
  - 新增 `/api/skills/*` 对应的插件方法
  - `POST /api/skills/deploy-targets/{target_id}` 支持按 target 整体更新 selected sources
  - `POST /api/skills/deploy-targets/repair-all` 支持按当前 snapshot 批量修复 repairable targets
  - doctor 追加 runtime state / projection health，覆盖 `manifest.json`、`lock.json`、`sources/*.json`、`generated/*.json` 和 `skill_bindings` 投影一致性
- 更新 `webui_server.py`
  - 暴露新的 `/api/skills/*` 路由

### Frontend
- 更新 `webui/index.html`
  - 主数据源切到 `/api/skills/overview`
  - `Save Skill Bindings` 更名为 `保存部署选择`
  - 新增 source/deploy 面板与 doctor 摘要
  - 保留已验证可用的软件筛选、scope 选择、兼容 source 快速勾选
  - 当前 Deploy Target 面板补充 drift 明细、projection diff 明细，并增加“重建当前投影”与批量修复入口

## Test Plan
- `tests/test_inventory_core.py`
  - 继续作为 inventory 兼容层回归测试
- `tests/test_skills_core.py`
  - 验证 manifest 构建
  - 验证缺失 source / 未安装宿主时的 deploy 状态
  - 验证 overview 保留 inventory 兼容字段
- `tests/test_webui_server.py`
  - 验证新增 `/api/skills/*` 路由
  - 验证 deploy / reproject / doctor 路径的成功/失败状态码
- `tests/test_skills_projection_core.py`
  - 验证 generated projection 缺失、无差异、有差异三种核心分支

## Assumptions
- 当前阶段 source-first 仍建立在 inventory 派生之上，不单独引入新的写配置 UI。
- `manifest.json` 已成为 deploy intent 主存储，`skill_bindings` 仅保留为兼容投影。
- 本轮已补上“generated diff 可见 + target 级 reproject”，但更进一步的 manifest 直接编辑与跨 target 重部署仍属于后续阶段。
