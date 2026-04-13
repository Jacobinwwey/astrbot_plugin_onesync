from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_hosts_core import (
    ASTRBOT_HOST_CAPABILITIES,
    DEFAULT_SOFTWARE_CATALOG,
    build_host_adapters,
    resolve_host_target_path,
)


class SkillsHostsCoreTests(unittest.TestCase):
    def test_default_software_catalog_keeps_skill_capable_hosts(self) -> None:
        ids = {item["id"] for item in DEFAULT_SOFTWARE_CATALOG}
        self.assertIn("claude_code", ids)
        self.assertIn("codex", ids)
        self.assertIn("zeroclaw", ids)
        self.assertIn("astrbot", ids)
        self.assertIn("antigravity", ids)
        self.assertIn("windsurf", ids)

    def test_default_software_catalog_declares_astrbot_as_claw_host(self) -> None:
        astrbot = next(item for item in DEFAULT_SOFTWARE_CATALOG if item["id"] == "astrbot")

        self.assertEqual("astrbot", astrbot["provider_key"])
        self.assertTrue(astrbot["enabled"])

    def test_build_host_adapters_projects_target_paths_and_supported_source_kinds(self) -> None:
        software_rows = [
            {
                "id": "codex",
                "display_name": "Codex",
                "software_kind": "cli",
                "software_family": "codex",
                "provider_key": "codex",
                "installed": True,
                "managed": False,
                "linked_target_name": "",
                "declared_skill_roots": ["/root/.codex/skills", "/workspace/.codex/skills"],
                "resolved_skill_roots": ["/root/.codex/skills", "/workspace/.codex/skills"],
            },
            {
                "id": "antigravity",
                "display_name": "Antigravity",
                "software_kind": "gui",
                "software_family": "antigravity",
                "provider_key": "antigravity",
                "installed": False,
                "managed": False,
                "linked_target_name": "",
                "declared_skill_roots": ["/root/antigravity/skills"],
                "resolved_skill_roots": [],
            },
        ]

        adapters = build_host_adapters(software_rows)
        self.assertEqual(2, len(adapters))

        codex = next(item for item in adapters if item["host_id"] == "codex")
        self.assertEqual("cli", codex["kind"])
        self.assertEqual(["npx_bundle", "npx_single", "manual_local", "manual_git"], codex["supports_source_kinds"])
        self.assertEqual("/root/.codex/skills", resolve_host_target_path(codex, "global"))
        self.assertEqual("/workspace/.codex/skills", resolve_host_target_path(codex, "workspace"))

        antigravity = next(item for item in adapters if item["host_id"] == "antigravity")
        self.assertEqual("gui", antigravity["kind"])
        self.assertFalse(antigravity["installed"])
        self.assertEqual("/root/antigravity/skills", resolve_host_target_path(antigravity, "global"))

    def test_build_host_adapters_exposes_astrbot_capabilities(self) -> None:
        software_rows = [
            {
                "id": "astrbot",
                "display_name": "AstrBot",
                "software_kind": "claw",
                "software_family": "astrbot",
                "provider_key": "astrbot",
                "installed": True,
                "managed": False,
                "linked_target_name": "",
                "declared_skill_roots": ["/srv/astrbot/data/skills"],
                "resolved_skill_roots": ["/srv/astrbot/data/skills"],
            }
        ]

        adapter = build_host_adapters(software_rows)[0]
        self.assertEqual("astrbot", adapter["runtime_state_backend"])
        self.assertEqual(ASTRBOT_HOST_CAPABILITIES, adapter["capabilities"])

    def test_resolve_host_target_path_prefers_runtime_data_root_for_astrbot_global(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            astrbot_root = Path(tempdir) / "astrbot"
            global_skills_root = astrbot_root / "data" / "skills"
            fallback_global_skills_root = Path(tempdir) / ".astrbot" / "data" / "skills"
            global_skills_root.mkdir(parents=True, exist_ok=True)
            fallback_global_skills_root.mkdir(parents=True, exist_ok=True)

            host = {
                "id": "astrbot",
                "host_id": "astrbot",
                "provider_key": "astrbot",
                "declared_skill_roots": [
                    str(global_skills_root),
                    str(fallback_global_skills_root),
                ],
                "resolved_skill_roots": [
                    str(global_skills_root),
                ],
            }

            self.assertEqual(str(global_skills_root), resolve_host_target_path(host, "global"))
            self.assertEqual("", resolve_host_target_path(host, "workspace"))

    def test_resolve_host_target_path_discovers_workspace_skills_under_astrbot_data_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            astrbot_root = Path(tempdir) / "astrbot"
            global_skills_root = astrbot_root / "data" / "skills"
            workspace_skills_root = astrbot_root / "data" / "workspaces" / "session_alpha" / "skills"
            global_skills_root.mkdir(parents=True, exist_ok=True)
            workspace_skills_root.mkdir(parents=True, exist_ok=True)

            host = {
                "id": "astrbot",
                "host_id": "astrbot",
                "provider_key": "astrbot",
                "declared_skill_roots": [str(global_skills_root)],
                "resolved_skill_roots": [str(global_skills_root)],
            }

            self.assertEqual(str(global_skills_root), resolve_host_target_path(host, "global"))
            self.assertEqual(str(workspace_skills_root), resolve_host_target_path(host, "workspace"))


if __name__ == "__main__":
    unittest.main()
