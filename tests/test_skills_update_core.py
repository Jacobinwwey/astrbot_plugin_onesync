from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_update_core import (
    build_git_rollback_preview,
    build_collection_group_update_plan,
    build_install_unit_update_plan,
    summarize_revision_capture_delta,
)


class SkillsUpdateCoreTests(unittest.TestCase):
    def test_build_install_unit_update_plan_prefers_registry_management_hint(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "npm:@every-env/compound-plugin",
                "display_name": "Compound Engineering",
                "install_ref": "@every-env/compound-plugin",
                "install_manager": "bunx",
                "management_hint": "bunx @every-env/compound-plugin",
                "update_policy": "registry",
            },
            [
                {
                    "source_id": "ce_brainstorm",
                    "source_path": "/root/.codex/skills/ce-brainstorm",
                }
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual("bunx", plan["manager"])
        self.assertEqual(
            [
                "command -v bunx >/dev/null 2>&1 || command -v npx >/dev/null 2>&1 || command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(
            [
                "bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
            ],
            plan["commands"],
        )

    def test_build_install_unit_update_plan_supports_git_pull(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "git:https://github.com/demo/tools.git",
                "display_name": "Demo Git Pack",
                "install_manager": "git",
                "update_policy": "manual",
            },
            [
                {
                    "source_id": "demo_tools",
                    "source_path": "/tmp/demo tools",
                },
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual("git", plan["manager"])
        self.assertEqual(
            [
                "git -C '/tmp/demo tools' rev-parse --is-inside-work-tree",
                "test -z \"$(git -C '/tmp/demo tools' status --porcelain)\"",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(["git -C '/tmp/demo tools' pull --ff-only"], plan["commands"])

    def test_build_install_unit_update_plan_supports_skill_lock_git_checkout(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills",
                "display_name": "find-skills",
                "install_manager": "github",
                "update_policy": "source_sync",
            },
            [
                {
                    "source_id": "npx_global_find_skills",
                    "source_path": "/root/.agents/skills/find-skills",
                },
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual("git", plan["manager"])
        self.assertEqual(
            [
                "git -C /root/.agents/skills/find-skills rev-parse --is-inside-work-tree",
                "test -z \"$(git -C /root/.agents/skills/find-skills status --porcelain)\"",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(["git -C /root/.agents/skills/find-skills pull --ff-only"], plan["commands"])

    def test_build_install_unit_update_plan_prefers_managed_git_checkout_path(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills",
                "display_name": "find-skills",
                "install_manager": "github",
                "update_policy": "source_sync",
            },
            [
                {
                    "source_id": "npx_global_find_skills",
                    "source_path": "/root/.agents/skills/find-skills",
                    "git_checkout_path": "/root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123456789abc",
                },
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual("git", plan["manager"])
        self.assertEqual(
            [
                "git -C /root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123456789abc rev-parse --is-inside-work-tree",
                "test -z \"$(git -C /root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123456789abc status --porcelain)\"",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(
            [
                "git -C /root/astrbot/data/plugin_data/astrbot_plugin_onesync/skills/git_repos/skills-123456789abc pull --ff-only",
            ],
            plan["commands"],
        )

    def test_build_install_unit_update_plan_rejects_manual_filesystem_units(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "filesystem:/tmp/demo",
                "display_name": "Manual Local Demo",
                "install_manager": "filesystem",
                "update_policy": "manual",
            },
            [
                {
                    "source_id": "manual_demo",
                    "source_path": "/tmp/demo",
                },
            ],
        )

        self.assertFalse(plan["supported"])
        self.assertEqual("manual_managed", plan["reason_code"])
        self.assertEqual([], plan["commands"])
        self.assertIn("unsupported", plan["message"])

    def test_build_install_unit_update_plan_rejects_local_custom_skill_even_if_policy_says_registry(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "local_custom:/root/.codex/skills/doc",
                "display_name": "doc",
                "install_manager": "manual",
                "update_policy": "registry",
            },
            [
                {
                    "source_id": "npx_global_doc",
                    "source_path": "/root/.codex/skills/doc",
                },
            ],
        )

        self.assertFalse(plan["supported"])
        self.assertEqual("registry", plan["policy"])
        self.assertEqual("manual_managed", plan["reason_code"])
        self.assertEqual([], plan["commands"])
        self.assertIn("unsupported", plan["message"])

    def test_build_install_unit_update_plan_rejects_unknown_manager_with_reason_code(self) -> None:
        plan = build_install_unit_update_plan(
            {
                "install_unit_id": "custompm:@demo/skills-pack",
                "display_name": "Demo Skills Pack",
                "install_ref": "@demo/skills-pack",
                "install_manager": "custompm",
                "update_policy": "registry",
            },
            [],
        )

        self.assertFalse(plan["supported"])
        self.assertEqual("unsupported_manager", plan["reason_code"])
        self.assertIn("manager", plan["message"])

    def test_build_collection_group_update_plan_keeps_supported_and_unsupported_units(self) -> None:
        plan = build_collection_group_update_plan(
            {
                "collection_group_id": "collection:mixed",
                "display_name": "Mixed Group",
            },
            [
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
                    "install_ref": "@every-env/compound-plugin",
                    "install_manager": "bunx",
                    "management_hint": "bunx @every-env/compound-plugin",
                    "update_policy": "registry",
                },
                {
                    "install_unit_id": "filesystem:/tmp/demo",
                    "display_name": "Manual Demo",
                    "install_manager": "filesystem",
                    "update_policy": "manual",
                },
            ],
            [
                {
                    "source_id": "ce_brainstorm",
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "source_path": "/root/.codex/skills/ce-brainstorm",
                },
                {
                    "source_id": "manual_demo",
                    "install_unit_id": "filesystem:/tmp/demo",
                    "source_path": "/tmp/demo",
                },
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual(1, plan["supported_install_unit_total"])
        self.assertEqual(1, plan["unsupported_install_unit_total"])
        self.assertEqual("manual_managed", plan["unsupported_install_units"][0]["reason_code"])
        self.assertEqual("manual_managed", plan["blocked_reasons"][0]["reason_code"])
        self.assertEqual(
            [
                "command -v bunx >/dev/null 2>&1 || command -v npx >/dev/null 2>&1 || command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(
            [
                "bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
            ],
            plan["commands"],
        )

    def test_build_collection_group_update_plan_returns_reason_code_for_manual_only_group(self) -> None:
        plan = build_collection_group_update_plan(
            {
                "collection_group_id": "collection:manual-only",
                "display_name": "Manual Only Group",
            },
            [
                {
                    "install_unit_id": "filesystem:/tmp/manual-a",
                    "display_name": "Manual A",
                    "install_manager": "filesystem",
                    "update_policy": "manual",
                },
            ],
            [
                {
                    "source_id": "manual_a",
                    "install_unit_id": "filesystem:/tmp/manual-a",
                    "source_path": "/tmp/manual-a",
                },
            ],
        )

        self.assertFalse(plan["supported"])
        self.assertEqual("manual_managed", plan["reason_code"])
        self.assertEqual(1, plan["unsupported_install_unit_total"])
        self.assertEqual("manual_managed", plan["unsupported_install_units"][0]["reason_code"])
        self.assertEqual("manual_managed", plan["blocked_reasons"][0]["reason_code"])

    def test_build_collection_group_update_plan_merges_git_precheck_commands(self) -> None:
        plan = build_collection_group_update_plan(
            {
                "collection_group_id": "collection:git-demo",
                "display_name": "Git Demo Group",
            },
            [
                {
                    "install_unit_id": "skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills",
                    "display_name": "find-skills",
                    "install_manager": "github",
                    "update_policy": "source_sync",
                },
            ],
            [
                {
                    "source_id": "npx_global_find_skills",
                    "install_unit_id": "skill_lock:https://github.com/vercel-labs/skills.git#skills/find-skills",
                    "source_path": "/root/.agents/skills/find-skills",
                },
            ],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual(
            [
                "git -C /root/.agents/skills/find-skills rev-parse --is-inside-work-tree",
                "test -z \"$(git -C /root/.agents/skills/find-skills status --porcelain)\"",
            ],
            plan["precheck_commands"],
        )
        self.assertEqual(["git -C /root/.agents/skills/find-skills pull --ff-only"], plan["commands"])

    def test_summarize_revision_capture_delta_tracks_changed_unchanged_and_unknown(self) -> None:
        summary = summarize_revision_capture_delta(
            [
                {
                    "source_id": "git_alpha",
                    "sync_resolved_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                {
                    "source_id": "git_beta",
                    "sync_resolved_revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                },
                {
                    "source_id": "git_gamma",
                    "sync_resolved_revision": "",
                },
            ],
            [
                {
                    "source_id": "git_alpha",
                    "sync_resolved_revision": "cccccccccccccccccccccccccccccccccccccccc",
                },
                {
                    "source_id": "git_beta",
                    "sync_resolved_revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                },
                {
                    "source_id": "git_gamma",
                    "sync_resolved_revision": "",
                },
            ],
        )

        self.assertEqual(3, summary["source_total"])
        self.assertEqual(["git_alpha"], summary["changed_source_ids"])
        self.assertEqual(["git_beta"], summary["unchanged_source_ids"])
        self.assertEqual(["git_gamma"], summary["unknown_source_ids"])
        self.assertTrue(summary["changed"])

    def test_summarize_revision_capture_delta_normalizes_source_id_case(self) -> None:
        summary = summarize_revision_capture_delta(
            [
                {
                    "source_id": "Git_Alpha",
                    "sync_resolved_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            ],
            [
                {
                    "source_id": "git_alpha",
                    "sync_resolved_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            ],
        )
        self.assertEqual(["git_alpha"], summary["source_ids"])
        self.assertEqual(["git_alpha"], summary["unchanged_source_ids"])
        self.assertFalse(summary["changed"])

    def test_build_git_rollback_preview_returns_reset_command_for_changed_source(self) -> None:
        preview = build_git_rollback_preview(
            [
                {
                    "source_id": "git_alpha",
                    "source_path": "/tmp/demo tools",
                },
            ],
            [
                {
                    "source_id": "git_alpha",
                    "sync_resolved_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            ],
            ["git_alpha"],
        )
        self.assertTrue(preview["supported"])
        self.assertEqual(1, preview["candidate_total"])
        self.assertEqual(
            "git -C '/tmp/demo tools' reset --hard aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            preview["candidates"][0]["command"],
        )
        self.assertEqual("preview_only_not_executed", preview["warning"])

    def test_build_git_rollback_preview_reports_missing_path_or_revision(self) -> None:
        preview = build_git_rollback_preview(
            [
                {
                    "source_id": "git_alpha",
                    "source_path": "",
                },
            ],
            [
                {
                    "source_id": "git_alpha",
                    "sync_resolved_revision": "",
                },
            ],
            ["git_alpha"],
        )
        self.assertFalse(preview["supported"])
        self.assertEqual(0, preview["candidate_total"])
        self.assertEqual(1, len(preview["skipped_sources"]))


if __name__ == "__main__":
    unittest.main()
