from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_sources_core import (
    build_skills_registry,
    normalize_skills_registry,
    refresh_registry_source,
    register_registry_source,
    remove_registry_source,
)


class SkillsSourcesCoreTests(unittest.TestCase):
    def test_build_skills_registry_merges_discovered_and_saved_sources(self) -> None:
        discovered_rows = [
            {
                "id": "npx_bundle_compound_engineering_global",
                "display_name": "Compound Engineering",
                "skill_kind": "skill_bundle",
                "provider_key": "compound_engineering",
                "source_scope": "global",
                "source_path": "/root/.codex/skills/ce-brainstorm",
                "member_count": 8,
                "member_skill_preview": ["ce:brainstorm", "ce:compound"],
                "member_skill_overflow": 6,
                "management_hint": "bunx @every-env/compound-plugin",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
                "compatible_software_ids": ["codex"],
                "compatible_software_families": ["codex"],
                "tags": ["npx-managed", "bundle:compound_engineering"],
                "discovered": True,
                "auto_discovered": True,
                "source_exists": True,
                "freshness_status": "fresh",
            },
        ]
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/demo/skills.git",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "management_hint": "git clone and sync manually",
                    "compatible_software_ids": ["codex"],
                    "enabled": True,
                },
            ],
        }

        registry = build_skills_registry(
            discovered_rows,
            saved_registry=saved_registry,
            generated_at="2026-04-06T08:10:00+00:00",
        )

        self.assertEqual(2, len(registry["sources"]))
        compound = next(
            item
            for item in registry["sources"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual("npx_bundle", compound["source_kind"])
        self.assertEqual("@every-env/compound-plugin", compound["locator"])
        self.assertEqual("npx", compound["managed_by"])
        self.assertEqual("registry", compound["update_policy"])

        manual_git = next(item for item in registry["sources"] if item["source_id"] == "manual_git_demo")
        self.assertEqual("manual_git", manual_git["source_kind"])
        self.assertEqual("https://github.com/demo/skills.git", manual_git["locator"])
        self.assertEqual(["codex"], manual_git["compatible_software_ids"])

    def test_register_registry_source_normalizes_locator_and_rejects_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "skills-pack"
            source_root.mkdir(parents=True, exist_ok=True)
            registry = normalize_skills_registry({})

            created = register_registry_source(
                registry,
                {
                    "display_name": "Local Skills Pack",
                    "source_kind": "manual_local",
                    "locator": str(source_root),
                    "source_scope": "workspace",
                    "compatible_software_ids": ["codex"],
                },
                generated_at="2026-04-06T09:00:00+00:00",
            )

            self.assertEqual(1, len(created["sources"]))
            source = created["sources"][0]
            self.assertEqual("manual_local", source["source_kind"])
            self.assertEqual(str(source_root.resolve()), source["locator"])
            self.assertEqual("workspace", source["source_scope"])
            self.assertTrue(source["source_id"].startswith("manual_local_"))

            with self.assertRaises(ValueError):
                register_registry_source(
                    created,
                    {
                        "display_name": "Duplicate Local Skills Pack",
                        "source_kind": "manual_local",
                        "locator": str(source_root),
                        "source_scope": "workspace",
                    },
                    generated_at="2026-04-06T09:01:00+00:00",
                )

    def test_refresh_and_remove_registry_source(self) -> None:
        registry = normalize_skills_registry(
            {
                "version": 1,
                "generated_at": "2026-04-06T09:00:00+00:00",
                "sources": [
                    {
                        "source_id": "manual_git_demo",
                        "display_name": "Demo Git Skills",
                        "source_kind": "manual_git",
                        "locator": "https://github.com/demo/skills.git",
                        "source_scope": "global",
                    },
                ],
            },
        )

        refreshed = refresh_registry_source(
            registry,
            "manual_git_demo",
            {
                "last_seen_at": "2026-04-06T09:10:00+00:00",
                "freshness_status": "fresh",
                "source_exists": True,
            },
            generated_at="2026-04-06T09:10:00+00:00",
        )
        source = refreshed["sources"][0]
        self.assertEqual("2026-04-06T09:10:00+00:00", source["last_refresh_at"])
        self.assertEqual("fresh", source["freshness_status"])
        self.assertTrue(source["source_exists"])

        removed = remove_registry_source(
            refreshed,
            "manual_git_demo",
            generated_at="2026-04-06T09:12:00+00:00",
        )
        self.assertEqual([], removed["sources"])


if __name__ == "__main__":
    unittest.main()
