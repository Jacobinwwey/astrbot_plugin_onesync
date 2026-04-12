from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib import error

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from source_sync_core import (
    build_source_sync_cache_key,
    build_source_sync_record,
    fetch_npm_registry_package_summary,
    is_source_syncable,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SourceSyncCoreTests(unittest.TestCase):
    def test_build_source_sync_cache_key_uses_repo_root_for_repo_metadata_sources(self) -> None:
        key_a = build_source_sync_cache_key(
            {
                "source_id": "javascript_pro",
                "source_path": "/root/.codex/skills/javascript-pro",
                "locator": "/root/.codex/skills/javascript-pro",
                "install_ref": "https://github.com/AndyAnh174/wellness.git#.agent/skills/javascript-pro",
                "install_manager": "manual",
                "update_policy": "registry",
            },
        )
        key_b = build_source_sync_cache_key(
            {
                "source_id": "javascript_mastery",
                "source_path": "/root/.codex/skills/javascript-mastery",
                "locator": "/root/.codex/skills/javascript-mastery",
                "install_ref": "https://github.com/AndyAnh174/wellness.git#.agent/skills/javascript-mastery",
                "install_manager": "manual",
                "update_policy": "registry",
            },
        )

        self.assertEqual("repo_metadata:github:AndyAnh174/wellness", key_a)
        self.assertEqual(key_a, key_b)

    def test_build_source_sync_cache_key_prefers_git_checkout_path(self) -> None:
        key = build_source_sync_cache_key(
            {
                "source_id": "find_skills",
                "source_path": "/root/.agents/skills/find-skills",
                "git_checkout_path": "/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123",
                "managed_by": "github",
                "update_policy": "source_sync",
                "locator": "https://github.com/vercel-labs/skills.git",
            },
        )

        self.assertEqual(
            "git_checkout:/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123",
            key,
        )

    def test_fetch_npm_registry_package_summary(self) -> None:
        def _fake_urlopen(url: str, timeout: int = 0):
            self.assertIn("%40every-env%2Fcompound-plugin", url)
            self.assertEqual(6, timeout)
            return _FakeResponse(
                {
                    "dist-tags": {"latest": "2.62.1"},
                    "versions": {
                        "2.62.1": {
                            "homepage": "https://github.com/every-env/compound-plugin",
                            "description": "Compound plugin bundle",
                        },
                    },
                    "time": {
                        "modified": "2026-04-01T12:00:00.000Z",
                        "2.62.1": "2026-04-01T11:58:00.000Z",
                    },
                },
            )

        summary = fetch_npm_registry_package_summary(
            "@every-env/compound-plugin",
            urlopen=_fake_urlopen,
            timeout_s=6,
        )

        self.assertTrue(summary["ok"])
        self.assertEqual("2.62.1", summary["registry_latest_version"])
        self.assertEqual("2026-04-01T11:58:00.000Z", summary["registry_published_at"])
        self.assertEqual("https://github.com/every-env/compound-plugin", summary["registry_homepage"])
        self.assertEqual("Compound plugin bundle", summary["registry_description"])
        self.assertEqual("npm_registry", summary["sync_kind"])
        self.assertEqual("2.62.1", summary["sync_resolved_revision"])
        self.assertEqual("2.62.1", summary["sync_remote_revision"])
        self.assertEqual("", summary["sync_local_revision"])
        self.assertFalse(summary["sync_dirty"])

    def test_build_source_sync_record_marks_unsupported_sources(self) -> None:
        record = build_source_sync_record(
            {
                "source_id": "manual_skill",
                "display_name": "Manual Skill",
                "registry_package_name": "",
                "registry_package_manager": "",
            },
            checked_at="2026-04-06T12:00:00+00:00",
        )

        self.assertEqual("unsupported", record["sync_status"])
        self.assertEqual("2026-04-06T12:00:00+00:00", record["sync_checked_at"])
        self.assertEqual("", record["registry_latest_version"])

    def test_build_source_sync_record_marks_non_npm_registry_sources_unsupported(self) -> None:
        record = build_source_sync_record(
            {
                "source_id": "manual_local_skill",
                "display_name": "manual-local-skill",
                "registry_package_name": "manual-local-skill",
                "registry_package_manager": "filesystem",
            },
            checked_at="2026-04-06T12:00:00+00:00",
        )

        self.assertEqual("unsupported", record["sync_status"])
        self.assertEqual("", record["sync_kind"])
        self.assertIn("supported sync adapter", record["sync_message"])

    def test_build_source_sync_record_fetches_npm_registry(self) -> None:
        def _fake_urlopen(_url: str, timeout: int = 0):
            self.assertEqual(8, timeout)
            return _FakeResponse(
                {
                    "dist-tags": {"latest": "2.62.1"},
                    "versions": {
                        "2.62.1": {
                            "homepage": "https://github.com/every-env/compound-plugin",
                            "description": "Compound plugin bundle",
                        },
                    },
                    "time": {
                        "modified": "2026-04-01T12:00:00.000Z",
                        "2.62.1": "2026-04-01T11:58:00.000Z",
                    },
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "npx_bundle_compound_engineering_global",
                "display_name": "Compound Engineering",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=8,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("2026-04-06T12:00:00+00:00", record["sync_checked_at"])
        self.assertEqual("2.62.1", record["registry_latest_version"])
        self.assertIn("@every-env/compound-plugin", record["sync_message"])

    def test_build_source_sync_record_fetches_git_remote_head(self) -> None:
        def _fake_git_runner(args: list[str], *, cwd: str | None = None, timeout_s: int = 8):
            self.assertEqual(8, timeout_s)
            self.assertIsNone(cwd)
            self.assertEqual(["ls-remote", "https://github.com/vercel-labs/skills.git", "HEAD"], args)
            return True, "0123456789abcdef0123456789abcdef01234567\tHEAD\n"

        record = build_source_sync_record(
            {
                "source_id": "skill_lock_find_skills",
                "display_name": "find-skills",
                "source_kind": "manual_git",
                "locator": "https://github.com/vercel-labs/skills.git",
                "managed_by": "github",
                "update_policy": "source_sync",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            git_runner=_fake_git_runner,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("git_remote", record["sync_kind"])
        self.assertEqual("0123456789abcdef0123456789abcdef01234567", record["registry_latest_version"])
        self.assertEqual("0123456789abcdef0123456789abcdef01234567", record["sync_remote_revision"])
        self.assertEqual("0123456789abcdef0123456789abcdef01234567", record["sync_resolved_revision"])
        self.assertEqual("", record["sync_local_revision"])
        self.assertEqual("", record["sync_branch"])
        self.assertFalse(record["sync_dirty"])
        self.assertIn("vercel-labs/skills.git", record["sync_message"])

    def test_build_source_sync_record_prefers_git_checkout_metadata_when_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "skills"
            source_path.mkdir(parents=True, exist_ok=True)

            def _fake_git_runner(args: list[str], *, cwd: str | None = None, timeout_s: int = 8):
                self.assertEqual(8, timeout_s)
                self.assertEqual(str(source_path), cwd)
                if args == ["rev-parse", "--is-inside-work-tree"]:
                    return True, "true"
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return True, "main"
                if args == ["rev-parse", "HEAD"]:
                    return True, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                if args == ["status", "--porcelain"]:
                    return True, " M SKILL.md"
                return False, "unexpected command"

            record = build_source_sync_record(
                {
                    "source_id": "skill_lock_find_skills_checkout",
                    "display_name": "find-skills",
                    "source_kind": "manual_git",
                    "source_path": str(source_path),
                    "managed_by": "github",
                    "update_policy": "source_sync",
                },
                checked_at="2026-04-06T12:00:00+00:00",
                git_runner=_fake_git_runner,
            )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("git_checkout", record["sync_kind"])
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", record["sync_local_revision"])
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", record["sync_resolved_revision"])
        self.assertEqual("main", record["sync_branch"])
        self.assertTrue(record["sync_dirty"])

    def test_build_source_sync_record_prefers_managed_git_checkout_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "skills" / "find-skills"
            source_path.mkdir(parents=True, exist_ok=True)
            git_checkout_path = Path(tmpdir) / "git-checkout"
            git_checkout_path.mkdir(parents=True, exist_ok=True)

            def _fake_git_runner(args: list[str], *, cwd: str | None = None, timeout_s: int = 8):
                self.assertEqual(8, timeout_s)
                self.assertEqual(str(git_checkout_path), cwd)
                if args == ["rev-parse", "--is-inside-work-tree"]:
                    return True, "true"
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return True, "main"
                if args == ["rev-parse", "HEAD"]:
                    return True, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                if args == ["status", "--porcelain"]:
                    return True, ""
                return False, "unexpected command"

            record = build_source_sync_record(
                {
                    "source_id": "skill_lock_find_skills_checkout",
                    "display_name": "find-skills",
                    "source_kind": "manual_git",
                    "source_path": str(source_path),
                    "git_checkout_path": str(git_checkout_path),
                    "managed_by": "github",
                    "update_policy": "source_sync",
                },
                checked_at="2026-04-06T12:00:00+00:00",
                git_runner=_fake_git_runner,
            )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("git_checkout", record["sync_kind"])
        self.assertEqual("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", record["sync_local_revision"])
        self.assertEqual("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", record["sync_resolved_revision"])
        self.assertFalse(record["sync_dirty"])

    def test_build_source_sync_record_fetches_github_repo_metadata_for_repo_locator(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(7, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            self.assertEqual("https://api.github.com/repos/vercel-labs/skills", request_url)
            return _FakeResponse(
                {
                    "html_url": "https://github.com/vercel-labs/skills",
                    "description": "Vercel skills repository",
                    "default_branch": "main",
                    "pushed_at": "2026-04-10T12:34:56Z",
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "documented_find_skills",
                "display_name": "find-skills",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "manual",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=7,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("repo_metadata_github", record["sync_kind"])
        self.assertEqual("2026-04-10T12:34:56Z", record["registry_latest_version"])
        self.assertEqual("2026-04-10T12:34:56Z", record["sync_remote_revision"])
        self.assertEqual("2026-04-10T12:34:56Z", record["sync_resolved_revision"])
        self.assertEqual("main", record["sync_branch"])
        self.assertEqual("https://github.com/vercel-labs/skills", record["registry_homepage"])
        self.assertEqual("Vercel skills repository", record["registry_description"])

    def test_build_source_sync_record_reports_repo_metadata_error(self) -> None:
        def _fake_urlopen(_req, timeout: int = 0):
            self.assertEqual(5, timeout)
            raise RuntimeError("network down")

        record = build_source_sync_record(
            {
                "source_id": "documented_find_skills",
                "display_name": "find-skills",
                "source_kind": "manual_local",
                "locator": "repo:github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "manual",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=5,
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_github", record["sync_kind"])
        self.assertEqual("repo_metadata_request_failed", record["sync_error_code"])
        self.assertIn("network down", record["sync_message"])

    def test_build_source_sync_record_supports_self_hosted_gitlab_with_auth(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(11, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            self.assertEqual("https://gitlab.internal/api/v4/projects/group%2Fskills-pack", request_url)
            headers = {str(key).lower(): str(value) for key, value in req.header_items()}
            self.assertEqual("token-abc", headers.get("private-token"))
            return _FakeResponse(
                {
                    "web_url": "https://gitlab.internal/group/skills-pack",
                    "description": "Internal skills pack",
                    "default_branch": "main",
                    "last_activity_at": "2026-04-10T16:00:00.000Z",
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "internal_gitlab_pack",
                "display_name": "internal gitlab pack",
                "source_kind": "manual_local",
                "locator": "repo:https://gitlab.internal/group/skills-pack#skills",
                "managed_by": "gitlab",
                "update_policy": "manual",
                "sync_api_base": "https://gitlab.internal/api/v4",
                "sync_auth_header": "private-token",
                "sync_auth_token": "token-abc",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=11,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("repo_metadata_gitlab", record["sync_kind"])
        self.assertEqual("2026-04-10T16:00:00.000Z", record["sync_resolved_revision"])

    def test_build_source_sync_record_reports_repo_metadata_auth_config_error(self) -> None:
        record = build_source_sync_record(
            {
                "source_id": "documented_private_repo",
                "display_name": "private repo",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "github",
                "update_policy": "manual",
                "sync_auth_header": "Bearer",
            },
            checked_at="2026-04-06T12:00:00+00:00",
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_auth_config_invalid", record["sync_error_code"])
        self.assertIn("auth config", record["sync_message"])

    def test_build_source_sync_record_reports_repo_metadata_auth_failure(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(6, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            raise error.HTTPError(request_url, 401, "Unauthorized", {}, None)

        record = build_source_sync_record(
            {
                "source_id": "documented_private_repo",
                "display_name": "private repo",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "github",
                "update_policy": "manual",
                "sync_auth_token": "bad-token",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=6,
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_auth_failed", record["sync_error_code"])
        self.assertIn("http 401", record["sync_message"])

    def test_build_source_sync_record_reports_repo_metadata_rate_limited(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(6, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            raise error.HTTPError(request_url, 429, "Too Many Requests", {"Retry-After": "60"}, None)

        record = build_source_sync_record(
            {
                "source_id": "documented_rate_limited_repo",
                "display_name": "rate limited repo",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "github",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=6,
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_rate_limited", record["sync_error_code"])
        self.assertIn("retry_after=60", record["sync_message"])

    def test_build_source_sync_record_reports_repo_metadata_provider_unreachable(self) -> None:
        def _fake_urlopen(_req, timeout: int = 0):
            self.assertEqual(6, timeout)
            raise error.URLError("timed out")

        record = build_source_sync_record(
            {
                "source_id": "documented_unreachable_repo",
                "display_name": "unreachable repo",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "github",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=6,
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_provider_unreachable", record["sync_error_code"])
        self.assertIn("timed out", record["sync_message"])

    def test_build_source_sync_record_reports_repo_metadata_invalid_api_base(self) -> None:
        record = build_source_sync_record(
            {
                "source_id": "documented_invalid_api_base",
                "display_name": "invalid api base",
                "source_kind": "manual_local",
                "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                "managed_by": "github",
                "update_policy": "manual",
                "sync_api_base": "http:///missing-host",
            },
            checked_at="2026-04-06T12:00:00+00:00",
        )

        self.assertEqual("error", record["sync_status"])
        self.assertEqual("repo_metadata_api_base_invalid", record["sync_error_code"])

    def test_build_source_sync_record_fetches_gitlab_repo_metadata_for_repo_locator(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(9, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            self.assertEqual("https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab", request_url)
            return _FakeResponse(
                {
                    "web_url": "https://gitlab.com/gitlab-org/gitlab",
                    "description": "GitLab project",
                    "default_branch": "main",
                    "last_activity_at": "2026-04-10T15:00:00.000Z",
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "documented_gitlab_project",
                "display_name": "gitlab project",
                "source_kind": "manual_local",
                "locator": "documented:https://gitlab.com/gitlab-org/gitlab#docs",
                "managed_by": "manual",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=9,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("repo_metadata_gitlab", record["sync_kind"])
        self.assertEqual("2026-04-10T15:00:00.000Z", record["registry_latest_version"])
        self.assertEqual("2026-04-10T15:00:00.000Z", record["sync_remote_revision"])
        self.assertEqual("2026-04-10T15:00:00.000Z", record["sync_resolved_revision"])
        self.assertEqual("main", record["sync_branch"])
        self.assertEqual("https://gitlab.com/gitlab-org/gitlab", record["registry_homepage"])
        self.assertEqual("GitLab project", record["registry_description"])

    def test_build_source_sync_record_fetches_bitbucket_repo_metadata_for_repo_locator(self) -> None:
        def _fake_urlopen(req, timeout: int = 0):
            self.assertEqual(10, timeout)
            request_url = req.full_url if hasattr(req, "full_url") else str(req)
            self.assertEqual(
                "https://api.bitbucket.org/2.0/repositories/atlassian/python-bitbucket",
                request_url,
            )
            return _FakeResponse(
                {
                    "description": "Bitbucket SDK",
                    "updated_on": "2026-04-09T05:06:07+00:00",
                    "mainbranch": {"name": "master"},
                    "links": {"html": {"href": "https://bitbucket.org/atlassian/python-bitbucket"}},
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "documented_bitbucket_project",
                "display_name": "bitbucket project",
                "source_kind": "manual_local",
                "locator": "catalog:https://bitbucket.org/atlassian/python-bitbucket#skills",
                "managed_by": "manual",
                "update_policy": "manual",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=10,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("repo_metadata_bitbucket", record["sync_kind"])
        self.assertEqual("2026-04-09T05:06:07+00:00", record["registry_latest_version"])
        self.assertEqual("2026-04-09T05:06:07+00:00", record["sync_remote_revision"])
        self.assertEqual("2026-04-09T05:06:07+00:00", record["sync_resolved_revision"])
        self.assertEqual("master", record["sync_branch"])
        self.assertEqual("https://bitbucket.org/atlassian/python-bitbucket", record["registry_homepage"])
        self.assertEqual("Bitbucket SDK", record["registry_description"])

    def test_is_source_syncable_supports_npm_and_git(self) -> None:
        self.assertTrue(
            is_source_syncable(
                {
                    "registry_package_name": "@every-env/compound-plugin",
                    "registry_package_manager": "npm",
                },
            ),
        )
        self.assertTrue(
            is_source_syncable(
                {
                    "source_kind": "manual_git",
                    "locator": "https://github.com/vercel-labs/skills.git",
                    "managed_by": "github",
                    "update_policy": "source_sync",
                },
            ),
        )
        self.assertTrue(
            is_source_syncable(
                {
                    "source_kind": "manual_local",
                    "locator": "repo:github.com/vercel-labs/skills#skills/find-skills",
                    "managed_by": "manual",
                    "update_policy": "manual",
                },
            ),
        )
        self.assertTrue(
            is_source_syncable(
                {
                    "source_kind": "manual_local",
                    "locator": "documented:https://gitlab.com/gitlab-org/gitlab#docs",
                    "managed_by": "manual",
                    "update_policy": "manual",
                },
            ),
        )
        self.assertTrue(
            is_source_syncable(
                {
                    "source_kind": "manual_local",
                    "locator": "catalog:https://bitbucket.org/atlassian/python-bitbucket#skills",
                    "managed_by": "manual",
                    "update_policy": "manual",
                },
            ),
        )
        self.assertTrue(
            is_source_syncable(
                {
                    "source_kind": "manual_local",
                    "locator": "repo:https://gitlab.internal/group/skills-pack#skills",
                    "managed_by": "gitlab",
                    "sync_api_base": "https://gitlab.internal/api/v4",
                    "update_policy": "manual",
                },
            ),
        )
        self.assertFalse(
            is_source_syncable(
                {
                    "source_kind": "manual_local",
                    "source_path": "/tmp/manual-skill",
                    "managed_by": "manual",
                    "update_policy": "manual",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
