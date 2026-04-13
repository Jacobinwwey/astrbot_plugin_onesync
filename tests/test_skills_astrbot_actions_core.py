from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_astrbot_actions_core import (
    delete_astrbot_local_skill,
    export_astrbot_skill_zip,
    import_astrbot_skill_zip,
    set_astrbot_skill_active,
)


class SkillsAstrBotActionsCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.root = Path(self._tempdir.name) / "astrbot-root"
        self.data_dir = self.root / "data"
        self.skills_root = self.data_dir / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = Path(self._tempdir.name) / "workspace-astrbot"
        self.workspace_data_dir = self.workspace_root / "data"
        self.workspace_skills_root = self.workspace_data_dir / "skills"
        self.workspace_skills_root.mkdir(parents=True, exist_ok=True)
        self.layout = {
            "host_id": "astrbot",
            "provider_key": "astrbot",
            "is_astrbot": True,
            "state_available": True,
            "skills_root": str(self.skills_root),
            "skills_config_path": str(self.data_dir / "skills.json"),
            "sandbox_cache_path": str(self.data_dir / "sandbox_skills_cache.json"),
            "scoped_layouts": {
                "global": {
                    "scope": "global",
                    "state_available": True,
                    "skills_root": str(self.skills_root),
                    "skills_config_path": str(self.data_dir / "skills.json"),
                    "sandbox_cache_path": str(self.data_dir / "sandbox_skills_cache.json"),
                },
                "workspace": {
                    "scope": "workspace",
                    "state_available": True,
                    "skills_root": str(self.workspace_skills_root),
                    "skills_config_path": str(self.workspace_data_dir / "skills.json"),
                    "sandbox_cache_path": str(self.workspace_data_dir / "sandbox_skills_cache.json"),
                },
            },
        }

    def _write_skill(self, skill_name: str, *, scope: str = "global") -> None:
        skill_root = self.skills_root if scope != "workspace" else self.workspace_skills_root
        skill_dir = skill_root / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"# {skill_name}\n",
            encoding="utf-8",
        )

    def _write_sandbox_cache(self, skill_names: list[str], *, scope: str = "global") -> None:
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
        data_dir = self.data_dir if scope != "workspace" else self.workspace_data_dir
        (data_dir / "sandbox_skills_cache.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_zip(
        self,
        relative_files: dict[str, str],
        *,
        archive_name: str = "skill.zip",
    ) -> Path:
        archive_path = Path(self._tempdir.name) / archive_name
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for relative_path, content in relative_files.items():
                handle.writestr(relative_path, content)
        return archive_path

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

    def test_set_astrbot_skill_active_updates_requested_workspace_scope(self) -> None:
        self._write_skill("workspace-demo", scope="workspace")
        self._write_sandbox_cache(["workspace-demo"], scope="workspace")

        result = set_astrbot_skill_active(self.layout, "workspace-demo", False, scope="workspace")
        self.assertTrue(result["ok"])
        self.assertEqual("workspace", result["scope"])

        workspace_payload = json.loads((self.workspace_data_dir / "skills.json").read_text(encoding="utf-8"))
        self.assertFalse(workspace_payload["skills"]["workspace-demo"]["active"])
        self.assertFalse((self.data_dir / "skills.json").exists())

    def test_delete_astrbot_local_skill_uses_requested_scope(self) -> None:
        self._write_skill("workspace-demo", scope="workspace")
        self._write_sandbox_cache(["workspace-demo"], scope="workspace")

        result = delete_astrbot_local_skill(self.layout, "workspace-demo", scope="workspace")
        self.assertTrue(result["ok"])
        self.assertEqual("workspace", result["scope"])
        self.assertFalse((self.workspace_skills_root / "workspace-demo").exists())

    def test_set_astrbot_skill_active_rejects_unavailable_scope(self) -> None:
        layout = dict(self.layout)
        layout["scoped_layouts"] = {
            "global": dict(self.layout["scoped_layouts"]["global"]),
        }

        result = set_astrbot_skill_active(layout, "demo", True, scope="workspace")
        self.assertFalse(result["ok"])
        self.assertEqual("scope_unavailable", result["reason_code"])

    def test_import_astrbot_skill_zip_installs_root_archive_and_marks_skill_active(self) -> None:
        archive_path = self._build_zip(
            {
                "SKILL.md": "---\ndescription: imported demo\n---\n# Imported\n",
                "README.md": "demo archive\n",
            },
            archive_name="imported-demo.zip",
        )

        result = import_astrbot_skill_zip(
            self.layout,
            str(archive_path),
            skill_name_hint="imported-demo",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(["imported-demo"], result["installed_skill_names"])
        self.assertEqual(1, result["installed_count"])
        self.assertTrue((self.skills_root / "imported-demo" / "SKILL.md").exists())

        payload = json.loads((self.data_dir / "skills.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["skills"]["imported-demo"]["active"])

    def test_import_astrbot_skill_zip_installs_under_workspace_scope_and_marks_workspace_active(self) -> None:
        archive_path = self._build_zip(
            {
                "SKILL.md": "---\ndescription: imported workspace demo\n---\n# Imported Workspace\n",
                "README.md": "workspace archive\n",
            },
            archive_name="workspace-imported.zip",
        )

        result = import_astrbot_skill_zip(
            self.layout,
            str(archive_path),
            scope="workspace",
            skill_name_hint="workspace-imported",
        )
        self.assertTrue(result["ok"])
        self.assertEqual("workspace", result["scope"])
        self.assertEqual(["workspace-imported"], result["installed_skill_names"])
        self.assertTrue((self.workspace_skills_root / "workspace-imported" / "SKILL.md").exists())

        workspace_payload = json.loads((self.workspace_data_dir / "skills.json").read_text(encoding="utf-8"))
        self.assertTrue(workspace_payload["skills"]["workspace-imported"]["active"])

        global_skills_config_path = self.data_dir / "skills.json"
        if global_skills_config_path.exists():
            global_payload = json.loads(global_skills_config_path.read_text(encoding="utf-8"))
            self.assertNotIn("workspace-imported", global_payload.get("skills", {}))

    def test_export_astrbot_skill_zip_creates_archive_for_local_skill(self) -> None:
        self._write_skill("demo")
        (self.skills_root / "demo" / "extra.txt").write_text("hello\n", encoding="utf-8")

        result = export_astrbot_skill_zip(self.layout, "demo")
        self.assertTrue(result["ok"])
        archive_path = Path(result["archive_path"])
        self.assertTrue(archive_path.exists())
        self.assertEqual("demo.zip", result["filename"])

        with zipfile.ZipFile(archive_path) as handle:
            names = sorted(handle.namelist())
        self.assertIn("demo/SKILL.md", names)
        self.assertIn("demo/extra.txt", names)

    def test_export_astrbot_skill_zip_rejects_sandbox_only_skill(self) -> None:
        self._write_sandbox_cache(["sandbox-only"])

        result = export_astrbot_skill_zip(self.layout, "sandbox-only")
        self.assertFalse(result["ok"])
        self.assertEqual("sandbox_only_skill", result["reason_code"])


if __name__ == "__main__":
    unittest.main()
