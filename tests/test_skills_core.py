from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_core import build_skills_lock, build_skills_manifest, build_skills_overview


class SkillsCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory_snapshot = {
            "ok": True,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "software_rows": [
                {
                    "id": "codex",
                    "display_name": "Codex",
                    "software_kind": "cli",
                    "software_family": "codex",
                    "provider_key": "codex",
                    "enabled": True,
                    "installed": True,
                    "managed": False,
                    "linked_target_name": "",
                    "declared_skill_roots": ["/root/.codex/skills"],
                    "resolved_skill_roots": ["/root/.codex/skills"],
                },
                {
                    "id": "antigravity",
                    "display_name": "Antigravity",
                    "software_kind": "gui",
                    "software_family": "antigravity",
                    "provider_key": "antigravity",
                    "enabled": True,
                    "installed": False,
                    "managed": False,
                    "linked_target_name": "",
                    "declared_skill_roots": ["/root/antigravity/skills"],
                    "resolved_skill_roots": [],
                },
            ],
            "skill_rows": [
                {
                    "id": "npx_bundle_compound_engineering_global",
                    "display_name": "Compound Engineering",
                    "skill_kind": "skill_bundle",
                    "provider_key": "compound_engineering",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/ce-brainstorm",
                    "member_count": 8,
                    "member_skill_preview": ["ce:brainstorm", "ce:compound"],
                    "member_skill_overflow": 6,
                    "management_hint": "bunx @every-env/compound-plugin",
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed", "bundle:compound_engineering"],
                },
                {
                    "id": "npx_global_find_skills",
                    "display_name": "find-skills",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": False,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.agents/skills/find-skills",
                    "member_count": 1,
                    "member_skill_preview": ["find-skills"],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "compatible_software_families": ["codex", "antigravity"],
                    "tags": ["npx-managed"],
                },
            ],
            "binding_rows": [
                {
                    "software_id": "codex",
                    "skill_id": "npx_bundle_compound_engineering_global",
                    "scope": "global",
                    "enabled": True,
                    "valid": True,
                    "reason": "",
                },
                {
                    "software_id": "antigravity",
                    "skill_id": "npx_global_find_skills",
                    "scope": "global",
                    "enabled": True,
                    "valid": True,
                    "reason": "",
                },
            ],
            "binding_map": {
                "codex": ["npx_bundle_compound_engineering_global"],
                "antigravity": ["npx_global_find_skills"],
            },
            "binding_map_by_scope": {
                "global": {
                    "codex": ["npx_bundle_compound_engineering_global"],
                    "antigravity": ["npx_global_find_skills"],
                },
                "workspace": {"codex": [], "antigravity": []},
            },
            "compatibility": {
                "codex": ["npx_bundle_compound_engineering_global", "npx_global_find_skills"],
                "antigravity": ["npx_global_find_skills"],
            },
            "counts": {
                "software_total": 2,
                "skills_total": 2,
                "bindings_total": 2,
                "skills_members_total": 9,
            },
            "warnings": [],
        }

    def test_build_skills_manifest_projects_sources_and_targets(self) -> None:
        manifest = build_skills_manifest(self.inventory_snapshot)
        self.assertEqual(2, len(manifest["sources"]))
        self.assertEqual(2, len(manifest["software_hosts"]))
        self.assertEqual(4, len(manifest["deploy_targets"]))

        compound = next(item for item in manifest["sources"] if item["source_id"] == "npx_bundle_compound_engineering_global")
        self.assertEqual("skill_bundle", compound["source_kind"])
        self.assertEqual(["codex"], compound["compatible_software_ids"])

        codex_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "codex:global")
        self.assertEqual(["npx_bundle_compound_engineering_global"], codex_global["selected_source_ids"])
        self.assertEqual("/root/.codex/skills", codex_global["target_path"])

    def test_build_skills_lock_marks_missing_sources_and_uninstalled_targets(self) -> None:
        manifest = build_skills_manifest(self.inventory_snapshot)
        lock = build_skills_lock(manifest, self.inventory_snapshot)

        find_skills = next(item for item in lock["sources"] if item["source_id"] == "npx_global_find_skills")
        self.assertEqual("missing", find_skills["status"])

        antigravity_global = next(item for item in lock["deploy_targets"] if item["target_id"] == "antigravity:global")
        self.assertEqual("unavailable", antigravity_global["status"])
        self.assertEqual("target_uninstalled", antigravity_global["drift_status"])

    def test_build_skills_overview_keeps_inventory_compatibility_fields(self) -> None:
        overview = build_skills_overview(self.inventory_snapshot)
        self.assertTrue(overview["ok"])
        self.assertIn("software_rows", overview)
        self.assertIn("skill_rows", overview)
        self.assertEqual(2, overview["counts"]["source_total"])
        self.assertEqual(4, overview["counts"]["deploy_target_total"])
        self.assertEqual(1, overview["counts"]["deploy_unavailable_total"])
        self.assertFalse(overview["doctor"]["ok"])
        self.assertGreaterEqual(overview["doctor"]["warning_count"], 2)


if __name__ == "__main__":
    unittest.main()
