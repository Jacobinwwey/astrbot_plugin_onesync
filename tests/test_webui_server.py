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
            "registry": {
                "version": 1,
                "generated_at": "2026-04-06T08:00:00+00:00",
                "sources": [
                    {
                        "source_id": "skill_cli",
                        "display_name": "CLI Skill",
                        "source_kind": "manual_local",
                        "locator": "/tmp/skill_cli",
                        "source_scope": "global",
                        "last_refresh_at": "2026-04-06T08:00:00+00:00",
                    },
                ],
            },
            "source_rows": [
                {
                    "source_id": "skill_cli",
                    "display_name": "CLI Skill",
                    "source_kind": "skill",
                    "install_unit_id": "install:skill_cli",
                    "collection_group_id": "collection:cli_tools",
                    "install_ref": "@every-env/compound-plugin",
                    "install_manager": "bunx",
                    "management_hint": "bunx @every-env/compound-plugin",
                    "update_policy": "registry",
                    "source_path": "/tmp/skill_cli",
                    "status": "ready",
                    "member_count": 1,
                    "deployed_target_count": 1,
                },
            ],
            "install_unit_rows": [
                {
                    "install_unit_id": "install:skill_cli",
                    "display_name": "CLI Tool Pack",
                    "source_ids": ["skill_cli"],
                    "source_count": 1,
                    "member_count": 1,
                    "collection_group_id": "collection:cli_tools",
                    "install_ref": "@every-env/compound-plugin",
                    "install_manager": "bunx",
                    "management_hint": "bunx @every-env/compound-plugin",
                    "update_policy": "registry",
                },
            ],
            "collection_group_rows": [
                {
                    "collection_group_id": "collection:cli_tools",
                    "display_name": "CLI Tools",
                    "install_unit_ids": ["install:skill_cli"],
                    "install_unit_count": 1,
                    "source_ids": ["skill_cli"],
                    "source_count": 1,
                    "member_count": 1,
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
            "host_rows": [
                {
                    "host_id": "claude_code",
                    "display_name": "Claude Code",
                    "kind": "cli",
                    "supports_source_kinds": ["npx_bundle", "npx_single", "manual_local", "manual_git"],
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

    def webui_get_install_unit_payload(self, install_unit_id: str) -> dict:
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "source_rows": self.skills_snapshot["source_rows"],
            "deploy_rows": self.skills_snapshot["deploy_rows"],
            "update_plan": {
                "install_unit_id": "install:skill_cli",
                "display_name": "CLI Tool Pack",
                "manager": "bunx",
                "policy": "registry",
                "install_ref": "@every-env/compound-plugin",
                "management_hint": "bunx @every-env/compound-plugin",
                "source_paths": ["/tmp/skill_cli"],
                "commands": ["bunx @every-env/compound-plugin"],
                "command_count": 1,
                "supported": True,
                "message": "registry update is available for CLI Tool Pack",
            },
            "warnings": [],
        }

    def webui_get_collection_group_payload(self, collection_group_id: str) -> dict:
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "source_rows": self.skills_snapshot["source_rows"],
            "deploy_rows": self.skills_snapshot["deploy_rows"],
            "update_plan": {
                "collection_group_id": "collection:cli_tools",
                "display_name": "CLI Tools",
                "supported": True,
                "manager": "bunx",
                "policy": "registry",
                "commands": ["bunx @every-env/compound-plugin"],
                "command_count": 1,
                "supported_install_unit_total": 1,
                "unsupported_install_unit_total": 0,
                "unsupported_install_units": [],
                "install_unit_plans": [
                    {
                        "install_unit_id": "install:skill_cli",
                        "display_name": "CLI Tool Pack",
                        "manager": "bunx",
                        "policy": "registry",
                        "install_ref": "@every-env/compound-plugin",
                        "management_hint": "bunx @every-env/compound-plugin",
                        "source_paths": ["/tmp/skill_cli"],
                        "commands": ["bunx @every-env/compound-plugin"],
                        "command_count": 1,
                        "supported": True,
                        "message": "registry update is available for CLI Tool Pack",
                    },
                ],
                "message": "collection group update prepared for 1 install units",
            },
            "warnings": [],
        }

    def webui_refresh_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        _ = payload
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "source_rows": self.skills_snapshot["source_rows"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_sync_install_unit(self, install_unit_id: str) -> dict:
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "source_rows": self.skills_snapshot["source_rows"],
            "synced_source_ids": ["skill_cli"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_update_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        _ = payload
        if install_unit_id == "unsupported":
            return {"ok": False, "message": "update unsupported for aggregate"}
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "source_rows": self.skills_snapshot["source_rows"],
            "update": {
                "supported": True,
                "policy": "registry",
                "manager": "bunx",
                "commands": ["bunx @every-env/compound-plugin"],
                "message": "updated",
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_deploy_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        if not payload.get("software_ids") and not payload.get("target_ids"):
            return {"ok": False, "message": "software_ids or target_ids is required"}
        return {
            "ok": True,
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "target_ids": ["claude_code:global"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_refresh_collection_group(self, collection_group_id: str, payload: dict) -> dict:
        _ = payload
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "source_rows": self.skills_snapshot["source_rows"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_sync_collection_group(self, collection_group_id: str) -> dict:
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "source_rows": self.skills_snapshot["source_rows"],
            "synced_source_ids": ["skill_cli"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_update_collection_group(self, collection_group_id: str, payload: dict) -> dict:
        _ = payload
        if collection_group_id == "unsupported":
            return {"ok": False, "message": "update unsupported for aggregate"}
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "source_rows": self.skills_snapshot["source_rows"],
            "update": {
                "supported": True,
                "policy": "registry",
                "manager": "bunx",
                "commands": ["bunx @every-env/compound-plugin"],
                "message": "updated",
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_deploy_collection_group(self, collection_group_id: str, payload: dict) -> dict:
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        if not payload.get("software_ids") and not payload.get("target_ids"):
            return {"ok": False, "message": "software_ids or target_ids is required"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "target_ids": ["claude_code:global"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_repair_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        _ = payload
        if install_unit_id != "install:skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": self.skills_snapshot["install_unit_rows"][0],
            "repaired_target_ids": ["claude_code:global"],
            "remaining_repairable_total": 0,
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_repair_collection_group(self, collection_group_id: str, payload: dict) -> dict:
        _ = payload
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "repaired_target_ids": ["claude_code:global"],
            "remaining_repairable_total": 0,
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_get_skills_registry_payload(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {"registry_total": 1},
            "items": self.skills_snapshot["registry"]["sources"],
            "warnings": [],
        }

    def webui_get_skills_hosts_payload(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {"host_total": 1},
            "items": self.skills_snapshot["host_rows"],
            "warnings": [],
        }

    async def webui_scan_inventory(self) -> dict:
        return self.inventory_snapshot

    async def webui_import_skills(self, payload: dict) -> dict:
        return {"ok": True, "skills": self.skills_snapshot, "inventory": self.inventory_snapshot}

    def webui_sync_skill_source(self, source_id: str) -> dict:
        return self.webui_get_skill_source_payload(source_id)

    def webui_register_skill_source(self, payload: dict) -> dict:
        if not str(payload.get("locator", "")).strip():
            return {"ok": False, "message": "locator is required"}
        return {
            "ok": True,
            "source": {
                "source_id": "manual_local_demo",
                "display_name": "Manual Local Demo",
                "source_kind": "manual_local",
                "locator": str(payload.get("locator")),
            },
            "registry": self.skills_snapshot["registry"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_refresh_skill_registry_source(self, source_id: str, payload: dict) -> dict:
        _ = payload
        if source_id != "skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "source": self.skills_snapshot["registry"]["sources"][0],
            "registry": self.skills_snapshot["registry"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_remove_skill_source(self, source_id: str, payload: dict) -> dict:
        _ = payload
        if source_id != "skill_cli":
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "removed_source_id": source_id,
            "registry": {"version": 1, "generated_at": self.skills_snapshot["generated_at"], "sources": []},
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

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
            "generated_projection": {
                "path": "/tmp/generated/claude_code_global.json",
                "exists": True,
                "payload": {
                    "target_id": "claude_code:global",
                    "selected_source_ids": ["skill_cli"],
                    "status": "ready",
                    "drift_status": "ok",
                },
                "diff": {
                    "ok": True,
                    "missing_file": False,
                    "field_diff_total": 0,
                    "changed_fields": [],
                    "fields": {},
                },
            },
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

    def webui_repair_all_deploy_targets(self, payload: dict) -> dict:
        _ = payload
        return {
            "ok": True,
            "repaired_target_ids": ["claude_code:global"],
            "repairable_target_ids": ["claude_code:global"],
            "results": [
                {
                    "target_id": "claude_code:global",
                    "changes": ["drop_missing_sources"],
                    "requested_actions": ["drop_missing_sources"],
                },
            ],
            "failed_targets": [],
            "remaining_repairable_total": 0,
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_reproject_deploy_target(self, target_id: str, payload: dict) -> dict:
        _ = payload
        if target_id != "claude_code:global":
            return {"ok": False, "message": "target not found"}
        return {
            "ok": True,
            "deploy_target": self.skills_snapshot["deploy_rows"][0],
            "generated_projection": {
                "path": "/tmp/generated/claude_code_global.json",
                "exists": True,
                "payload": {"target_id": "claude_code:global"},
                "diff": {"ok": True, "missing_file": False, "field_diff_total": 0, "changed_fields": [], "fields": {}},
            },
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

        registry_resp = self.client.get("/api/skills/registry")
        self.assertEqual(200, registry_resp.status_code)
        self.assertEqual("skill_cli", registry_resp.json()["items"][0]["source_id"])

        hosts_resp = self.client.get("/api/skills/hosts")
        self.assertEqual(200, hosts_resp.status_code)
        self.assertEqual("claude_code", hosts_resp.json()["items"][0]["host_id"])

        sources_resp = self.client.get("/api/skills/sources")
        self.assertEqual(200, sources_resp.status_code)
        self.assertEqual("skill_cli", sources_resp.json()["items"][0]["source_id"])

        detail_resp = self.client.get("/api/skills/sources/skill_cli")
        self.assertEqual(200, detail_resp.status_code)
        self.assertEqual("skill_cli", detail_resp.json()["source"]["source_id"])

        install_unit_detail_resp = self.client.get("/api/skills/install-units/install%3Askill_cli")
        self.assertEqual(200, install_unit_detail_resp.status_code)
        self.assertEqual("install:skill_cli", install_unit_detail_resp.json()["install_unit"]["install_unit_id"])
        self.assertIn("update_plan", install_unit_detail_resp.json())
        self.assertTrue(install_unit_detail_resp.json()["update_plan"]["supported"])

        collection_detail_resp = self.client.get("/api/skills/collections/collection%3Acli_tools")
        self.assertEqual(200, collection_detail_resp.status_code)
        self.assertEqual("collection:cli_tools", collection_detail_resp.json()["collection_group"]["collection_group_id"])
        self.assertIn("update_plan", collection_detail_resp.json())
        self.assertTrue(collection_detail_resp.json()["update_plan"]["supported"])

        target_detail_resp = self.client.get("/api/skills/deploy-targets/claude_code:global")
        self.assertEqual(200, target_detail_resp.status_code)
        self.assertEqual("claude_code:global", target_detail_resp.json()["deploy_target"]["target_id"])
        self.assertTrue(target_detail_resp.json()["generated_projection"]["exists"])

        missing_install_unit_detail_resp = self.client.get("/api/skills/install-units/missing")
        self.assertEqual(404, missing_install_unit_detail_resp.status_code)
        self.assertFalse(missing_install_unit_detail_resp.json()["ok"])

        missing_collection_detail_resp = self.client.get("/api/skills/collections/missing")
        self.assertEqual(404, missing_collection_detail_resp.status_code)
        self.assertFalse(missing_collection_detail_resp.json()["ok"])

        missing_target_detail_resp = self.client.get("/api/skills/deploy-targets/missing:global")
        self.assertEqual(404, missing_target_detail_resp.status_code)
        self.assertFalse(missing_target_detail_resp.json()["ok"])

    def test_skills_mutation_routes_return_expected_statuses(self) -> None:
        import_resp = self.client.post("/api/skills/import", json={})
        self.assertEqual(200, import_resp.status_code)
        self.assertTrue(import_resp.json()["ok"])

        register_resp = self.client.post(
            "/api/skills/sources/register",
            json={"source_kind": "manual_local", "locator": "/tmp/demo-skills"},
        )
        self.assertEqual(200, register_resp.status_code)
        self.assertTrue(register_resp.json()["ok"])
        self.assertEqual("manual_local_demo", register_resp.json()["source"]["source_id"])

        bad_register_resp = self.client.post(
            "/api/skills/sources/register",
            json={"source_kind": "manual_local"},
        )
        self.assertEqual(400, bad_register_resp.status_code)
        self.assertFalse(bad_register_resp.json()["ok"])

        sync_resp = self.client.post("/api/skills/sources/skill_cli/sync", json={})
        self.assertEqual(200, sync_resp.status_code)
        self.assertTrue(sync_resp.json()["ok"])

        unit_refresh_resp = self.client.post("/api/skills/install-units/install%3Askill_cli/refresh", json={})
        self.assertEqual(200, unit_refresh_resp.status_code)
        self.assertTrue(unit_refresh_resp.json()["ok"])
        self.assertEqual("install:skill_cli", unit_refresh_resp.json()["install_unit"]["install_unit_id"])

        unit_sync_resp = self.client.post("/api/skills/install-units/install%3Askill_cli/sync", json={})
        self.assertEqual(200, unit_sync_resp.status_code)
        self.assertTrue(unit_sync_resp.json()["ok"])
        self.assertEqual(["skill_cli"], unit_sync_resp.json()["synced_source_ids"])

        unit_update_resp = self.client.post("/api/skills/install-units/install%3Askill_cli/update", json={})
        self.assertEqual(200, unit_update_resp.status_code)
        self.assertTrue(unit_update_resp.json()["ok"])
        self.assertEqual("bunx", unit_update_resp.json()["update"]["manager"])

        group_refresh_resp = self.client.post("/api/skills/collections/collection%3Acli_tools/refresh", json={})
        self.assertEqual(200, group_refresh_resp.status_code)
        self.assertTrue(group_refresh_resp.json()["ok"])
        self.assertEqual("collection:cli_tools", group_refresh_resp.json()["collection_group"]["collection_group_id"])

        group_sync_resp = self.client.post("/api/skills/collections/collection%3Acli_tools/sync", json={})
        self.assertEqual(200, group_sync_resp.status_code)
        self.assertTrue(group_sync_resp.json()["ok"])
        self.assertEqual(["skill_cli"], group_sync_resp.json()["synced_source_ids"])

        group_update_resp = self.client.post("/api/skills/collections/collection%3Acli_tools/update", json={})
        self.assertEqual(200, group_update_resp.status_code)
        self.assertTrue(group_update_resp.json()["ok"])
        self.assertEqual("bunx", group_update_resp.json()["update"]["manager"])

        unit_deploy_resp = self.client.post(
            "/api/skills/install-units/install%3Askill_cli/deploy",
            json={"software_ids": ["claude_code"], "scope": "global"},
        )
        self.assertEqual(200, unit_deploy_resp.status_code)
        self.assertTrue(unit_deploy_resp.json()["ok"])
        self.assertEqual(["claude_code:global"], unit_deploy_resp.json()["target_ids"])

        group_deploy_resp = self.client.post(
            "/api/skills/collections/collection%3Acli_tools/deploy",
            json={"software_ids": ["claude_code"], "scope": "global"},
        )
        self.assertEqual(200, group_deploy_resp.status_code)
        self.assertTrue(group_deploy_resp.json()["ok"])
        self.assertEqual(["claude_code:global"], group_deploy_resp.json()["target_ids"])

        unit_repair_resp = self.client.post("/api/skills/install-units/install%3Askill_cli/repair", json={})
        self.assertEqual(200, unit_repair_resp.status_code)
        self.assertTrue(unit_repair_resp.json()["ok"])
        self.assertEqual(["claude_code:global"], unit_repair_resp.json()["repaired_target_ids"])

        group_repair_resp = self.client.post("/api/skills/collections/collection%3Acli_tools/repair", json={})
        self.assertEqual(200, group_repair_resp.status_code)
        self.assertTrue(group_repair_resp.json()["ok"])
        self.assertEqual(["claude_code:global"], group_repair_resp.json()["repaired_target_ids"])

        missing_unit_refresh_resp = self.client.post("/api/skills/install-units/missing/refresh", json={})
        self.assertEqual(404, missing_unit_refresh_resp.status_code)
        self.assertFalse(missing_unit_refresh_resp.json()["ok"])

        missing_unit_sync_resp = self.client.post("/api/skills/install-units/missing/sync", json={})
        self.assertEqual(404, missing_unit_sync_resp.status_code)
        self.assertFalse(missing_unit_sync_resp.json()["ok"])

        missing_unit_update_resp = self.client.post("/api/skills/install-units/missing/update", json={})
        self.assertEqual(404, missing_unit_update_resp.status_code)
        self.assertFalse(missing_unit_update_resp.json()["ok"])

        missing_group_refresh_resp = self.client.post("/api/skills/collections/missing/refresh", json={})
        self.assertEqual(404, missing_group_refresh_resp.status_code)
        self.assertFalse(missing_group_refresh_resp.json()["ok"])

        missing_group_sync_resp = self.client.post("/api/skills/collections/missing/sync", json={})
        self.assertEqual(404, missing_group_sync_resp.status_code)
        self.assertFalse(missing_group_sync_resp.json()["ok"])

        missing_group_update_resp = self.client.post("/api/skills/collections/missing/update", json={})
        self.assertEqual(404, missing_group_update_resp.status_code)
        self.assertFalse(missing_group_update_resp.json()["ok"])

        missing_unit_repair_resp = self.client.post("/api/skills/install-units/missing/repair", json={})
        self.assertEqual(404, missing_unit_repair_resp.status_code)
        self.assertFalse(missing_unit_repair_resp.json()["ok"])

        missing_group_repair_resp = self.client.post("/api/skills/collections/missing/repair", json={})
        self.assertEqual(404, missing_group_repair_resp.status_code)
        self.assertFalse(missing_group_repair_resp.json()["ok"])

        bad_unit_update_resp = self.client.post("/api/skills/install-units/unsupported/update", json={})
        self.assertEqual(400, bad_unit_update_resp.status_code)
        self.assertFalse(bad_unit_update_resp.json()["ok"])

        bad_group_update_resp = self.client.post("/api/skills/collections/unsupported/update", json={})
        self.assertEqual(400, bad_group_update_resp.status_code)
        self.assertFalse(bad_group_update_resp.json()["ok"])

        bad_unit_deploy_resp = self.client.post(
            "/api/skills/install-units/install%3Askill_cli/deploy",
            json={},
        )
        self.assertEqual(400, bad_unit_deploy_resp.status_code)
        self.assertFalse(bad_unit_deploy_resp.json()["ok"])

        bad_group_deploy_resp = self.client.post(
            "/api/skills/collections/collection%3Acli_tools/deploy",
            json={},
        )
        self.assertEqual(400, bad_group_deploy_resp.status_code)
        self.assertFalse(bad_group_deploy_resp.json()["ok"])

        refresh_resp = self.client.post("/api/skills/sources/skill_cli/refresh", json={})
        self.assertEqual(200, refresh_resp.status_code)
        self.assertTrue(refresh_resp.json()["ok"])

        bad_refresh_resp = self.client.post("/api/skills/sources/missing/refresh", json={})
        self.assertEqual(404, bad_refresh_resp.status_code)
        self.assertFalse(bad_refresh_resp.json()["ok"])

        remove_resp = self.client.post("/api/skills/sources/skill_cli/remove", json={})
        self.assertEqual(200, remove_resp.status_code)
        self.assertTrue(remove_resp.json()["ok"])
        self.assertEqual("skill_cli", remove_resp.json()["removed_source_id"])

        bad_remove_resp = self.client.post("/api/skills/sources/missing/remove", json={})
        self.assertEqual(404, bad_remove_resp.status_code)
        self.assertFalse(bad_remove_resp.json()["ok"])

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

        reproject_resp = self.client.post(
            "/api/skills/deploy-targets/claude_code:global/reproject",
            json={},
        )
        self.assertEqual(200, reproject_resp.status_code)
        self.assertTrue(reproject_resp.json()["ok"])
        self.assertTrue(reproject_resp.json()["generated_projection"]["exists"])

        repair_all_resp = self.client.post(
            "/api/skills/deploy-targets/repair-all",
            json={},
        )
        self.assertEqual(200, repair_all_resp.status_code)
        self.assertTrue(repair_all_resp.json()["ok"])
        self.assertEqual(["claude_code:global"], repair_all_resp.json()["repaired_target_ids"])
        self.assertEqual(0, repair_all_resp.json()["remaining_repairable_total"])

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

        bad_reproject_resp = self.client.post(
            "/api/skills/deploy-targets/missing:global/reproject",
            json={},
        )
        self.assertEqual(400, bad_reproject_resp.status_code)
        self.assertFalse(bad_reproject_resp.json()["ok"])


if __name__ == "__main__":
    unittest.main()
