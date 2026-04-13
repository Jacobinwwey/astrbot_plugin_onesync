from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_core import (
    build_astrbot_neo_source_rows,
    build_collection_group_detail_payload,
    build_skills_lock,
    build_skills_manifest,
    build_skills_overview,
    build_install_unit_detail_payload,
    manifest_to_binding_rows,
    project_inventory_snapshot_bindings_from_manifest,
    normalize_saved_skills_manifest,
    normalize_saved_skills_lock,
)


class SkillsCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self._set_cache_roots(Path(self._tempdir.name) / ".isolated-package-cache")
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

    def _set_cache_roots(self, *roots: Path) -> None:
        previous = os.environ.get("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS")
        os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = os.pathsep.join(
            str(root) for root in roots
        )

        def _restore() -> None:
            if previous is None:
                os.environ.pop("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS", None)
            else:
                os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = previous

        self.addCleanup(_restore)

    def test_build_skills_manifest_projects_sources_and_targets(self) -> None:
        manifest = build_skills_manifest(self.inventory_snapshot)
        self.assertEqual(2, len(manifest["sources"]))
        self.assertEqual(2, len(manifest["software_hosts"]))
        self.assertEqual(4, len(manifest["deploy_targets"]))

        compound = next(item for item in manifest["sources"] if item["source_id"] == "npx_bundle_compound_engineering_global")
        self.assertEqual("npx_bundle", compound["source_kind"])
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
        self.assertIn("install_unit_rows", overview)
        self.assertIn("collection_group_rows", overview)
        self.assertIn("install_atom_registry", overview)
        self.assertIn("install_atom_total", overview["counts"])
        self.assertIn("install_atom_health", overview["doctor"])
        self.assertEqual(2, overview["counts"]["source_total"])
        self.assertEqual(4, overview["counts"]["deploy_target_total"])
        self.assertEqual(1, overview["counts"]["deploy_unavailable_total"])
        self.assertFalse(overview["doctor"]["ok"])
        self.assertGreaterEqual(overview["doctor"]["warning_count"], 2)

    def test_build_skills_overview_exposes_astrbot_runtime_state(self) -> None:
        astrbot_root = Path(self._tempdir.name) / "astrbot-root"
        skills_root = astrbot_root / "data" / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        (skills_root / "local-demo").mkdir(parents=True, exist_ok=True)
        (skills_root / "local-demo" / "SKILL.md").write_text(
            "---\ndescription: local demo\n---\n# local-demo\n",
            encoding="utf-8",
        )
        (astrbot_root / "data" / "skills.json").write_text(
            json.dumps({"skills": {"local-demo": {"active": True}}}, ensure_ascii=False),
            encoding="utf-8",
        )

        snapshot = {
            "ok": True,
            "generated_at": "2026-04-09T10:00:00+00:00",
            "software_rows": [
                {
                    "id": "astrbot",
                    "display_name": "AstrBot",
                    "software_kind": "claw",
                    "software_family": "astrbot",
                    "provider_key": "astrbot",
                    "enabled": True,
                    "installed": True,
                    "managed": False,
                    "linked_target_name": "",
                    "declared_skill_roots": [str(skills_root)],
                    "resolved_skill_roots": [str(skills_root)],
                }
            ],
            "skill_rows": [],
            "binding_rows": [],
            "binding_map": {},
            "binding_map_by_scope": {"global": {}, "workspace": {}},
            "compatibility": {},
            "counts": {},
            "warnings": [],
        }

        overview = build_skills_overview(snapshot)

        astrbot_host = next(item for item in overview["host_rows"] if item["host_id"] == "astrbot")
        self.assertEqual("astrbot", astrbot_host["runtime_state_backend"])
        self.assertEqual(1, astrbot_host["runtime_state_summary"]["local_skill_total"])
        self.assertEqual(1, len(overview["astrbot_state_rows"]))
        self.assertEqual(1, overview["counts"]["astrbot_host_total"])
        self.assertEqual(1, overview["counts"]["astrbot_local_skill_total"])

    def test_build_skills_overview_exposes_astrbot_neo_source_rows(self) -> None:
        astrbot_root = Path(self._tempdir.name) / "astrbot-neo-root"
        skills_root = astrbot_root / "data" / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        (skills_root / "neo-demo").mkdir(parents=True, exist_ok=True)
        (skills_root / "neo-demo" / "SKILL.md").write_text(
            "---\ndescription: neo demo\n---\n# neo-demo\n",
            encoding="utf-8",
        )
        (astrbot_root / "data" / "skills.json").write_text(
            json.dumps({"skills": {"neo-demo": {"active": True}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (skills_root / "neo_skill_map.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": {
                        "demo.skill": {
                            "local_skill_name": "neo-demo",
                            "latest_release_id": "rel-1",
                            "latest_candidate_id": "cand-1",
                            "latest_payload_ref": "blob:1",
                            "updated_at": "2026-04-11T10:00:00+00:00",
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        snapshot = {
            "ok": True,
            "generated_at": "2026-04-11T10:00:00+00:00",
            "software_rows": [
                {
                    "id": "astrbot",
                    "display_name": "AstrBot",
                    "software_kind": "claw",
                    "software_family": "astrbot",
                    "provider_key": "astrbot",
                    "enabled": True,
                    "installed": True,
                    "managed": False,
                    "linked_target_name": "",
                    "declared_skill_roots": [str(skills_root)],
                    "resolved_skill_roots": [str(skills_root)],
                }
            ],
            "skill_rows": [],
            "binding_rows": [],
            "binding_map": {},
            "binding_map_by_scope": {"global": {}, "workspace": {}},
            "compatibility": {},
            "counts": {},
            "warnings": [],
        }

        overview = build_skills_overview(snapshot)
        neo_rows = overview.get("astrbot_neo_source_rows", [])
        self.assertEqual(1, len(neo_rows))
        neo_row = neo_rows[0]
        self.assertEqual("astrneo:astrbot:demo.skill", neo_row["source_id"])
        self.assertEqual("astrneo_release", neo_row["source_kind"])
        self.assertEqual("neo-demo", neo_row["astrneo_skill_name"])
        self.assertEqual("demo.skill", neo_row["astrneo_skill_key"])
        self.assertEqual("rel-1", neo_row["astrneo_release_id"])
        self.assertEqual(1, overview["counts"]["astrbot_neo_source_total"])
        self.assertEqual(1, overview["doctor"]["astrbot_runtime_health"]["neo_source_total"])

    def test_build_astrbot_neo_source_rows_dedupes_same_skill_across_scopes(self) -> None:
        rows = build_astrbot_neo_source_rows(
            [
                {
                    "host_id": "astrbot",
                    "scope": "global",
                    "skill_name": "neo-demo",
                    "neo_skill_key": "demo.skill",
                    "neo_release_id": "rel-1",
                    "neo_updated_at": "2026-04-09T10:05:00+00:00",
                    "local_exists": False,
                    "local_path": "",
                },
                {
                    "host_id": "astrbot",
                    "scope": "workspace",
                    "skill_name": "neo-demo",
                    "neo_skill_key": "demo.skill",
                    "neo_release_id": "rel-1",
                    "neo_updated_at": "2026-04-09T10:05:00+00:00",
                    "local_exists": True,
                    "local_path": "/workspace/astrbot/data/skills/neo-demo/SKILL.md",
                },
            ]
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("astrneo:astrbot:demo.skill", rows[0]["source_id"])
        self.assertEqual("ready", rows[0]["status"])
        self.assertEqual("/workspace/astrbot/data/skills/neo-demo/SKILL.md", rows[0]["source_path"])

    def test_build_skills_overview_exposes_provenance_summary_on_rows_and_doctor(self) -> None:
        overview = build_skills_overview(self.inventory_snapshot)

        source_rows = {item["source_id"]: item for item in overview["source_rows"]}
        install_unit_rows = {item["install_unit_id"]: item for item in overview["install_unit_rows"]}
        collection_group_rows = {item["collection_group_id"]: item for item in overview["collection_group_rows"]}

        compound_source = source_rows["npx_bundle_compound_engineering_global"]
        self.assertEqual("resolved", compound_source["provenance_state"])
        self.assertEqual("@every-env/compound-plugin", compound_source["provenance_primary_package_name"])
        self.assertEqual("Compound Engineering", compound_source["provenance_primary_origin_label"])

        unresolved_source = source_rows["npx_global_find_skills"]
        self.assertEqual("unresolved", unresolved_source["provenance_state"])
        self.assertEqual("skills_root", unresolved_source["provenance_primary_origin_kind"])
        self.assertEqual("Agents Skills Root", unresolved_source["provenance_primary_origin_label"])
        self.assertEqual("legacy_root_only", unresolved_source["provenance_note_kind"])

        compound_unit = install_unit_rows["npm:@every-env/compound-plugin"]
        self.assertEqual("resolved", compound_unit["provenance_state"])
        self.assertEqual("@every-env/compound-plugin", compound_unit["provenance_primary_package_name"])

        find_skills_unit = install_unit_rows["synthetic_single:npx_global_find_skills"]
        self.assertEqual("unresolved", find_skills_unit["provenance_state"])
        self.assertEqual("legacy_root_only", find_skills_unit["provenance_note_kind"])

        compound_group = collection_group_rows["collection:compound_engineering"]
        self.assertEqual("resolved", compound_group["provenance_state"])

        self.assertEqual(1, overview["doctor"]["provenance_health"]["resolved"])
        self.assertEqual(0, overview["doctor"]["provenance_health"]["partial"])
        self.assertEqual(1, overview["doctor"]["provenance_health"]["unresolved"])

        install_atom_registry = overview.get("install_atom_registry", {})
        install_atoms = {
            item["install_unit_id"]: item
            for item in install_atom_registry.get("install_atoms", [])
            if isinstance(item, dict) and item.get("install_unit_id")
        }
        self.assertEqual("explicit", install_atoms["npm:@every-env/compound-plugin"]["evidence_level"])
        self.assertEqual("resolved", install_atoms["npm:@every-env/compound-plugin"]["resolution_status"])
        self.assertEqual(
            "unresolved",
            install_atoms["synthetic_single:npx_global_find_skills"]["resolution_status"],
        )

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

    def test_build_skills_overview_surfaces_legacy_family_collection_groups_for_unresolved_roots(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"].extend(
            [
                {
                    "id": "npx_global_git_commit",
                    "display_name": "git-commit",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/git-commit",
                    "member_count": 1,
                    "member_skill_preview": ["git-commit"],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_git_worktree",
                    "display_name": "git-worktree",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/git-worktree",
                    "member_count": 1,
                    "member_skill_preview": ["git-worktree"],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
            ],
        )
        snapshot["compatibility"]["codex"] = [
            "npx_bundle_compound_engineering_global",
            "npx_global_find_skills",
            "npx_global_git_commit",
            "npx_global_git_worktree",
        ]

        overview = build_skills_overview(snapshot)

        install_unit_rows = {
            item["install_unit_id"]: item
            for item in overview["install_unit_rows"]
        }
        self.assertEqual(
            "collection:legacy_family_codex_skills_root_git_global",
            install_unit_rows["synthetic_single:npx_global_git_commit"]["collection_group_id"],
        )
        self.assertEqual(
            "collection:legacy_family_codex_skills_root_git_global",
            install_unit_rows["synthetic_single:npx_global_git_worktree"]["collection_group_id"],
        )

        meaningful_groups = {
            item["collection_group_id"]: item
            for item in overview["meaningful_collection_group_rows"]
        }
        self.assertIn("collection:legacy_family_codex_skills_root_git_global", meaningful_groups)
        self.assertEqual("legacy_family", meaningful_groups["collection:legacy_family_codex_skills_root_git_global"]["collection_group_kind"])
        self.assertEqual(2, meaningful_groups["collection:legacy_family_codex_skills_root_git_global"]["install_unit_count"])
        self.assertEqual(2, meaningful_groups["collection:legacy_family_codex_skills_root_git_global"]["member_count"])
        self.assertNotIn("collection:find_skills", meaningful_groups)

    def test_build_skills_overview_recovers_cache_backed_package_install_units(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
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

            cache_root = temp_root / ".npm" / "_npx"
            package_root = cache_root / "cache123" / "node_modules" / "@every-env" / "compound-plugin"
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
            snapshot["skill_rows"].extend(
                [
                    {
                        "id": "npx_global_git_commit",
                        "display_name": "git-commit",
                        "skill_kind": "skill",
                        "provider_key": "npx_skills",
                        "enabled": True,
                        "discovered": True,
                        "auto_discovered": True,
                        "source_scope": "global",
                        "source_path": str(git_commit_source),
                        "member_count": 1,
                        "member_skill_preview": ["git-commit"],
                        "member_skill_overflow": 0,
                        "management_hint": "",
                        "compatible_software_families": ["codex"],
                        "tags": ["npx-managed"],
                    },
                    {
                        "id": "npx_global_git_worktree",
                        "display_name": "git-worktree",
                        "skill_kind": "skill",
                        "provider_key": "npx_skills",
                        "enabled": True,
                        "discovered": True,
                        "auto_discovered": True,
                        "source_scope": "global",
                        "source_path": str(git_worktree_source),
                        "member_count": 1,
                        "member_skill_preview": ["git-worktree"],
                        "member_skill_overflow": 0,
                        "management_hint": "",
                        "compatible_software_families": ["codex"],
                        "tags": ["npx-managed"],
                    },
                ],
            )
            snapshot["compatibility"]["codex"] = [
                "npx_bundle_compound_engineering_global",
                "npx_global_find_skills",
                "npx_global_git_commit",
                "npx_global_git_worktree",
            ]

            overview = build_skills_overview(snapshot)

        install_unit_rows = {
            item["install_unit_id"]: item
            for item in overview["install_unit_rows"]
        }
        compound_unit = install_unit_rows["npm:@every-env/compound-plugin"]
        self.assertEqual("Compound Engineering", compound_unit["display_name"])
        self.assertGreaterEqual(compound_unit["source_count"], 3)
        self.assertEqual("resolved", compound_unit["provenance_state"])

        meaningful_groups = {
            item["collection_group_id"]: item
            for item in overview["meaningful_collection_group_rows"]
        }
        self.assertIn("collection:compound_engineering", meaningful_groups)
        self.assertEqual("package", meaningful_groups["collection:compound_engineering"]["collection_group_kind"])
        self.assertGreaterEqual(
            meaningful_groups["collection:compound_engineering"]["member_count"],
            10,
        )

    def test_build_skills_overview_merges_saved_source_sync_metadata(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "display_name": "Compound Engineering",
                    "source_kind": "npx_bundle",
                    "locator": "@every-env/compound-plugin",
                    "sync_api_base": "https://gitlab.internal/api/v4",
                    "sync_auth_header": "PRIVATE-TOKEN",
                    "sync_auth_token": "token-abc",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "sync_remote_revision": "2.62.1",
                    "sync_resolved_revision": "2.62.1",
                    "sync_message": "fetched npm registry metadata for @every-env/compound-plugin",
                    "registry_latest_version": "2.62.1",
                    "registry_published_at": "2026-04-01T11:58:00.000Z",
                    "registry_homepage": "https://github.com/every-env/compound-plugin",
                    "registry_description": "Compound plugin bundle",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)
        compound = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual("ok", compound["sync_status"])
        self.assertEqual("2.62.1", compound["registry_latest_version"])
        self.assertEqual("2026-04-06T08:05:00+00:00", compound["sync_checked_at"])
        self.assertEqual("https://github.com/every-env/compound-plugin", compound["registry_homepage"])
        self.assertEqual("2.62.1", compound["sync_remote_revision"])
        self.assertEqual("2.62.1", compound["sync_resolved_revision"])
        self.assertEqual("https://gitlab.internal/api/v4", compound["sync_api_base"])
        self.assertEqual("PRIVATE-TOKEN", compound["sync_auth_header"])
        self.assertEqual("token-abc", compound["sync_auth_token"])

    def test_build_skills_overview_allows_sync_overlay_to_clear_stale_error_fields(self) -> None:
        inventory_snapshot = copy.deepcopy(self.inventory_snapshot)
        target_row = next(
            item
            for item in inventory_snapshot["skill_rows"]
            if item["id"] == "npx_bundle_compound_engineering_global"
        )
        target_row["sync_status"] = "error"
        target_row["sync_error_code"] = "git_source_unresolved"
        target_row["sync_message"] = "git source unresolved"

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "display_name": "Compound Engineering",
                    "source_kind": "npx_bundle",
                    "locator": "@every-env/compound-plugin",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "sync_error_code": "",
                    "sync_message": "",
                    "git_checkout_path": "/tmp/managed-checkout",
                    "git_checkout_error": "",
                },
            ],
        }

        overview = build_skills_overview(inventory_snapshot, saved_registry=saved_registry)
        compound = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual("ok", compound["sync_status"])
        self.assertEqual("", compound["sync_error_code"])
        self.assertEqual("", compound["sync_message"])
        self.assertEqual("/tmp/managed-checkout", compound["git_checkout_path"])

    def test_build_skills_overview_summarizes_source_sync_health(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "source_kind": "npx_bundle",
                    "locator": "@every-env/compound-plugin",
                    "registry_package_name": "@every-env/compound-plugin",
                    "registry_package_manager": "npm",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "registry_latest_version": "2.62.1",
                },
                {
                    "source_id": "npx_global_find_skills",
                    "source_kind": "npx_single",
                    "locator": "/root/.agents/skills/find-skills",
                    "registry_package_name": "@demo/find-skills-pack",
                    "registry_package_manager": "npm",
                    "sync_status": "error",
                    "sync_checked_at": "2026-04-06T08:06:00+00:00",
                    "sync_message": "registry timeout",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)

        self.assertEqual(2, overview["counts"]["source_syncable_total"])
        self.assertEqual(1, overview["counts"]["source_synced_total"])
        self.assertEqual(1, overview["counts"]["source_sync_error_total"])
        self.assertEqual(0, overview["counts"]["source_sync_pending_total"])
        self.assertEqual(2, overview["counts"]["install_unit_syncable_total"])
        self.assertEqual(1, overview["counts"]["install_unit_synced_total"])
        self.assertEqual(1, overview["counts"]["install_unit_sync_error_total"])
        self.assertEqual(2, overview["counts"]["collection_group_syncable_total"])
        self.assertEqual(1, overview["counts"]["collection_group_synced_total"])
        self.assertEqual(1, overview["counts"]["collection_group_sync_error_total"])
        self.assertEqual(2, overview["doctor"]["source_sync"]["syncable"])
        self.assertEqual(1, overview["doctor"]["source_sync"]["ok"])
        self.assertEqual(1, overview["doctor"]["source_sync"]["error"])
        self.assertEqual(2, overview["doctor"]["install_unit_sync"]["syncable"])
        self.assertEqual(1, overview["doctor"]["install_unit_sync"]["ok"])
        self.assertEqual(1, overview["doctor"]["install_unit_sync"]["error"])
        self.assertEqual(2, overview["doctor"]["collection_group_sync"]["syncable"])
        self.assertEqual(1, overview["doctor"]["collection_group_sync"]["ok"])
        self.assertEqual(1, overview["doctor"]["collection_group_sync"]["error"])
        self.assertIn("registry timeout", "\n".join(overview["warnings"]))

    def test_build_skills_overview_counts_git_sources_as_syncable(self) -> None:
        baseline = build_skills_overview(self.inventory_snapshot)
        baseline_syncable = int(baseline["counts"]["source_syncable_total"])

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:10:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_vercel_skills",
                    "display_name": "vercel-labs/skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/vercel-labs/skills.git",
                    "managed_by": "github",
                    "update_policy": "source_sync",
                    "sync_status": "ok",
                    "sync_kind": "git_remote",
                    "sync_remote_revision": "0123456789abcdef0123456789abcdef01234567",
                    "sync_resolved_revision": "0123456789abcdef0123456789abcdef01234567",
                    "registry_latest_version": "0123456789abcdef0123456789abcdef01234567",
                    "sync_checked_at": "2026-04-06T08:09:00+00:00",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)
        self.assertEqual(
            baseline_syncable + 1,
            int(overview["counts"]["source_syncable_total"]),
        )
        git_source = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "manual_git_vercel_skills"
        )
        self.assertEqual("manual_git", git_source["source_kind"])
        self.assertEqual("ok", git_source["sync_status"])
        self.assertEqual("git_remote", git_source["sync_kind"])
        self.assertEqual(
            "0123456789abcdef0123456789abcdef01234567",
            git_source["sync_remote_revision"],
        )

    def test_build_skills_overview_counts_repo_metadata_sources_as_syncable(self) -> None:
        baseline = build_skills_overview(self.inventory_snapshot)
        baseline_syncable = int(baseline["counts"]["source_syncable_total"])

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:10:00+00:00",
            "sources": [
                {
                    "source_id": "documented_vercel_skills_repo",
                    "display_name": "vercel-labs/skills documented",
                    "source_kind": "manual_git",
                    "locator": "repo:https://github.com/vercel-labs/skills#skills/find-skills",
                    "managed_by": "manual",
                    "update_policy": "manual",
                    "sync_status": "ok",
                    "sync_kind": "repo_metadata_github",
                    "sync_remote_revision": "2026-04-10T12:34:56Z",
                    "sync_resolved_revision": "2026-04-10T12:34:56Z",
                    "registry_latest_version": "2026-04-10T12:34:56Z",
                    "sync_checked_at": "2026-04-06T08:09:00+00:00",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)
        self.assertEqual(
            baseline_syncable + 1,
            int(overview["counts"]["source_syncable_total"]),
        )
        repo_source = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "documented_vercel_skills_repo"
        )
        self.assertEqual("manual_git", repo_source["source_kind"])
        self.assertEqual("ok", repo_source["sync_status"])
        self.assertEqual("repo_metadata_github", repo_source["sync_kind"])
        self.assertEqual("2026-04-10T12:34:56Z", repo_source["sync_remote_revision"])

    def test_build_skills_overview_refreshes_freshness_from_recent_successful_sync(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-12T09:12:34+00:00",
            "sources": [
                {
                    "source_id": "npx_global_ui_ux_pro_max",
                    "display_name": "ui-ux-pro-max",
                    "source_kind": "npx_single",
                    "provider_key": "npx_skills",
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/ui-ux-pro-max",
                    "locator": "/root/.codex/skills/ui-ux-pro-max",
                    "managed_by": "npx",
                    "update_policy": "registry",
                    "source_exists": True,
                    "last_seen_at": "2026-03-25T02:15:37.179549+00:00",
                    "last_refresh_at": "2026-04-12T09:12:34.003161+00:00",
                    "source_age_days": 18,
                    "freshness_status": "aging",
                    "sync_status": "ok",
                    "sync_kind": "repo_metadata_github",
                    "sync_checked_at": "2026-04-12T09:12:24.739012+00:00",
                    "sync_message": "fetched github repository metadata for nextlevelbuilder/ui-ux-pro-max-skill",
                    "sync_remote_revision": "2026-04-03T05:08:19Z",
                    "sync_resolved_revision": "2026-04-03T05:08:19Z",
                    "registry_latest_version": "2026-04-03T05:08:19Z",
                    "registry_homepage": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
                    "compatible_software_ids": ["codex"],
                    "compatible_software_families": ["codex"],
                    "install_ref": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git#.claude/skills/ui-ux-pro-max",
                    "tags": ["npx-managed"],
                },
            ],
        }

        overview = build_skills_overview(
            self.inventory_snapshot,
            saved_registry=saved_registry,
            generated_at="2026-04-12T09:12:35+00:00",
        )

        source_row = next(
            item for item in overview["source_rows"] if item["source_id"] == "npx_global_ui_ux_pro_max"
        )
        install_unit_row = next(
            item
            for item in overview["install_unit_rows"]
            if item["primary_source_id"] == "npx_global_ui_ux_pro_max"
        )
        collection_group_row = next(
            item
            for item in overview["collection_group_rows"]
            if item["primary_source_id"] == "npx_global_ui_ux_pro_max"
        )

        self.assertEqual("fresh", source_row["freshness_status"])
        self.assertEqual(0, source_row["source_age_days"])
        self.assertEqual("fresh", install_unit_row["freshness_status"])
        self.assertEqual("fresh", collection_group_row["freshness_status"])

    def test_build_skills_overview_tracks_sync_dirty_and_revision_drift(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:10:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_vercel_skills",
                    "display_name": "vercel-labs/skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/vercel-labs/skills.git",
                    "managed_by": "github",
                    "update_policy": "source_sync",
                    "sync_status": "ok",
                    "sync_kind": "git_checkout",
                    "sync_local_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "sync_remote_revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "sync_resolved_revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "sync_branch": "main",
                    "sync_dirty": True,
                    "sync_checked_at": "2026-04-06T08:09:00+00:00",
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)
        self.assertEqual(1, int(overview["counts"]["source_sync_dirty_total"]))
        self.assertEqual(1, int(overview["counts"]["source_sync_revision_drift_total"]))
        self.assertEqual(1, int(overview["doctor"]["source_sync"]["dirty"]))
        self.assertEqual(1, int(overview["doctor"]["source_sync"]["revision_drift"]))

    def test_build_skills_overview_summarizes_aggregate_health(self) -> None:
        overview = build_skills_overview(self.inventory_snapshot)

        self.assertEqual(1, overview["counts"]["install_unit_ready_total"])
        self.assertEqual(1, overview["counts"]["install_unit_missing_total"])
        self.assertEqual(1, overview["counts"]["collection_group_ready_total"])
        self.assertEqual(1, overview["counts"]["collection_group_missing_total"])
        self.assertEqual(1, overview["doctor"]["install_unit_health"]["ready"])
        self.assertEqual(1, overview["doctor"]["install_unit_health"]["missing"])
        self.assertEqual(1, overview["doctor"]["collection_group_health"]["ready"])
        self.assertEqual(1, overview["doctor"]["collection_group_health"]["missing"])

    def test_build_skills_overview_projects_compatible_source_rows_by_software(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"][0].update(
            {
                "source_exists": True,
                "freshness_status": "fresh",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
        )
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "source_kind": "npx_bundle",
                    "locator": "@every-env/compound-plugin",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-06T08:05:00+00:00",
                    "registry_latest_version": "2.62.1",
                },
            ],
        }

        overview = build_skills_overview(snapshot, saved_registry=saved_registry)
        compatible_map = overview["compatible_source_rows_by_software"]

        self.assertEqual(
            [
                "npx_bundle_compound_engineering_global",
                "npx_global_find_skills",
            ],
            [item["source_id"] for item in compatible_map["codex"]],
        )
        compound = next(
            item
            for item in compatible_map["codex"]
            if item["source_id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual("ok", compound["sync_status"])
        self.assertEqual("2.62.1", compound["registry_latest_version"])

        self.assertEqual(["npx_global_find_skills"], [item["source_id"] for item in compatible_map["antigravity"]])
        self.assertEqual("missing", compatible_map["antigravity"][0]["status"])

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
            "sources": [
                {
                    "source_id": "npx_bundle_codex_skill_pack_global",
                    "display_name": "Codex Skill Pack",
                    "source_kind": "npx_bundle",
                    "provider_key": "codex_skill_pack",
                    "source_path": "/root/.codex/skills",
                    "compatible_software_ids": ["codex"],
                },
            ],
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

    def test_build_skills_overview_expands_legacy_codex_root_bundle_selection(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        codex_root = Path(self._tempdir.name) / "codex-skills"
        codex_root.mkdir(parents=True, exist_ok=True)
        snapshot["software_rows"][0]["resolved_skill_roots"] = [str(codex_root)]
        snapshot["software_rows"][0]["declared_skill_roots"] = [str(codex_root)]
        snapshot["skill_rows"].extend(
            [
                {
                    "id": "npx_global_correctness_reviewer",
                    "display_name": "correctness-reviewer",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/correctness-reviewer",
                    "member_count": 1,
                    "member_skill_preview": ["correctness-reviewer"],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_design_iterator",
                    "display_name": "design-iterator",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/design-iterator",
                    "member_count": 1,
                    "member_skill_preview": ["design-iterator"],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
            ],
        )
        snapshot["compatibility"]["codex"] = [
            "npx_bundle_compound_engineering_global",
            "npx_global_correctness_reviewer",
            "npx_global_design_iterator",
            "npx_global_find_skills",
        ]

        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": [
                        "npx_bundle_codex_skill_pack_global",
                        "npx_bundle_compound_engineering_global",
                    ],
                },
            ],
        }
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:30+00:00",
            "sources": [
                {
                    "source_id": "npx_bundle_codex_skill_pack_global",
                    "display_name": "Codex Skill Pack",
                    "source_kind": "npx_bundle",
                    "provider_key": "codex_skill_pack",
                    "locator": "/root/.codex/skills",
                    "compatible_software_ids": ["codex"],
                },
            ],
        }

        overview = build_skills_overview(snapshot, saved_manifest=saved_manifest, saved_registry=saved_registry)
        manifest_source_ids = {item["source_id"] for item in overview["manifest"]["sources"]}

        codex_global_manifest = next(
            item for item in overview["manifest"]["deploy_targets"] if item["target_id"] == "codex:global"
        )
        self.assertEqual(
            [
                "npx_global_correctness_reviewer",
                "npx_global_design_iterator",
                "npx_bundle_compound_engineering_global",
            ],
            codex_global_manifest["selected_source_ids"],
        )
        self.assertNotIn("npx_bundle_codex_skill_pack_global", manifest_source_ids)
        self.assertNotIn("npx_bundle_codex_skill_pack_global", codex_global_manifest["available_source_ids"])

        codex_global = next(item for item in overview["deploy_rows"] if item["target_id"] == "codex:global")
        self.assertEqual("ready", codex_global["status"])
        self.assertNotIn("npx_bundle_codex_skill_pack_global", codex_global["selected_source_ids"])
        self.assertNotIn("npx_bundle_codex_skill_pack_global", codex_global["available_source_ids"])

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

    def test_build_skills_manifest_preserves_explicit_empty_selection_from_saved_manifest(self) -> None:
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": [],
                },
            ],
        }

        manifest = build_skills_manifest(self.inventory_snapshot, saved_manifest=saved_manifest)
        codex_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "codex:global")
        self.assertEqual([], codex_global["selected_source_ids"])

    def test_build_skills_manifest_uses_saved_lock_selection_when_manifest_target_missing(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["binding_rows"] = []
        snapshot["binding_map"] = {"codex": [], "antigravity": []}
        snapshot["binding_map_by_scope"] = {
            "global": {"codex": [], "antigravity": []},
            "workspace": {"codex": [], "antigravity": []},
        }

        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [],
            "deploy_targets": [],
        }
        saved_lock = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["npx_global_find_skills"],
                },
            ],
        }

        manifest = build_skills_manifest(
            snapshot,
            saved_manifest=saved_manifest,
            saved_lock=saved_lock,
        )
        codex_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "codex:global")
        self.assertEqual(["npx_global_find_skills"], codex_global["selected_source_ids"])

    def test_build_skills_manifest_prefers_source_compatible_ids_over_inventory_compatibility(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["compatibility"] = {
            "codex": [],
            "antigravity": ["npx_bundle_compound_engineering_global", "npx_global_find_skills"],
        }

        manifest = build_skills_manifest(snapshot)
        compound = next(item for item in manifest["sources"] if item["source_id"] == "npx_bundle_compound_engineering_global")
        self.assertEqual(["codex"], compound["compatible_software_ids"])

        codex_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "codex:global")
        antigravity_global = next(item for item in manifest["deploy_targets"] if item["target_id"] == "antigravity:global")
        self.assertIn("npx_bundle_compound_engineering_global", codex_global["available_source_ids"])
        self.assertNotIn("npx_bundle_compound_engineering_global", antigravity_global["available_source_ids"])

    def test_build_skills_overview_exposes_registry_and_host_rows(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T07:59:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/demo/skills.git",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "compatible_software_ids": ["codex"],
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)

        self.assertIn("registry", overview)
        self.assertIn("host_rows", overview)
        self.assertEqual(3, len(overview["registry"]["sources"]))

        manual_git = next(
            item
            for item in overview["registry"]["sources"]
            if item["source_id"] == "manual_git_demo"
        )
        self.assertEqual("manual_git", manual_git["source_kind"])
        self.assertEqual(["codex"], manual_git["compatible_software_ids"])

        codex = next(item for item in overview["host_rows"] if item["host_id"] == "codex")
        self.assertEqual("cli", codex["kind"])
        self.assertEqual(["npx_bundle", "npx_single", "manual_local", "manual_git"], codex["supports_source_kinds"])

    def test_build_skills_overview_aggregates_install_units_and_collection_groups(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"].extend(
            [
                {
                    "id": "npx_global_design_implementation_reviewer",
                    "display_name": "design-implementation-reviewer",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/design-implementation-reviewer",
                    "member_count": 1,
                    "member_skill_preview": ["design-implementation-reviewer"],
                    "member_skill_overflow": 0,
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_design_iterator",
                    "display_name": "design-iterator",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/design-iterator",
                    "member_count": 1,
                    "member_skill_preview": ["design-iterator"],
                    "member_skill_overflow": 0,
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_design_lens_reviewer",
                    "display_name": "design-lens-reviewer",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/design-lens-reviewer",
                    "member_count": 1,
                    "member_skill_preview": ["design-lens-reviewer"],
                    "member_skill_overflow": 0,
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_dhh_rails_style",
                    "display_name": "dhh-rails-style",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/dhh-rails-style",
                    "member_count": 1,
                    "member_skill_preview": ["dhh-rails-style"],
                    "member_skill_overflow": 0,
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
                {
                    "id": "npx_global_dhh_rails_reviewer",
                    "display_name": "dhh-rails-reviewer",
                    "skill_kind": "skill",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "discovered": True,
                    "auto_discovered": True,
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/dhh-rails-reviewer",
                    "member_count": 1,
                    "member_skill_preview": ["dhh-rails-reviewer"],
                    "member_skill_overflow": 0,
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
            ],
        )
        snapshot["compatibility"]["codex"] = [
            "npx_bundle_compound_engineering_global",
            "npx_global_find_skills",
            "npx_global_design_implementation_reviewer",
            "npx_global_design_iterator",
            "npx_global_design_lens_reviewer",
            "npx_global_dhh_rails_style",
            "npx_global_dhh_rails_reviewer",
        ]

        overview = build_skills_overview(snapshot)
        self.assertIn("meaningful_collection_group_rows", overview)

        design_unit = next(
            item for item in overview["install_unit_rows"]
            if item["install_unit_id"] == "curated:design_review_pack"
        )
        self.assertEqual(3, design_unit["source_count"])
        self.assertEqual(3, design_unit["member_count"])
        self.assertEqual(
            [
                "npx_global_design_implementation_reviewer",
                "npx_global_design_iterator",
                "npx_global_design_lens_reviewer",
            ],
            design_unit["source_ids"],
        )

        design_group = next(
            item for item in overview["collection_group_rows"]
            if item["collection_group_id"] == "collection:design_review"
        )
        self.assertEqual(1, design_group["install_unit_count"])
        self.assertEqual(3, design_group["source_count"])
        self.assertEqual(3, design_group["member_count"])

        dhh_group = next(
            item for item in overview["collection_group_rows"]
            if item["collection_group_id"] == "collection:dhh_rails"
        )
        self.assertEqual(2, dhh_group["source_count"])
        self.assertEqual(2, dhh_group["member_count"])

        meaningful_group_ids = {
            item["collection_group_id"]
            for item in overview["meaningful_collection_group_rows"]
        }
        self.assertIn("collection:compound_engineering", meaningful_group_ids)
        self.assertIn("collection:design_review", meaningful_group_ids)
        self.assertIn("collection:dhh_rails", meaningful_group_ids)
        self.assertNotIn("collection:find_skills", meaningful_group_ids)

        self.assertGreaterEqual(overview["counts"]["install_unit_total"], 4)
        self.assertGreaterEqual(overview["counts"]["collection_group_total"], 4)

    def test_build_install_unit_detail_payload_returns_member_sources_and_related_targets(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"][0].update(
            {
                "source_exists": True,
                "freshness_status": "fresh",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
        )
        overview = build_skills_overview(snapshot)

        detail = build_install_unit_detail_payload(overview, "npm:@every-env/compound-plugin")

        self.assertTrue(detail["ok"])
        self.assertEqual("npm:@every-env/compound-plugin", detail["install_unit"]["install_unit_id"])
        self.assertEqual(
            ["npx_bundle_compound_engineering_global"],
            [item["source_id"] for item in detail["source_rows"]],
        )
        self.assertEqual(
            ["codex:global"],
            [item["target_id"] for item in detail["deploy_rows"]],
        )
        self.assertEqual("collection:compound_engineering", detail["collection_group"]["collection_group_id"])
        self.assertTrue(detail["update_plan"]["supported"])
        self.assertEqual("bunx", detail["update_plan"]["manager"])
        self.assertEqual(
            [
                "bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
            ],
            detail["update_plan"]["commands"],
        )

    def test_build_collection_group_detail_payload_returns_install_units_sources_and_targets(self) -> None:
        snapshot = copy.deepcopy(self.inventory_snapshot)
        snapshot["skill_rows"][0].update(
            {
                "source_exists": True,
                "freshness_status": "fresh",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
        )
        overview = build_skills_overview(snapshot)

        detail = build_collection_group_detail_payload(overview, "collection:compound_engineering")

        self.assertTrue(detail["ok"])
        self.assertEqual("collection:compound_engineering", detail["collection_group"]["collection_group_id"])
        self.assertEqual(
            ["npm:@every-env/compound-plugin"],
            [item["install_unit_id"] for item in detail["install_unit_rows"]],
        )
        self.assertEqual(
            ["npx_bundle_compound_engineering_global"],
            [item["source_id"] for item in detail["source_rows"]],
        )
        self.assertEqual(
            ["codex:global"],
            [item["target_id"] for item in detail["deploy_rows"]],
        )
        self.assertTrue(detail["update_plan"]["supported"])
        self.assertEqual(1, detail["update_plan"]["supported_install_unit_total"])
        self.assertEqual(0, detail["update_plan"]["unsupported_install_unit_total"])
        self.assertEqual(
            [
                "bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
            ],
            detail["update_plan"]["commands"],
        )

    def test_build_collection_group_detail_payload_exposes_block_reason_codes(self) -> None:
        overview = {
            "generated_at": "2026-04-11T00:00:00+00:00",
            "warnings": [],
            "collection_group_rows": [
                {
                    "collection_group_id": "collection:mixed",
                    "display_name": "Mixed Group",
                    "install_unit_ids": [
                        "npm:@every-env/compound-plugin",
                        "filesystem:/tmp/manual-demo",
                    ],
                    "source_ids": [
                        "npx_bundle_compound_engineering_global",
                        "manual_demo",
                    ],
                },
            ],
            "install_unit_rows": [
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
                    "install_ref": "@every-env/compound-plugin",
                    "install_manager": "bunx",
                    "management_hint": "bunx @every-env/compound-plugin",
                    "update_policy": "registry",
                    "source_ids": ["npx_bundle_compound_engineering_global"],
                },
                {
                    "install_unit_id": "filesystem:/tmp/manual-demo",
                    "display_name": "Manual Demo",
                    "install_manager": "filesystem",
                    "update_policy": "manual",
                    "source_ids": ["manual_demo"],
                },
            ],
            "source_rows": [
                {
                    "source_id": "npx_bundle_compound_engineering_global",
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "source_path": "/tmp/compound",
                },
                {
                    "source_id": "manual_demo",
                    "install_unit_id": "filesystem:/tmp/manual-demo",
                    "source_path": "/tmp/manual-demo",
                },
            ],
            "deploy_rows": [],
        }

        detail = build_collection_group_detail_payload(overview, "collection:mixed")

        self.assertTrue(detail["ok"])
        self.assertEqual(1, detail["update_plan"]["supported_install_unit_total"])
        self.assertEqual(1, detail["update_plan"]["unsupported_install_unit_total"])
        self.assertEqual("manual_managed", detail["update_plan"]["unsupported_install_units"][0]["reason_code"])
        self.assertEqual("manual_managed", detail["update_plan"]["blocked_reasons"][0]["reason_code"])

    def test_build_skills_overview_preserves_registry_source_subpath(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/demo/skills.git",
                    "source_subpath": "packages/codex",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "compatible_software_ids": ["codex"],
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)
        manual_git = next(
            item
            for item in overview["source_rows"]
            if item["source_id"] == "manual_git_demo"
        )
        self.assertEqual("packages/codex", manual_git["source_subpath"])

    def test_build_skills_overview_groups_manual_git_subpaths_by_repo_collection(self) -> None:
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_ui_audit",
                    "display_name": "UI Audit",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/demo/skills.git",
                    "source_subpath": "packages/ui-audit",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "compatible_software_ids": ["codex"],
                    "enabled": True,
                },
                {
                    "source_id": "manual_git_ui_reviewer",
                    "display_name": "UI Reviewer",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/demo/skills.git",
                    "source_subpath": "packages/ui-reviewer",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "compatible_software_ids": ["codex"],
                    "enabled": True,
                },
            ],
        }

        overview = build_skills_overview(self.inventory_snapshot, saved_registry=saved_registry)

        install_units = [
            item
            for item in overview["install_unit_rows"]
            if str(item.get("collection_group_id") or "") == "collection:source_repo_demo_skills"
        ]
        self.assertEqual(2, len(install_units))
        self.assertEqual(
            {
                "git:https://github.com/demo/skills.git#packages/ui-audit",
                "git:https://github.com/demo/skills.git#packages/ui-reviewer",
            },
            {item["install_unit_id"] for item in install_units},
        )

        group = next(
            item
            for item in overview["meaningful_collection_group_rows"]
            if item["collection_group_id"] == "collection:source_repo_demo_skills"
        )
        self.assertEqual("demo/skills", group["display_name"])
        self.assertEqual("source_repo", group["collection_group_kind"])
        self.assertEqual("https://github.com/demo/skills.git", group["locator"])
        self.assertEqual(
            ["packages/ui-audit", "packages/ui-reviewer"],
            group["source_subpaths"],
        )
        self.assertEqual(2, group["install_unit_count"])
        self.assertEqual(2, group["source_count"])

    def test_normalize_saved_skills_manifest_keeps_intent_only_fields(self) -> None:
        normalized = normalize_saved_skills_manifest(
            {
                "version": 1,
                "generated_at": "2026-04-06T08:00:00+00:00",
                "sources": [
                    {
                        "source_id": "npx_bundle_compound_engineering_global",
                        "display_name": "Compound Engineering",
                        "source_kind": "npx_bundle",
                        "provider_key": "compound_engineering",
                        "enabled": True,
                        "source_scope": "global",
                        "update_policy": "registry",
                        "source_path": "/root/.codex/skills/ce-brainstorm",
                        "sync_status": "ok",
                        "sync_checked_at": "2026-04-06T08:05:00+00:00",
                        "registry_latest_version": "2.62.1",
                    },
                ],
                "deploy_targets": [
                    {
                        "target_id": "codex:global",
                        "software_id": "codex",
                        "scope": "global",
                        "selected_source_ids": ["npx_bundle_compound_engineering_global"],
                    },
                ],
            },
        )

        source = normalized["sources"][0]
        self.assertEqual("npx_bundle_compound_engineering_global", source["source_id"])
        self.assertEqual("registry", source["update_policy"])
        self.assertNotIn("source_path", source)
        self.assertNotIn("sync_status", source)
        self.assertNotIn("registry_latest_version", source)

    def test_normalize_saved_skills_lock_preserves_explicit_aggregation_fields(self) -> None:
        normalized = normalize_saved_skills_lock(
            {
                "version": 1,
                "generated_at": "2026-04-07T12:00:00+00:00",
                "sources": [
                    {
                        "source_id": "npx_global_ui_audit",
                        "display_name": "ui-audit",
                        "source_kind": "npx_single",
                        "provider_key": "npx_skills",
                        "source_scope": "global",
                        "source_path": "/tmp/.agents/skills/ui-audit",
                        "locator": "https://github.com/demo/tools.git",
                        "source_subpath": "skills/ui-audit",
                        "install_unit_id": "skill_lock:https://github.com/demo/tools.git#skills/ui-audit",
                        "install_unit_kind": "skill_lock_entry",
                        "install_ref": "https://github.com/demo/tools.git#skills/ui-audit",
                        "install_manager": "github",
                        "install_unit_display_name": "ui-audit",
                        "aggregation_strategy": "skill_lock_path",
                        "collection_group_id": "collection:source_repo_demo_tools",
                        "collection_group_name": "demo/tools",
                        "collection_group_kind": "source_repo",
                        "last_synced_at": "2026-04-07T12:00:00+00:00",
                    },
                ],
                "deploy_targets": [],
            },
        )

        source = normalized["sources"][0]
        self.assertEqual(
            "skill_lock:https://github.com/demo/tools.git#skills/ui-audit",
            source["install_unit_id"],
        )
        self.assertEqual("skill_lock_entry", source["install_unit_kind"])
        self.assertEqual("https://github.com/demo/tools.git#skills/ui-audit", source["install_ref"])
        self.assertEqual("collection:source_repo_demo_tools", source["collection_group_id"])
        self.assertEqual("demo/tools", source["collection_group_name"])

    def test_build_skills_lock_overlays_registry_provenance_without_manifest_runtime_fields(self) -> None:
        manifest = {
            "version": 1,
            "generated_at": "2026-04-07T13:10:00+00:00",
            "sources": [
                {
                    "source_id": "npx_global_correctness_reviewer",
                    "display_name": "correctness-reviewer",
                    "source_kind": "npx_single",
                    "provider_key": "npx_skills",
                    "enabled": True,
                    "source_scope": "global",
                    "update_policy": "registry",
                    "compatible_software_ids": ["codex"],
                    "compatible_software_families": ["codex"],
                    "tags": ["npx-managed"],
                },
            ],
            "deploy_targets": [],
        }
        registry = {
            "version": 1,
            "generated_at": "2026-04-07T13:10:00+00:00",
            "sources": [
                {
                    "source_id": "npx_global_correctness_reviewer",
                    "display_name": "correctness-reviewer",
                    "source_kind": "npx_single",
                    "provider_key": "npx_skills",
                    "source_scope": "global",
                    "source_path": "/root/.codex/skills/correctness-reviewer",
                    "provenance_origin_kind": "skills_root",
                    "provenance_origin_ref": "/root/.codex/skills",
                    "provenance_origin_label": "Codex Skills Root",
                    "provenance_root_kind": "codex_home_skills",
                    "provenance_root_path": "/root/.codex/skills",
                    "provenance_package_strategy": "fallback_root",
                    "provenance_confidence": "low",
                },
            ],
        }

        lock = build_skills_lock(
            manifest,
            {"generated_at": "2026-04-07T13:10:00+00:00"},
            registry=registry,
        )

        source = lock["sources"][0]
        self.assertEqual("skills_root", source["provenance_origin_kind"])
        self.assertEqual("/root/.codex/skills", source["provenance_origin_ref"])
        self.assertEqual("Codex Skills Root", source["provenance_origin_label"])
        self.assertEqual("codex_home_skills", source["provenance_root_kind"])
        self.assertEqual("/root/.codex/skills", source["provenance_root_path"])
        self.assertEqual("fallback_root", source["provenance_package_strategy"])
        self.assertEqual("low", source["provenance_confidence"])

    def test_build_skills_overview_uses_saved_state_when_inventory_is_unavailable(self) -> None:
        target_root = Path(self._tempdir.name) / "codex-skills"
        target_root.mkdir(parents=True, exist_ok=True)

        unavailable_inventory = {
            "ok": False,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "software_rows": [],
            "skill_rows": [],
            "binding_rows": [],
            "binding_map": {},
            "binding_map_by_scope": {"global": {}, "workspace": {}},
            "compatibility": {},
            "counts": {},
            "warnings": ["inventory unavailable"],
        }
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
                    "compatible_software_ids": ["codex"],
                    "enabled": True,
                },
            ],
        }
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "provider_key": "manual",
                    "enabled": True,
                    "source_scope": "global",
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["manual_git_demo"],
                },
            ],
        }
        saved_lock = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "status": "ready",
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "software_display_name": "Codex",
                    "software_family": "codex",
                    "provider_key": "codex",
                    "scope": "global",
                    "installed": True,
                    "managed": False,
                    "target_path": str(target_root),
                    "selected_source_ids": ["manual_git_demo"],
                    "available_source_ids": ["manual_git_demo"],
                    "declared_skill_roots": [str(target_root)],
                    "resolved_skill_roots": [str(target_root)],
                },
            ],
        }

        overview = build_skills_overview(
            unavailable_inventory,
            saved_manifest=saved_manifest,
            saved_registry=saved_registry,
            saved_lock=saved_lock,
        )

        self.assertFalse(overview["ok"])
        self.assertEqual(1, len(overview["source_rows"]))
        self.assertEqual(1, len(overview["deploy_rows"]))
        self.assertEqual(1, len(overview["host_rows"]))
        self.assertEqual("manual_git_demo", overview["source_rows"][0]["source_id"])
        self.assertEqual("codex:global", overview["deploy_rows"][0]["target_id"])

    def test_build_skills_overview_uses_saved_lock_runtime_when_inventory_host_observation_degrades(self) -> None:
        degraded_inventory = copy.deepcopy(self.inventory_snapshot)
        degraded_inventory["software_rows"][0].update(
            {
                "installed": False,
                "declared_skill_roots": [],
                "resolved_skill_roots": [],
            },
        )
        degraded_inventory["binding_rows"] = []
        degraded_inventory["binding_map"] = {"codex": [], "antigravity": []}
        degraded_inventory["binding_map_by_scope"] = {
            "global": {"codex": [], "antigravity": []},
            "workspace": {"codex": [], "antigravity": []},
        }

        target_root = Path(self._tempdir.name) / "codex-runtime"
        target_root.mkdir(parents=True, exist_ok=True)

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/example/demo-skills.git",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "compatible_software_ids": ["codex"],
                    "enabled": True,
                    "discovered": True,
                    "source_exists": True,
                },
            ],
        }
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "provider_key": "manual",
                    "enabled": True,
                    "source_scope": "global",
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["manual_git_demo"],
                },
            ],
        }
        saved_lock = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "status": "ready",
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "software_display_name": "Codex",
                    "software_family": "codex",
                    "software_kind": "cli",
                    "provider_key": "codex",
                    "scope": "global",
                    "installed": True,
                    "managed": False,
                    "target_path": str(target_root),
                    "selected_source_ids": ["manual_git_demo"],
                    "available_source_ids": ["manual_git_demo"],
                    "declared_skill_roots": [str(target_root)],
                    "resolved_skill_roots": [str(target_root)],
                },
            ],
        }

        overview = build_skills_overview(
            degraded_inventory,
            saved_manifest=saved_manifest,
            saved_registry=saved_registry,
            saved_lock=saved_lock,
        )

        codex_host = next(item for item in overview["host_rows"] if item["host_id"] == "codex")
        self.assertTrue(codex_host["installed"])
        self.assertEqual([str(target_root)], codex_host["resolved_skill_roots"])
        self.assertEqual(str(target_root), codex_host["target_paths"]["global"])

        codex_global = next(item for item in overview["deploy_rows"] if item["target_id"] == "codex:global")
        self.assertEqual("ready", codex_global["status"])
        self.assertEqual("ok", codex_global["drift_status"])
        self.assertEqual(str(target_root), codex_global["target_path"])

    def test_build_skills_overview_projects_binding_and_compatibility_from_manifest_authority(self) -> None:
        stale_inventory = copy.deepcopy(self.inventory_snapshot)
        stale_inventory["binding_rows"] = []
        stale_inventory["binding_map"] = {"codex": [], "antigravity": []}
        stale_inventory["binding_map_by_scope"] = {
            "global": {"codex": [], "antigravity": []},
            "workspace": {"codex": [], "antigravity": []},
        }
        stale_inventory["compatibility"] = {
            "codex": [],
            "antigravity": ["npx_bundle_compound_engineering_global", "npx_global_find_skills"],
        }

        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["npx_bundle_compound_engineering_global"],
                },
                {
                    "target_id": "antigravity:global",
                    "software_id": "antigravity",
                    "scope": "global",
                    "selected_source_ids": [],
                },
            ],
        }

        overview = build_skills_overview(stale_inventory, saved_manifest=saved_manifest)

        self.assertEqual(
            ["npx_bundle_compound_engineering_global"],
            overview["binding_map"]["codex"],
        )
        self.assertEqual([], overview["binding_map"]["antigravity"])
        self.assertEqual(1, overview["counts"]["bindings_total"])
        self.assertEqual(1, overview["counts"]["bindings_valid"])
        self.assertEqual(0, overview["counts"]["bindings_invalid"])
        self.assertIn(
            "npx_bundle_compound_engineering_global",
            overview["compatibility"]["codex"],
        )
        self.assertNotIn(
            "npx_bundle_compound_engineering_global",
            overview["compatibility"]["antigravity"],
        )

    def test_build_skills_overview_manifest_projection_prefers_selected_target_hints_for_unconstrained_source(self) -> None:
        stale_inventory = copy.deepcopy(self.inventory_snapshot)
        stale_inventory["compatibility"] = {"codex": [], "antigravity": []}

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "locator": "https://github.com/example/demo-skills.git",
                    "source_scope": "global",
                    "provider_key": "manual",
                    "enabled": True,
                },
            ],
        }
        saved_manifest = {
            "version": 1,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "sources": [
                {
                    "source_id": "manual_git_demo",
                    "display_name": "Demo Git Skills",
                    "source_kind": "manual_git",
                    "provider_key": "manual",
                    "enabled": True,
                    "source_scope": "global",
                },
            ],
            "deploy_targets": [
                {
                    "target_id": "codex:global",
                    "software_id": "codex",
                    "scope": "global",
                    "selected_source_ids": ["manual_git_demo"],
                },
                {
                    "target_id": "antigravity:global",
                    "software_id": "antigravity",
                    "scope": "global",
                    "selected_source_ids": [],
                },
            ],
        }

        overview = build_skills_overview(
            stale_inventory,
            saved_manifest=saved_manifest,
            saved_registry=saved_registry,
        )

        self.assertIn("manual_git_demo", overview["compatibility"]["codex"])
        self.assertNotIn("manual_git_demo", overview["compatibility"]["antigravity"])

    def test_build_skills_overview_manifest_projection_drops_inventory_only_compatibility_keys(self) -> None:
        stale_inventory = copy.deepcopy(self.inventory_snapshot)
        stale_inventory["compatibility"] = {
            "codex": stale_inventory["compatibility"]["codex"],
            "antigravity": stale_inventory["compatibility"]["antigravity"],
            "ghost_tool": ["npx_global_find_skills"],
        }

        overview = build_skills_overview(stale_inventory)

        self.assertNotIn("ghost_tool", overview["compatibility"])

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

    def test_project_inventory_snapshot_bindings_from_manifest_reprojects_binding_views(self) -> None:
        inventory_snapshot = copy.deepcopy(self.inventory_snapshot)
        inventory_snapshot["binding_rows"] = []
        inventory_snapshot["binding_map"] = {"codex": [], "antigravity": []}
        inventory_snapshot["binding_map_by_scope"] = {
            "global": {"codex": [], "antigravity": []},
            "workspace": {"codex": [], "antigravity": []},
        }
        inventory_snapshot["software_rows"][0]["binding_count"] = 0
        inventory_snapshot["software_rows"][1]["binding_count"] = 0
        inventory_snapshot["counts"]["bindings_total"] = 0
        inventory_snapshot["counts"]["bindings_valid"] = 0
        inventory_snapshot["counts"]["bindings_invalid"] = 0

        manifest = build_skills_manifest(self.inventory_snapshot)
        for item in manifest["deploy_targets"]:
            if item["target_id"] == "codex:global":
                item["selected_source_ids"] = ["npx_global_find_skills"]
            else:
                item["selected_source_ids"] = []

        projected = project_inventory_snapshot_bindings_from_manifest(inventory_snapshot, manifest)

        self.assertEqual(
            [
                {
                    "software_id": "codex",
                    "skill_id": "npx_global_find_skills",
                    "scope": "global",
                    "enabled": True,
                    "valid": True,
                    "reason": "",
                },
            ],
            projected["binding_rows"],
        )
        self.assertEqual(["npx_global_find_skills"], projected["binding_map"]["codex"])
        self.assertEqual([], projected["binding_map"]["antigravity"])
        self.assertEqual(["npx_global_find_skills"], projected["binding_map_by_scope"]["global"]["codex"])
        self.assertEqual([], projected["binding_map_by_scope"]["workspace"]["codex"])
        self.assertEqual(1, projected["software_rows"][0]["binding_count"])
        self.assertEqual(0, projected["software_rows"][1]["binding_count"])
        self.assertEqual(1, projected["counts"]["bindings_total"])
        self.assertEqual(1, projected["counts"]["bindings_valid"])
        self.assertEqual(0, projected["counts"]["bindings_invalid"])


if __name__ == "__main__":
    unittest.main()
