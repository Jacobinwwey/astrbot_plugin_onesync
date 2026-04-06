from __future__ import annotations

import tempfile
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

        self.assertIn("npx_bundle_compound_engineering_global", snapshot["compatibility"]["codex"])
        self.assertNotIn("npx_bundle_compound_engineering_global", snapshot["compatibility"]["claude_code"])
        self.assertEqual(6, snapshot["counts"]["skills_members_total"])

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
