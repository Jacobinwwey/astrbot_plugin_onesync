from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_update_core import (
    build_collection_group_update_plan,
    build_install_unit_update_plan,
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
            [],
        )

        self.assertTrue(plan["supported"])
        self.assertEqual("bunx", plan["manager"])
        self.assertEqual(["bunx @every-env/compound-plugin"], plan["commands"])

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
        self.assertEqual(["git -C /root/.agents/skills/find-skills pull --ff-only"], plan["commands"])

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
        self.assertEqual([], plan["commands"])
        self.assertIn("unsupported", plan["message"])

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
                    "source_path": "/tmp/compound",
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
        self.assertEqual(["bunx @every-env/compound-plugin"], plan["commands"])


if __name__ == "__main__":
    unittest.main()
