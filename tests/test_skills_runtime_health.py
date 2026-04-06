from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_runtime_health import build_skills_runtime_health


class SkillsRuntimeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.root = Path(self._tempdir.name)
        self.manifest_path = self.root / "skills" / "manifest.json"
        self.lock_path = self.root / "skills" / "lock.json"
        self.sources_dir = self.root / "skills" / "sources"
        self.generated_dir = self.root / "skills" / "generated"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot = {
            "manifest": {
                "sources": [
                    {"source_id": "npx_bundle_compound_engineering_global"},
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
            "source_rows": [
                {"source_id": "npx_bundle_compound_engineering_global"},
            ],
            "deploy_rows": [
                {"target_id": "codex:global"},
            ],
        }

    def test_runtime_health_reports_clean_state_when_files_and_projection_match(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text("{}", encoding="utf-8")
        self.lock_path.write_text("{}", encoding="utf-8")
        (self.sources_dir / "npx_bundle_compound_engineering_global.json").write_text("{}", encoding="utf-8")
        (self.generated_dir / "codex_global.json").write_text("{}", encoding="utf-8")

        health = build_skills_runtime_health(
            self.snapshot,
            current_bindings=[
                {
                    "software_id": "codex",
                    "skill_id": "npx_bundle_compound_engineering_global",
                    "scope": "global",
                    "enabled": True,
                    "settings": {},
                },
            ],
            manifest_path=self.manifest_path,
            lock_path=self.lock_path,
            sources_dir=self.sources_dir,
            generated_dir=self.generated_dir,
        )

        self.assertTrue(health["state_health"]["ok"])
        self.assertTrue(health["projection_health"]["ok"])
        self.assertEqual([], health["warnings"])
        self.assertEqual(0, health["counts"]["state_source_files_missing_total"])
        self.assertEqual(0, health["counts"]["projection_binding_missing_total"])

    def test_runtime_health_reports_missing_files_and_projection_drift(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text("{}", encoding="utf-8")
        (self.sources_dir / "unexpected_source.json").write_text("{}", encoding="utf-8")
        (self.generated_dir / "unexpected_target.json").write_text("{}", encoding="utf-8")

        health = build_skills_runtime_health(
            self.snapshot,
            current_bindings=[],
            manifest_path=self.manifest_path,
            lock_path=self.lock_path,
            sources_dir=self.sources_dir,
            generated_dir=self.generated_dir,
        )

        self.assertFalse(health["state_health"]["ok"])
        self.assertFalse(health["projection_health"]["ok"])
        self.assertFalse(health["state_health"]["lock_present"])
        self.assertEqual(1, health["counts"]["state_source_files_missing_total"])
        self.assertEqual(1, health["counts"]["state_source_files_extra_total"])
        self.assertEqual(1, health["counts"]["state_generated_files_missing_total"])
        self.assertEqual(1, health["counts"]["state_generated_files_extra_total"])
        self.assertEqual(1, health["counts"]["projection_binding_missing_total"])
        self.assertGreaterEqual(len(health["warnings"]), 4)


if __name__ == "__main__":
    unittest.main()
