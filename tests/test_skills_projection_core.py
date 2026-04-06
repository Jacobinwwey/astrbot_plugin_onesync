from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_projection_core import build_generated_target_diff


class SkillsProjectionCoreTests(unittest.TestCase):
    def test_generated_target_diff_reports_missing_projection_file(self) -> None:
        current_target = {
            "target_id": "codex:global",
            "software_id": "codex",
            "scope": "global",
            "target_path": "/root/.codex/skills",
            "selected_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "ready_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "missing_source_ids": [],
            "incompatible_source_ids": [],
            "repair_actions": [],
            "status": "ready",
            "drift_status": "ok",
        }

        diff = build_generated_target_diff(current_target, None)

        self.assertFalse(diff["ok"])
        self.assertTrue(diff["missing_file"])
        self.assertIn("generated_projection", diff["changed_fields"])

    def test_generated_target_diff_reports_clean_projection_when_fields_match(self) -> None:
        current_target = {
            "target_id": "codex:global",
            "software_id": "codex",
            "scope": "global",
            "target_path": "/root/.codex/skills",
            "selected_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "ready_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "missing_source_ids": [],
            "incompatible_source_ids": [],
            "repair_actions": [],
            "status": "ready",
            "drift_status": "ok",
        }
        persisted = dict(current_target)

        diff = build_generated_target_diff(current_target, persisted)

        self.assertTrue(diff["ok"])
        self.assertFalse(diff["missing_file"])
        self.assertEqual([], diff["changed_fields"])
        self.assertEqual(0, diff["field_diff_total"])

    def test_generated_target_diff_reports_changed_fields(self) -> None:
        current_target = {
            "target_id": "codex:global",
            "software_id": "codex",
            "scope": "global",
            "target_path": "/root/.codex/skills",
            "selected_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "ready_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "missing_source_ids": [],
            "incompatible_source_ids": [],
            "repair_actions": [],
            "status": "ready",
            "drift_status": "ok",
        }
        persisted = {
            "target_id": "codex:global",
            "software_id": "codex",
            "scope": "global",
            "target_path": "/root/.codex/skills-stale",
            "selected_source_ids": [],
            "ready_source_ids": [],
            "missing_source_ids": ["npx_bundle_codex_skill_pack_global"],
            "incompatible_source_ids": [],
            "repair_actions": ["drop_missing_sources"],
            "status": "stale",
            "drift_status": "missing_source",
        }

        diff = build_generated_target_diff(current_target, persisted)

        self.assertFalse(diff["ok"])
        self.assertEqual(6, diff["field_diff_total"])
        self.assertIn("target_path", diff["changed_fields"])
        self.assertIn("selected_source_ids", diff["changed_fields"])
        self.assertIn("status", diff["changed_fields"])
        self.assertIn("drift_status", diff["changed_fields"])


if __name__ == "__main__":
    unittest.main()
