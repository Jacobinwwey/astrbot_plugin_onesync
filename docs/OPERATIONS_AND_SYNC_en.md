# OneSync Operations and Sync Manual (Maintainers)

> Language / 语言: [English](./OPERATIONS_AND_SYNC_en.md) | [中文](./OPERATIONS_AND_SYNC_zh.md)

This manual is for repository maintainers and covers:

- Plugin upload metadata
- GitHub About setup
- Versioning and release workflow
- Local to GitHub synchronization process

## 1. Doc Navigation

- User install and config: [INSTALL_AND_CONFIG_en.md](./INSTALL_AND_CONFIG_en.md)
- About templates: [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)

## 2. Plugin Upload Metadata

Suggested values when publishing the plugin:

1. `[Plugin]`: `astrbot_plugin_onesync`
2. Metadata JSON:

```json
{
  "name": "astrbot_plugin_onesync",
  "display_name": "OneSync",
  "desc": "Extensible software updater plugin for AstrBot with scheduling, auto-update, mirror fallback, and state tracking.",
  "author": "Jacobinwwey",
  "repo": "https://github.com/Jacobinwwey/astrbot_plugin_onesync",
  "tags": ["updater", "automation", "devops", "zeroclaw", "astrbot"],
  "social_link": "https://github.com/Jacobinwwey"
}
```

In-repo file reference:

- [plugin_upload_info.json](../plugin_upload_info.json)

## 3. GitHub About Setup

Direct templates:

- [GITHUB_ABOUT_en.md](./GITHUB_ABOUT_en.md)
- [GITHUB_ABOUT_zh.md](./GITHUB_ABOUT_zh.md)

Recommendations:

- Keep description short and clear (within 160 chars).
- Include core topics like `astrbot-plugin`, `updater`, `github-mirror`.
- Use `logo_256.png` or `logo.png` as social preview.

## 4. Versioning and Releases

### 4.1 Recommended release command

Run in the plugin repository:

```bash
./scripts/release.sh v0.1.1
```

This script will:

- Update `metadata.yaml` version
- Add a missing section to `CHANGELOG.md`
- Commit, tag, and push automatically

### 4.2 Local dry run (no push)

```bash
NO_PUSH=1 ./scripts/release.sh v0.1.1
```

### 4.3 Versioning strategy

- New features: bump `MINOR` (for example `v0.2.0`)
- Bugfix/compatibility: bump `PATCH` (for example `v0.1.1`)

## 5. Code Sync Workflow (Local -> GitHub)

### 5.1 Regular commit

```bash
git status
git add .
git commit -m "feat: xxx"
git push origin main
```

### 5.2 Push tags after release

```bash
git push origin main --tags
```

### 5.3 Pre-push checklist

Before pushing, verify:

- `README.md` keeps user-facing content only
- `docs/` includes maintainer documentation in both zh/en
- `_conf_schema.json` is valid JSON
- Python files pass syntax checks
- WebUI JavaScript has no syntax errors
- WebUI routes are reachable (`/api/health` and `/api/config`)
