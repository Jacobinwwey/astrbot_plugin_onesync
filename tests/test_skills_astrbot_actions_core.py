from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_astrbot_actions_core import delete_astrbot_local_skill, set_astrbot_skill_active


class SkillsAstrBotActionsCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.root = Path(self._tempdir.name) / "astrbot-root"
        self.data_dir = self.root / "data"
        self.skills_root = self.data_dir / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self.layout = {
            "host_id": "astrbot",
            "provider_key": "astrbot",
            "is_astrbot": True,
            "state_available": True,
            "skills_root": str(self.skills_root),
            "skills_config_path": str(self.data_dir / "skills.json"),
            "sandbox_cache_path": str(self.data_dir / "sandbox_skills_cache.json"),
        }

    def _write_skill(self, skill_name: str) -> None:
        skill_dir = self.skills_root / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"# {skill_name}\n",
            encoding="utf-8",
        )

    def _write_sandbox_cache(self, skill_names: list[str]) -> None:
        payload = {
            "version": 1,
            "skills": [
                {
                    "name": skill_name,
                    "description": f"{skill_name} from sandbox",
                    "path": f"/workspace/skills/{skill_name}/SKILL.md",
                }
                for skill_name in skill_names
            ],
        }
        (self.data_dir / "sandbox_skills_cache.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_set_astrbot_skill_active_updates_skills_config(self) -> None:
        self._write_skill("demo")
        self._write_sandbox_cache(["demo"])

        result = set_astrbot_skill_active(self.layout, "demo", False)
        self.assertTrue(result["ok"])
        self.assertEqual("demo", result["skill_name"])
        self.assertFalse(result["active"])
        self.assertTrue(result["changed"])

        payload = json.loads((self.data_dir / "skills.json").read_text(encoding="utf-8"))
        self.assertIn("skills", payload)
        self.assertIn("demo", payload["skills"])
        self.assertFalse(payload["skills"]["demo"]["active"])

    def test_set_astrbot_skill_active_rejects_sandbox_only_skill(self) -> None:
        self._write_sandbox_cache(["sandbox-only"])

        result = set_astrbot_skill_active(self.layout, "sandbox-only", False)
        self.assertFalse(result["ok"])
        self.assertEqual("sandbox_only_skill", result["reason_code"])
        self.assertFalse(result["local_exists"])
        self.assertTrue(result["sandbox_exists"])

    def test_delete_astrbot_local_skill_removes_local_dir_config_and_cache_entry(self) -> None:
        self._write_skill("demo")
        self._write_sandbox_cache(["demo", "keep"])
        (self.data_dir / "skills.json").write_text(
            json.dumps(
                {
                    "skills": {
                        "demo": {"active": True},
                        "keep": {"active": True},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        result = delete_astrbot_local_skill(self.layout, "demo")
        self.assertTrue(result["ok"])
        self.assertTrue(result["deleted_local_dir"])
        self.assertTrue(result["removed_from_config"])
        self.assertTrue(result["removed_from_sandbox_cache"])

        self.assertFalse((self.skills_root / "demo").exists())
        config_payload = json.loads((self.data_dir / "skills.json").read_text(encoding="utf-8"))
        self.assertNotIn("demo", config_payload.get("skills", {}))
        cache_payload = json.loads((self.data_dir / "sandbox_skills_cache.json").read_text(encoding="utf-8"))
        cached_names = [str(item.get("name") or "") for item in cache_payload.get("skills", []) if isinstance(item, dict)]
        self.assertEqual(["keep"], cached_names)


if __name__ == "__main__":
    unittest.main()
