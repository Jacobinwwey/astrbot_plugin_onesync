from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_core import (
    build_skills_lock,
    build_skills_manifest,
    build_skills_overview,
    manifest_to_binding_rows,
)


class SkillsCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
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

    def test_build_skills_overview_propagates_source_freshness_metadata(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"][0].update(
            {
                "source_exists": True,
                "last_seen_at": "2026-04-06T07:58:00+00:00",
                "source_age_days": 0,
                "freshness_status": "fresh",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
        )
        snapshot["skill_rows"][1].update(
            {
                "source_exists": False,
                "last_seen_at": "",
                "source_age_days": None,
                "freshness_status": "missing",
            },
        )

        overview = build_skills_overview(snapshot)

        compound = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertTrue(compound["source_exists"])
        self.assertEqual("fresh", compound["freshness_status"])
        self.assertEqual("@every-env/compound-plugin", compound["registry_package_name"])

        self.assertEqual(1, overview["counts"]["source_fresh_total"])
        self.assertEqual(1, overview["counts"]["source_missing_total"])
        self.assertEqual(0, overview["counts"]["source_aging_total"])
        self.assertEqual(0, overview["counts"]["source_stale_total"])
        self.assertEqual(1, overview["doctor"]["source_freshness"]["fresh"])
        self.assertEqual(1, overview["doctor"]["source_freshness"]["missing"])

    def test_build_skills_overview_merges_saved_source_sync_metadata(self) -> None:
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "display_name": "Compound Engineering",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "sync_message": "fetched npm registry metadata for @every-env/compound-plugin",
                    "registry_latest_version": "2.62.1",
                    "registry_published_at": "2026-04-01T11:58:00.000Z",
                    "registry_homepage": "https://github.com/every-env/compound-plugin",
                    "registry_description": "Compound plugin bundle",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_manifest=saved_manifest)
        compound = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual("ok", compound["sync_status"])
        self.assertEqual("2.62.1", compound["registry_latest_version"])
        self.assertEqual("2026-04-06T08:05:00+00:00", compound["sync_checked_at"])
        self.assertEqual("https://github.com/every-env/compound-plugin", compound["registry_homepage"])

    def test_build_skills_overview_summarizes_source_sync_health(self) -> None:
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "registry_package_name": "@every-env/compound-plugin",
                    "registry_package_manager": "npm",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "registry_latest_version": "2.62.1",
                },
                {
                    "source_id": "npx_global_find_skills",
                    "registry_package_name": "@demo/find-skills-pack",
                    "registry_package_manager": "npm",
                    "sync_status": "error",
                    "sync_checked_at": "2026-04-06T08:06:00+00:00",
                    "sync_message": "registry timeout",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_manifest=saved_manifest)

        self.assertEqual(2, overview["counts"]["source_syncable_total"])
        self.assertEqual(1, overview["counts"]["source_synced_total"])
        self.assertEqual(1, overview["counts"]["source_sync_error_total"])
        self.assertEqual(0, overview["counts"]["source_sync_pending_total"])
        self.assertEqual(2, overview["doctor"]["source_sync"]["syncable"])
        self.assertEqual(1, overview["doctor"]["source_sync"]["ok"])
        self.assertEqual(1, overview["doctor"]["source_sync"]["error"])
        self.assertIn("registry timeout", "\n".join(overview["warnings"]))

    def test_build_skills_lock_marks_missing_target_path_and_repair_actions(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        missing_root = Path(self._tempdir.name) / "missing-codex-skills"
        snapshot["software_rows"][0]["resolved_skill_roots"] = [str(missing_root)]
        snapshot["software_rows"][0]["declared_skill_roots"] = [str(missing_root)]

        manifest = build_skills_manifest(snapshot)
        lock = build_skills_lock(manifest, snapshot)

        codex_global = next(item for item in lock["deploy_targets"] if item["target_id"] == "codex:global")
        self.assertEqual("stale", codex_global["status"])
        self.assertEqual("missing_target_path", codex_global["drift_status"])
        self.assertFalse(codex_global["target_path_exists"])
        self.assertEqual(["npx_bundle_compound_engineering_global"], codex_global["ready_source_ids"])
        self.assertEqual(["create_target_path"], codex_global["repair_actions"])

    def test_build_skills_lock_marks_incompatible_selection_and_drop_action(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["software_rows"][1]["installed"] = True
        compatible_root = Path(self._tempdir.name) / "antigravity-skills"
        compatible_root.mkdir(parents=True, exist_ok=True)
        snapshot["software_rows"][1]["resolved_skill_roots"] = [str(compatible_root)]
        snapshot["software_rows"][1]["declared_skill_roots"] = [str(compatible_root)]

        snapshot["skill_rows"].append(
            {
                "id": "gui_only_bundle",
                "display_name": "GUI Only Bundle",
                "skill_kind": "skill_bundle",
                "provider_key": "gui_bundle",
                "enabled": True,
                "discovered": True,
                "auto_discovered": False,
                "source_scope": "global",
                "source_path": str(compatible_root / "gui-only"),
                "member_count": 2,
                "member_skill_preview": ["gui:launch", "gui:inspect"],
                "member_skill_overflow": 0,
                "management_hint": "bunx gui-only-plugin",
                "compatible_software_families": ["antigravity"],
                "tags": ["npx-managed"],
            },
        )
        snapshot["compatibility"]["antigravity"] = ["gui_only_bundle", "npx_global_find_skills"]
        snapshot["binding_rows"] = []
        snapshot["binding_map"] = {"codex": [], "antigravity": []}
        snapshot["binding_map_by_scope"] = {
            "global": {"codex": [], "antigravity": []},
            "workspace": {"codex": [], "antigravity": []},
        }

        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["gui_only_bundle"],
                },
            ],
        }

        overview = build_skills_overview(snapshot, saved_manifest=saved_manifest)
        codex_global = next(item for item in overview["deploy_rows"] if item["target_id"] == "codex:global")
        self.assertEqual("stale", codex_global["status"])
        self.assertEqual("incompatible_selection", codex_global["drift_status"])
        self.assertEqual(["gui_only_bundle"], codex_global["incompatible_source_ids"])
        self.assertEqual(["drop_incompatible_sources"], codex_global["repair_actions"])
        self.assertIn("contains incompatible sources", "\n".join(overview["warnings"]))

    def test_saved_manifest_preserves_missing_sources_and_selected_targets(self) -> None:
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "retired_bundle",
                    "display_name": "Retired Bundle",
                    "source_kind": "skill_bundle",
                    "provider_key": "legacy",
                    "source_path": "/tmp/retired",
                    "member_count": 3,
                    "member_skill_preview": ["a", "b"],
                    "selected_source_ids": [],
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["retired_bundle", "npx_bundle_compound_engineering_global"],
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_manifest=saved_manifest)
        manifest = overview["manifest"]
        source_ids = {item["source_id"] for item in manifest["sources"]}
        self.assertIn("retired_bundle", source_ids)

        codex_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "codex:global")
        self.assertEqual(
            ["retired_bundle", "npx_bundle_compound_engineering_global"],
            codex_global["selected_source_ids"],
        )

        lock_target = next(item for item in overview["deploy_rows"] if item["target_id"] == "codex:global")
        self.assertEqual("stale", lock_target["status"])
        self.assertEqual("missing_source", lock_target["drift_status"])
        self.assertIn("retired_bundle", lock_target["missing_source_ids"])

    def test_manifest_to_binding_rows_projects_selected_sources(self) -> None:
        manifest = build_skills_manifest(self.inventory_snapshot)
        for item in manifest["deploy_targets"]:
            if item["target_id"] == "codex:global":
                item["selected_source_ids"] = ["npx_bundle_compound_engineering_global", "npx_global_find_skills"]
            else:
                item["selected_source_ids"] = []

        rows = manifest_to_binding_rows(manifest)
        keys = {(row["software_id"], row["skill_id"], row["scope"]) for row in rows}
        self.assertIn(("codex", "npx_bundle_compound_engineering_global", "global"), keys)
        self.assertIn(("codex", "npx_global_find_skills", "global"), keys)


if __name__ == "__main__":
    unittest.main()
