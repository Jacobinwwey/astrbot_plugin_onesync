from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_astrbot_state_core import (
    build_astrbot_host_runtime_state,
    build_astrbot_state_index,
    resolve_astrbot_host_layout,
)


class SkillsAstrBotStateCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.root = Path(self._tempdir.name) / "astrbot-root"
        self.skills_root = self.root / "data" / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = self.root / "data" / "workspaces" / "session-alpha"
        self.workspace_skills_root = self.workspace_root / "skills"
        self.workspace_skills_root.mkdir(parents=True, exist_ok=True)

    def _write_skill(self, name: str, description: str = "", *, scope: str = "global") -> None:
        skill_root = self.skills_root if scope != "workspace" else self.workspace_skills_root
        skill_dir = skill_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = ""
        if description:
            frontmatter = f"---\ndescription: {description}\n---\n"
        (skill_dir / "SKILL.md").write_text(
            f"{frontmatter}# {name}\n",
            encoding="utf-8",
        )

    def _build_host(self) -> dict[str, object]:
        return {
            "host_id": "astrbot",
            "provider_key": "astrbot",
            "installed": True,
            "target_paths": {
                "global": str(self.skills_root),
                "workspace": str(self.workspace_skills_root),
            },
            "resolved_skill_roots": [str(self.skills_root)],
            "declared_skill_roots": [str(self.skills_root), str(self.workspace_skills_root)],
        }

    def test_build_astrbot_host_runtime_state_merges_local_sandbox_and_neo(self) -> None:
        self._write_skill("local-only", "local only")
        self._write_skill("synced", "synced skill")
        self._write_skill("neo-demo", "neo skill")

        (self.root / "data" / "skills.json").write_text(
            json.dumps(
                {
                    "skills": {
                        "local-only": {"active": False},
                        "synced": {"active": True},
                        "neo-demo": {"active": True},
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.root / "data" / "sandbox_skills_cache.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "updated_at": "2026-04-09T10:00:00+00:00",
                    "skills": [
                        {
                            "name": "synced",
                            "description": "synced cache",
                            "path": "/workspace/skills/synced/SKILL.md",
                        },
                        {
                            "name": "sandbox-only",
                            "description": "sandbox only",
                            "path": "/workspace/skills/sandbox-only/SKILL.md",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.skills_root / "neo_skill_map.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": {
                        "demo.skill": {
                            "local_skill_name": "neo-demo",
                            "latest_release_id": "rel-1",
                            "latest_candidate_id": "cand-1",
                            "latest_payload_ref": "blob:1",
                            "updated_at": "2026-04-09T10:05:00+00:00",
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        state = build_astrbot_host_runtime_state(self._build_host())

        self.assertEqual("astrbot", state["runtime_state_backend"])
        self.assertTrue(state["summary"]["skills_config_exists"])
        self.assertTrue(state["summary"]["sandbox_cache_exists"])
        self.assertTrue(state["summary"]["neo_map_exists"])
        self.assertEqual(3, state["summary"]["local_skill_total"])
        self.assertEqual(1, state["summary"]["local_only_total"])
        self.assertEqual(1, state["summary"]["synced_total"])
        self.assertEqual(1, state["summary"]["sandbox_only_total"])
        self.assertEqual(1, state["summary"]["neo_managed_total"])

        rows = {item["skill_name"]: item for item in state["state_rows"]}
        self.assertEqual("local_only", rows["local-only"]["state_classification"])
        self.assertFalse(rows["local-only"]["active"])
        self.assertEqual("synced", rows["synced"]["state_classification"])
        self.assertEqual("sandbox_only", rows["sandbox-only"]["state_classification"])
        self.assertEqual("neo_managed", rows["neo-demo"]["state_classification"])
        self.assertEqual("demo.skill", rows["neo-demo"]["neo_skill_key"])

        index = build_astrbot_state_index([self._build_host()])
        self.assertIn("astrbot", index["by_host"])
        self.assertEqual(4, len(index["rows"]))

    def test_build_astrbot_host_runtime_state_reports_missing_files_and_neo_drift(self) -> None:
        (self.skills_root / "neo_skill_map.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": {
                        "demo.skill": {
                            "local_skill_name": "missing-local",
                            "latest_release_id": "rel-1",
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        state = build_astrbot_host_runtime_state(self._build_host())

        self.assertFalse(state["summary"]["skills_config_exists"])
        self.assertFalse(state["summary"]["sandbox_cache_exists"])
        self.assertEqual(1, state["summary"]["drifted_total"])
        rows = {item["skill_name"]: item for item in state["state_rows"]}
        self.assertEqual("drifted", rows["missing-local"]["state_classification"])
        self.assertIn("neo_missing_local_skill", rows["missing-local"]["drift_reasons"])
        self.assertTrue(any("state drift for missing-local" in item for item in state["warnings"]))

    def test_resolve_astrbot_host_layout_returns_expected_paths(self) -> None:
        layout = resolve_astrbot_host_layout(self._build_host())

        self.assertTrue(layout["is_astrbot"])
        self.assertTrue(layout["state_available"])
        self.assertEqual(str(self.skills_root), layout["skills_root"])
        self.assertEqual(str(self.root / "data"), layout["astrbot_data_dir"])
        self.assertEqual(str(self.root / "data" / "skills.json"), layout["skills_config_path"])
        self.assertEqual(
            str(self.root / "data" / "sandbox_skills_cache.json"),
            layout["sandbox_cache_path"],
        )
        self.assertEqual(str(self.skills_root / "neo_skill_map.json"), layout["neo_map_path"])
        self.assertEqual(["global", "workspace"], layout["available_scopes"])
        self.assertEqual(str(self.workspace_skills_root), layout["scoped_layouts"]["workspace"]["skills_root"])
        self.assertEqual("session_alpha", layout["selected_workspace_id"])
        self.assertEqual(1, len(layout["workspace_profiles"]))
        self.assertEqual(
            str(self.workspace_root),
            layout["workspace_profiles"][0]["workspace_root"],
        )

    def test_resolve_astrbot_host_layout_does_not_treat_secondary_global_root_as_workspace(self) -> None:
        isolated_skills_root = Path(self._tempdir.name) / "isolated-astrbot" / "data" / "skills"
        isolated_skills_root.mkdir(parents=True, exist_ok=True)
        hidden_root = Path(self._tempdir.name) / ".astrbot" / "data" / "skills"
        host = {
            "host_id": "astrbot",
            "provider_key": "astrbot",
            "installed": True,
            "target_paths": {"global": "", "workspace": ""},
            "resolved_skill_roots": [str(isolated_skills_root)],
            "declared_skill_roots": [str(isolated_skills_root), str(hidden_root)],
        }

        layout = resolve_astrbot_host_layout(host)

        self.assertEqual(["global"], layout["available_scopes"])
        self.assertTrue(layout["scoped_layouts"]["global"]["state_available"])
        self.assertFalse(layout["scoped_layouts"]["workspace"]["state_available"])
        self.assertEqual(str(isolated_skills_root), layout["scoped_layouts"]["global"]["skills_root"])
        self.assertEqual("", layout["selected_workspace_id"])
        self.assertEqual([], layout["workspace_profiles"])

    def test_resolve_astrbot_host_layout_discovers_workspace_roots_from_data_workspaces(self) -> None:
        discovered_workspace_skills_root = self.root / "data" / "workspaces" / "session-alpha" / "skills"
        discovered_workspace_skills_root.mkdir(parents=True, exist_ok=True)
        host = {
            "host_id": "astrbot",
            "provider_key": "astrbot",
            "installed": True,
            "target_paths": {"global": str(self.skills_root), "workspace": ""},
            "resolved_skill_roots": [str(self.skills_root)],
            "declared_skill_roots": [str(self.skills_root)],
        }

        layout = resolve_astrbot_host_layout(host)

        self.assertEqual(["global", "workspace"], layout["available_scopes"])
        self.assertEqual(
            str(discovered_workspace_skills_root),
            layout["scoped_layouts"]["workspace"]["skills_root"],
        )
        self.assertEqual("", layout["selected_workspace_id"])
        self.assertEqual(1, len(layout["workspace_profiles"]))

    def test_build_astrbot_host_runtime_state_tracks_rows_per_scope(self) -> None:
        self._write_skill("global-demo", "global skill", scope="global")
        self._write_skill("workspace-demo", "workspace skill", scope="workspace")

        (self.root / "data" / "skills.json").write_text(
            json.dumps({"skills": {"global-demo": {"active": True}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.workspace_root / "skills.json").write_text(
            json.dumps({"skills": {"workspace-demo": {"active": False}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "data" / "sandbox_skills_cache.json").write_text(
            json.dumps({"version": 1, "skills": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.workspace_root / "sandbox_skills_cache.json").write_text(
            json.dumps({"version": 1, "skills": []}, ensure_ascii=False),
            encoding="utf-8",
        )

        state = build_astrbot_host_runtime_state(self._build_host())

        self.assertEqual(2, state["summary"]["local_skill_total"])
        self.assertEqual(2, state["summary"]["state_row_total"])
        self.assertEqual("session_alpha", state["summary"]["selected_workspace_id"])
        self.assertEqual(1, state["summary"]["scope_summaries"]["global"]["local_skill_total"])
        self.assertEqual(1, state["summary"]["scope_summaries"]["workspace"]["local_skill_total"])
        self.assertEqual(1, state["summary"]["workspace_summaries"]["session_alpha"]["local_skill_total"])

        rows = {(item["scope"], item["skill_name"]): item for item in state["state_rows"]}
        self.assertTrue(rows[("global", "global-demo")]["active"])
        self.assertFalse(rows[("workspace", "workspace-demo")]["active"])

    def test_build_astrbot_host_runtime_state_supports_multiple_workspace_profiles(self) -> None:
        workspace_beta_root = self.root / "data" / "workspaces" / "session-beta"
        workspace_beta_skills_root = workspace_beta_root / "skills"
        workspace_beta_skills_root.mkdir(parents=True, exist_ok=True)

        self._write_skill("workspace-alpha", "workspace alpha", scope="workspace")
        skill_dir_beta = workspace_beta_skills_root / "workspace-beta"
        skill_dir_beta.mkdir(parents=True, exist_ok=True)
        (skill_dir_beta / "SKILL.md").write_text("# workspace-beta\n", encoding="utf-8")

        (self.workspace_root / "skills.json").write_text(
            json.dumps({"skills": {"workspace-alpha": {"active": True}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (workspace_beta_root / "skills.json").write_text(
            json.dumps({"skills": {"workspace-beta": {"active": False}}}, ensure_ascii=False),
            encoding="utf-8",
        )

        host = self._build_host()
        host["declared_skill_roots"] = [
            str(self.skills_root),
            str(self.workspace_skills_root),
            str(workspace_beta_skills_root),
        ]

        state = build_astrbot_host_runtime_state(host)

        self.assertEqual(2, len(state["summary"]["workspace_summaries"]))
        self.assertEqual(1, state["summary"]["workspace_summaries"]["session_alpha"]["local_skill_total"])
        self.assertEqual(1, state["summary"]["workspace_summaries"]["session_beta"]["local_skill_total"])

        workspace_rows = [
            item for item in state["state_rows"]
            if item.get("scope") == "workspace"
        ]
        self.assertEqual(2, len(workspace_rows))
        self.assertEqual(
            {"session_alpha", "session_beta"},
            {str(item.get("workspace_id") or "") for item in workspace_rows},
        )


if __name__ == "__main__":
    unittest.main()
