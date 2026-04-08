from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import skills_aggregation_core as skills_core
from skills_aggregation_core import (
    build_collection_group_rows,
    build_install_unit_rows,
    derive_source_aggregation_fields,
    derive_source_provenance_fields,
)


class SkillsAggregationCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self._set_cache_roots(Path(self._tempdir.name) / ".isolated-package-cache")

    def _set_cache_roots(self, *roots: Path) -> None:
        previous = os.environ.get("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS")
        joined = os.pathsep.join(str(root) for root in roots)
        os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = joined

        def _restore() -> None:
            if previous is None:
                os.environ.pop("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS", None)
            else:
                os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = previous

        self.addCleanup(_restore)

    def _set_local_mirror_roots(self, *roots: Path) -> None:
        previous = os.environ.get("ONESYNC_SKILL_LOCAL_MIRROR_ROOTS")
        joined = os.pathsep.join(str(root) for root in roots)
        os.environ["ONESYNC_SKILL_LOCAL_MIRROR_ROOTS"] = joined

        def _restore() -> None:
            if previous is None:
                os.environ.pop("ONESYNC_SKILL_LOCAL_MIRROR_ROOTS", None)
            else:
                os.environ["ONESYNC_SKILL_LOCAL_MIRROR_ROOTS"] = previous

        self.addCleanup(_restore)

    def test_manual_git_subpath_uses_repo_group_and_subpath_install_unit(self) -> None:
        source = {
            "source_id": "manual_git_ui_audit",
            "display_name": "UI Audit",
            "source_kind": "manual_git",
            "locator": "https://github.com/demo/skills.git",
            "source_subpath": "packages/ui-audit",
            "source_scope": "global",
        }

        provenance = derive_source_provenance_fields(source)
        aggregation = derive_source_aggregation_fields(source)

        self.assertEqual("git_source", provenance["provenance_origin_kind"])
        self.assertEqual("https://github.com/demo/skills.git", provenance["provenance_origin_ref"])
        self.assertEqual("demo/skills", provenance["provenance_origin_label"])
        self.assertEqual("source_locator_subpath", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])

        self.assertEqual(
            "git:https://github.com/demo/skills.git#packages/ui-audit",
            aggregation["install_unit_id"],
        )
        self.assertEqual(
            "https://github.com/demo/skills.git#packages/ui-audit",
            aggregation["install_ref"],
        )
        self.assertEqual("git_source", aggregation["install_unit_kind"])
        self.assertEqual("source_locator_subpath", aggregation["aggregation_strategy"])
        self.assertEqual("demo/skills :: packages/ui-audit", aggregation["install_unit_display_name"])
        self.assertEqual("collection:source_repo_demo_skills", aggregation["collection_group_id"])
        self.assertEqual("demo/skills", aggregation["collection_group_name"])
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_manual_local_subpath_uses_root_group_and_subpath_install_unit(self) -> None:
        source = {
            "source_id": "manual_local_codex",
            "display_name": "Workspace Codex Skills",
            "source_kind": "manual_local",
            "locator": "/opt/skills-pack",
            "source_subpath": "bundles/codex",
            "source_scope": "workspace",
        }

        provenance = derive_source_provenance_fields(source)
        aggregation = derive_source_aggregation_fields(source)

        self.assertEqual("local_source", provenance["provenance_origin_kind"])
        self.assertEqual("/opt/skills-pack", provenance["provenance_origin_ref"])
        self.assertEqual("skills-pack", provenance["provenance_origin_label"])
        self.assertEqual("source_locator_subpath", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])

        self.assertEqual(
            "local:/opt/skills-pack#bundles/codex",
            aggregation["install_unit_id"],
        )
        self.assertEqual("/opt/skills-pack#bundles/codex", aggregation["install_ref"])
        self.assertEqual("local_source", aggregation["install_unit_kind"])
        self.assertEqual("source_locator_subpath", aggregation["aggregation_strategy"])
        self.assertEqual("skills-pack :: bundles/codex", aggregation["install_unit_display_name"])
        self.assertEqual("collection:source_root_opt_skills_pack", aggregation["collection_group_id"])
        self.assertEqual("skills-pack", aggregation["collection_group_name"])
        self.assertEqual("source_root", aggregation["collection_group_kind"])

    def test_build_collection_group_rows_groups_manual_git_subpaths_under_same_repo(self) -> None:
        source_rows = [
            {
                "source_id": "manual_git_ui_audit",
                "display_name": "UI Audit",
                "source_kind": "manual_git",
                "locator": "https://github.com/demo/skills.git",
                "source_subpath": "packages/ui-audit",
                "source_scope": "global",
                "member_count": 1,
                "member_skill_preview": ["ui-audit"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            },
            {
                "source_id": "manual_git_ui_reviewer",
                "display_name": "UI Reviewer",
                "source_kind": "manual_git",
                "locator": "https://github.com/demo/skills.git",
                "source_subpath": "packages/ui-reviewer",
                "source_scope": "global",
                "member_count": 1,
                "member_skill_preview": ["ui-reviewer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            },
        ]

        install_unit_rows = build_install_unit_rows(source_rows, [])
        collection_group_rows = build_collection_group_rows(install_unit_rows)

        self.assertEqual(2, len(install_unit_rows))
        self.assertEqual(
            {
                "git:https://github.com/demo/skills.git#packages/ui-audit",
                "git:https://github.com/demo/skills.git#packages/ui-reviewer",
            },
            {item["install_unit_id"] for item in install_unit_rows},
        )
        self.assertEqual(1, len(collection_group_rows))
        self.assertEqual("collection:source_repo_demo_skills", collection_group_rows[0]["collection_group_id"])
        self.assertEqual("source_repo", collection_group_rows[0]["collection_group_kind"])
        self.assertEqual("https://github.com/demo/skills.git", collection_group_rows[0]["locator"])
        self.assertEqual(
            ["packages/ui-audit", "packages/ui-reviewer"],
            collection_group_rows[0]["source_subpaths"],
        )
        self.assertEqual(2, collection_group_rows[0]["install_unit_count"])
        self.assertEqual(2, collection_group_rows[0]["source_count"])
        install_unit_by_id = {item["install_unit_id"]: item for item in install_unit_rows}
        self.assertEqual(
            "https://github.com/demo/skills.git",
            install_unit_by_id["git:https://github.com/demo/skills.git#packages/ui-audit"]["locator"],
        )
        self.assertEqual(
            "packages/ui-audit",
            install_unit_by_id["git:https://github.com/demo/skills.git#packages/ui-audit"]["source_subpath"],
        )
        self.assertEqual(
            ["packages/ui-audit"],
            install_unit_by_id["git:https://github.com/demo/skills.git#packages/ui-audit"]["source_subpaths"],
        )

    def test_build_install_units_promotes_legacy_root_family_groups_without_merging_install_units(self) -> None:
        source_rows = [
            {
                "source_id": "npx_global_git_commit",
                "display_name": "git-commit",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": "/root/.codex/skills/git-commit",
                "member_count": 1,
                "member_skill_preview": ["git-commit"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            },
            {
                "source_id": "npx_global_git_worktree",
                "display_name": "git-worktree",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": "/root/.codex/skills/git-worktree",
                "member_count": 1,
                "member_skill_preview": ["git-worktree"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            },
            {
                "source_id": "npx_global_find_skills",
                "display_name": "find-skills",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": "/root/.agents/skills/find-skills",
                "member_count": 1,
                "member_skill_preview": ["find-skills"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            },
        ]

        install_unit_rows = build_install_unit_rows(source_rows, [])
        collection_group_rows = build_collection_group_rows(install_unit_rows)

        install_unit_by_id = {item["install_unit_id"]: item for item in install_unit_rows}
        git_commit = install_unit_by_id["synthetic_single:npx_global_git_commit"]
        git_worktree = install_unit_by_id["synthetic_single:npx_global_git_worktree"]
        find_skills = install_unit_by_id["synthetic_single:npx_global_find_skills"]

        self.assertEqual(
            "collection:legacy_family_codex_skills_root_git_global",
            git_commit["collection_group_id"],
        )
        self.assertEqual(
            "collection:legacy_family_codex_skills_root_git_global",
            git_worktree["collection_group_id"],
        )
        self.assertEqual("Git", git_commit["collection_group_name"])
        self.assertEqual("legacy_family", git_commit["collection_group_kind"])
        self.assertEqual("collection:find_skills", find_skills["collection_group_id"])
        self.assertEqual("install_unit", find_skills["collection_group_kind"])

        collection_group_by_id = {
            item["collection_group_id"]: item
            for item in collection_group_rows
        }
        git_group = collection_group_by_id["collection:legacy_family_codex_skills_root_git_global"]
        self.assertEqual("legacy_family", git_group["collection_group_kind"])
        self.assertEqual(2, git_group["install_unit_count"])
        self.assertEqual(2, git_group["source_count"])
        self.assertEqual(2, git_group["member_count"])
        self.assertEqual(
            {
                "synthetic_single:npx_global_git_commit",
                "synthetic_single:npx_global_git_worktree",
            },
            set(git_group["install_unit_ids"]),
        )

    def test_npx_single_recovers_generic_package_from_cache_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            alpha_source = source_root / "alpha-reviewer"
            beta_source = source_root / "beta-reviewer"
            alpha_source.mkdir(parents=True, exist_ok=True)
            beta_source.mkdir(parents=True, exist_ok=True)
            alpha_content = "---\nname: alpha-reviewer\ndescription: Alpha reviewer\n---\n"
            beta_content = "---\nname: beta-reviewer\ndescription: Beta reviewer\n---\n"
            (alpha_source / "SKILL.md").write_text(alpha_content, encoding="utf-8")
            (beta_source / "SKILL.md").write_text(beta_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "demo123" / "node_modules" / "@demo" / "review-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/review-pack"}),
                encoding="utf-8",
            )
            alpha_cache = package_root / "skills" / "alpha-reviewer"
            beta_cache = package_root / "skills" / "beta-reviewer"
            alpha_cache.mkdir(parents=True, exist_ok=True)
            beta_cache.mkdir(parents=True, exist_ok=True)
            (alpha_cache / "SKILL.md").write_text(alpha_content, encoding="utf-8")
            (beta_cache / "SKILL.md").write_text(beta_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            alpha_source_row = {
                "source_id": "npx_global_alpha_reviewer",
                "display_name": "alpha-reviewer",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(alpha_source),
                "member_count": 1,
                "member_skill_preview": ["alpha-reviewer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }
            beta_source_row = {
                "source_id": "npx_global_beta_reviewer",
                "display_name": "beta-reviewer",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(beta_source),
                "member_count": 1,
                "member_skill_preview": ["beta-reviewer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(alpha_source_row)
            aggregation = derive_source_aggregation_fields(alpha_source_row)
            install_unit_rows = build_install_unit_rows(
                [alpha_source_row, beta_source_row],
                [],
            )
            collection_group_rows = build_collection_group_rows(install_unit_rows)

        self.assertEqual("@demo/review-pack", provenance["provenance_package_name"])
        self.assertEqual("cache_path_heuristic", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])
        self.assertEqual("npm:@demo/review-pack", aggregation["install_unit_id"])
        self.assertEqual("@demo/review-pack", aggregation["install_unit_display_name"])
        self.assertEqual("package", aggregation["collection_group_kind"])

        self.assertEqual(1, len(install_unit_rows))
        self.assertEqual("npm:@demo/review-pack", install_unit_rows[0]["install_unit_id"])
        self.assertEqual(2, install_unit_rows[0]["source_count"])
        self.assertEqual(2, install_unit_rows[0]["member_count"])
        self.assertEqual("@demo/review-pack", install_unit_rows[0]["display_name"])
        self.assertEqual("package", install_unit_rows[0]["collection_group_kind"])
        self.assertEqual(1, len(collection_group_rows))
        self.assertEqual("package", collection_group_rows[0]["collection_group_kind"])
        self.assertEqual(1, collection_group_rows[0]["install_unit_count"])
        self.assertEqual(2, collection_group_rows[0]["source_count"])

    def test_npx_single_recovers_package_from_high_similarity_cache_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "agent-browser"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: agent-browser\n"
                "description: Browser automation CLI for AI agents.\n"
                "---\n\n"
                "Priority order: ~/.agent-browser/config.json < .the agent-browser skill.json < env vars.\n"
                "Use AGENT_BROWSER_CONFIG for custom config.\n"
            )
            cache_content = (
                "---\n"
                "name: agent-browser\n"
                "description: Browser automation CLI for AI agents.\n"
                "---\n\n"
                "Priority order: ~/.agent-browser/config.json < ./agent-browser.json < env vars.\n"
                "Use AGENT_BROWSER_CONFIG for custom config.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "browser-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/browser-pack"}),
                encoding="utf-8",
            )
            cache_skill = package_root / "skills" / "agent-browser"
            cache_skill.mkdir(parents=True, exist_ok=True)
            (cache_skill / "SKILL.md").write_text(cache_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_agent_browser",
                "display_name": "agent-browser",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["agent-browser"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("@demo/browser-pack", provenance["provenance_package_name"])
        self.assertEqual("cache_similarity_match", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])
        self.assertEqual("npm:@demo/browser-pack", aggregation["install_unit_id"])
        self.assertEqual("package", aggregation["collection_group_kind"])

    def test_npx_single_does_not_recover_package_when_cache_match_is_too_different(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "agent-browser"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: agent-browser\n"
                "description: Browser automation CLI for AI agents.\n"
                "---\n\n"
                "Completely different local content.\n"
                "This should not be treated as the same installed package.\n"
            )
            cache_content = (
                "---\n"
                "name: agent-browser\n"
                "description: Browser automation CLI for AI agents.\n"
                "---\n\n"
                "Canonical cache content with many operational details.\n"
                "Use AGENT_BROWSER_CONFIG for custom config.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "browser-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/browser-pack"}),
                encoding="utf-8",
            )
            cache_skill = package_root / "skills" / "agent-browser"
            cache_skill.mkdir(parents=True, exist_ok=True)
            (cache_skill / "SKILL.md").write_text(cache_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_agent_browser",
                "display_name": "agent-browser",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["agent-browser"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("", provenance["provenance_package_name"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("synthetic_single:npx_global_agent_browser", aggregation["install_unit_id"])

    def test_npx_single_recovers_package_from_agent_export_cache_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "security-reviewer"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: security-reviewer\n"
                "description: Conditional code-review persona for security issues.\n"
                "---\n\n"
                "# Security Reviewer\n\n"
                "Review code for exploitable vulnerabilities.\n"
            )
            mirror_content = (
                "---\n"
                "name: security-reviewer\n"
                "description: Conditional code-review persona for security issues.\n"
                "model: inherit\n"
                "tools: Read, Grep, Glob, Bash\n"
                "color: blue\n"
                "---\n\n"
                "# Security Reviewer\n\n"
                "Review code for exploitable vulnerabilities.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "review-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/review-pack"}),
                encoding="utf-8",
            )
            mirror_doc = package_root / "plugins" / "review-pack" / "agents" / "review" / "security-reviewer.md"
            mirror_doc.parent.mkdir(parents=True, exist_ok=True)
            mirror_doc.write_text(mirror_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_security_reviewer",
                "display_name": "security-reviewer",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["security-reviewer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("@demo/review-pack", provenance["provenance_package_name"])
        self.assertEqual("cache_agent_similarity_match", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])
        self.assertEqual("npm:@demo/review-pack", aggregation["install_unit_id"])
        self.assertEqual("package", aggregation["collection_group_kind"])

    def test_npx_single_ignores_test_fixture_agent_export_cache_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "security-reviewer"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: security-reviewer\n"
                "description: Conditional code-review persona for security issues.\n"
                "---\n\n"
                "# Security Reviewer\n\n"
                "Review code for exploitable vulnerabilities.\n"
            )
            mirror_content = (
                "---\n"
                "name: security-reviewer\n"
                "description: Conditional code-review persona for security issues.\n"
                "model: inherit\n"
                "tools: Read, Grep, Glob, Bash\n"
                "---\n\n"
                "# Security Reviewer\n\n"
                "Review code for exploitable vulnerabilities.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "review-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/review-pack"}),
                encoding="utf-8",
            )
            mirror_doc = package_root / "tests" / "fixtures" / "sample-plugin" / "agents" / "review" / "security-reviewer.md"
            mirror_doc.parent.mkdir(parents=True, exist_ok=True)
            mirror_doc.write_text(mirror_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_security_reviewer",
                "display_name": "security-reviewer",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["security-reviewer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("", provenance["provenance_package_name"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("synthetic_single:npx_global_security_reviewer", aggregation["install_unit_id"])

    def test_npx_single_recovers_local_plugin_bundle_from_exact_skill_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "frontend-skill"
            source_skill.mkdir(parents=True, exist_ok=True)
            skill_content = (
                "---\n"
                "name: frontend-skill\n"
                "description: Use when the task asks for a visually strong landing page.\n"
                "---\n\n"
                "# Frontend Skill\n\n"
                "Use this skill when the quality of the work depends on art direction.\n"
            )
            (source_skill / "SKILL.md").write_text(skill_content, encoding="utf-8")

            plugin_root = temp_root / ".codex" / ".tmp" / "plugins" / "plugins" / "build-web-apps"
            mirror_skill = plugin_root / "skills" / "frontend-skill"
            mirror_skill.mkdir(parents=True, exist_ok=True)
            (mirror_skill / "SKILL.md").write_text(skill_content, encoding="utf-8")
            plugin_meta_dir = plugin_root / ".codex-plugin"
            plugin_meta_dir.mkdir(parents=True, exist_ok=True)
            (plugin_meta_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": "build-web-apps",
                        "repository": "https://github.com/openai/plugins",
                        "interface": {
                            "displayName": "Build Web Apps",
                        },
                    },
                ),
                encoding="utf-8",
            )

            self._set_local_mirror_roots(temp_root / ".codex" / ".tmp" / "plugins")

            source_row = {
                "source_id": "npx_global_frontend_skill",
                "display_name": "frontend-skill",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["frontend-skill"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("local_plugin_bundle", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/openai/plugins#build-web-apps",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("Build Web Apps", provenance["provenance_origin_label"])
        self.assertEqual("local_plugin_exact_mirror", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])
        self.assertEqual(
            "plugin:https://github.com/openai/plugins#build-web-apps",
            aggregation["install_unit_id"],
        )
        self.assertEqual("local_plugin_bundle", aggregation["install_unit_kind"])
        self.assertEqual("Build Web Apps", aggregation["install_unit_display_name"])
        self.assertEqual("plugin_bundle", aggregation["collection_group_kind"])

    def test_npx_single_recovers_documented_source_repo_from_embedded_clone_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "humanizer"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: humanizer\n"
                "description: Remove signs of AI-generated writing from text.\n"
                "---\n",
                encoding="utf-8",
            )
            (source_skill / "README.md").write_text(
                "# Humanizer\n\n"
                "Install with:\n\n"
                "```bash\n"
                "git clone https://github.com/blader/humanizer.git ~/.claude/skills/humanizer\n"
                "```\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_humanizer",
                "display_name": "humanizer",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["humanizer"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("documented_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual("https://github.com/blader/humanizer.git", provenance["provenance_origin_ref"])
        self.assertEqual("blader/humanizer", provenance["provenance_origin_label"])
        self.assertEqual("embedded_git_clone_url", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])

        self.assertEqual("repo:https://github.com/blader/humanizer.git", aggregation["install_unit_id"])
        self.assertEqual("documented_source_repo", aggregation["install_unit_kind"])
        self.assertEqual("https://github.com/blader/humanizer.git", aggregation["install_ref"])
        self.assertEqual("manual", aggregation["install_manager"])
        self.assertEqual("blader/humanizer", aggregation["install_unit_display_name"])
        self.assertEqual("collection:source_repo_blader_humanizer", aggregation["collection_group_id"])
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_npx_single_documented_source_repo_prefers_install_repo_over_reference_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "humanizer-zh"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: humanizer-zh\n"
                "description: 去除文本中的 AI 生成痕迹。\n"
                "---\n",
                encoding="utf-8",
            )
            (source_skill / "README.md").write_text(
                "# Humanizer-zh\n\n"
                "灵感来源：https://github.com/blader/humanizer\n\n"
                "安装：\n\n"
                "```bash\n"
                "npx skills add https://github.com/op7418/Humanizer-zh.git\n"
                "```\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_humanizer_zh",
                "display_name": "humanizer-zh",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["humanizer-zh"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)

        self.assertEqual("documented_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual("https://github.com/op7418/Humanizer-zh.git", provenance["provenance_origin_ref"])
        self.assertEqual("op7418/Humanizer-zh", provenance["provenance_origin_label"])
        self.assertEqual("embedded_skills_add_url", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])

    def test_npx_single_recovers_documented_source_repo_subpath_from_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "playwright"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: playwright\n"
                "description: Browser automation from the terminal.\n"
                "---\n",
                encoding="utf-8",
            )
            (source_skill / "NOTICE.txt").write_text(
                "This skill includes material derived from the Microsoft playwright-cli repository.\n\n"
                "Source:\n"
                "- Repository: microsoft/playwright-cli\n"
                "- Path: skills/playwright-cli/SKILL.md\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_playwright",
                "display_name": "playwright",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["playwright"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("documented_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/microsoft/playwright-cli.git#skills/playwright-cli",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("microsoft/playwright-cli", provenance["provenance_origin_label"])
        self.assertEqual("embedded_notice_repository", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])

        self.assertEqual(
            "repo:https://github.com/microsoft/playwright-cli.git#skills/playwright-cli",
            aggregation["install_unit_id"],
        )
        self.assertEqual("documented_source_repo", aggregation["install_unit_kind"])
        self.assertEqual(
            "microsoft/playwright-cli :: skills/playwright-cli",
            aggregation["install_unit_display_name"],
        )
        self.assertEqual("collection:source_repo_microsoft_playwright_cli", aggregation["collection_group_id"])
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_npx_single_recovers_catalog_source_repo_from_curated_reference_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "ui-ux-pro-max"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: ui-ux-pro-max\n"
                "description: UI/UX design intelligence for web and mobile.\n"
                "---\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_ui_ux_pro_max",
                "display_name": "ui-ux-pro-max",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["ui-ux-pro-max"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("catalog_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git#.claude/skills/ui-ux-pro-max",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("nextlevelbuilder/ui-ux-pro-max-skill", provenance["provenance_origin_label"])
        self.assertEqual("catalog_reference_hint", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])

        self.assertEqual(
            "repo:https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git#.claude/skills/ui-ux-pro-max",
            aggregation["install_unit_id"],
        )
        self.assertEqual("catalog_source_repo", aggregation["install_unit_kind"])
        self.assertEqual(
            "nextlevelbuilder/ui-ux-pro-max-skill :: .claude/skills/ui-ux-pro-max",
            aggregation["install_unit_display_name"],
        )
        self.assertEqual("collection:source_repo_nextlevelbuilder_ui_ux_pro_max_skill", aggregation["collection_group_id"])
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_npx_single_catalog_source_repo_hint_does_not_promote_unlisted_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "javascript-pro"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: javascript-pro\n"
                "description: Master modern JavaScript with ES6+.\n"
                "---\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_javascript_pro",
                "display_name": "javascript-pro",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["javascript-pro"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("skills_root", provenance["provenance_origin_kind"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("low", provenance["provenance_confidence"])
        self.assertEqual("synthetic_single:npx_global_javascript_pro", aggregation["install_unit_id"])

    def test_npx_single_recovers_community_source_repo_from_curated_reference_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "javascript-mastery"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: javascript-mastery\n"
                "description: Comprehensive JavaScript reference covering 33+ essential concepts every developer should know.\n"
                "---\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_javascript_mastery",
                "display_name": "javascript-mastery",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["javascript-mastery"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("community_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/sickn33/antigravity-awesome-skills.git#skills/javascript-mastery",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("sickn33/antigravity-awesome-skills", provenance["provenance_origin_label"])
        self.assertEqual("community_reference_hint", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])

        self.assertEqual(
            "repo:https://github.com/sickn33/antigravity-awesome-skills.git#skills/javascript-mastery",
            aggregation["install_unit_id"],
        )
        self.assertEqual("community_source_repo", aggregation["install_unit_kind"])
        self.assertEqual(
            "sickn33/antigravity-awesome-skills :: skills/javascript-mastery",
            aggregation["install_unit_display_name"],
        )
        self.assertEqual(
            "collection:source_repo_sickn33_antigravity_awesome_skills",
            aggregation["collection_group_id"],
        )
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_npx_single_recovers_second_community_source_repo_from_curated_reference_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "powershell-windows"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: powershell-windows\n"
                "description: PowerShell Windows patterns. Critical pitfalls, operator syntax, error handling.\n"
                "---\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_powershell_windows",
                "display_name": "powershell-windows",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["powershell-windows"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)

        self.assertEqual("community_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/sickn33/antigravity-awesome-skills.git#skills/powershell-windows",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("community_reference_hint", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])

    def test_npx_single_community_source_repo_hint_does_not_promote_unverified_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "database-migrations-sql-migrations"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: database-migrations-sql-migrations\n"
                "description: SQL database migrations with zero-downtime strategies for PostgreSQL, MySQL, SQL Server\n"
                "---\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_database_migrations_sql_migrations",
                "display_name": "database-migrations-sql-migrations",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["database-migrations-sql-migrations"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("skills_root", provenance["provenance_origin_kind"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("low", provenance["provenance_confidence"])
        self.assertEqual(
            "synthetic_single:npx_global_database_migrations_sql_migrations",
            aggregation["install_unit_id"],
        )

    def test_npx_single_recovers_community_source_repo_from_exact_support_file_derivative_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "database-migrations-sql-migrations"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: database-migrations-sql-migrations\n"
                "description: SQL database migrations with zero-downtime strategies for PostgreSQL, MySQL, SQL Server\n"
                "---\n",
                encoding="utf-8",
            )
            support_text = (
                "# Implementation Playbook\n\n"
                "Exact upstream derivative evidence.\n"
            )
            support_file = source_skill / "resources" / "implementation-playbook.md"
            support_file.parent.mkdir(parents=True, exist_ok=True)
            support_file.write_text(support_text, encoding="utf-8")

            previous_hints = dict(skills_core._COMMUNITY_DERIVATIVE_SKILL_REPO_HINTS)
            skills_core._COMMUNITY_DERIVATIVE_SKILL_REPO_HINTS = {
                "database-migrations-sql-migrations": {
                    "origin_ref": "https://github.com/demo/community-skills.git#skills/database-migrations-sql-migrations",
                    "required_support_file": "resources/implementation-playbook.md",
                    "required_support_signature": skills_core._normalized_text_sha1(support_text),
                }
            }
            self.addCleanup(
                setattr,
                skills_core,
                "_COMMUNITY_DERIVATIVE_SKILL_REPO_HINTS",
                previous_hints,
            )

            source_row = {
                "source_id": "npx_global_database_migrations_sql_migrations",
                "display_name": "database-migrations-sql-migrations",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["database-migrations-sql-migrations"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("community_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/demo/community-skills.git#skills/database-migrations-sql-migrations",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("demo/community-skills", provenance["provenance_origin_label"])
        self.assertEqual("community_support_file_derivative", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])
        self.assertEqual(
            "repo:https://github.com/demo/community-skills.git#skills/database-migrations-sql-migrations",
            aggregation["install_unit_id"],
        )
        self.assertEqual("community_source_repo", aggregation["install_unit_kind"])
        self.assertEqual(
            "demo/community-skills :: skills/database-migrations-sql-migrations",
            aggregation["install_unit_display_name"],
        )
        self.assertEqual(
            "collection:source_repo_demo_community_skills",
            aggregation["collection_group_id"],
        )

    def test_npx_single_recovers_community_source_repo_from_exact_markdown_tail_derivative_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "javascript-pro"
            source_skill.mkdir(parents=True, exist_ok=True)
            tail_text = (
                "## Focus Areas\n\n"
                "- Async patterns\n"
                "- Node.js APIs\n\n"
                "## Output\n\n"
                "- Modern JavaScript\n"
            )
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: javascript-pro\n"
                "description: Master modern JavaScript with ES6+.\n"
                "---\n\n"
                "Host-adapted preamble.\n\n"
                "## Use this skill when\n\n"
                "- Building JavaScript tools\n\n"
                f"{tail_text}",
                encoding="utf-8",
            )

            previous_hints = dict(skills_core._COMMUNITY_MARKDOWN_TAIL_DERIVATIVE_SKILL_REPO_HINTS)
            skills_core._COMMUNITY_MARKDOWN_TAIL_DERIVATIVE_SKILL_REPO_HINTS = {
                "javascript-pro": {
                    "origin_ref": "https://github.com/demo/js-skills.git#skills/javascript-pro",
                    "required_tail_marker": "## Focus Areas",
                    "required_tail_signature": skills_core._normalized_text_sha1(tail_text),
                }
            }
            self.addCleanup(
                setattr,
                skills_core,
                "_COMMUNITY_MARKDOWN_TAIL_DERIVATIVE_SKILL_REPO_HINTS",
                previous_hints,
            )

            source_row = {
                "source_id": "npx_global_javascript_pro",
                "display_name": "javascript-pro",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["javascript-pro"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("community_source_repo", provenance["provenance_origin_kind"])
        self.assertEqual(
            "https://github.com/demo/js-skills.git#skills/javascript-pro",
            provenance["provenance_origin_ref"],
        )
        self.assertEqual("demo/js-skills", provenance["provenance_origin_label"])
        self.assertEqual("community_markdown_tail_derivative", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])
        self.assertEqual(
            "repo:https://github.com/demo/js-skills.git#skills/javascript-pro",
            aggregation["install_unit_id"],
        )
        self.assertEqual("community_source_repo", aggregation["install_unit_kind"])

    def test_npx_single_recovers_explicit_local_custom_skill_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "doc"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: doc\n"
                "description: Improve project documentation\n"
                "---\n\n"
                "Local custom documentation workflow.\n",
                encoding="utf-8",
            )

            previous_hints = dict(skills_core._LOCAL_CUSTOM_SKILL_HINTS)
            skills_core._LOCAL_CUSTOM_SKILL_HINTS = {
                "doc": {
                    "origin_label": "Local Custom Skill",
                }
            }
            self.addCleanup(
                setattr,
                skills_core,
                "_LOCAL_CUSTOM_SKILL_HINTS",
                previous_hints,
            )

            source_row = {
                "source_id": "npx_global_doc",
                "display_name": "doc",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["doc"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("local_custom_skill", provenance["provenance_origin_kind"])
        self.assertEqual(str(source_skill), provenance["provenance_origin_ref"])
        self.assertEqual("Local Custom Skill", provenance["provenance_origin_label"])
        self.assertEqual("explicit_local_custom_hint", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])
        self.assertEqual(f"local_custom:{source_skill}", aggregation["install_unit_id"])
        self.assertEqual("local_custom_skill", aggregation["install_unit_kind"])
        self.assertEqual(str(source_skill), aggregation["install_ref"])
        self.assertEqual("doc", aggregation["install_unit_display_name"])
        self.assertEqual("collection:local_custom_codex_home_skills", aggregation["collection_group_id"])
        self.assertEqual("Local Custom Skills", aggregation["collection_group_name"])
        self.assertEqual("local_custom", aggregation["collection_group_kind"])

    def test_npx_single_recovers_local_derivative_group_from_embedded_base_skill_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"

            base_skill = source_root / "playwright"
            base_skill.mkdir(parents=True, exist_ok=True)
            (base_skill / "SKILL.md").write_text(
                "---\n"
                "name: playwright\n"
                "description: Browser automation from the terminal.\n"
                "---\n",
                encoding="utf-8",
            )
            (base_skill / "NOTICE.txt").write_text(
                "This skill includes material derived from the Microsoft playwright-cli repository.\n\n"
                "Source:\n"
                "- Repository: microsoft/playwright-cli\n"
                "- Path: skills/playwright-cli/SKILL.md\n",
                encoding="utf-8",
            )

            source_skill = source_root / "playwright-interactive"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: playwright-interactive\n"
                "description: Persistent browser and Electron interaction through js_repl.\n"
                "---\n",
                encoding="utf-8",
            )
            (source_skill / "NOTICE.txt").write_text(
                "This skill reuses the Playwright icon assets from `.codex/skills/playwright/assets/`.\n\n"
                "The local `playwright` skill attributes those assets to the Microsoft\n"
                "`playwright-cli` repository.\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_playwright_interactive",
                "display_name": "playwright-interactive",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["playwright-interactive"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("local_skill_derivative", provenance["provenance_origin_kind"])
        self.assertEqual("playwright", provenance["provenance_origin_ref"])
        self.assertEqual("playwright", provenance["provenance_origin_label"])
        self.assertEqual("embedded_local_derivative_notice", provenance["provenance_package_strategy"])
        self.assertEqual("medium", provenance["provenance_confidence"])

        self.assertEqual("derived:npx_global_playwright_interactive", aggregation["install_unit_id"])
        self.assertEqual("local_skill_derivative", aggregation["install_unit_kind"])
        self.assertEqual("playwright-interactive", aggregation["install_unit_display_name"])
        self.assertEqual("collection:source_repo_microsoft_playwright_cli", aggregation["collection_group_id"])
        self.assertEqual("source_repo", aggregation["collection_group_kind"])

    def test_npx_single_local_derivative_notice_requires_resolvable_base_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"

            source_skill = source_root / "playwright-interactive"
            source_skill.mkdir(parents=True, exist_ok=True)
            (source_skill / "SKILL.md").write_text(
                "---\n"
                "name: playwright-interactive\n"
                "description: Persistent browser and Electron interaction through js_repl.\n"
                "---\n",
                encoding="utf-8",
            )
            (source_skill / "NOTICE.txt").write_text(
                "This skill reuses the Playwright icon assets from `.codex/skills/playwright/assets/`.\n\n"
                "The local `playwright` skill attributes those assets to the Microsoft\n"
                "`playwright-cli` repository.\n",
                encoding="utf-8",
            )

            source_row = {
                "source_id": "npx_global_playwright_interactive",
                "display_name": "playwright-interactive",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["playwright-interactive"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("skills_root", provenance["provenance_origin_kind"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("low", provenance["provenance_confidence"])
        self.assertEqual("synthetic_single:npx_global_playwright_interactive", aggregation["install_unit_id"])

    def test_npx_single_recovers_package_from_structured_cache_skill_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "git-commit"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: git-commit\n"
                "description: Create a git commit with a clear, value-communicating message.\n"
                "---\n\n"
                "# Git Commit\n\n"
                "Create a single, well-crafted git commit from the current working tree changes.\n\n"
                "## Context\n\n"
                "Use pre-populated git context when available.\n\n"
                "## Workflow\n\n"
                "### Step 1: Gather context\n\n"
                "Use the context above instead of re-running commands.\n\n"
                "### Step 2: Determine commit message convention\n\n"
                "Follow repo conventions first.\n\n"
                "### Step 3: Consider logical commits\n\n"
                "Split only when file-level concerns are obvious.\n\n"
                "### Step 4: Stage and commit\n\n"
                "Prefer staging explicit files and commit in one call.\n\n"
                "### Step 5: Confirm\n\n"
                "Run git status after the commit.\n"
            )
            cache_content = (
                "---\n"
                "name: git-commit\n"
                "description: Create a git commit with a clear, value-communicating message.\n"
                "---\n\n"
                "# Git Commit\n\n"
                "Create a single, well-crafted git commit from the current working tree changes.\n\n"
                "## Workflow\n\n"
                "### Step 1: Gather context\n\n"
                "Run these commands to understand the current state.\n\n"
                "### Step 2: Determine commit message convention\n\n"
                "Follow repo conventions first.\n\n"
                "### Step 3: Consider logical commits\n\n"
                "Split only when file-level concerns are obvious.\n\n"
                "### Step 4: Stage and commit\n\n"
                "Stage relevant files by name and commit.\n\n"
                "### Step 5: Confirm\n\n"
                "Run git status after the commit.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "review-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/review-pack"}),
                encoding="utf-8",
            )
            cache_skill = package_root / "skills" / "git-commit"
            cache_skill.mkdir(parents=True, exist_ok=True)
            (cache_skill / "SKILL.md").write_text(cache_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_git_commit",
                "display_name": "git-commit",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["git-commit"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("@demo/review-pack", provenance["provenance_package_name"])
        self.assertEqual("cache_structured_similarity_match", provenance["provenance_package_strategy"])
        self.assertEqual("high", provenance["provenance_confidence"])
        self.assertEqual("npm:@demo/review-pack", aggregation["install_unit_id"])
        self.assertEqual("package", aggregation["collection_group_kind"])

    def test_npx_single_does_not_recover_package_from_structured_cache_when_sections_diverge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            source_skill = source_root / "git-commit"
            source_skill.mkdir(parents=True, exist_ok=True)
            local_content = (
                "---\n"
                "name: git-commit\n"
                "description: Create a git commit with a clear, value-communicating message.\n"
                "---\n\n"
                "# Git Commit\n\n"
                "Create a single, well-crafted git commit from the current working tree changes.\n\n"
                "## Workflow\n\n"
                "### Step 1: Gather context\n\n"
                "Use pre-populated git context when available.\n\n"
                "### Step 2: Determine commit message convention\n\n"
                "Follow repo conventions first.\n"
            )
            cache_content = (
                "---\n"
                "name: git-commit\n"
                "description: Create a git commit with a clear, value-communicating message.\n"
                "---\n\n"
                "# Git Commit\n\n"
                "Different content focused on release automation.\n\n"
                "## Usage\n\n"
                "### Prepare release metadata\n\n"
                "Generate a changelog and tag preview before continuing.\n\n"
                "### Publish artifacts\n\n"
                "Upload release assets to the package registry.\n"
            )
            (source_skill / "SKILL.md").write_text(local_content, encoding="utf-8")

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@demo" / "review-pack"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@demo/review-pack"}),
                encoding="utf-8",
            )
            cache_skill = package_root / "skills" / "git-commit"
            cache_skill.mkdir(parents=True, exist_ok=True)
            (cache_skill / "SKILL.md").write_text(cache_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_row = {
                "source_id": "npx_global_git_commit",
                "display_name": "git-commit",
                "source_kind": "npx_single",
                "source_scope": "global",
                "source_path": str(source_skill),
                "member_count": 1,
                "member_skill_preview": ["git-commit"],
                "compatible_software_ids": ["codex"],
                "status": "ready",
                "freshness_status": "fresh",
            }

            provenance = derive_source_provenance_fields(source_row)
            aggregation = derive_source_aggregation_fields(source_row)

        self.assertEqual("", provenance["provenance_package_name"])
        self.assertEqual("fallback_root", provenance["provenance_package_strategy"])
        self.assertEqual("synthetic_single:npx_global_git_commit", aggregation["install_unit_id"])

    def test_npx_single_cache_mirror_can_promote_curated_package_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / ".codex" / "skills"
            git_commit_source = source_root / "git-commit"
            git_worktree_source = source_root / "git-worktree"
            git_commit_source.mkdir(parents=True, exist_ok=True)
            git_worktree_source.mkdir(parents=True, exist_ok=True)
            git_commit_content = "---\nname: git-commit\ndescription: Git commit skill\n---\n"
            git_worktree_content = "---\nname: git-worktree\ndescription: Git worktree skill\n---\n"
            (git_commit_source / "SKILL.md").write_text(git_commit_content, encoding="utf-8")
            (git_worktree_source / "SKILL.md").write_text(git_worktree_content, encoding="utf-8")

            cache_root = temp_root / ".bun" / "install" / "cache"
            package_root = (
                cache_root
                / "@every-env"
                / "compound-plugin@2.61.0@@@1"
                / "node_modules"
                / "@every-env"
                / "compound-plugin"
            )
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "package.json").write_text(
                json.dumps({"name": "@every-env/compound-plugin"}),
                encoding="utf-8",
            )
            git_commit_cache = package_root / "plugins" / "compound-engineering" / "skills" / "git-commit"
            git_worktree_cache = package_root / "plugins" / "compound-engineering" / "skills" / "git-worktree"
            git_commit_cache.mkdir(parents=True, exist_ok=True)
            git_worktree_cache.mkdir(parents=True, exist_ok=True)
            (git_commit_cache / "SKILL.md").write_text(git_commit_content, encoding="utf-8")
            (git_worktree_cache / "SKILL.md").write_text(git_worktree_content, encoding="utf-8")

            self._set_cache_roots(cache_root)

            source_rows = [
                {
                    "source_id": "npx_global_git_commit",
                    "display_name": "git-commit",
                    "source_kind": "npx_single",
                    "source_scope": "global",
                    "source_path": str(git_commit_source),
                    "member_count": 1,
                    "member_skill_preview": ["git-commit"],
                    "compatible_software_ids": ["codex"],
                    "status": "ready",
                    "freshness_status": "fresh",
                },
                {
                    "source_id": "npx_global_git_worktree",
                    "display_name": "git-worktree",
                    "source_kind": "npx_single",
                    "source_scope": "global",
                    "source_path": str(git_worktree_source),
                    "member_count": 1,
                    "member_skill_preview": ["git-worktree"],
                    "compatible_software_ids": ["codex"],
                    "status": "ready",
                    "freshness_status": "fresh",
                },
            ]

            install_unit_rows = build_install_unit_rows(source_rows, [])
            collection_group_rows = build_collection_group_rows(install_unit_rows)

        self.assertEqual(1, len(install_unit_rows))
        self.assertEqual("npm:@every-env/compound-plugin", install_unit_rows[0]["install_unit_id"])
        self.assertEqual("Compound Engineering", install_unit_rows[0]["display_name"])
        self.assertEqual("collection:compound_engineering", install_unit_rows[0]["collection_group_id"])
        self.assertEqual("package", install_unit_rows[0]["collection_group_kind"])
        self.assertEqual(2, install_unit_rows[0]["source_count"])
        self.assertEqual(2, install_unit_rows[0]["member_count"])
        self.assertEqual("@every-env/compound-plugin", install_unit_rows[0]["provenance_primary_package_name"])

        self.assertEqual(1, len(collection_group_rows))
        self.assertEqual("collection:compound_engineering", collection_group_rows[0]["collection_group_id"])
        self.assertEqual("Compound Engineering", collection_group_rows[0]["collection_group_name"])
        self.assertEqual("package", collection_group_rows[0]["collection_group_kind"])
        self.assertEqual(2, collection_group_rows[0]["source_count"])


if __name__ == "__main__":
    unittest.main()
