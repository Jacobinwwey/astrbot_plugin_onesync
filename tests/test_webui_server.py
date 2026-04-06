from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_astrbot_stub() -> None:
    if "astrbot.api" in sys.modules:
        return
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")

    class _Logger:
        def warning(self, *args, **kwargs) -> None:
            return None

        def info(self, *args, **kwargs) -> None:
            return None

        def error(self, *args, **kwargs) -> None:
            return None

    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api


_install_astrbot_stub()

from webui_server import FASTAPI_AVAILABLE, OneSyncWebUIServer

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient
else:  # pragma: no cover
    TestClient = None


class _FakePlugin:
    def __init__(self) -> None:
        self.config = {"web_admin": {}}
        self.inventory_snapshot = {
            "ok": True,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "software_rows": [
                {
                    "id": "claude_code",
                    "display_name": "Claude Code",
                    "software_kind": "cli",
                    "provider_key": "claude_code",
                    "installed": True,
                    "managed": False,
                    "binding_count": 1,
                },
                {
                    "id": "antigravity",
                    "display_name": "Antigravity",
                    "software_kind": "gui",
                    "provider_key": "antigravity",
                    "installed": False,
                    "managed": False,
                    "binding_count": 0,
                },
            ],
            "skill_rows": [
                {
                    "id": "skill_cli",
                    "display_name": "CLI Skill",
                    "discovered": True,
                    "source_path": "/tmp/skill_cli",
                },
            ],
            "binding_rows": [
                {
                    "software_id": "claude_code",
                    "skill_id": "skill_cli",
                    "scope": "global",
                    "enabled": True,
                    "valid": True,
                    "reason": "",
                },
            ],
            "binding_map": {"claude_code": ["skill_cli"], "antigravity": []},
            "binding_map_by_scope": {
                "global": {"claude_code": ["skill_cli"], "antigravity": []},
                "workspace": {"claude_code": [], "antigravity": []},
            },
            "compatibility": {"claude_code": ["skill_cli"], "antigravity": []},
            "counts": {
                "software_total": 2,
                "software_installed": 1,
                "software_managed": 0,
                "skills_total": 1,
                "skills_discovered": 1,
                "bindings_total": 1,
                "bindings_valid": 1,
                "bindings_invalid": 0,
            },
            "warnings": [],
        }
        self.skills_snapshot = {
            "ok": True,
            "generated_at": "2026-04-06T08:00:00+00:00",
            "source_rows": [
                {
                    "source_id": "skill_cli",
                    "display_name": "CLI Skill",
                    "source_kind": "skill",
                    "status": "ready",
                    "member_count": 1,
                    "deployed_target_count": 1,
                },
            ],
            "deploy_rows": [
                {
                    "target_id": "claude_code:global",
                    "software_id": "claude_code",
                    "software_display_name": "Claude Code",
                    "scope": "global",
                    "status": "ready",
                    "drift_status": "ok",
                    "selected_source_ids": ["skill_cli"],
                    "available_source_ids": ["skill_cli"],
                    "ready_source_ids": ["skill_cli"],
                    "missing_source_ids": [],
                    "incompatible_source_ids": [],
                    "repair_actions": [],
                },
            ],
            "software_hosts": [
                {
                    "id": "claude_code",
                    "display_name": "Claude Code",
                },
            ],
            "doctor": {"ok": True, "warning_count": 0, "warnings": []},
            "counts": {
                "source_total": 1,
                "deploy_target_total": 1,
                "deploy_ready_total": 1,
            },
            "warnings": [],
        }

    def webui_get_inventory_payload(self) -> dict:
        return self.inventory_snapshot

    def webui_get_skills_payload(self) -> dict:
        return self.skills_snapshot

    def webui_get_skill_sources_payload(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": self.skills_snapshot["counts"],
            "items": self.skills_snapshot["source_rows"],
            "warnings": [],
        }

    def webui_get_skill_source_payload(self, source_id: str) -> dict:
        if source_id != "skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "source": self.skills_snapshot["source_rows"][0],
            "deploy_rows": self.skills_snapshot["deploy_rows"],
            "warnings": [],
        }

    async def webui_scan_inventory(self) -> dict:
        return self.inventory_snapshot

    async def webui_import_skills(self, payload: dict) -> dict:
        return {"ok": True, "skills": self.skills_snapshot, "inventory": self.inventory_snapshot}

    def webui_sync_skill_source(self, source_id: str) -> dict:
        return self.webui_get_skill_source_payload(source_id)

    def webui_sync_all_skill_sources(self) -> dict:
        return {
            "ok": True,
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
            "synced_source_ids": ["skill_cli"],
            "failed_sources": [],
        }

    def webui_deploy_skill_source(self, source_id: str, payload: dict) -> dict:
        if source_id != "skill_cli":
            return {"ok": False, "message": "not found"}
        if not payload.get("software_ids"):
            return {"ok": False, "message": "software_ids or target_ids is required"}
        return {"ok": True, "skills": self.skills_snapshot, "inventory": self.inventory_snapshot}

    def webui_update_deploy_target(self, target_id: str, payload: dict) -> dict:
        if target_id != "claude_code:global":
            return {"ok": False, "message": "target not found"}
        if not isinstance(payload.get("selected_source_ids"), list):
            return {"ok": False, "message": "selected_source_ids is required"}
        return {"ok": True, "skills": self.skills_snapshot, "inventory": self.inventory_snapshot}

    def webui_get_deploy_target_payload(self, target_id: str) -> dict:
        if target_id != "claude_code:global":
            return {"ok": False, "message": "target not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "deploy_target": self.skills_snapshot["deploy_rows"][0],
            "warnings": [],
        }

    def webui_repair_deploy_target(self, target_id: str, payload: dict) -> dict:
        if target_id != "claude_code:global":
            return {"ok": False, "message": "target not found"}
        return {
            "ok": True,
            "changes": ["drop_missing_sources"],
            "deploy_target": self.skills_snapshot["deploy_rows"][0],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_doctor_skills(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "doctor": self.skills_snapshot["doctor"],
            "warnings": [],
            "counts": self.skills_snapshot["counts"],
        }

    def webui_update_inventory_bindings(self, payload: dict) -> dict:
        if str(payload.get("software_id", "")) == "bad":
            return {"ok": False, "message": "software_id not found"}
        return {"ok": True, "inventory": self.inventory_snapshot, "skills": self.skills_snapshot}

    def webui_get_overview_payload(self) -> dict:
        return {"ok": True, "rows": [], "counts": {}, "latest_job": None}

    def webui_get_config_payload(self) -> dict:
        return {"ok": True, "config": {}, "meta": {}}

    def webui_update_config(self, payload: dict) -> dict:
        return {"ok": True, "config": payload}

    def webui_get_latest_job(self):
        return None

    def webui_get_job(self, job_id: str):
        return None

    def webui_get_debug_logs(self, **kwargs) -> dict:
        return {"ok": True, "items": [], "last_id": 0}

    def webui_clear_debug_logs(self) -> dict:
        return {"ok": True}

    async def webui_start_run(self, scope: str, targets):
        return {"ok": True, "scope": scope, "targets": targets}


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is unavailable in this environment")
class WebUIServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = _FakePlugin()
        self.server = OneSyncWebUIServer(self.plugin)
        self.client = TestClient(self.server.app)

    def test_inventory_detail_routes_return_expected_payloads(self) -> None:
        software_resp = self.client.get("/api/inventory/software")
        self.assertEqual(200, software_resp.status_code)
        software_data = software_resp.json()
        self.assertEqual(2, len(software_data["items"]))
        self.assertEqual("claude_code", software_data["items"][0]["id"])

        skills_resp = self.client.get("/api/inventory/skills")
        self.assertEqual(200, skills_resp.status_code)
        skills_data = skills_resp.json()
        self.assertEqual(1, len(skills_data["items"]))
        self.assertEqual("skill_cli", skills_data["items"][0]["id"])

        bindings_resp = self.client.get("/api/inventory/bindings")
        self.assertEqual(200, bindings_resp.status_code)
        bindings_data = bindings_resp.json()
        self.assertEqual(1, len(bindings_data["items"]))
        self.assertIn("skill_cli", bindings_data["binding_map"]["claude_code"])
        self.assertIn(
            "skill_cli",
            bindings_data["binding_map_by_scope"]["global"]["claude_code"],
        )

    def test_inventory_scan_and_save_binding_routes(self) -> None:
        scan_resp = self.client.post("/api/inventory/scan", json={})
        self.assertEqual(200, scan_resp.status_code)
        self.assertTrue(scan_resp.json()["ok"])

        save_resp = self.client.post(
            "/api/inventory/bindings",
            json={"software_id": "claude_code", "skill_ids": ["skill_cli"], "scope": "workspace"},
        )
        self.assertEqual(200, save_resp.status_code)
        self.assertTrue(save_resp.json()["ok"])

    def test_inventory_bindings_route_returns_400_on_plugin_error(self) -> None:
        resp = self.client.post(
            "/api/inventory/bindings",
            json={"software_id": "bad", "skill_ids": ["skill_cli"], "scope": "global"},
        )
        self.assertEqual(400, resp.status_code)
        self.assertFalse(resp.json()["ok"])

    def test_skills_routes_return_expected_payloads(self) -> None:
        overview_resp = self.client.get("/api/skills/overview")
        self.assertEqual(200, overview_resp.status_code)
        self.assertEqual(1, overview_resp.json()["counts"]["source_total"])

        sources_resp = self.client.get("/api/skills/sources")
        self.assertEqual(200, sources_resp.status_code)
        self.assertEqual("skill_cli", sources_resp.json()["items"][0]["source_id"])

        detail_resp = self.client.get("/api/skills/sources/skill_cli")
        self.assertEqual(200, detail_resp.status_code)
        self.assertEqual("skill_cli", detail_resp.json()["source"]["source_id"])

        target_detail_resp = self.client.get("/api/skills/deploy-targets/claude_code:global")
        self.assertEqual(200, target_detail_resp.status_code)
        self.assertEqual("claude_code:global", target_detail_resp.json()["deploy_target"]["target_id"])

        missing_target_detail_resp = self.client.get("/api/skills/deploy-targets/missing:global")
        self.assertEqual(404, missing_target_detail_resp.status_code)
        self.assertFalse(missing_target_detail_resp.json()["ok"])

    def test_skills_mutation_routes_return_expected_statuses(self) -> None:
        import_resp = self.client.post("/api/skills/import", json={})
        self.assertEqual(200, import_resp.status_code)
        self.assertTrue(import_resp.json()["ok"])

        sync_resp = self.client.post("/api/skills/sources/skill_cli/sync", json={})
        self.assertEqual(200, sync_resp.status_code)
        self.assertTrue(sync_resp.json()["ok"])

        sync_all_resp = self.client.post("/api/skills/sources/sync-all", json={})
        self.assertEqual(200, sync_all_resp.status_code)
        self.assertTrue(sync_all_resp.json()["ok"])
        self.assertEqual(["skill_cli"], sync_all_resp.json()["synced_source_ids"])

        deploy_resp = self.client.post(
            "/api/skills/sources/skill_cli/deploy",
            json={"software_ids": ["claude_code"], "scope": "global"},
        )
        self.assertEqual(200, deploy_resp.status_code)
        self.assertTrue(deploy_resp.json()["ok"])

        bad_deploy_resp = self.client.post(
            "/api/skills/sources/skill_cli/deploy",
            json={},
        )
        self.assertEqual(400, bad_deploy_resp.status_code)
        self.assertFalse(bad_deploy_resp.json()["ok"])

        doctor_resp = self.client.post("/api/skills/doctor", json={})
        self.assertEqual(200, doctor_resp.status_code)
        self.assertTrue(doctor_resp.json()["ok"])

        target_resp = self.client.post(
            "/api/skills/deploy-targets/claude_code:global",
            json={"selected_source_ids": ["skill_cli"]},
        )
        self.assertEqual(200, target_resp.status_code)
        self.assertTrue(target_resp.json()["ok"])

        repair_resp = self.client.post(
            "/api/skills/deploy-targets/claude_code:global/repair",
            json={},
        )
        self.assertEqual(200, repair_resp.status_code)
        self.assertTrue(repair_resp.json()["ok"])
        self.assertEqual(["drop_missing_sources"], repair_resp.json()["changes"])

        bad_target_resp = self.client.post(
            "/api/skills/deploy-targets/missing:global",
            json={"selected_source_ids": ["skill_cli"]},
        )
        self.assertEqual(400, bad_target_resp.status_code)
        self.assertFalse(bad_target_resp.json()["ok"])

        bad_repair_resp = self.client.post(
            "/api/skills/deploy-targets/missing:global/repair",
            json={},
        )
        self.assertEqual(400, bad_repair_resp.status_code)
        self.assertFalse(bad_repair_resp.json()["ok"])


if __name__ == "__main__":
    unittest.main()
