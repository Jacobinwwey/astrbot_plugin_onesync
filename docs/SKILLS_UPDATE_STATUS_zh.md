# OneSync Skills 来源与更新能力现状

> 语言 / Language: [中文](./SKILLS_UPDATE_STATUS_zh.md) | [English](./SKILLS_UPDATE_STATUS_en.md)

审计日期：`2026-04-08`  
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

- 只有同时满足以下条件的 source 才支持：
  - `registry_package_name` 非空
  - `registry_package_manager == "npm"`
- 当前实现只会抓取 npm registry 元数据。
- GitHub/community/catalog/documented repo 这类来源，目前还不能做 metadata sync。

### 2.3 `Update Install Unit` / `Update Collection`

这个动作会执行真实的更新命令，由 install unit 推导得出。

当前真实情况：

- registry-backed install unit 支持通过 `bunx`、`npx`、`pnpm dlx` 或 `npm install -g` 更新。
- git-backed install unit 在存在本地 checkout 路径时，支持执行 `git -C <source_path> pull --ff-only`。
- manual / local custom / 仅 repo 引用聚合这几类来源，如果无法推导出明确可执行命令，当前仍属于不支持更新。

## 3. 当前支持矩阵

| 安装/来源形态 | 示例 | `Sync Source` | `Update Install Unit` | 说明 |
| --- | --- | --- | --- | --- |
| npm 包支撑的 bundle/single | `npm:@every-env/compound-plugin` | 支持 | 支持 | Sync 读取 npm registry 元数据；Update 优先使用 `management_hint`，否则构造 registry 更新命令。 |
| git 本地 checkout / skill-lock 条目 | `skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills` | 不支持 | 支持，前提是存在本地 `source_path` | Update 会转成 `git -C <path> pull --ff-only`。这是 update 支持，不代表 source-sync 已支持。 |
| 只有 repo 引用的 documented/catalog/community 来源 | `repo:https://github.com/...#skills/foo` | 不支持 | 通常不支持 | 这些行主要用于来源归因与聚合展示，还不能自动更新。 |
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

一个需要特别说明的细节：

- 某些 source 行可能因为 npx 发现链路的归一化规则，仍然带着 `update_policy=registry`。
- 这 **不等于** 对应 install unit 一定可以更新。
- 最终真相应以 install unit 级别的 `update_plan` 为准。

这点对 `doc` 这类本地自建 skill 尤其重要：它虽然可能和 npx 管理的 skills 一起被发现，但本质上仍是手工维护，因此当前仍不支持自动更新。

## 5. 当前结论

如果问题是“当前 skill 更新功能是否已经完善”，结论是：

- 发现 / 导入 / 来源归因：对当前 v1 范围来说已经比较完整。
- install unit 更新执行：部分完善。
- source 元数据同步：尚未完善。

更具体地说：

- 对 npm 包驱动的 skills 更新，以及带本地 checkout 的 git 来源更新，已经足够可用。
- 对只有来源归因意义的 repo 派生 source，还不算完善。
- 对 local custom / manual skills，还不算完善。
- 对非 npm 的上游 metadata sync，还不算完善。

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
- `counts.source_syncable_total` 现在只会统计 npm-backed source
- 支持更新的 install unit 会暴露非空 `update_plan.commands`
- local custom skill 会显示 `update_plan.supported = false`

## 7. 下一步建议

如果要把这个能力称为“完善”，下一步建议是：

1. 为 git / GitHub 类来源补齐 repo-aware source sync 适配器。
2. 在 UI 中更明确展示 unsupported 原因。
3. 在面板文案中进一步区分“来源归因”和“更新机制”。
4. 增加更多 install-unit 详情与 live sync/update 行为的端到端测试。
