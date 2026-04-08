from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inventory_core import (
    build_inventory_snapshot,
    normalize_skill_bindings_payload,
    normalize_skill_catalog_payload,
    normalize_software_catalog_payload,
    replace_bindings_for_scope,
)


class InventoryCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        previous = os.environ.get("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS")
        os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = str(
            Path(self._tempdir.name) / ".isolated-package-cache"
        )

        def _restore() -> None:
            if previous is None:
                os.environ.pop("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS", None)
            else:
                os.environ["ONESYNC_SKILL_PACKAGE_CACHE_ROOTS"] = previous

        self.addCleanup(_restore)

    def test_software_catalog_defaults(self) -> None:
        rows = normalize_software_catalog_payload([], fallback_defaults=True)
        ids = {row["id"] for row in rows}
        self.assertIn("claude_code", ids)
        self.assertIn("codex", ids)
        self.assertIn("zeroclaw", ids)
        self.assertIn("cursor_agent", ids)
        self.assertIn("gemini_cli", ids)
        self.assertIn("qwen_code", ids)
        self.assertIn("windsurf", ids)

    def test_software_catalog_defaults_expand_skill_capable_hosts(self) -> None:
        rows = normalize_software_catalog_payload([], fallback_defaults=True)
        by_id = {row["id"]: row for row in rows}

        self.assertEqual("gui", by_id["cursor_agent"]["software_kind"])
        self.assertIn("cursor-agent", by_id["cursor_agent"]["detect_commands"])
        self.assertTrue(any("cursor" in path.lower() for path in by_id["cursor_agent"]["skill_roots"]))

        self.assertEqual("cli", by_id["gemini_cli"]["software_kind"])
        self.assertIn("gemini-cli", by_id["gemini_cli"]["detect_commands"])

        self.assertEqual("cli", by_id["openhands"]["software_kind"])
        self.assertIn("openhands", by_id["openhands"]["detect_commands"])

        self.assertEqual("gui", by_id["windsurf"]["software_kind"])
        self.assertIn("windsurf", by_id["windsurf"]["detect_commands"])

    def test_software_catalog_duplicate_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_software_catalog_payload(
                [
                    {"id": "dup", "provider_key": "generic"},
                    {"id": "dup", "provider_key": "generic"},
                ],
                fallback_defaults=False,
            )

    def test_skill_catalog_normalization(self) -> None:
        rows = normalize_skill_catalog_payload(
            [
                {
                    "id": "My Skill",
                    "provider_key": "codex",
                    "compatible_software_kinds": ["cli", "invalid_kind", "gui"],
                },
            ],
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("my_skill", rows[0]["id"])
        self.assertEqual(["cli", "gui"], rows[0]["compatible_software_kinds"])

    def test_skill_bindings_dedup_scope_normalize(self) -> None:
        rows = normalize_skill_bindings_payload(
            [
                {"software_id": "soft_a", "skill_id": "skill_a", "scope": "GLOBAL"},
                {"software_id": "soft_a", "skill_id": "skill_a", "scope": "global"},
                {"software_id": "soft_a", "skill_id": "skill_a", "scope": "workspace"},
            ],
        )
        self.assertEqual(2, len(rows))
        keys = {(row["software_id"], row["skill_id"], row["scope"]) for row in rows}
        self.assertIn(("soft_a", "skill_a", "global"), keys)
        self.assertIn(("soft_a", "skill_a", "workspace"), keys)

    def test_replace_bindings_for_scope_preserves_other_scopes(self) -> None:
        current = normalize_skill_bindings_payload(
            [
                {"software_id": "soft_a", "skill_id": "skill_old", "scope": "global"},
                {"software_id": "soft_a", "skill_id": "skill_ws", "scope": "workspace"},
                {"software_id": "soft_b", "skill_id": "skill_b", "scope": "global"},
            ],
        )
        next_rows = replace_bindings_for_scope(
            current,
            software_id="soft_a",
            skill_ids=["skill_new"],
            scope="global",
        )
        keys = {(row["software_id"], row["skill_id"], row["scope"]) for row in next_rows}
        self.assertIn(("soft_a", "skill_new", "global"), keys)
        self.assertIn(("soft_a", "skill_ws", "workspace"), keys)
        self.assertIn(("soft_b", "skill_b", "global"), keys)
        self.assertNotIn(("soft_a", "skill_old", "global"), keys)

    def test_build_inventory_snapshot_with_manual_and_auto_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_root = root / "skills"
            auto_skill_dir = skill_root / "auto_one"
            auto_skill_dir.mkdir(parents=True, exist_ok=True)
            (auto_skill_dir / "SKILL.md").write_text("# auto\n", encoding="utf-8")

            manual_skill_dir = root / "manual_skill"
            manual_skill_dir.mkdir(parents=True, exist_ok=True)
            (manual_skill_dir / "SKILL.md").write_text("# manual\n", encoding="utf-8")

            software_catalog = normalize_software_catalog_payload(
                [
                    {
                        "id": "soft_cli",
                        "display_name": "Soft CLI",
                        "software_kind": "cli",
                        "provider_key": "generic_cli",
                        "detect_paths": [str(root)],
                        "skill_roots": [str(skill_root)],
                        "linked_target_name": "soft_target",
                        "enabled": True,
                    },
                ],
                fallback_defaults=False,
            )
            skill_catalog = normalize_skill_catalog_payload(
                [
                    {
                        "id": "manual_skill",
                        "display_name": "Manual Skill",
                        "provider_key": "generic",
                        "source_path": str(manual_skill_dir),
                        "compatible_software_kinds": ["cli"],
                        "enabled": True,
                    },
                ],
            )
            bindings = normalize_skill_bindings_payload(
                [
                    {"software_id": "soft_cli", "skill_id": "manual_skill", "scope": "global"},
                    {"software_id": "soft_cli", "skill_id": "manual_skill", "scope": "workspace"},
                    {"software_id": "soft_cli", "skill_id": "missing_skill", "scope": "global"},
                ],
            )

            snapshot = build_inventory_snapshot(
                software_catalog=software_catalog,
                skill_catalog=skill_catalog,
                skill_bindings=bindings,
                target_rows={
                    "soft_target": {
                        "status": "up_to_date",
                        "current_version": "1.0.0",
                        "latest_version": "1.0.0",
                    },
                },
                inventory_options={
                    "skill_management_mode": "filesystem",
                    "auto_discover_cli": False,
                },
            )

            self.assertTrue(snapshot["ok"])
            self.assertEqual(1, snapshot["counts"]["software_total"])
            self.assertGreaterEqual(snapshot["counts"]["skills_total"], 2)
            self.assertEqual(3, snapshot["counts"]["bindings_total"])
            self.assertEqual(2, snapshot["counts"]["bindings_valid"])
            self.assertEqual(1, snapshot["counts"]["bindings_invalid"])

            by_scope = snapshot.get("binding_map_by_scope", {})
            self.assertIn("manual_skill", by_scope.get("global", {}).get("soft_cli", []))
            self.assertIn("manual_skill", by_scope.get("workspace", {}).get("soft_cli", []))

            software_rows = snapshot["software_rows"]
            self.assertEqual("up_to_date", software_rows[0]["update_status"])
            self.assertTrue(software_rows[0]["managed"])
            self.assertTrue(software_rows[0]["installed"])

            skills = snapshot["skill_rows"]
            self.assertTrue(any(row.get("auto_discovered") for row in skills))
            self.assertTrue(any(row["id"] == "manual_skill" for row in skills))
            manual_row = next(row for row in skills if row["id"] == "manual_skill")
            self.assertTrue(manual_row["source_exists"])
            self.assertEqual("fresh", manual_row["freshness_status"])
            self.assertIsInstance(manual_row["source_age_days"], int)
            self.assertTrue(manual_row["last_seen_at"])

    def test_build_inventory_snapshot_with_npx_skills_mode(self) -> None:
        software_catalog = normalize_software_catalog_payload(
            [
                {
                    "id": "codex",
                    "display_name": "Codex",
                    "software_kind": "cli",
                    "provider_key": "codex",
                    "detect_commands": [],
                    "enabled": True,
                },
                {
                    "id": "claude_code",
                    "display_name": "Claude Code",
                    "software_kind": "cli",
                    "provider_key": "claude_code",
                    "detect_commands": [],
                    "enabled": True,
                },
            ],
            fallback_defaults=False,
        )

        def _fake_run(command, **_kwargs):
            class _Result:
                def __init__(self, stdout: str) -> None:
                    self.stdout = stdout
                    self.stderr = ""
                    self.returncode = 0

            if "-g" in command:
                return _Result(
                    (
                        "["
                        "{\"name\":\"ce:brainstorm\",\"path\":\"/root/.codex/skills/ce-brainstorm\",\"scope\":\"global\",\"agents\":[\"Codex\"]},"
                        "{\"name\":\"ce:compound\",\"path\":\"/root/.codex/skills/ce-compound\",\"scope\":\"global\",\"agents\":[\"Codex\"]},"
                        "{\"name\":\"design-iterator\",\"path\":\"/root/.codex/skills/design-iterator\",\"scope\":\"global\",\"agents\":[\"Codex\"]},"
                        "{\"name\":\"correctness-reviewer\",\"path\":\"/root/.codex/skills/correctness-reviewer\",\"scope\":\"global\",\"agents\":[\"Codex\"]},"
                        "{\"name\":\"frontend-design\",\"path\":\"/root/.agents/skills/frontend-design\",\"scope\":\"global\",\"agents\":[\"Codex\"]},"
                        "{\"name\":\"find-skills\",\"path\":\"/root/.agents/skills/find-skills\",\"scope\":\"global\",\"agents\":[]}"
                        "]"
                    ),
                )
            return _Result("[]")

        snapshot = build_inventory_snapshot(
            software_catalog=software_catalog,
            skill_catalog=normalize_skill_catalog_payload([{"id": "manual_skill"}]),
            skill_bindings=[],
            target_rows={},
            inventory_options={
                "skill_management_mode": "npx",
                "npx_timeout_s": 3,
                "auto_discover_cli": False,
            },
            command_runner=_fake_run,
        )

        skill_ids = {row.get("id") for row in snapshot["skill_rows"]}
        self.assertIn("npx_bundle_compound_engineering_global", skill_ids)
        self.assertIn("npx_global_find_skills", skill_ids)
        self.assertIn("npx_global_frontend_design", skill_ids)
        self.assertNotIn("manual_skill", skill_ids)
        compound_row = next(
            row for row in snapshot["skill_rows"] if row["id"] == "npx_bundle_compound_engineering_global"
        )
        self.assertEqual(2, compound_row["member_count"])
        self.assertEqual("skill_bundle", compound_row["skill_kind"])
        self.assertEqual("bunx @every-env/compound-plugin", compound_row["management_hint"])
        self.assertEqual("@every-env/compound-plugin", compound_row["registry_package_name"])
        self.assertEqual("npm:@every-env/compound-plugin", compound_row["install_unit_id"])
        self.assertEqual("collection:compound_engineering", compound_row["collection_group_id"])
        self.assertEqual("fresh", compound_row["freshness_status"])

        self.assertIn("npx_bundle_compound_engineering_global", snapshot["compatibility"]["codex"])
        self.assertNotIn("npx_bundle_compound_engineering_global", snapshot["compatibility"]["claude_code"])
        self.assertEqual(6, snapshot["counts"]["skills_members_total"])

    def test_build_inventory_snapshot_marks_curated_npx_install_units_for_related_skill_sets(self) -> None:
        software_catalog = normalize_software_catalog_payload(
            [
                {
                    "id": "codex",
                    "display_name": "Codex",
                    "software_kind": "cli",
                    "provider_key": "codex",
                    "detect_commands": [],
                    "enabled": True,
                },
            ],
            fallback_defaults=False,
        )

        global_items = [
            {"name": "design-implementation-reviewer", "path": "/root/.codex/skills/design-implementation-reviewer", "scope": "global", "agents": ["Codex"]},
            {"name": "design-iterator", "path": "/root/.codex/skills/design-iterator", "scope": "global", "agents": ["Codex"]},
            {"name": "design-lens-reviewer", "path": "/root/.codex/skills/design-lens-reviewer", "scope": "global", "agents": ["Codex"]},
            {"name": "dhh-rails-style", "path": "/root/.codex/skills/dhh-rails-style", "scope": "global", "agents": ["Codex"]},
            {"name": "dhh-rails-reviewer", "path": "/root/.codex/skills/dhh-rails-reviewer", "scope": "global", "agents": ["Codex"]},
        ]

        def _fake_run(command, **_kwargs):
            class _Result:
                def __init__(self, stdout: str) -> None:
                    self.stdout = stdout
                    self.stderr = ""
                    self.returncode = 0

            if "-g" in command:
                return _Result(json.dumps(global_items))
            return _Result("[]")

        snapshot = build_inventory_snapshot(
            software_catalog=software_catalog,
            skill_catalog=[],
            skill_bindings=[],
            target_rows={},
            inventory_options={
                "skill_management_mode": "npx",
                "npx_timeout_s": 3,
                "auto_discover_cli": False,
            },
            command_runner=_fake_run,
        )

        by_id = {row["id"]: row for row in snapshot["skill_rows"]}

        design_impl = by_id["npx_global_design_implementation_reviewer"]
        design_iter = by_id["npx_global_design_iterator"]
        design_lens = by_id["npx_global_design_lens_reviewer"]
        self.assertEqual("curated:design_review_pack", design_impl["install_unit_id"])
        self.assertEqual("curated:design_review_pack", design_iter["install_unit_id"])
        self.assertEqual("curated:design_review_pack", design_lens["install_unit_id"])
        self.assertEqual("collection:design_review", design_impl["collection_group_id"])
        self.assertEqual("collection:design_review", design_iter["collection_group_id"])
        self.assertEqual("collection:design_review", design_lens["collection_group_id"])

        dhh_style = by_id["npx_global_dhh_rails_style"]
        dhh_reviewer = by_id["npx_global_dhh_rails_reviewer"]
        self.assertEqual("curated:dhh_rails_pack", dhh_style["install_unit_id"])
        self.assertEqual("curated:dhh_rails_pack", dhh_reviewer["install_unit_id"])
        self.assertEqual("collection:dhh_rails", dhh_style["collection_group_id"])
        self.assertEqual("collection:dhh_rails", dhh_reviewer["collection_group_id"])

    def test_build_inventory_snapshot_infers_skill_lock_provenance_groups_from_repo_metadata(self) -> None:
        software_catalog = normalize_software_catalog_payload(
            [
                {
                    "id": "codex",
                    "display_name": "Codex",
                    "software_kind": "cli",
                    "provider_key": "codex",
                    "detect_commands": [],
                    "enabled": True,
                },
            ],
            fallback_defaults=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_root = root / ".agents"
            skills_root = agents_root / "skills"
            ui_audit_dir = skills_root / "ui-audit"
            ui_reviewer_dir = skills_root / "ui-reviewer"
            ui_audit_dir.mkdir(parents=True, exist_ok=True)
            ui_reviewer_dir.mkdir(parents=True, exist_ok=True)
            (ui_audit_dir / "SKILL.md").write_text("# ui-audit\n", encoding="utf-8")
            (ui_reviewer_dir / "SKILL.md").write_text("# ui-reviewer\n", encoding="utf-8")
            (agents_root / ".skill-lock.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "skills": {
                            "ui-audit": {
                                "source": "demo/tools",
                                "sourceType": "github",
                                "sourceUrl": "https://github.com/demo/tools.git",
                                "skillPath": "skills/ui-audit/SKILL.md",
                            },
                            "ui-reviewer": {
                                "source": "demo/tools",
                                "sourceType": "github",
                                "sourceUrl": "https://github.com/demo/tools.git",
                                "skillPath": "skills/ui-reviewer/SKILL.md",
                            },
                        },
                    },
                ),
                encoding="utf-8",
            )

            global_items = [
                {"name": "ui-audit", "path": str(ui_audit_dir), "scope": "global", "agents": ["Codex"]},
                {"name": "ui-reviewer", "path": str(ui_reviewer_dir), "scope": "global", "agents": ["Codex"]},
            ]

            def _fake_run(command, **_kwargs):
                class _Result:
                    def __init__(self, stdout: str) -> None:
                        self.stdout = stdout
                        self.stderr = ""
                        self.returncode = 0

                if "-g" in command:
                    return _Result(json.dumps(global_items))
                return _Result("[]")

            snapshot = build_inventory_snapshot(
                software_catalog=software_catalog,
                skill_catalog=[],
                skill_bindings=[],
                target_rows={},
                inventory_options={
                    "skill_management_mode": "npx",
                    "npx_timeout_s": 3,
                    "auto_discover_cli": False,
                },
                command_runner=_fake_run,
            )

        by_id = {row["id"]: row for row in snapshot["skill_rows"]}
        ui_audit = by_id["npx_global_ui_audit"]
        ui_reviewer = by_id["npx_global_ui_reviewer"]

        self.assertEqual("https://github.com/demo/tools.git", ui_audit["locator"])
        self.assertEqual("skills/ui-audit", ui_audit["source_subpath"])
        self.assertEqual(
            "skill_lock:https://github.com/demo/tools.git#skills/ui-audit",
            ui_audit["install_unit_id"],
        )
        self.assertEqual(
            "skill_lock:https://github.com/demo/tools.git#skills/ui-reviewer",
            ui_reviewer["install_unit_id"],
        )
        self.assertEqual("collection:source_repo_demo_tools", ui_audit["collection_group_id"])
        self.assertEqual("collection:source_repo_demo_tools", ui_reviewer["collection_group_id"])
        self.assertEqual("demo/tools", ui_audit["collection_group_name"])
        self.assertEqual("skill_lock_path", ui_audit["aggregation_strategy"])
        self.assertEqual("skill_lock_source", ui_audit["provenance_origin_kind"])
        self.assertEqual("https://github.com/demo/tools.git", ui_audit["provenance_origin_ref"])
        self.assertEqual("demo/tools", ui_audit["provenance_origin_label"])
        self.assertEqual("skill_lock_path", ui_audit["provenance_package_strategy"])
        self.assertEqual("high", ui_audit["provenance_confidence"])

    def test_build_inventory_snapshot_keeps_codex_root_skills_split_by_source(self) -> None:
        software_catalog = normalize_software_catalog_payload(
            [
                {
                    "id": "codex",
                    "display_name": "Codex",
                    "software_kind": "cli",
                    "provider_key": "codex",
                    "detect_commands": [],
                    "enabled": True,
                },
            ],
            fallback_defaults=False,
        )

        global_items = [
            {"name": "ce:brainstorm", "path": "/root/.codex/skills/ce-brainstorm", "scope": "global", "agents": ["Codex"]},
            {"name": "ce:compound", "path": "/root/.codex/skills/ce-compound", "scope": "global", "agents": ["Codex"]},
            {"name": "correctness-reviewer", "path": "/root/.codex/skills/correctness-reviewer", "scope": "global", "agents": ["Codex"]},
            {"name": "design-iterator", "path": "/root/.codex/skills/design-iterator", "scope": "global", "agents": ["Codex"]},
            {"name": "frontend-design", "path": "/root/.codex/skills/frontend-design", "scope": "global", "agents": ["Codex"]},
            {"name": "find-skills", "path": "/root/.codex/skills/find-skills", "scope": "global", "agents": ["Codex"]},
            {"name": "performance-oracle", "path": "/root/.codex/skills/performance-oracle", "scope": "global", "agents": ["Codex"]},
            {"name": "systematic-debugging", "path": "/root/.codex/skills/systematic-debugging", "scope": "global", "agents": ["Codex"]},
            {"name": "verification-before-completion", "path": "/root/.codex/skills/verification-before-completion", "scope": "global", "agents": ["Codex"]},
            {"name": "requesting-code-review", "path": "/root/.codex/skills/requesting-code-review", "scope": "global", "agents": ["Codex"]},
        ]

        def _fake_run(command, **_kwargs):
            class _Result:
                def __init__(self, stdout: str) -> None:
                    self.stdout = stdout
                    self.stderr = ""
                    self.returncode = 0

            if "-g" in command:
                return _Result(json.dumps(global_items))
            return _Result("[]")

        snapshot = build_inventory_snapshot(
            software_catalog=software_catalog,
            skill_catalog=[],
            skill_bindings=[],
            target_rows={},
            inventory_options={
                "skill_management_mode": "npx",
                "npx_timeout_s": 3,
                "auto_discover_cli": False,
            },
            command_runner=_fake_run,
        )

        skill_ids = {row.get("id") for row in snapshot["skill_rows"]}
        self.assertIn("npx_bundle_compound_engineering_global", skill_ids)
        self.assertNotIn("npx_bundle_codex_skill_pack_global", skill_ids)
        self.assertIn("npx_global_correctness_reviewer", skill_ids)
        self.assertIn("npx_global_design_iterator", skill_ids)
        self.assertIn("npx_global_frontend_design", skill_ids)
        self.assertIn("npx_global_find_skills", skill_ids)
        self.assertIn("npx_global_performance_oracle", skill_ids)
        self.assertIn("npx_global_systematic_debugging", skill_ids)
        self.assertIn("npx_global_verification_before_completion", skill_ids)
        self.assertIn("npx_global_requesting_code_review", skill_ids)
        self.assertEqual(10, snapshot["counts"]["skills_members_total"])

        correctness = next(
            row for row in snapshot["skill_rows"] if row["id"] == "npx_global_correctness_reviewer"
        )
        self.assertEqual("skills_root", correctness["provenance_origin_kind"])
        self.assertEqual("Codex Skills Root", correctness["provenance_origin_label"])
        self.assertEqual("codex_home_skills", correctness["provenance_root_kind"])
        self.assertEqual("/root/.codex/skills", correctness["provenance_root_path"])
        self.assertEqual("low", correctness["provenance_confidence"])

    def test_build_inventory_snapshot_marks_stale_skill_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stale_skill_dir = root / "stale_skill"
            stale_skill_dir.mkdir(parents=True, exist_ok=True)
            skill_md = stale_skill_dir / "SKILL.md"
            skill_md.write_text("# stale\n", encoding="utf-8")
            old_ts = time.time() - (45 * 24 * 60 * 60)
            os.utime(stale_skill_dir, (old_ts, old_ts))
            os.utime(skill_md, (old_ts, old_ts))

            software_catalog = normalize_software_catalog_payload(
                [
                    {
                        "id": "soft_cli",
                        "display_name": "Soft CLI",
                        "software_kind": "cli",
                        "provider_key": "generic_cli",
                        "detect_paths": [str(root)],
                        "skill_roots": [str(root)],
                        "enabled": True,
                    },
                ],
                fallback_defaults=False,
            )
            skill_catalog = normalize_skill_catalog_payload(
                [
                    {
                        "id": "stale_skill",
                        "display_name": "Stale Skill",
                        "provider_key": "generic",
                        "source_path": str(stale_skill_dir),
                        "compatible_software_kinds": ["cli"],
                        "enabled": True,
                    },
                ],
            )

            snapshot = build_inventory_snapshot(
                software_catalog=software_catalog,
                skill_catalog=skill_catalog,
                skill_bindings=[],
                target_rows={},
                inventory_options={"skill_management_mode": "filesystem", "auto_discover_cli": False},
            )

            stale_row = next(row for row in snapshot["skill_rows"] if row["id"] == "stale_skill")
            self.assertTrue(stale_row["source_exists"])
            self.assertEqual("stale", stale_row["freshness_status"])
            self.assertGreaterEqual(stale_row["source_age_days"], 44)
            self.assertTrue(stale_row["last_seen_at"])

    def test_build_inventory_snapshot_with_auto_cli_discovery(self) -> None:
        software_catalog = normalize_software_catalog_payload([], fallback_defaults=False)

        def _fake_which(cmd: str):
            if cmd in {"claude", "codex"}:
                return f"/usr/local/bin/{cmd}"
            return None

        with patch("inventory_core.shutil.which", side_effect=_fake_which):
            snapshot = build_inventory_snapshot(
                software_catalog=software_catalog,
                skill_catalog=[],
                skill_bindings=[],
                target_rows={},
                inventory_options={
                    "skill_management_mode": "filesystem",
                    "auto_discover_cli": True,
                    "auto_cli_only_known": True,
                    "auto_discover_cli_max": 10,
                },
            )

        software_ids = {row.get("id") for row in snapshot["software_rows"]}
        self.assertIn("cli_claude", software_ids)
        self.assertIn("cli_codex", software_ids)


if __name__ == "__main__":
    unittest.main()
