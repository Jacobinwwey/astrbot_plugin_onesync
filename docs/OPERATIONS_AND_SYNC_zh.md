# OneSync 操作与同步手册（维护者）

> 语言 / Language: [中文](./OPERATIONS_AND_SYNC_zh.md) | [English](./OPERATIONS_AND_SYNC_en.md)

本文档面向仓库维护者，包含：

- 插件上传信息
- GitHub About 配置
- 版本维护与发版
- 本地与 GitHub 同步流程

## 1. 文档导航

- 项目首页： [README.md](../README.md)
- 用户安装与配置： [INSTALL_AND_CONFIG_zh.md](INSTALL_AND_CONFIG_zh.md)
- 用户安装与配置（英文）： [INSTALL_AND_CONFIG_en.md](./INSTALL_AND_CONFIG_en.md)
- 开发指南（中文）： [DEVELOPER_GUIDE_zh.md](./DEVELOPER_GUIDE_zh.md)
- 接口参考（中文）： [API_REFERENCE_zh.md](./API_REFERENCE_zh.md)
- About 详细模板（中文）： [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md)
- About 详细模板（英文）： [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)
- Skills 来源与更新审计（英文）： [SKILLS_UPDATE_STATUS_en.md](./SKILLS_UPDATE_STATUS_en.md)
- Skills 来源与更新审计（中文）： [SKILLS_UPDATE_STATUS_zh.md](./SKILLS_UPDATE_STATUS_zh.md)

## 2. 插件上传信息

上传平台时建议使用以下内容：

1. `[Plugin]`：`astrbot_plugin_onesync`
2. 元信息 JSON：

```json
{
  "name": "astrbot_plugin_onesync",
  "display_name": "OneSync",
  "desc": "通用可扩展的软件更新器插件，支持定时检查、自动更新、镜像回退与状态追踪。",
  "author": "Jacobinwwey",
  "repo": "https://github.com/Jacobinwwey/astrbot_plugin_onesync",
  "tags": ["updater", "automation", "devops", "zeroclaw", "astrbot"],
  "social_link": "https://github.com/Jacobinwwey"
}
```

仓库内文件：

- [plugin_upload_info.json](../plugin_upload_info.json)

## 3. GitHub About 配置

可直接复用：

- [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md)
- [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)

建议：

- Description 用英文短句（160 字符以内）。
- Topics 覆盖 `astrbot-plugin`、`updater`、`github-mirror` 等关键词。
- Social Preview 使用 `logo_256.png` 或 `logo.png`。

## 4. 版本维护与发版

### 4.1 推荐发版命令

在插件仓库目录执行：

```bash
./scripts/release.sh v0.2.1
```

该脚本会自动：

- 更新 `metadata.yaml` 的 `version`
- 缺失时补充 `CHANGELOG.md` 对应版本段
- 自动 `git commit`、`git tag`、`git push`

### 4.2 本地演练（不推送）

```bash
NO_PUSH=1 ./scripts/release.sh v0.2.1
```

### 4.3 版本策略建议

- 功能新增：`MINOR` 递增（例如 `v0.2.0`）
- 兼容性修复：`PATCH` 递增（例如 `v0.1.1`）

### 4.4 当前仓库基线

- `metadata.yaml` 当前版本：`v0.2.1`
- 内置 WebUI OpenAPI 版本：`0.2.1`
- 当前完整回归基线：`pytest -q -> 191 passed`

## 5. 代码同步流程（本地 -> GitHub）

### 5.1 常规提交

```bash
git status
git add .
git commit -m "feat: xxx"
git push origin main
```

### 5.2 发布后同步标签

```bash
git push origin main --tags
```

### 5.3 推荐检查项

推送前建议检查：

- README 是否仅保留用户向内容
- `docs/` 是否包含维护文档
- `_conf_schema.json` 是否可被 JSON 解析
- Python 文件是否通过语法检查
- `pytest -q` 是否在推送前通过
- WebUI 路由是否可用（至少校验 `/api/health` 与 `/api/config`）

### 5.4 文档同步建议

当本轮改动既影响实现又影响运维认知时，不要只改一份状态文档。

建议至少同步这些入口：

- `README.md` / `README_en.md`
- `docs/SKILLS_UPDATE_STATUS_zh.md` / `docs/SKILLS_UPDATE_STATUS_en.md`
- 相关 `docs/plans/*` 与 `docs/brainstorms/*`

如果本机 live 插件目录与开发仓库并行存在，还要额外确认：

- `/root/astrbot/data/plugins/astrbot_plugin_onesync/docs/*` 是否需要同步到当前运行实例
- 文档引用的 API 路径、统计口径和运行态验证结果是否与 8099 当前服务一致

## 6. Skills 更新维护说明

在维护 Skills 管理链路时，需要明确区分以下几类动作：

- `POST /api/skills/import`：重建本地 source-first 快照
- `Sync Source`：刷新 source 的上游元数据
- `Update Install Unit` / `Update Collection`：执行真实更新命令

当前实现状态：

- Source sync 现已支持：
  - npm registry metadata
  - git remote/head 或本地 checkout 元数据
  - GitHub / GitLab / Bitbucket repo metadata
- install unit update 取决于 `update_plan` 的真实执行能力，而不是 `source_kind` 名称。
- 绑定保存现已直接基于 persisted `manifest` 与最新 skills snapshot 生成投影，维护者不应再假设“保存绑定后必须重扫 inventory 才会生效”。
- 命令更新成功后，freshness anchor 会回写到 saved registry；下一次 overview 重建应立即消除错误的 `AGING` 状态。
- git-backed `skill_lock` / repo 来源现在支持“受管 checkout 自动补齐”：
  - 若叶子 skill 目录不是 git 仓库，OneSync 会在 `plugin_data/.../skills/git_repos/` 下自动物化受管 checkout。
  - 后续 `sync/update` 均优先走该 checkout。
- `synthetic_single`、`derived`、`local_custom` 这类没有真实包边界的 install unit 现已明确归为 `manual_only`，不再伪造错误更新命令。
- WebUI 现已支持：
  - `POST /api/skills/aggregates/update-all`
  - 前端 “更新全部聚合” 按钮
  - executed / skipped / source-sync 分层反馈

如果要排查“为什么不能更新”，应优先查看 install unit 详情接口中的 `update_plan`，并以它作为最终真相源。

当前 8099 live 运行态最近一次 `update-all` 验证结果：

- `candidate_install_unit_total = 20`
- `executed_install_unit_total = 14`
- `command_install_unit_total = 3`
- `source_sync_install_unit_total = 11`
- `skipped_install_unit_total = 6`
- `success_count = 8`
- `failure_count = 2`
- `precheck_failure_count = 0`
