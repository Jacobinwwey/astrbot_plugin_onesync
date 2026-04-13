from __future__ import annotations

import sys
import tempfile
import types
import unittest
import zipfile
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
        self._web_admin_cfg = {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8099,
        }
        self._web_admin_password = "seed-password"
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
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
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
        self.last_astrbot_toggle_payload = None
        self.last_astrbot_delete_payload = None
        self.last_astrbot_sync_payload = None
        self.last_astrbot_import_payload = None
        self.last_astrbot_export_payload = None
        self.last_astrbot_neo_sync_payload = None
        self.last_astrbot_neo_promote_payload = None
        self.last_astrbot_neo_rollback_payload = None
        self._tempdir = tempfile.TemporaryDirectory()
        self.update_all_progress_snapshot = {
            "run_id": "",
            "status": "idle",
            "workflow_kind": "aggregate_update_all",
            "active": False,
            "candidate_install_unit_total": 0,
            "planned_install_unit_total": 0,
            "actionable_install_unit_total": 0,
            "command_install_unit_total": 0,
            "source_sync_install_unit_total": 0,
            "completed_command_install_unit_total": 0,
            "completed_source_sync_install_unit_total": 0,
            "completed_install_unit_total": 0,
            "skipped_install_unit_total": 0,
            "failure_count": 0,
            "success_count": 0,
            "source_sync_cache_hit_total": 0,
            "atom_candidate_install_unit_total": 0,
            "atom_improved_count": 0,
            "atom_unchanged_count": 0,
            "started_at": "",
            "updated_at": "2026-04-06T08:00:00+00:00",
            "message": "",
        }

    def _get_install_unit_row(self, install_unit_id: str) -> dict | None:
        for row in self.skills_snapshot["install_unit_rows"]:
            if row["install_unit_id"] == install_unit_id:
                return row
        return None

    def _build_install_unit_update_plan(self, install_unit_id: str, display_name: str) -> dict:
        return {
            "install_unit_id": install_unit_id,
            "display_name": display_name,
            "manager": "bunx",
            "policy": "registry",
            "install_ref": "@every-env/compound-plugin",
            "management_hint": "bunx @every-env/compound-plugin",
            "source_paths": ["/tmp/skill_cli"],
            "commands": ["bunx @every-env/compound-plugin"],
            "command_count": 1,
            "supported": True,
            "message": f"registry update is available for {display_name}",
        }

    @staticmethod
    def _redact_sync_auth_header(value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if ":" not in raw:
            return raw
        header_name = raw.split(":", 1)[0].strip()
        if not header_name:
            return "<redacted>"
        return f"{header_name}: <redacted>"

    def webui_redact_sensitive_payload(self, payload):
        def _walk(value):
            if isinstance(value, list):
                return [_walk(item) for item in value]
            if isinstance(value, tuple):
                return [_walk(item) for item in value]
            if isinstance(value, dict):
                redacted = {}
                for key, item in value.items():
                    normalized_key = str(key or "").strip()
                    if normalized_key == "sync_auth_token":
                        token_text = str(item or "").strip()
                        redacted[normalized_key] = ""
                        redacted["sync_auth_token_configured"] = bool(token_text)
                        continue
                    if normalized_key == "sync_auth_header":
                        header_text = str(item or "").strip()
                        redacted[normalized_key] = self._redact_sync_auth_header(header_text)
                        redacted["sync_auth_header_configured"] = bool(header_text)
                        continue
                    redacted[normalized_key] = _walk(item)
                return redacted
            return value

        return _walk(payload)

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
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "install_unit": install_unit,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "source_rows": self.skills_snapshot["source_rows"],
            "deploy_rows": self.skills_snapshot["deploy_rows"],
            "update_plan": self._build_install_unit_update_plan(
                install_unit_id=install_unit["install_unit_id"],
                display_name=install_unit["display_name"],
            ),
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
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": install_unit,
            "source_rows": self.skills_snapshot["source_rows"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_sync_install_unit(self, install_unit_id: str) -> dict:
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": install_unit,
            "source_rows": self.skills_snapshot["source_rows"],
            "synced_source_ids": ["skill_cli"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_update_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        _ = payload
        if install_unit_id == "unsupported":
            return {"ok": False, "message": "update unsupported for aggregate"}
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": install_unit,
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
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        if not payload.get("software_ids") and not payload.get("target_ids"):
            return {"ok": False, "message": "software_ids or target_ids is required"}
        return {
            "ok": True,
            "install_unit": install_unit,
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

    async def webui_update_all_skill_aggregates(self, payload: dict | None = None) -> dict:
        body = payload if isinstance(payload, dict) else {}
        if body.get("force_fail"):
            return {"ok": False, "message": "aggregate update-all failed"}
        self.update_all_progress_snapshot = {
            "run_id": "run-demo-001",
            "status": "completed",
            "workflow_kind": "aggregate_update_all",
            "active": False,
            "candidate_install_unit_total": 1,
            "planned_install_unit_total": 1,
            "actionable_install_unit_total": 1,
            "command_install_unit_total": 1,
            "source_sync_install_unit_total": 0,
            "completed_command_install_unit_total": 1,
            "completed_source_sync_install_unit_total": 0,
            "completed_install_unit_total": 1,
            "skipped_install_unit_total": 0,
            "failure_count": 0,
            "success_count": 1,
            "source_sync_cache_hit_total": 0,
            "atom_candidate_install_unit_total": 0,
            "atom_improved_count": 0,
            "atom_unchanged_count": 0,
            "started_at": "2026-04-06T08:10:00+00:00",
            "updated_at": "2026-04-06T08:10:10+00:00",
            "message": "aggregate update-all finished",
        }
        return {
            "ok": True,
            "run_id": "run-demo-001",
            "progress": dict(self.update_all_progress_snapshot),
            "candidate_install_unit_total": 1,
            "planned_install_unit_total": 1,
            "executed_install_unit_total": 1,
            "success_count": 1,
            "failure_count": 0,
            "precheck_failure_count": 0,
            "skipped_install_unit_total": 0,
            "source_sync_cache_hit_total": 0,
            "failure_taxonomy": {
                "failed_install_unit_total": 0,
                "failed_install_unit_reason_groups": [],
                "failed_install_unit_manager_groups": [],
                "blocked_install_unit_total": 0,
                "blocked_reason_groups": [],
                "failed_source_total": 0,
                "failed_source_sync_error_groups": [],
            },
            "update": {
                "supported": True,
                "actionable": True,
                "update_mode": "command",
                "planned_install_unit_total": 1,
                "deduplicated_install_unit_total": 1,
                "command_install_unit_total": 1,
                "source_sync_install_unit_total": 0,
                "skipped_install_unit_total": 0,
                "executed_install_unit_total": 1,
                "source_sync_cache_hit_total": 0,
                "failure_taxonomy": {
                    "failed_install_unit_total": 0,
                    "failed_install_unit_reason_groups": [],
                    "failed_install_unit_manager_groups": [],
                    "blocked_install_unit_total": 0,
                    "blocked_reason_groups": [],
                    "failed_source_total": 0,
                    "failed_source_sync_error_groups": [],
                },
                "success_count": 1,
                "failure_count": 0,
                "message": "aggregate update-all finished",
            },
            "updated_install_unit_ids": ["install:skill_cli"],
            "failed_install_units": [],
            "unsupported_install_units": [],
            "skipped_install_unit_ids": [],
            "deduplicated_install_unit_ids": ["npm:@every-env/compound-plugin"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_improve_all_skills(self, payload: dict | None = None) -> dict:
        body = payload if isinstance(payload, dict) else {}
        if body.get("force_fail"):
            return {"ok": False, "message": "skills improve-all failed"}
        self.update_all_progress_snapshot = {
            "run_id": "run-demo-improve-001",
            "status": "completed",
            "workflow_kind": "improve_all",
            "active": False,
            "candidate_install_unit_total": 1,
            "planned_install_unit_total": 1,
            "actionable_install_unit_total": 1,
            "command_install_unit_total": 1,
            "source_sync_install_unit_total": 0,
            "completed_command_install_unit_total": 1,
            "completed_source_sync_install_unit_total": 0,
            "completed_install_unit_total": 1,
            "skipped_install_unit_total": 0,
            "failure_count": 0,
            "success_count": 1,
            "source_sync_cache_hit_total": 0,
            "atom_candidate_install_unit_total": 1,
            "atom_improved_count": 1,
            "atom_unchanged_count": 0,
            "started_at": "2026-04-06T08:12:00+00:00",
            "updated_at": "2026-04-06T08:12:20+00:00",
            "message": "aggregate update-all finished",
        }
        return {
            "ok": True,
            "run_id": "run-demo-improve-001",
            "progress": dict(self.update_all_progress_snapshot),
            "candidate_install_unit_total": 1,
            "planned_install_unit_total": 1,
            "executed_install_unit_total": 1,
            "success_count": 1,
            "failure_count": 0,
            "precheck_failure_count": 0,
            "skipped_install_unit_total": 0,
            "source_sync_cache_hit_total": 0,
            "failure_taxonomy": {
                "failed_install_unit_total": 0,
                "failed_install_unit_reason_groups": [],
                "failed_install_unit_manager_groups": [],
                "blocked_install_unit_total": 0,
                "blocked_reason_groups": [],
                "failed_source_total": 0,
                "failed_source_sync_error_groups": [],
            },
            "atom_refresh": {
                "strategy": "all",
                "total": 1,
                "success": 1,
                "improved": 1,
                "unchanged": 0,
                "failed": 0,
                "failureGroups": [],
                "failureItems": [],
                "completedAt": "2026-04-06T08:12:05+00:00",
            },
            "update": {
                "supported": True,
                "actionable": True,
                "update_mode": "command",
                "planned_install_unit_total": 1,
                "deduplicated_install_unit_total": 1,
                "command_install_unit_total": 1,
                "source_sync_install_unit_total": 0,
                "skipped_install_unit_total": 0,
                "executed_install_unit_total": 1,
                "source_sync_cache_hit_total": 0,
                "failure_taxonomy": {
                    "failed_install_unit_total": 0,
                    "failed_install_unit_reason_groups": [],
                    "failed_install_unit_manager_groups": [],
                    "blocked_install_unit_total": 0,
                    "blocked_reason_groups": [],
                    "failed_source_total": 0,
                    "failed_source_sync_error_groups": [],
                },
                "success_count": 1,
                "failure_count": 0,
                "message": "aggregate update-all finished",
            },
            "updated_install_unit_ids": ["install:skill_cli"],
            "failed_install_units": [],
            "unsupported_install_units": [],
            "skipped_install_unit_ids": [],
            "deduplicated_install_unit_ids": ["npm:@every-env/compound-plugin"],
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_get_update_all_aggregate_progress_payload(self, run_id: str = "") -> dict:
        requested_run_id = str(run_id or "").strip()
        current_run_id = str(self.update_all_progress_snapshot.get("run_id") or "").strip()
        if requested_run_id and requested_run_id != current_run_id:
            return {
                "ok": False,
                "message": f"aggregate update-all progress not found: {requested_run_id}",
                "progress": dict(self.update_all_progress_snapshot),
            }
        return {
            "ok": True,
            "run_id": current_run_id,
            "status": str(self.update_all_progress_snapshot.get("status") or "idle"),
            "workflow_kind": str(self.update_all_progress_snapshot.get("workflow_kind") or "aggregate_update_all"),
            "progress": dict(self.update_all_progress_snapshot),
        }

    def webui_get_update_all_aggregate_history_payload(self, limit: int = 40) -> dict:
        _ = limit
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {"total": 1},
            "items": [
                {
                    "run_id": "run-demo-improve-001",
                    "timestamp": "2026-04-06T08:12:20+00:00",
                    "workflow_kind": "improve_all",
                    "source_id": "all",
                    "atom_refresh": {
                        "run_id": "run-demo-improve-001",
                        "strategy": "all",
                        "total": 1,
                        "success": 1,
                        "improved": 1,
                        "unchanged": 0,
                        "failed": 0,
                        "failureGroups": [],
                        "failureItems": [],
                        "completedAt": "2026-04-06T08:12:05+00:00",
                    },
                    "update": {
                        "run_id": "run-demo-improve-001",
                        "planned_install_unit_total": 1,
                        "executed_install_unit_total": 1,
                        "success_count": 1,
                        "failure_count": 0,
                        "skipped_install_unit_total": 0,
                        "source_sync_install_unit_total": 0,
                        "source_sync_cache_hit_total": 0,
                        "failure_taxonomy": {
                            "failed_install_unit_total": 0,
                            "failed_install_unit_reason_groups": [],
                            "failed_install_unit_manager_groups": [],
                            "blocked_install_unit_total": 0,
                            "blocked_reason_groups": [],
                            "failed_source_total": 0,
                            "failed_source_sync_error_groups": [],
                        },
                        "message": "aggregate update-all finished",
                    },
                },
            ],
            "warnings": [],
        }

    async def webui_rollback_install_unit(self, install_unit_id: str, payload: dict) -> dict:
        if install_unit_id == "unsupported":
            return {"ok": False, "message": "rollback unsupported for aggregate"}
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        if not payload.get("execute") or str(payload.get("confirm", "")) != "ROLLBACK_ACCEPT_RISK":
            return {"ok": False, "message": "rollback confirmation is required"}
        return {
            "ok": True,
            "install_unit": install_unit,
            "source_rows": self.skills_snapshot["source_rows"],
            "rollback": {
                "candidate_total": 1,
                "success_count": 1,
                "failure_count": 0,
                "restored_source_total": 1,
                "not_restored_source_total": 0,
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_rollback_collection_group(self, collection_group_id: str, payload: dict) -> dict:
        if collection_group_id == "unsupported":
            return {"ok": False, "message": "rollback unsupported for aggregate"}
        if collection_group_id != "collection:cli_tools":
            return {"ok": False, "message": "not found"}
        if not payload.get("execute") or str(payload.get("confirm", "")) != "ROLLBACK_ACCEPT_RISK":
            return {"ok": False, "message": "rollback confirmation is required"}
        return {
            "ok": True,
            "collection_group": self.skills_snapshot["collection_group_rows"][0],
            "install_unit_rows": self.skills_snapshot["install_unit_rows"],
            "source_rows": self.skills_snapshot["source_rows"],
            "rollback": {
                "candidate_total": 1,
                "success_count": 1,
                "failure_count": 0,
                "restored_source_total": 1,
                "not_restored_source_total": 0,
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
        install_unit = self._get_install_unit_row(install_unit_id)
        if install_unit is None:
            return {"ok": False, "message": "not found"}
        return {
            "ok": True,
            "install_unit": install_unit,
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
            "counts": {"registry_total": 1, "install_atom_total": 2},
            "items": self.skills_snapshot["registry"]["sources"],
            "warnings": [],
        }

    def webui_get_install_atom_registry_payload(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {
                "install_atom_total": 2,
                "resolved_total": 1,
                "partial_total": 0,
                "unresolved_total": 1,
            },
            "items": [
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
                    "evidence_level": "explicit",
                    "resolution_status": "resolved",
                },
                {
                    "install_unit_id": "install:skill_cli",
                    "display_name": "CLI Tool Pack",
                    "evidence_level": "unresolved",
                    "resolution_status": "unresolved",
                },
            ],
            "warnings": [],
        }

    def webui_get_skills_audit_payload(self, *, limit: int = 50, action: str = "", source_id: str = "") -> dict:
        items = [
            {
                "timestamp": "2026-04-11T09:00:00+00:00",
                "action": "install_unit_rollback",
                "source_id": "install:skill_cli",
                "payload": {
                    "candidate_total": 1,
                    "restored_source_total": 1,
                    "not_restored_source_total": 0,
                    "failure_count": 0,
                },
            },
            {
                "timestamp": "2026-04-11T08:58:00+00:00",
                "action": "collection_group_rollback",
                "source_id": "collection:cli_tools",
                "payload": {
                    "candidate_total": 2,
                    "restored_source_total": 1,
                    "not_restored_source_total": 1,
                    "failure_count": 1,
                },
            },
        ]
        action_keyword = str(action or "").strip().lower()
        normalized_source_id = str(source_id or "").strip()
        filtered = [
            item
            for item in items
            if (not action_keyword or action_keyword in str(item.get("action") or "").lower())
            and (not normalized_source_id or str(item.get("source_id") or "") == normalized_source_id)
        ][: max(1, int(limit or 1))]
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {"total": len(filtered)},
            "items": filtered,
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

    def webui_get_astrbot_neo_sources_payload(self) -> dict:
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "counts": {"source_total": 1, "ready_total": 1, "missing_total": 0},
            "items": [
                {
                    "source_id": "astrneo:astrbot:demo.skill",
                    "display_name": "neo-demo",
                    "source_kind": "astrneo_release",
                    "provider_key": "astrbot",
                    "astrneo_host_id": "astrbot",
                    "astrneo_skill_key": "demo.skill",
                    "astrneo_release_id": "rel-1",
                    "status": "ready",
                },
            ],
            "warnings": [],
        }

    def webui_get_astrbot_neo_source_payload(self, source_id: str) -> dict:
        if source_id != "astrneo:astrbot:demo.skill":
            return {"ok": False, "message": "astrbot neo source not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "source": {
                "source_id": "astrneo:astrbot:demo.skill",
                "display_name": "neo-demo",
                "source_kind": "astrneo_release",
                "provider_key": "astrbot",
                "astrneo_host_id": "astrbot",
                "astrneo_skill_key": "demo.skill",
                "astrneo_release_id": "rel-1",
                "status": "ready",
            },
            "neo_capabilities": {
                "sync_supported": True,
                "promote_supported": True,
                "rollback_supported": True,
            },
            "neo_defaults": {
                "candidate_id": "cand-1",
                "release_id": "rel-1",
                "stage": "stable",
                "sync_to_local": True,
                "require_stable": True,
            },
            "warnings": [],
        }


    async def webui_sync_astrbot_neo_source(self, source_id: str, payload: dict | None = None) -> dict:
        action_payload = payload if isinstance(payload, dict) else {}
        self.last_astrbot_neo_sync_payload = {"source_id": source_id, "payload": action_payload}
        if source_id != "astrneo:astrbot:demo.skill":
            return {"ok": False, "message": "astrbot neo source not found"}
        if action_payload.get("force_fail"):
            return {"ok": False, "message": "astrbot neo source sync failed", "reason_code": "neo_sync_failed"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "action": "neo_source_sync",
            "source": {
                "source_id": "astrneo:astrbot:demo.skill",
                "display_name": "neo-demo",
                "source_kind": "astrneo_release",
                "provider_key": "astrbot",
                "astrneo_host_id": "astrbot",
                "astrneo_skill_key": "demo.skill",
                "astrneo_release_id": "rel-2",
                "status": "ready",
            },
            "sync": {
                "skill_key": "demo.skill",
                "local_skill_name": "neo-demo",
                "release_id": str(action_payload.get("release_id") or "rel-2"),
                "candidate_id": "cand-2",
                "payload_ref": "payload-2",
                "map_path": "/tmp/astrbot/data/skills/neo_skill_map.json",
                "synced_at": self.skills_snapshot["generated_at"],
            },
            "warnings": [],
        }

    async def webui_promote_astrbot_neo_source(self, source_id: str, payload: dict | None = None) -> dict:
        action_payload = payload if isinstance(payload, dict) else {}
        self.last_astrbot_neo_promote_payload = {"source_id": source_id, "payload": action_payload}
        if source_id != "astrneo:astrbot:demo.skill":
            return {"ok": False, "message": "astrbot neo source not found"}
        if action_payload.get("force_fail"):
            return {"ok": False, "message": "astrbot neo source promote failed", "reason_code": "neo_promote_failed"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "action": "neo_source_promote",
            "source": {
                "source_id": "astrneo:astrbot:demo.skill",
                "display_name": "neo-demo",
                "source_kind": "astrneo_release",
                "provider_key": "astrbot",
                "astrneo_host_id": "astrbot",
                "astrneo_skill_key": "demo.skill",
                "astrneo_release_id": "rel-3",
                "status": "ready",
            },
            "promotion": {
                "candidate_id": str(action_payload.get("candidate_id") or "cand-1"),
                "stage": str(action_payload.get("stage") or "stable"),
                "sync_to_local": bool(action_payload.get("sync_to_local", True)),
                "release": {
                    "id": "rel-3",
                    "skill_key": "demo.skill",
                    "candidate_id": str(action_payload.get("candidate_id") or "cand-1"),
                    "stage": str(action_payload.get("stage") or "stable"),
                },
                "sync": {
                    "skill_key": "demo.skill",
                    "local_skill_name": "neo-demo",
                    "release_id": "rel-3",
                    "candidate_id": str(action_payload.get("candidate_id") or "cand-1"),
                    "payload_ref": "payload-3",
                    "map_path": "/tmp/astrbot/data/skills/neo_skill_map.json",
                    "synced_at": self.skills_snapshot["generated_at"],
                },
                "rollback": None,
                "sync_error": None,
            },
            "warnings": [],
        }

    async def webui_rollback_astrbot_neo_source(self, source_id: str, payload: dict | None = None) -> dict:
        action_payload = payload if isinstance(payload, dict) else {}
        self.last_astrbot_neo_rollback_payload = {"source_id": source_id, "payload": action_payload}
        if source_id != "astrneo:astrbot:demo.skill":
            return {"ok": False, "message": "astrbot neo source not found"}
        if action_payload.get("force_fail"):
            return {"ok": False, "message": "astrbot neo source rollback failed", "reason_code": "neo_rollback_failed"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "action": "neo_source_rollback",
            "source": {
                "source_id": "astrneo:astrbot:demo.skill",
                "display_name": "neo-demo",
                "source_kind": "astrneo_release",
                "provider_key": "astrbot",
                "astrneo_host_id": "astrbot",
                "astrneo_skill_key": "demo.skill",
                "astrneo_release_id": str(action_payload.get("release_id") or "rel-1"),
                "status": "ready",
            },
            "rollback": {
                "release_id": str(action_payload.get("release_id") or "rel-1"),
                "active_release_id": "rel-0",
                "rolled_back": True,
            },
            "warnings": [],
        }

    def webui_get_astrbot_host_payload(self, host_id: str) -> dict:
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        return {
            "ok": True,
            "generated_at": self.skills_snapshot["generated_at"],
            "host": {
                "host_id": "astrbot",
                "display_name": "AstrBot",
                "runtime_state_backend": "astrbot",
            },
            "runtime_state": {
                "summary": {
                    "state_available": True,
                    "skills_root": "/tmp/astrbot/data/skills",
                    "selected_scope": "global",
                    "available_scopes": ["global", "workspace"],
                    "scope_summaries": {
                        "global": {
                            "state_available": True,
                            "skills_root": "/tmp/astrbot/data/skills",
                            "local_skill_total": 4,
                        },
                        "workspace": {
                            "state_available": True,
                            "skills_root": "/tmp/workspace-astrbot/data/skills",
                            "local_skill_total": 2,
                        },
                    },
                },
                "state_rows": [],
                "warnings": [],
            },
            "layout": {
                "host_id": "astrbot",
                "skills_root": "/tmp/astrbot/data/skills",
                "astrbot_data_dir": "/tmp/astrbot/data",
                "skills_config_path": "/tmp/astrbot/data/skills.json",
                "sandbox_cache_path": "/tmp/astrbot/data/sandbox_skills_cache.json",
                "neo_map_path": "/tmp/astrbot/data/skills/neo_skill_map.json",
                "selected_scope": "global",
                "available_scopes": ["global", "workspace"],
                "scoped_layouts": {
                    "global": {
                        "scope": "global",
                        "skills_root": "/tmp/astrbot/data/skills",
                    },
                    "workspace": {
                        "scope": "workspace",
                        "skills_root": "/tmp/workspace-astrbot/data/skills",
                    },
                },
            },
            "warnings": [],
        }

    def webui_set_astrbot_skill_active(self, host_id: str, payload: dict) -> dict:
        self.last_astrbot_toggle_payload = {"host_id": host_id, "payload": payload}
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        if not str((payload or {}).get("skill_name", "")).strip():
            return {"ok": False, "message": "invalid skill_name"}
        return {
            "ok": True,
            "action": "toggle_skill",
            "result": {
                "ok": True,
                "skill_name": str(payload.get("skill_name")),
                "active": bool(payload.get("active", True)),
                "scope": str(payload.get("scope") or "global"),
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_delete_astrbot_skill(self, host_id: str, payload: dict) -> dict:
        self.last_astrbot_delete_payload = {"host_id": host_id, "payload": payload}
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        if not str((payload or {}).get("skill_name", "")).strip():
            return {"ok": False, "message": "invalid skill_name"}
        return {
            "ok": True,
            "action": "delete_skill",
            "result": {
                "ok": True,
                "skill_name": str(payload.get("skill_name")),
                "scope": str(payload.get("scope") or "global"),
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    async def webui_sync_astrbot_sandbox(self, host_id: str, payload: dict) -> dict:
        self.last_astrbot_sync_payload = {"host_id": host_id, "payload": payload}
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        return {
            "ok": True,
            "action": "sandbox_sync",
            "result": {
                "ok": True,
                "message": "sync done",
                "scope": str(payload.get("scope") or "global"),
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_import_astrbot_skill_zip(self, host_id: str, zip_path: str, payload: dict | None = None) -> dict:
        action_payload = payload if isinstance(payload, dict) else {}
        self.last_astrbot_import_payload = {
            "host_id": host_id,
            "zip_path": zip_path,
            "payload": action_payload,
        }
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        if not Path(str(zip_path or "")).exists():
            return {"ok": False, "message": "zip file not found"}
        return {
            "ok": True,
            "action": "import_zip",
            "result": {
                "ok": True,
                "scope": str(action_payload.get("scope") or "global"),
                "installed_skill_names": ["demo-import"],
                "installed_count": 1,
                "archive_path": str(zip_path),
            },
            "skills": self.skills_snapshot,
            "inventory": self.inventory_snapshot,
        }

    def webui_export_astrbot_skill_zip(self, host_id: str, payload: dict | None = None) -> dict:
        action_payload = payload if isinstance(payload, dict) else {}
        self.last_astrbot_export_payload = {
            "host_id": host_id,
            "payload": action_payload,
        }
        if host_id != "astrbot":
            return {"ok": False, "message": "host_id not found"}
        skill_name = str(action_payload.get("skill_name") or "").strip()
        if not skill_name:
            return {"ok": False, "message": "invalid skill_name"}
        archive_path = Path(self._tempdir.name) / f"{skill_name}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            handle.writestr(f"{skill_name}/SKILL.md", "# demo\n")
        return {
            "ok": True,
            "action": "export_zip",
            "result": {
                "ok": True,
                "scope": str(action_payload.get("scope") or "global"),
                "skill_name": skill_name,
                "archive_path": str(archive_path),
                "filename": f"{skill_name}.zip",
                "media_type": "application/zip",
            },
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
        password_configured = bool(str(self._web_admin_password or "").strip())
        return {
            "ok": True,
            "config": {
                "web_admin": {
                    "enabled": bool(self._web_admin_cfg.get("enabled", False)),
                    "host": str(self._web_admin_cfg.get("host", "127.0.0.1") or "127.0.0.1"),
                    "port": int(self._web_admin_cfg.get("port", 8099) or 8099),
                    "password": "",
                    "password_configured": password_configured,
                },
            },
            "meta": {
                "web_admin_password_configured": password_configured,
            },
        }

    def webui_update_config(self, payload: dict) -> dict:
        incoming = payload.get("config", payload)
        if not isinstance(incoming, dict):
            return {"ok": False, "message": "config must be object"}
        web_cfg_raw = incoming.get("web_admin", {})
        if not isinstance(web_cfg_raw, dict):
            return {"ok": False, "message": "web_admin must be object"}
        self._web_admin_cfg = {
            "enabled": bool(web_cfg_raw.get("enabled", False)),
            "host": str(web_cfg_raw.get("host", "127.0.0.1") or "127.0.0.1"),
            "port": int(web_cfg_raw.get("port", 8099) or 8099),
        }
        password_mode = str(web_cfg_raw.get("password_mode", "") or "").strip().lower()
        has_password = "password" in web_cfg_raw
        raw_password = str(web_cfg_raw.get("password", "") or "")
        if password_mode == "clear":
            self._web_admin_password = ""
        elif password_mode == "set":
            self._web_admin_password = raw_password
        elif password_mode == "keep":
            pass
        elif has_password:
            self._web_admin_password = raw_password
        return self.webui_get_config_payload()

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

    def test_config_routes_keep_web_password_secret_and_support_password_mode(self) -> None:
        get_resp = self.client.get("/api/config")
        self.assertEqual(200, get_resp.status_code)
        get_data = get_resp.json()
        self.assertEqual("", get_data["config"]["web_admin"]["password"])
        self.assertTrue(get_data["config"]["web_admin"]["password_configured"])
        self.assertTrue(get_data["meta"]["web_admin_password_configured"])

        keep_resp = self.client.post(
            "/api/config",
            json={"config": {"web_admin": {"enabled": True, "host": "127.0.0.1", "port": 8099, "password_mode": "keep"}}},
        )
        self.assertEqual(200, keep_resp.status_code)
        keep_data = keep_resp.json()
        self.assertEqual("", keep_data["config"]["web_admin"]["password"])
        self.assertTrue(keep_data["config"]["web_admin"]["password_configured"])
        self.assertTrue(keep_data["meta"]["web_admin_password_configured"])

        clear_resp = self.client.post(
            "/api/config",
            json={"config": {"web_admin": {"enabled": True, "host": "127.0.0.1", "port": 8099, "password_mode": "clear"}}},
        )
        self.assertEqual(200, clear_resp.status_code)
        clear_data = clear_resp.json()
        self.assertEqual("", clear_data["config"]["web_admin"]["password"])
        self.assertFalse(clear_data["config"]["web_admin"]["password_configured"])
        self.assertFalse(clear_data["meta"]["web_admin_password_configured"])

        set_resp = self.client.post(
            "/api/config",
            json={
                "config": {
                    "web_admin": {
                        "enabled": True,
                        "host": "127.0.0.1",
                        "port": 8099,
                        "password_mode": "set",
                        "password": "new-secret-password",
                    },
                },
            },
        )
        self.assertEqual(200, set_resp.status_code)
        set_data = set_resp.json()
        self.assertEqual("", set_data["config"]["web_admin"]["password"])
        self.assertTrue(set_data["config"]["web_admin"]["password_configured"])
        self.assertTrue(set_data["meta"]["web_admin_password_configured"])

    def test_docs_routes_expose_local_markdown_index_and_content(self) -> None:
        index_resp = self.client.get(
            "/api/docs/index",
            params={"lang": "zh", "keyword": "INSTALL", "limit": 100},
        )
        self.assertEqual(200, index_resp.status_code)
        index_data = index_resp.json()
        self.assertTrue(index_data["ok"])
        self.assertEqual("zh", index_data["lang"])
        self.assertGreaterEqual(index_data["counts"]["total"], 1)
        install_item = next(
            (
                item
                for item in index_data["items"]
                if item["path"] in {"docs/INSTALL_AND_CONFIG_zh.md", "docs/INSTALL_AND_CONFIG_en.md"}
            ),
            None,
        )
        self.assertIsNotNone(install_item)

        content_resp = self.client.get(
            "/api/docs/content",
            params={"path": "docs/INSTALL_AND_CONFIG_zh.md"},
        )
        self.assertEqual(200, content_resp.status_code)
        content_data = content_resp.json()
        self.assertTrue(content_data["ok"])
        self.assertEqual("docs/INSTALL_AND_CONFIG_zh.md", content_data["path"])
        self.assertIn("content", content_data)
        self.assertIn("OneSync", content_data["content"])
        self.assertIn(content_data["lang"], {"zh", "multi"})

        raw_resp = self.client.get(
            "/api/docs/raw",
            params={"path": "README.md"},
        )
        self.assertEqual(200, raw_resp.status_code)
        self.assertIn("text/markdown", raw_resp.headers.get("content-type", ""))
        self.assertIn("OneSync", raw_resp.text)

    def test_docs_content_route_rejects_path_traversal_and_missing_file(self) -> None:
        traversal_resp = self.client.get(
            "/api/docs/content",
            params={"path": "../../etc/passwd"},
        )
        self.assertEqual(404, traversal_resp.status_code)
        self.assertFalse(traversal_resp.json()["ok"])

        missing_resp = self.client.get(
            "/api/docs/raw",
            params={"path": "docs/missing-file.md"},
        )
        self.assertEqual(404, missing_resp.status_code)
        self.assertIn("document not found", missing_resp.text)

    def test_skills_routes_return_expected_payloads(self) -> None:
        overview_resp = self.client.get("/api/skills/overview")
        self.assertEqual(200, overview_resp.status_code)
        self.assertEqual(1, overview_resp.json()["counts"]["source_total"])

        registry_resp = self.client.get("/api/skills/registry")
        self.assertEqual(200, registry_resp.status_code)
        self.assertEqual("skill_cli", registry_resp.json()["items"][0]["source_id"])

        install_atom_resp = self.client.get("/api/skills/install-atoms")
        self.assertEqual(200, install_atom_resp.status_code)
        self.assertEqual(2, install_atom_resp.json()["counts"]["install_atom_total"])
        self.assertEqual(
            "npm:@every-env/compound-plugin",
            install_atom_resp.json()["items"][0]["install_unit_id"],
        )
        rollback_audit_resp = self.client.get(
            "/api/skills/audit",
            params={"limit": 10, "action": "rollback", "source_id": "install:skill_cli"},
        )
        self.assertEqual(200, rollback_audit_resp.status_code)
        self.assertEqual(1, rollback_audit_resp.json()["counts"]["total"])
        self.assertEqual("install_unit_rollback", rollback_audit_resp.json()["items"][0]["action"])
        self.assertEqual("install:skill_cli", rollback_audit_resp.json()["items"][0]["source_id"])

        aggregate_history_resp = self.client.get(
            "/api/skills/aggregates/update-all/history",
            params={"limit": 10},
        )
        self.assertEqual(200, aggregate_history_resp.status_code)
        self.assertTrue(aggregate_history_resp.json()["ok"])
        self.assertEqual(1, aggregate_history_resp.json()["counts"]["total"])
        self.assertEqual("run-demo-improve-001", aggregate_history_resp.json()["items"][0]["run_id"])
        self.assertEqual("improve_all", aggregate_history_resp.json()["items"][0]["workflow_kind"])
        self.assertEqual(1, aggregate_history_resp.json()["items"][0]["atom_refresh"]["improved"])
        self.assertEqual(1, aggregate_history_resp.json()["items"][0]["update"]["planned_install_unit_total"])

        hosts_resp = self.client.get("/api/skills/hosts")
        self.assertEqual(200, hosts_resp.status_code)
        self.assertEqual("claude_code", hosts_resp.json()["items"][0]["host_id"])

        astrbot_neo_sources_resp = self.client.get("/api/skills/astrbot-neo-sources")
        self.assertEqual(200, astrbot_neo_sources_resp.status_code)
        self.assertEqual(1, astrbot_neo_sources_resp.json()["counts"]["source_total"])
        self.assertEqual(
            "astrneo:astrbot:demo.skill",
            astrbot_neo_sources_resp.json()["items"][0]["source_id"],
        )

        astrbot_neo_source_detail_resp = self.client.get("/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill")
        self.assertEqual(200, astrbot_neo_source_detail_resp.status_code)
        self.assertEqual(
            "astrneo:astrbot:demo.skill",
            astrbot_neo_source_detail_resp.json()["source"]["source_id"],
        )
        self.assertTrue(astrbot_neo_source_detail_resp.json()["neo_capabilities"]["promote_supported"])
        self.assertEqual("cand-1", astrbot_neo_source_detail_resp.json()["neo_defaults"]["candidate_id"])

        missing_astrbot_neo_source_detail_resp = self.client.get("/api/skills/astrbot-neo-sources/missing")
        self.assertEqual(404, missing_astrbot_neo_source_detail_resp.status_code)
        self.assertFalse(missing_astrbot_neo_source_detail_resp.json()["ok"])

        astrbot_host_resp = self.client.get("/api/skills/hosts/astrbot/astrbot")
        self.assertEqual(200, astrbot_host_resp.status_code)
        self.assertEqual("astrbot", astrbot_host_resp.json()["host"]["host_id"])
        self.assertEqual(
            ["global", "workspace"],
            astrbot_host_resp.json()["runtime_state"]["summary"]["available_scopes"],
        )
        self.assertEqual(
            "/tmp/workspace-astrbot/data/skills",
            astrbot_host_resp.json()["layout"]["scoped_layouts"]["workspace"]["skills_root"],
        )

        missing_astrbot_host_resp = self.client.get("/api/skills/hosts/missing/astrbot")
        self.assertEqual(404, missing_astrbot_host_resp.status_code)
        self.assertFalse(missing_astrbot_host_resp.json()["ok"])

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

        update_all_resp = self.client.post("/api/skills/aggregates/update-all", json={})
        self.assertEqual(200, update_all_resp.status_code)
        self.assertTrue(update_all_resp.json()["ok"])
        self.assertEqual("run-demo-001", update_all_resp.json()["run_id"])
        self.assertEqual("completed", update_all_resp.json()["progress"]["status"])
        self.assertEqual(1, update_all_resp.json()["update"]["planned_install_unit_total"])
        self.assertEqual(1, update_all_resp.json()["planned_install_unit_total"])
        self.assertEqual(1, update_all_resp.json()["success_count"])
        self.assertEqual([], update_all_resp.json()["failure_taxonomy"]["blocked_reason_groups"])
        self.assertEqual(["install:skill_cli"], update_all_resp.json()["updated_install_unit_ids"])

        progress_resp = self.client.get("/api/skills/aggregates/update-all/progress")
        self.assertEqual(200, progress_resp.status_code)
        self.assertTrue(progress_resp.json()["ok"])
        self.assertEqual("run-demo-001", progress_resp.json()["run_id"])
        self.assertEqual("completed", progress_resp.json()["progress"]["status"])

        progress_by_run_resp = self.client.get("/api/skills/aggregates/update-all/progress?run_id=run-demo-001")
        self.assertEqual(200, progress_by_run_resp.status_code)
        self.assertTrue(progress_by_run_resp.json()["ok"])
        self.assertEqual("run-demo-001", progress_by_run_resp.json()["progress"]["run_id"])

        missing_progress_resp = self.client.get("/api/skills/aggregates/update-all/progress?run_id=missing-run")
        self.assertEqual(404, missing_progress_resp.status_code)
        self.assertFalse(missing_progress_resp.json()["ok"])

        improve_all_resp = self.client.post("/api/skills/improve-all", json={})
        self.assertEqual(200, improve_all_resp.status_code)
        self.assertTrue(improve_all_resp.json()["ok"])
        self.assertEqual("run-demo-improve-001", improve_all_resp.json()["run_id"])
        self.assertEqual("completed", improve_all_resp.json()["progress"]["status"])
        self.assertEqual("improve_all", improve_all_resp.json()["progress"]["workflow_kind"])
        self.assertEqual(1, improve_all_resp.json()["progress"]["atom_candidate_install_unit_total"])
        self.assertEqual(1, improve_all_resp.json()["progress"]["atom_improved_count"])
        self.assertEqual(0, improve_all_resp.json()["progress"]["atom_unchanged_count"])
        self.assertEqual(1, improve_all_resp.json()["atom_refresh"]["total"])
        self.assertEqual(1, improve_all_resp.json()["atom_refresh"]["improved"])
        self.assertEqual(1, improve_all_resp.json()["update"]["planned_install_unit_total"])

        improve_progress_resp = self.client.get(
            "/api/skills/aggregates/update-all/progress?run_id=run-demo-improve-001",
        )
        self.assertEqual(200, improve_progress_resp.status_code)
        self.assertTrue(improve_progress_resp.json()["ok"])
        self.assertEqual("improve_all", improve_progress_resp.json()["progress"]["workflow_kind"])
        self.assertEqual(1, improve_progress_resp.json()["progress"]["atom_candidate_install_unit_total"])
        self.assertEqual(1, improve_progress_resp.json()["progress"]["atom_improved_count"])

        astrbot_toggle_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/skills/toggle",
            json={"skill_name": "demo", "active": False, "scope": "workspace"},
        )
        self.assertEqual(200, astrbot_toggle_resp.status_code)
        self.assertTrue(astrbot_toggle_resp.json()["ok"])
        self.assertEqual("toggle_skill", astrbot_toggle_resp.json()["action"])
        self.assertEqual("workspace", astrbot_toggle_resp.json()["result"]["scope"])
        self.assertEqual("workspace", self.plugin.last_astrbot_toggle_payload["payload"]["scope"])

        astrbot_delete_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/skills/delete",
            json={"skill_name": "demo", "scope": "workspace"},
        )
        self.assertEqual(200, astrbot_delete_resp.status_code)
        self.assertTrue(astrbot_delete_resp.json()["ok"])
        self.assertEqual("delete_skill", astrbot_delete_resp.json()["action"])
        self.assertEqual("workspace", astrbot_delete_resp.json()["result"]["scope"])
        self.assertEqual("workspace", self.plugin.last_astrbot_delete_payload["payload"]["scope"])

        astrbot_sync_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/sandbox/sync",
            json={"scope": "workspace"},
        )
        self.assertEqual(200, astrbot_sync_resp.status_code)
        self.assertTrue(astrbot_sync_resp.json()["ok"])
        self.assertEqual("sandbox_sync", astrbot_sync_resp.json()["action"])
        self.assertEqual("workspace", astrbot_sync_resp.json()["result"]["scope"])
        self.assertEqual("workspace", self.plugin.last_astrbot_sync_payload["payload"]["scope"])

        astrbot_import_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/skills/import-zip",
            data={"scope": "workspace"},
            files={"file": ("demo-import.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
        )
        self.assertEqual(200, astrbot_import_resp.status_code)
        self.assertTrue(astrbot_import_resp.json()["ok"])
        self.assertEqual("import_zip", astrbot_import_resp.json()["action"])
        self.assertEqual("workspace", astrbot_import_resp.json()["result"]["scope"])
        self.assertEqual("workspace", self.plugin.last_astrbot_import_payload["payload"]["scope"])

        astrbot_export_resp = self.client.get(
            "/api/skills/hosts/astrbot/astrbot/skills/export-zip",
            params={"skill_name": "demo", "scope": "workspace"},
        )
        self.assertEqual(200, astrbot_export_resp.status_code)
        self.assertEqual("application/zip", astrbot_export_resp.headers["content-type"])
        self.assertIn("demo.zip", astrbot_export_resp.headers.get("content-disposition", ""))
        self.assertEqual("workspace", self.plugin.last_astrbot_export_payload["payload"]["scope"])


        astrbot_neo_sync_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/sync",
            json={"release_id": "rel-2"},
        )
        self.assertEqual(200, astrbot_neo_sync_resp.status_code)
        self.assertTrue(astrbot_neo_sync_resp.json()["ok"])
        self.assertEqual("neo_source_sync", astrbot_neo_sync_resp.json()["action"])
        self.assertEqual("astrneo:astrbot:demo.skill", self.plugin.last_astrbot_neo_sync_payload["source_id"])

        astrbot_neo_sync_bad_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/sync",
            json={"force_fail": True},
        )
        self.assertEqual(400, astrbot_neo_sync_bad_resp.status_code)
        self.assertFalse(astrbot_neo_sync_bad_resp.json()["ok"])

        astrbot_neo_sync_missing_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/missing/sync",
            json={},
        )
        self.assertEqual(404, astrbot_neo_sync_missing_resp.status_code)
        self.assertFalse(astrbot_neo_sync_missing_resp.json()["ok"])

        astrbot_neo_promote_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/promote",
            json={"candidate_id": "cand-3", "stage": "stable", "sync_to_local": True},
        )
        self.assertEqual(200, astrbot_neo_promote_resp.status_code)
        self.assertTrue(astrbot_neo_promote_resp.json()["ok"])
        self.assertEqual("neo_source_promote", astrbot_neo_promote_resp.json()["action"])
        self.assertEqual("astrneo:astrbot:demo.skill", self.plugin.last_astrbot_neo_promote_payload["source_id"])
        self.assertEqual("cand-3", astrbot_neo_promote_resp.json()["promotion"]["candidate_id"])

        astrbot_neo_promote_bad_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/promote",
            json={"force_fail": True},
        )
        self.assertEqual(400, astrbot_neo_promote_bad_resp.status_code)
        self.assertFalse(astrbot_neo_promote_bad_resp.json()["ok"])

        astrbot_neo_promote_missing_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/missing/promote",
            json={},
        )
        self.assertEqual(404, astrbot_neo_promote_missing_resp.status_code)
        self.assertFalse(astrbot_neo_promote_missing_resp.json()["ok"])

        astrbot_neo_rollback_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/rollback",
            json={"release_id": "rel-3"},
        )
        self.assertEqual(200, astrbot_neo_rollback_resp.status_code)
        self.assertTrue(astrbot_neo_rollback_resp.json()["ok"])
        self.assertEqual("neo_source_rollback", astrbot_neo_rollback_resp.json()["action"])
        self.assertEqual("astrneo:astrbot:demo.skill", self.plugin.last_astrbot_neo_rollback_payload["source_id"])
        self.assertEqual("rel-3", astrbot_neo_rollback_resp.json()["rollback"]["release_id"])

        astrbot_neo_rollback_bad_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/astrneo%3Aastrbot%3Ademo.skill/rollback",
            json={"force_fail": True},
        )
        self.assertEqual(400, astrbot_neo_rollback_bad_resp.status_code)
        self.assertFalse(astrbot_neo_rollback_bad_resp.json()["ok"])

        astrbot_neo_rollback_missing_resp = self.client.post(
            "/api/skills/astrbot-neo-sources/missing/rollback",
            json={},
        )
        self.assertEqual(404, astrbot_neo_rollback_missing_resp.status_code)
        self.assertFalse(astrbot_neo_rollback_missing_resp.json()["ok"])

        astrbot_toggle_bad_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/skills/toggle",
            json={"skill_name": ""},
        )
        self.assertEqual(400, astrbot_toggle_bad_resp.status_code)
        self.assertFalse(astrbot_toggle_bad_resp.json()["ok"])

        astrbot_sync_missing_resp = self.client.post(
            "/api/skills/hosts/missing/astrbot/sandbox/sync",
            json={},
        )
        self.assertEqual(404, astrbot_sync_missing_resp.status_code)
        self.assertFalse(astrbot_sync_missing_resp.json()["ok"])

        astrbot_import_bad_resp = self.client.post(
            "/api/skills/hosts/astrbot/astrbot/skills/import-zip",
            data={"scope": "workspace"},
        )
        self.assertEqual(400, astrbot_import_bad_resp.status_code)
        self.assertFalse(astrbot_import_bad_resp.json()["ok"])

        astrbot_export_bad_resp = self.client.get(
            "/api/skills/hosts/astrbot/astrbot/skills/export-zip",
            params={"skill_name": ""},
        )
        self.assertEqual(400, astrbot_export_bad_resp.status_code)
        self.assertFalse(astrbot_export_bad_resp.json()["ok"])

        unit_rollback_resp = self.client.post(
            "/api/skills/install-units/install%3Askill_cli/rollback",
            json={
                "execute": True,
                "confirm": "ROLLBACK_ACCEPT_RISK",
                "before_revisions": [{"source_id": "skill_cli", "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
            },
        )
        self.assertEqual(200, unit_rollback_resp.status_code)
        self.assertTrue(unit_rollback_resp.json()["ok"])
        self.assertEqual(1, unit_rollback_resp.json()["rollback"]["restored_source_total"])

        group_rollback_resp = self.client.post(
            "/api/skills/collections/collection%3Acli_tools/rollback",
            json={
                "execute": True,
                "confirm": "ROLLBACK_ACCEPT_RISK",
                "before_revisions": [{"source_id": "skill_cli", "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
            },
        )
        self.assertEqual(200, group_rollback_resp.status_code)
        self.assertTrue(group_rollback_resp.json()["ok"])
        self.assertEqual(1, group_rollback_resp.json()["rollback"]["restored_source_total"])

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

        missing_unit_rollback_resp = self.client.post(
            "/api/skills/install-units/missing/rollback",
            json={"execute": True, "confirm": "ROLLBACK_ACCEPT_RISK"},
        )
        self.assertEqual(404, missing_unit_rollback_resp.status_code)
        self.assertFalse(missing_unit_rollback_resp.json()["ok"])

        missing_group_refresh_resp = self.client.post("/api/skills/collections/missing/refresh", json={})
        self.assertEqual(404, missing_group_refresh_resp.status_code)
        self.assertFalse(missing_group_refresh_resp.json()["ok"])

        missing_group_sync_resp = self.client.post("/api/skills/collections/missing/sync", json={})
        self.assertEqual(404, missing_group_sync_resp.status_code)
        self.assertFalse(missing_group_sync_resp.json()["ok"])

        missing_group_update_resp = self.client.post("/api/skills/collections/missing/update", json={})
        self.assertEqual(404, missing_group_update_resp.status_code)
        self.assertFalse(missing_group_update_resp.json()["ok"])

        missing_group_rollback_resp = self.client.post(
            "/api/skills/collections/missing/rollback",
            json={"execute": True, "confirm": "ROLLBACK_ACCEPT_RISK"},
        )
        self.assertEqual(404, missing_group_rollback_resp.status_code)
        self.assertFalse(missing_group_rollback_resp.json()["ok"])

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

        bad_update_all_resp = self.client.post("/api/skills/aggregates/update-all", json={"force_fail": True})
        self.assertEqual(400, bad_update_all_resp.status_code)
        self.assertFalse(bad_update_all_resp.json()["ok"])

        bad_unit_rollback_resp = self.client.post(
            "/api/skills/install-units/install%3Askill_cli/rollback",
            json={},
        )
        self.assertEqual(400, bad_unit_rollback_resp.status_code)
        self.assertFalse(bad_unit_rollback_resp.json()["ok"])

        unsupported_unit_rollback_resp = self.client.post(
            "/api/skills/install-units/unsupported/rollback",
            json={"execute": True, "confirm": "ROLLBACK_ACCEPT_RISK"},
        )
        self.assertEqual(400, unsupported_unit_rollback_resp.status_code)
        self.assertFalse(unsupported_unit_rollback_resp.json()["ok"])

        bad_group_rollback_resp = self.client.post(
            "/api/skills/collections/collection%3Acli_tools/rollback",
            json={},
        )
        self.assertEqual(400, bad_group_rollback_resp.status_code)
        self.assertFalse(bad_group_rollback_resp.json()["ok"])

        unsupported_group_rollback_resp = self.client.post(
            "/api/skills/collections/unsupported/rollback",
            json={"execute": True, "confirm": "ROLLBACK_ACCEPT_RISK"},
        )
        self.assertEqual(400, unsupported_group_rollback_resp.status_code)
        self.assertFalse(unsupported_group_rollback_resp.json()["ok"])

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

    def test_skills_routes_redact_sync_auth_fields(self) -> None:
        self.plugin.skills_snapshot["source_rows"][0]["sync_auth_token"] = "token-source-secret"
        self.plugin.skills_snapshot["source_rows"][0]["sync_auth_header"] = "PRIVATE-TOKEN: source-header-secret"
        self.plugin.skills_snapshot["registry"]["sources"][0]["sync_auth_token"] = "token-registry-secret"
        self.plugin.skills_snapshot["registry"]["sources"][0]["sync_auth_header"] = "Authorization: Bearer registry-secret"

        overview_resp = self.client.get("/api/skills/overview")
        self.assertEqual(200, overview_resp.status_code)
        overview_data = overview_resp.json()
        source_row = overview_data["source_rows"][0]
        registry_row = overview_data["registry"]["sources"][0]

        self.assertEqual("", source_row["sync_auth_token"])
        self.assertTrue(source_row["sync_auth_token_configured"])
        self.assertEqual("PRIVATE-TOKEN: <redacted>", source_row["sync_auth_header"])
        self.assertTrue(source_row["sync_auth_header_configured"])

        self.assertEqual("", registry_row["sync_auth_token"])
        self.assertTrue(registry_row["sync_auth_token_configured"])
        self.assertEqual("Authorization: <redacted>", registry_row["sync_auth_header"])
        self.assertTrue(registry_row["sync_auth_header_configured"])

        self.plugin.skills_snapshot["source_rows"][0]["sync_auth_header"] = "X-GitHub-Token"
        sources_resp = self.client.get("/api/skills/sources")
        self.assertEqual(200, sources_resp.status_code)
        self.assertEqual("X-GitHub-Token", sources_resp.json()["items"][0]["sync_auth_header"])

        bindings_resp = self.client.post(
            "/api/inventory/bindings",
            json={"software_id": "claude_code", "skill_ids": ["skill_cli"], "scope": "global"},
        )
        self.assertEqual(200, bindings_resp.status_code)
        bindings_data = bindings_resp.json()
        binding_source_row = bindings_data["skills"]["source_rows"][0]
        self.assertEqual("", binding_source_row["sync_auth_token"])
        self.assertTrue(binding_source_row["sync_auth_token_configured"])
        self.assertEqual("X-GitHub-Token", binding_source_row["sync_auth_header"])
        self.assertTrue(binding_source_row["sync_auth_header_configured"])

    def test_install_unit_routes_support_ids_with_slashes(self) -> None:
        encoded_install_unit_id = "npm%3A%40every-env%2Fcompound-plugin"
        expected_install_unit_id = "npm:@every-env/compound-plugin"

        detail_resp = self.client.get(f"/api/skills/install-units/{encoded_install_unit_id}")
        self.assertEqual(200, detail_resp.status_code)
        self.assertEqual(expected_install_unit_id, detail_resp.json()["install_unit"]["install_unit_id"])

        refresh_resp = self.client.post(f"/api/skills/install-units/{encoded_install_unit_id}/refresh", json={})
        self.assertEqual(200, refresh_resp.status_code)
        self.assertEqual(expected_install_unit_id, refresh_resp.json()["install_unit"]["install_unit_id"])

        sync_resp = self.client.post(f"/api/skills/install-units/{encoded_install_unit_id}/sync", json={})
        self.assertEqual(200, sync_resp.status_code)
        self.assertEqual(expected_install_unit_id, sync_resp.json()["install_unit"]["install_unit_id"])

        update_resp = self.client.post(f"/api/skills/install-units/{encoded_install_unit_id}/update", json={})
        self.assertEqual(200, update_resp.status_code)
        self.assertEqual(expected_install_unit_id, update_resp.json()["install_unit"]["install_unit_id"])

        deploy_resp = self.client.post(
            f"/api/skills/install-units/{encoded_install_unit_id}/deploy",
            json={"software_ids": ["claude_code"], "scope": "global"},
        )
        self.assertEqual(200, deploy_resp.status_code)
        self.assertEqual(expected_install_unit_id, deploy_resp.json()["install_unit"]["install_unit_id"])

        repair_resp = self.client.post(f"/api/skills/install-units/{encoded_install_unit_id}/repair", json={})
        self.assertEqual(200, repair_resp.status_code)
        self.assertEqual(expected_install_unit_id, repair_resp.json()["install_unit"]["install_unit_id"])


if __name__ == "__main__":
    unittest.main()
