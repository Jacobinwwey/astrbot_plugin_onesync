# Release Notes Template

Use this file as the source draft for GitHub release notes.

Recommended flow:

```bash
# create the repository release commit/tag first
./scripts/release.sh vX.Y.Z

# then publish or update the GitHub release from the bilingual notes file
gh release edit vX.Y.Z --title "vX.Y.Z · english title / 中文标题" --notes-file docs/releases/vX.Y.Z.md
```

## English

### Why this release

- Explain the main user-facing goal of the release in 1 to 3 bullets.

### Core capabilities highlighted

- Summarize the most important product or operational capabilities.

### User convenience highlights

- Explain what became easier, clearer, faster, or lower-risk for users.

### Upgrade notes

- Note any restart, refresh, migration, or compatibility requirement.

### Verification

- List the concrete commands and outcomes used to verify the release.

## 中文

### 这个版本解决什么问题

- 用 1 到 3 条说明这次发布的主要用户价值。

### 重点能力

- 概述本次需要强调的产品能力或运维能力。

### 用户便利性改进

- 说明什么变得更容易、更清晰、更稳、更省操作。

### 升级说明

- 标注是否需要重启、刷新、迁移或兼容性确认。

### 验证结果

- 写清楚用于证明版本可发布的命令与结果。
