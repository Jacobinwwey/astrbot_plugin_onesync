from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_aggregation_core import (
    build_collection_group_rows,
    build_install_unit_rows,
    derive_source_aggregation_fields,
    derive_source_provenance_fields,
)


class SkillsAggregationCoreTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
