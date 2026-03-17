# OneSync 操作与同步手册（维护者）

> 语言 / Language: [中文](./OPERATIONS_AND_SYNC_zh.md) | [English](./OPERATIONS_AND_SYNC_en.md)

本文档面向仓库维护者，包含：

- 插件上传信息
- GitHub About 配置
- 版本维护与发版
- 本地与 GitHub 同步流程

## 1. 文档导航

- 用户安装与配置： [INSTALL_AND_CONFIG_zh.md](INSTALL_AND_CONFIG_zh.md)
- 用户安装与配置（英文）： [INSTALL_AND_CONFIG_en.md](./INSTALL_AND_CONFIG_en.md)
- About 详细模板（中文）： [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md)
- About 详细模板（英文）： [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)

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
./scripts/release.sh v0.1.1
```

该脚本会自动：

- 更新 `metadata.yaml` 的 `version`
- 缺失时补充 `CHANGELOG.md` 对应版本段
- 自动 `git commit`、`git tag`、`git push`

### 4.2 本地演练（不推送）

```bash
NO_PUSH=1 ./scripts/release.sh v0.1.1
```

### 4.3 版本策略建议

- 功能新增：`MINOR` 递增（例如 `v0.2.0`）
- 兼容性修复：`PATCH` 递增（例如 `v0.1.1`）

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
