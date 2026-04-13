from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .skills_astrbot_state_core import build_astrbot_state_index
    from .skills_aggregation_core import (
        PROVENANCE_FIELD_KEYS,
        build_collection_group_rows,
        build_compatible_aggregate_rows_by_software,
        build_install_unit_rows,
        derive_source_provenance_fields,
        enrich_source_aggregation,
    )
    from .skills_install_atoms_core import (
        apply_install_atom_registry,
        build_install_atom_registry,
        normalize_install_atom_registry,
    )
    from .skills_hosts_core import build_host_adapters, resolve_host_target_path
    from .skills_sources_core import build_skills_registry, normalize_skills_registry
    from .skills_update_core import (
        build_collection_group_update_plan,
        build_install_unit_update_plan,
    )
    from .source_sync_core import is_source_syncable
except ImportError:  # pragma: no cover - direct test imports
    from skills_astrbot_state_core import build_astrbot_state_index
    from skills_aggregation_core import (
        PROVENANCE_FIELD_KEYS,
        build_collection_group_rows,
        build_compatible_aggregate_rows_by_software,
        build_install_unit_rows,
        derive_source_provenance_fields,
        enrich_source_aggregation,
    )
    from skills_install_atoms_core import (
        apply_install_atom_registry,
        build_install_atom_registry,
        normalize_install_atom_registry,
    )
    from skills_hosts_core import build_host_adapters, resolve_host_target_path
    from skills_sources_core import build_skills_registry, normalize_skills_registry
    from skills_update_core import (
        build_collection_group_update_plan,
        build_install_unit_update_plan,
    )
    from source_sync_core import is_source_syncable

VALID_DEPLOY_SCOPES = ("global", "workspace")
SOURCE_FRESH_MAX_AGE_DAYS = 7
SOURCE_AGING_MAX_AGE_DAYS = 30

LEGACY_NPX_ROOT_BUNDLE_RULES = [
    {
        "legacy_source_id_prefix": "npx_bundle_codex_skill_pack_",
        "path_markers": ["/.codex/skills/"],
    },
    {
        "legacy_source_id_prefix": "npx_bundle_agent_skill_pack_",
        "path_markers": ["/.agents/skills/"],
    },
    {
        "legacy_source_id_prefix": "npx_bundle_claude_code_skill_pack_",
        "path_markers": ["/.claude/skills/"],
    },
    {
        "legacy_source_id_prefix": "npx_bundle_zeroclaw_skill_pack_",
        "path_markers": ["/zeroclaw/.claude/skills/", "/zeroclaw/src/skills/"],
    },
    {
        "legacy_source_id_prefix": "npx_bundle_astrbot_skill_pack_",
        "path_markers": ["/astrbot/data/skills/", "/.astrbot/data/skills/"],
    },
    {
        "legacy_source_id_prefix": "npx_bundle_antigravity_skill_pack_",
        "path_markers": ["/antigravity/skills/"],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_status_from_age(age_days: int | None, *, exists: bool) -> str:
    if not exists:
        return "missing"
    if age_days is None:
        return "fresh"
    if age_days <= SOURCE_FRESH_MAX_AGE_DAYS:
        return "fresh"
    if age_days <= SOURCE_AGING_MAX_AGE_DAYS:
        return "aging"
    return "stale"


def _refresh_source_freshness_from_sync(
    source_row: dict[str, Any],
    *,
    now_iso: str,
) -> dict[str, Any]:
    row = source_row if isinstance(source_row, dict) else {}
    source_exists = _to_bool(row.get("source_exists", False), False)
    if not source_exists:
        row["source_age_days"] = None
        row["freshness_status"] = "missing"
        return row

    freshness_anchor = _parse_iso_datetime(row.get("last_seen_at"))
    sync_ok = str(row.get("sync_status") or "").strip().lower() == "ok" and is_source_syncable(row)
    if sync_ok:
        for key in ("sync_checked_at", "last_refresh_at", "last_synced_at"):
            candidate = _parse_iso_datetime(row.get(key))
            if candidate and (freshness_anchor is None or candidate > freshness_anchor):
                freshness_anchor = candidate

    now_dt = _parse_iso_datetime(now_iso) or datetime.now(timezone.utc)
    age_days: int | None = None
    if freshness_anchor is not None:
        age_seconds = max(0.0, (now_dt - freshness_anchor).total_seconds())
        age_days = int(age_seconds // 86400)
    row["source_age_days"] = age_days
    row["freshness_status"] = _freshness_status_from_age(age_days, exists=source_exists)
    return row


def _slug(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text or default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "on"}:
            return True
        if norm in {"0", "false", "no", "off"}:
            return False
    return default


def _to_int(value: Any, default: int, min_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        parsed = min_value
    return parsed


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return _to_str_list(parsed)
        return [seg.strip() for seg in re.split(r"[\n,]+", text) if seg.strip()]
    return []


def _dedupe_keep_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _count_rows_by_field(rows: list[dict[str, Any]], field: str, expected: str) -> int:
    return sum(1 for item in rows if str(item.get(field, "")).strip() == expected)


def _count_syncable_rows(rows: list[dict[str, Any]]) -> int:
    return sum(1 for item in rows if is_source_syncable(item))


def _count_sync_dirty_rows(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in rows
        if is_source_syncable(item)
        and _to_bool(item.get("sync_dirty", False), False)
    )


def _count_sync_revision_drift_rows(rows: list[dict[str, Any]]) -> int:
    total = 0
    for item in rows:
        if not is_source_syncable(item):
            continue
        local_revision = str(item.get("sync_local_revision") or "").strip()
        remote_revision = str(item.get("sync_remote_revision") or "").strip()
        if local_revision and remote_revision and local_revision != remote_revision:
            total += 1
    return total


def _normalize_astrneo_source_id(host_id: Any, skill_key: Any) -> str:
    normalized_host_id = _slug(host_id, default="")
    normalized_skill_key = str(skill_key or "").strip()
    if not normalized_host_id or not normalized_skill_key:
        return ""
    return f"astrneo:{normalized_host_id}:{normalized_skill_key}"


def build_astrbot_neo_source_rows(astrbot_state_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows_by_source_id: dict[str, dict[str, Any]] = {}
    for item in (astrbot_state_rows or []):
        if not isinstance(item, dict):
            continue
        neo_skill_key = str(item.get("neo_skill_key") or "").strip()
        host_id = str(item.get("host_id") or "").strip()
        skill_name = str(item.get("skill_name") or "").strip()
        scope = str(item.get("scope") or "").strip().lower() or "global"
        source_id = _normalize_astrneo_source_id(host_id, neo_skill_key)
        if not source_id:
            continue
        local_exists = _to_bool(item.get("local_exists"), False)
        source_row = {
            "source_id": source_id,
            "display_name": skill_name or neo_skill_key,
            "source_kind": "astrneo_release",
            "provider_key": "astrbot",
            "source_scope": scope,
            "managed_by": "astrneo",
            "update_policy": "manual",
            "locator": f"astrneo:{neo_skill_key}",
            "source_path": str(item.get("local_path") or ""),
            "source_exists": local_exists,
            "status": "ready" if local_exists else "missing",
            "freshness_status": "fresh" if local_exists else "missing",
            "last_seen_at": str(item.get("neo_updated_at") or ""),
            "last_refresh_at": str(item.get("neo_updated_at") or ""),
            "member_count": 1,
            "member_skill_preview": [skill_name or neo_skill_key],
            "member_skill_overflow": 0,
            "compatible_software_ids": [host_id] if host_id else [],
            "compatible_software_families": ["astrbot"],
            "tags": ["astrneo-managed", "astrbot-runtime"],
            "astrneo_host_id": host_id,
            "astrneo_skill_name": skill_name,
            "astrneo_skill_key": neo_skill_key,
            "astrneo_release_id": str(item.get("neo_release_id") or ""),
            "astrneo_candidate_id": str(item.get("neo_candidate_id") or ""),
            "astrneo_payload_ref": str(item.get("neo_payload_ref") or ""),
            "astrneo_updated_at": str(item.get("neo_updated_at") or ""),
            "state_classification": str(item.get("state_classification") or ""),
            "drift_reasons": _to_str_list(item.get("drift_reasons", [])),
            "active": _to_bool(item.get("active"), True),
        }
        existing = rows_by_source_id.get(source_id)
        if existing is None:
            source_row["astrneo_scopes"] = [scope]
            rows_by_source_id[source_id] = source_row
            continue
        existing_scopes = _to_str_list(existing.get("astrneo_scopes", []))
        if scope and scope not in existing_scopes:
            existing_scopes.append(scope)
        existing["astrneo_scopes"] = existing_scopes
        if local_exists and not _to_bool(existing.get("source_exists"), False):
            source_row["astrneo_scopes"] = existing_scopes
            rows_by_source_id[source_id] = source_row

    rows = list(rows_by_source_id.values())
    rows.sort(
        key=lambda item: (
            str(item.get("display_name") or "").lower(),
            str(item.get("source_id") or "").lower(),
        ),
    )
    return rows


def _is_meaningful_collection_group_row(row: dict[str, Any]) -> bool:
    kind = str(row.get("collection_group_kind") or "").strip().lower()
    if kind and kind != "install_unit":
        return True
    if _to_int(row.get("install_unit_count", 0), 0, 0) > 1:
        return True
    if _to_int(row.get("source_count", 0), 0, 0) > 1:
        return True
    if _to_int(row.get("member_count", 0), 0, 0) > 1:
        return True
    return False


def build_meaningful_collection_group_rows(collection_group_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(item)
        for item in collection_group_rows
        if isinstance(item, dict) and _is_meaningful_collection_group_row(item)
    ]


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_scope(value: Any, default: str = "global") -> str:
    scope = _slug(value, default=default)
    if scope not in VALID_DEPLOY_SCOPES:
        scope = default
    return scope


def _target_path_exists(target_path: str) -> bool:
    text = str(target_path or "").strip()
    if not text:
        return False
    path = Path(text)
    return path.exists() and path.is_dir()


def _path_matches_markers(path_text: Any, markers: list[str]) -> bool:
    normalized = str(path_text or "").strip().replace("\\", "/").lower()
    if not normalized:
        return False
    for marker in markers:
        marker_text = str(marker or "").strip().replace("\\", "/").lower()
        if marker_text and marker_text in normalized:
            return True
    return False


def _saved_manifest_index(saved_manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    source_index: dict[str, dict[str, Any]] = {}
    for item in saved_manifest.get("sources", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        source_index[source_id] = copy.deepcopy(item)

    target_index: dict[str, dict[str, Any]] = {}
    for item in saved_manifest.get("deploy_targets", []):
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", "")).strip()
        if not target_id:
            continue
        target_index[target_id] = copy.deepcopy(item)
    return source_index, target_index


def _saved_lock_index(saved_lock: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    source_index: dict[str, dict[str, Any]] = {}
    for item in saved_lock.get("sources", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        source_index[source_id] = copy.deepcopy(item)

    target_index: dict[str, dict[str, Any]] = {}
    for item in saved_lock.get("deploy_targets", []):
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", "")).strip()
        if not target_id:
            continue
        target_index[target_id] = copy.deepcopy(item)
    return source_index, target_index


def normalize_saved_skills_manifest(raw: Any) -> dict[str, Any]:
    manifest = raw if isinstance(raw, dict) else {}
    sources: list[dict[str, Any]] = []
    for item in manifest.get("sources", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        source_record = {
            "source_id": source_id,
            "display_name": str(item.get("display_name") or source_id),
            "source_kind": str(item.get("source_kind") or "skill"),
            "provider_key": str(item.get("provider_key") or "generic"),
            "enabled": _to_bool(item.get("enabled", True), True),
            "source_scope": str(item.get("source_scope") or "global"),
            "update_policy": str(item.get("update_policy") or ""),
            "compatible_software_ids": _dedupe_keep_order(_to_str_list(item.get("compatible_software_ids", []))),
            "compatible_software_families": _dedupe_keep_order(_to_str_list(item.get("compatible_software_families", []))),
            "tags": _dedupe_keep_order(_to_str_list(item.get("tags", []))),
        }
        source_record.update(enrich_source_aggregation(source_record))
        sources.append(source_record)

    deploy_targets: list[dict[str, Any]] = []
    for item in manifest.get("deploy_targets", []):
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", "")).strip()
        if not target_id:
            continue
        deploy_targets.append(
            {
                "target_id": target_id,
                "software_id": str(item.get("software_id") or ""),
                "scope": _normalize_scope(item.get("scope", "global")),
                "selected_source_ids": _dedupe_keep_order(_to_str_list(item.get("selected_source_ids", []))),
            },
        )

    return {
        "version": _to_int(manifest.get("version", 1), 1, 1),
        "generated_at": str(manifest.get("generated_at") or ""),
        "sources": sources,
        "deploy_targets": deploy_targets,
    }


def normalize_saved_skills_lock(raw: Any) -> dict[str, Any]:
    lock = raw if isinstance(raw, dict) else {}

    sources: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for item in lock.get("sources", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id or source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        source_age_days = item.get("source_age_days")
        source_record = {
            "source_id": source_id,
            "display_name": str(item.get("display_name") or source_id),
            "source_kind": str(item.get("source_kind") or "skill"),
            "provider_key": str(item.get("provider_key") or "generic"),
            "enabled": _to_bool(item.get("enabled", True), True),
            "discovered": _to_bool(item.get("discovered", False), False),
            "auto_discovered": _to_bool(item.get("auto_discovered", False), False),
            "source_scope": str(item.get("source_scope") or "global"),
            "source_path": str(item.get("source_path") or ""),
            "locator": str(item.get("locator") or ""),
            "source_subpath": str(item.get("source_subpath") or ""),
            "managed_by": str(item.get("managed_by") or ""),
            "update_policy": str(item.get("update_policy") or ""),
            "member_count": _to_int(item.get("member_count", 1), 1, 1),
            "member_skill_preview": _to_str_list(item.get("member_skill_preview", [])),
            "member_skill_overflow": _to_int(item.get("member_skill_overflow", 0), 0, 0),
            "management_hint": str(item.get("management_hint") or ""),
            "source_exists": _to_bool(item.get("source_exists", False), False),
            "last_seen_at": str(item.get("last_seen_at") or ""),
            "last_refresh_at": str(item.get("last_refresh_at") or ""),
            "source_age_days": _to_int(source_age_days, 0) if source_age_days is not None else None,
            "freshness_status": str(item.get("freshness_status") or "missing"),
            "registry_package_name": str(item.get("registry_package_name") or ""),
            "registry_package_manager": str(item.get("registry_package_manager") or ""),
            "sync_auth_token": str(item.get("sync_auth_token") or ""),
            "sync_auth_header": str(item.get("sync_auth_header") or ""),
            "sync_api_base": str(item.get("sync_api_base") or ""),
            "sync_status": str(item.get("sync_status") or ""),
            "sync_checked_at": str(item.get("sync_checked_at") or ""),
            "sync_kind": str(item.get("sync_kind") or ""),
            "sync_message": str(item.get("sync_message") or ""),
            "sync_local_revision": str(item.get("sync_local_revision") or ""),
            "sync_remote_revision": str(item.get("sync_remote_revision") or ""),
            "sync_resolved_revision": str(item.get("sync_resolved_revision") or ""),
            "sync_branch": str(item.get("sync_branch") or ""),
            "sync_dirty": _to_bool(item.get("sync_dirty", False), False),
            "sync_error_code": str(item.get("sync_error_code") or ""),
            "registry_latest_version": str(item.get("registry_latest_version") or ""),
            "registry_published_at": str(item.get("registry_published_at") or ""),
            "registry_homepage": str(item.get("registry_homepage") or ""),
            "registry_description": str(item.get("registry_description") or ""),
            "compatible_software_ids": _dedupe_keep_order(_to_str_list(item.get("compatible_software_ids", []))),
            "compatible_software_families": _dedupe_keep_order(_to_str_list(item.get("compatible_software_families", []))),
            "tags": _dedupe_keep_order(_to_str_list(item.get("tags", []))),
            "status": str(item.get("status") or ""),
            "deployed_target_ids": _dedupe_keep_order(_to_str_list(item.get("deployed_target_ids", []))),
            "deployed_target_count": _to_int(item.get("deployed_target_count", 0), 0, 0),
            "resolution_hash": str(item.get("resolution_hash") or ""),
            "last_synced_at": str(item.get("last_synced_at") or ""),
            "install_unit_id": str(item.get("install_unit_id") or ""),
            "install_unit_kind": str(item.get("install_unit_kind") or ""),
            "install_ref": str(item.get("install_ref") or ""),
            "install_manager": str(item.get("install_manager") or ""),
            "install_unit_display_name": str(item.get("install_unit_display_name") or ""),
            "aggregation_strategy": str(item.get("aggregation_strategy") or ""),
            "collection_group_id": str(item.get("collection_group_id") or ""),
            "collection_group_name": str(item.get("collection_group_name") or ""),
            "collection_group_kind": str(item.get("collection_group_kind") or ""),
        }
        for field_name in PROVENANCE_FIELD_KEYS:
            source_record[field_name] = str(item.get(field_name) or "")
        source_record.update(derive_source_provenance_fields(source_record))
        source_record.update(enrich_source_aggregation(source_record))
        sources.append(source_record)

    deploy_targets: list[dict[str, Any]] = []
    seen_target_ids: set[str] = set()
    for item in lock.get("deploy_targets", []):
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", "")).strip()
        if not target_id or target_id in seen_target_ids:
            continue
        seen_target_ids.add(target_id)
        deploy_targets.append(
            {
                "target_id": target_id,
                "software_id": str(item.get("software_id") or ""),
                "software_display_name": str(item.get("software_display_name") or item.get("software_id") or ""),
                "software_family": str(item.get("software_family") or item.get("provider_key") or item.get("software_id") or ""),
                "software_kind": str(item.get("software_kind") or item.get("kind") or "other"),
                "provider_key": str(item.get("provider_key") or "generic"),
                "scope": _normalize_scope(item.get("scope", "global")),
                "installed": _to_bool(item.get("installed", False), False),
                "managed": _to_bool(item.get("managed", False), False),
                "linked_target_name": str(item.get("linked_target_name") or ""),
                "target_path": str(item.get("target_path") or ""),
                "declared_skill_roots": _dedupe_keep_order(_to_str_list(item.get("declared_skill_roots", []))),
                "resolved_skill_roots": _dedupe_keep_order(_to_str_list(item.get("resolved_skill_roots", []))),
                "available_source_ids": _dedupe_keep_order(_to_str_list(item.get("available_source_ids", []))),
                "selected_source_ids": _dedupe_keep_order(_to_str_list(item.get("selected_source_ids", []))),
                "status": str(item.get("status") or ""),
                "drift_status": str(item.get("drift_status") or ""),
                "target_path_exists": _to_bool(item.get("target_path_exists", False), False),
                "ready_source_ids": _dedupe_keep_order(_to_str_list(item.get("ready_source_ids", []))),
                "missing_source_ids": _dedupe_keep_order(_to_str_list(item.get("missing_source_ids", []))),
                "incompatible_source_ids": _dedupe_keep_order(_to_str_list(item.get("incompatible_source_ids", []))),
                "available_source_count": _to_int(item.get("available_source_count", 0), 0, 0),
                "selected_source_count": _to_int(item.get("selected_source_count", 0), 0, 0),
                "ready_source_count": _to_int(item.get("ready_source_count", 0), 0, 0),
                "repair_actions": _dedupe_keep_order(_to_str_list(item.get("repair_actions", []))),
                "deployment_hash": str(item.get("deployment_hash") or ""),
                "last_synced_at": str(item.get("last_synced_at") or ""),
            },
        )

    return {
        "version": _to_int(lock.get("version", 1), 1, 1),
        "generated_at": str(lock.get("generated_at") or ""),
        "sources": sources,
        "deploy_targets": deploy_targets,
    }


def manifest_to_binding_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in manifest.get("deploy_targets", []):
        if not isinstance(item, dict):
            continue
        software_id = str(item.get("software_id", "")).strip()
        if not software_id:
            continue
        scope = _normalize_scope(item.get("scope", "global"))
        for source_id in _dedupe_keep_order(_to_str_list(item.get("selected_source_ids", []))):
            rows.append(
                {
                    "software_id": software_id,
                    "skill_id": source_id,
                    "scope": scope,
                    "enabled": True,
                    "settings": {},
                },
            )
    return rows


def project_inventory_snapshot_bindings_from_manifest(
    inventory_snapshot: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    snapshot = copy.deepcopy(inventory_snapshot if isinstance(inventory_snapshot, dict) else {})
    software_rows = [
        item
        for item in snapshot.get("software_rows", [])
        if isinstance(item, dict)
    ]
    skill_rows = [
        item
        for item in snapshot.get("skill_rows", [])
        if isinstance(item, dict)
    ]
    compatibility_raw = snapshot.get("compatibility", {})
    compatibility = compatibility_raw if isinstance(compatibility_raw, dict) else {}
    software_ids = [
        str(item.get("id") or "").strip()
        for item in software_rows
        if str(item.get("id") or "").strip()
    ]
    software_index = {
        str(item.get("id") or "").strip(): item
        for item in software_rows
        if str(item.get("id") or "").strip()
    }
    skill_index = {
        str(item.get("id") or "").strip(): item
        for item in skill_rows
        if str(item.get("id") or "").strip()
    }

    binding_map: dict[str, list[str]] = {software_id: [] for software_id in software_ids}
    binding_map_by_scope: dict[str, dict[str, list[str]]] = {
        scope: {software_id: [] for software_id in software_ids}
        for scope in VALID_DEPLOY_SCOPES
    }
    binding_rows: list[dict[str, Any]] = []
    valid_binding_count = 0
    invalid_binding_count = 0

    for binding in manifest_to_binding_rows(manifest if isinstance(manifest, dict) else {}):
        software_id = str(binding.get("software_id") or "").strip()
        skill_id = str(binding.get("skill_id") or "").strip()
        scope = _normalize_scope(binding.get("scope", "global"))
        enabled = _to_bool(binding.get("enabled", True), True)
        valid = True
        invalid_reason = ""

        software = software_index.get(software_id)
        skill = skill_index.get(skill_id)
        if not software:
            valid = False
            invalid_reason = "software_not_found"
        elif not skill:
            valid = False
            invalid_reason = "skill_not_found"
        elif skill_id not in set(_to_str_list(compatibility.get(software_id, []))):
            valid = False
            invalid_reason = "incompatible_kind"

        if valid and enabled:
            skill_ids = binding_map.setdefault(software_id, [])
            if skill_id not in skill_ids:
                skill_ids.append(skill_id)
            scoped_map = binding_map_by_scope.setdefault(scope, {sid: [] for sid in software_ids})
            scoped_list = scoped_map.setdefault(software_id, [])
            if skill_id not in scoped_list:
                scoped_list.append(skill_id)
            valid_binding_count += 1
        elif not valid:
            invalid_binding_count += 1

        binding_rows.append(
            {
                "software_id": software_id,
                "skill_id": skill_id,
                "scope": scope,
                "enabled": enabled,
                "valid": valid,
                "reason": invalid_reason,
            },
        )

    for software_id in software_ids:
        software = software_index.get(software_id)
        if not software:
            continue
        software["binding_count"] = len(binding_map.get(software_id, []))

    skill_binding_reverse: dict[str, set[str]] = {}
    for software_id, skill_ids in binding_map.items():
        for skill_id in skill_ids:
            owners = skill_binding_reverse.setdefault(skill_id, set())
            owners.add(software_id)

    for skill in skill_rows:
        skill_id = str(skill.get("id") or "").strip()
        owners = sorted(skill_binding_reverse.get(skill_id, set()))
        skill["bound_software_count"] = len(owners)
        skill["bound_software_ids"] = owners

    counts = snapshot.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    counts = {
        **counts,
        "bindings_total": len(binding_rows),
        "bindings_valid": valid_binding_count,
        "bindings_invalid": invalid_binding_count,
    }

    existing_warnings = [
        str(item or "").strip()
        for item in snapshot.get("warnings", [])
        if str(item or "").strip()
    ] if isinstance(snapshot.get("warnings", []), list) else []
    warnings = [
        warning
        for warning in existing_warnings
        if not warning.startswith("binding[")
    ]
    for binding in binding_rows:
        if not _to_bool(binding.get("valid", False), False):
            warnings.append(
                f"binding[{binding.get('software_id')}->{binding.get('skill_id')}] is invalid: {binding.get('reason')}",
            )

    snapshot["software_rows"] = software_rows
    snapshot["skill_rows"] = skill_rows
    snapshot["binding_rows"] = binding_rows
    snapshot["binding_map"] = binding_map
    snapshot["binding_map_by_scope"] = binding_map_by_scope
    snapshot["counts"] = counts
    snapshot["warnings"] = warnings
    return snapshot


def _project_binding_state_from_manifest(
    manifest: dict[str, Any],
    *,
    source_rows: list[dict[str, Any]],
    software_hosts: list[dict[str, Any]],
    inventory_compatibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_index = {
        str(item.get("source_id") or item.get("id") or "").strip(): copy.deepcopy(item)
        for item in source_rows
        if isinstance(item, dict) and str(item.get("source_id") or item.get("id") or "").strip()
    }
    host_index = {
        str(item.get("host_id") or item.get("id") or "").strip(): copy.deepcopy(item)
        for item in software_hosts
        if isinstance(item, dict) and str(item.get("host_id") or item.get("id") or "").strip()
    }
    software_ids = _dedupe_keep_order(
        list(host_index.keys())
        + [
            str(item.get("software_id") or "").strip()
            for item in manifest.get("deploy_targets", [])
            if isinstance(item, dict) and str(item.get("software_id") or "").strip()
        ],
    )
    for software_id in software_ids:
        if software_id not in host_index:
            host_index[software_id] = {
                "id": software_id,
                "host_id": software_id,
                "software_family": software_id,
                "family": software_id,
            }

    manifest_selected_hosts_by_source: dict[str, set[str]] = {}
    manifest_available_hosts_by_source: dict[str, set[str]] = {}
    for target in manifest.get("deploy_targets", []):
        if not isinstance(target, dict):
            continue
        software_id = str(target.get("software_id") or "").strip()
        if not software_id:
            continue
        for source_id in _to_str_list(target.get("selected_source_ids", [])):
            if not source_id:
                continue
            manifest_selected_hosts_by_source.setdefault(source_id, set()).add(software_id)
        for source_id in _to_str_list(target.get("available_source_ids", [])):
            if not source_id:
                continue
            manifest_available_hosts_by_source.setdefault(source_id, set()).add(software_id)

    inventory_compatibility_map: dict[str, list[str]] = {}
    inventory_hint_hosts_by_source: dict[str, set[str]] = {}
    compatibility_raw = inventory_compatibility if isinstance(inventory_compatibility, dict) else {}
    for software_id, source_ids in compatibility_raw.items():
        normalized_software_id = str(software_id or "").strip()
        if not normalized_software_id:
            continue
        normalized_source_ids = _dedupe_keep_order(_to_str_list(source_ids))
        inventory_compatibility_map[normalized_software_id] = normalized_source_ids
        for source_id in normalized_source_ids:
            inventory_hint_hosts_by_source.setdefault(source_id, set()).add(normalized_software_id)

    compatibility: dict[str, list[str]] = {}
    for software_id in software_ids:
        host = host_index.get(software_id, {"host_id": software_id, "id": software_id})
        compatible_source_ids: list[str] = []
        for source_id, source in source_index.items():
            explicit_constraints = bool(
                _to_str_list(source.get("compatible_software_ids", []))
                or _to_str_list(source.get("compatible_software_families", [])),
            )
            if explicit_constraints:
                if _source_matches_host(source, host, None):
                    compatible_source_ids.append(source_id)
                continue

            selected_hint_hosts = manifest_selected_hosts_by_source.get(source_id, set())
            if selected_hint_hosts:
                if software_id in selected_hint_hosts:
                    compatible_source_ids.append(source_id)
                continue

            available_hint_hosts = manifest_available_hosts_by_source.get(source_id, set())
            if available_hint_hosts:
                if software_id in available_hint_hosts:
                    compatible_source_ids.append(source_id)
                continue

            inventory_hint_hosts = inventory_hint_hosts_by_source.get(source_id, set())
            if inventory_hint_hosts:
                if software_id in inventory_hint_hosts:
                    compatible_source_ids.append(source_id)
                continue

            # No authority hints: keep permissive fallback for generic/manual sources.
            compatible_source_ids.append(source_id)
        compatibility[software_id] = _dedupe_keep_order(compatible_source_ids)

    binding_rows: list[dict[str, Any]] = []
    binding_map: dict[str, list[str]] = {software_id: [] for software_id in software_ids}
    binding_map_by_scope: dict[str, dict[str, list[str]]] = {
        scope: {software_id: [] for software_id in software_ids}
        for scope in VALID_DEPLOY_SCOPES
    }
    valid_total = 0
    invalid_total = 0
    warnings: list[str] = []
    compatible_id_sets = {
        software_id: set(_to_str_list(source_ids))
        for software_id, source_ids in compatibility.items()
    }

    for binding in manifest_to_binding_rows(manifest if isinstance(manifest, dict) else {}):
        software_id = str(binding.get("software_id") or "").strip()
        source_id = str(binding.get("skill_id") or "").strip()
        scope = _normalize_scope(binding.get("scope", "global"))
        enabled = _to_bool(binding.get("enabled", True), True)
        valid = True
        reason = ""

        if software_id not in set(software_ids):
            valid = False
            reason = "software_not_found"
        elif source_id not in source_index:
            valid = False
            reason = "skill_not_found"
        elif source_id not in compatible_id_sets.get(software_id, set()):
            valid = False
            reason = "incompatible_kind"

        if valid and enabled:
            software_bindings = binding_map.setdefault(software_id, [])
            if source_id not in software_bindings:
                software_bindings.append(source_id)
            scoped_map = binding_map_by_scope.setdefault(
                scope,
                {sid: [] for sid in software_ids},
            )
            scoped_bindings = scoped_map.setdefault(software_id, [])
            if source_id not in scoped_bindings:
                scoped_bindings.append(source_id)
            valid_total += 1
        elif not valid:
            invalid_total += 1
            warnings.append(
                f"binding[{software_id}->{source_id}] is invalid: {reason}",
            )

        binding_rows.append(
            {
                "software_id": software_id,
                "skill_id": source_id,
                "scope": scope,
                "enabled": enabled,
                "valid": valid,
                "reason": reason,
            },
        )

    return {
        "binding_rows": binding_rows,
        "binding_map": binding_map,
        "binding_map_by_scope": binding_map_by_scope,
        "compatibility": compatibility,
        "counts": {
            "bindings_total": len(binding_rows),
            "bindings_valid": valid_total,
            "bindings_invalid": invalid_total,
        },
        "warnings": warnings,
    }


def _source_matches_host(
    source: dict[str, Any],
    host: dict[str, Any],
    compatibility: dict[str, Any] | None = None,
) -> bool:
    host_id = str(host.get("host_id") or host.get("id") or "").strip()
    host_family = str(host.get("family") or host.get("software_family") or host_id).strip()
    compatible_ids = set(_dedupe_keep_order(_to_str_list(source.get("compatible_software_ids", []))))
    if compatible_ids:
        return host_id in compatible_ids

    compatible_families = set(_dedupe_keep_order(_to_str_list(source.get("compatible_software_families", []))))
    if compatible_families:
        return host_family in compatible_families or host_id in compatible_families

    compat_map = compatibility if isinstance(compatibility, dict) else {}
    if host_id and host_id in compat_map:
        return str(source.get("source_id", "")).strip() in set(_to_str_list(compat_map.get(host_id, [])))
    return True


def _match_legacy_root_bundle(source_id: str) -> tuple[dict[str, Any], str] | None:
    normalized_source_id = str(source_id or "").strip().lower()
    if not normalized_source_id:
        return None
    for rule in LEGACY_NPX_ROOT_BUNDLE_RULES:
        legacy_prefix = str(rule.get("legacy_source_id_prefix", "")).strip().lower()
        if not legacy_prefix or not normalized_source_id.startswith(legacy_prefix):
            continue
        scope_suffix = normalized_source_id[len(legacy_prefix) :].strip()
        if scope_suffix:
            return rule, scope_suffix
    return None


def _legacy_root_bundle_replacement_ids(
    source_id: str,
    *,
    sources: list[dict[str, Any]],
    host: dict[str, Any] | None = None,
    compatibility: dict[str, Any] | None = None,
) -> list[str]:
    matched = _match_legacy_root_bundle(source_id)
    if not matched:
        return []
    matched_rule, scope_suffix = matched
    source_id_prefix = f"npx_{scope_suffix}_"
    replacement_ids: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        candidate_id = str(source.get("source_id", "")).strip()
        if not candidate_id or candidate_id == source_id:
            continue
        if str(source.get("source_kind", "")).strip() != "npx_single":
            continue
        if not candidate_id.startswith(source_id_prefix):
            continue
        if not _path_matches_markers(source.get("source_path", ""), _to_str_list(matched_rule.get("path_markers", []))):
            continue
        if host is not None and not _source_matches_host(source, host, compatibility):
            continue
        replacement_ids.append(candidate_id)
    return _dedupe_keep_order(replacement_ids)


def _drop_legacy_root_bundle_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", "")).strip()
        if source_id and _legacy_root_bundle_replacement_ids(source_id, sources=sources):
            continue
        filtered.append(source)
    return filtered


def _expand_legacy_root_bundle_selection(
    selected_source_ids: list[str],
    *,
    sources: list[dict[str, Any]],
    host: dict[str, Any],
    compatibility: dict[str, Any] | None = None,
) -> list[str]:
    current_source_ids = {
        str(item.get("source_id", "")).strip()
        for item in sources
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }
    expanded: list[str] = []

    for selected_source_id in _dedupe_keep_order(_to_str_list(selected_source_ids)):
        replacement_ids = _legacy_root_bundle_replacement_ids(
            selected_source_id,
            sources=sources,
            host=host,
            compatibility=compatibility,
        )
        if replacement_ids:
            expanded.extend(replacement_ids)
            continue
        if selected_source_id in current_source_ids:
            expanded.append(selected_source_id)
            continue
        expanded.append(selected_source_id)

    return _dedupe_keep_order(expanded)


def build_skills_manifest(
    inventory_snapshot: dict[str, Any],
    *,
    saved_manifest: dict[str, Any] | None = None,
    saved_registry: dict[str, Any] | None = None,
    saved_lock: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    host_rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    normalized_saved_manifest = normalize_saved_skills_manifest(saved_manifest or {})
    normalized_saved_lock = normalize_saved_skills_lock(saved_lock or {})
    saved_source_index, saved_target_index = _saved_manifest_index(normalized_saved_manifest)
    _, saved_lock_target_index = _saved_lock_index(normalized_saved_lock)
    software_rows = [
        copy.deepcopy(item)
        for item in inventory_snapshot.get("software_rows", [])
        if isinstance(item, dict)
    ]
    skill_rows = [
        copy.deepcopy(item)
        for item in inventory_snapshot.get("skill_rows", [])
        if isinstance(item, dict)
    ]
    compatibility_raw = inventory_snapshot.get("compatibility", {})
    compatibility = compatibility_raw if isinstance(compatibility_raw, dict) else {}
    binding_map_by_scope_raw = inventory_snapshot.get("binding_map_by_scope", {})
    binding_map_by_scope = binding_map_by_scope_raw if isinstance(binding_map_by_scope_raw, dict) else {}
    runtime_registry = registry if isinstance(registry, dict) else build_skills_registry(
        skill_rows,
        saved_registry=saved_registry,
        generated_at=ts,
    )

    compatible_hosts_by_source: dict[str, list[str]] = {}
    for software_id, skill_ids in compatibility.items():
        host_id = str(software_id or "").strip()
        for skill_id in _to_str_list(skill_ids):
            compatible_hosts_by_source.setdefault(skill_id, []).append(host_id)

    software_hosts = [
        copy.deepcopy(item)
        for item in (host_rows if isinstance(host_rows, list) else build_host_adapters(software_rows))
        if isinstance(item, dict)
    ]

    sources: list[dict[str, Any]] = []
    for item in runtime_registry.get("sources", []):
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        saved_source = saved_source_index.get(source_id, {})
        authoritative_compatible_hosts = _dedupe_keep_order(
            _to_str_list(item.get("compatible_software_ids", []))
            + _to_str_list(saved_source.get("compatible_software_ids", [])),
        )
        authoritative_compatible_families = _dedupe_keep_order(
            _to_str_list(item.get("compatible_software_families", []))
            + _to_str_list(saved_source.get("compatible_software_families", [])),
        )
        has_authoritative_constraints = bool(authoritative_compatible_hosts or authoritative_compatible_families)
        derived_hosts_from_families: list[str] = []
        if authoritative_compatible_families:
            family_set = set(authoritative_compatible_families)
            for host in software_hosts:
                host_id = str(host.get("host_id") or host.get("id") or "").strip()
                host_family = str(host.get("family") or host.get("software_family") or host_id).strip()
                if not host_id:
                    continue
                if host_id in family_set or host_family in family_set:
                    derived_hosts_from_families.append(host_id)
        compatible_hosts = _dedupe_keep_order(
            authoritative_compatible_hosts
            or derived_hosts_from_families
            or ([] if has_authoritative_constraints else compatible_hosts_by_source.get(source_id, [])),
        )
        source_record = {
                "source_id": source_id,
                "display_name": str(item.get("display_name") or saved_source.get("display_name") or source_id),
                "source_kind": str(item.get("source_kind") or saved_source.get("source_kind") or "skill"),
                "provider_key": str(item.get("provider_key") or saved_source.get("provider_key") or "generic"),
                "enabled": _to_bool(saved_source.get("enabled", item.get("enabled", True)), True),
                "discovered": _to_bool(item.get("discovered", saved_source.get("discovered", False)), False),
                "auto_discovered": _to_bool(item.get("auto_discovered", saved_source.get("auto_discovered", False)), False),
                "source_scope": str(item.get("source_scope") or saved_source.get("source_scope") or "global"),
                "source_path": str(item.get("source_path") or saved_source.get("source_path") or ""),
                "locator": str(item.get("locator") or saved_source.get("locator") or ""),
                "source_subpath": str(item.get("source_subpath") or saved_source.get("source_subpath") or ""),
                "managed_by": str(item.get("managed_by") or saved_source.get("managed_by") or ""),
                "update_policy": str(item.get("update_policy") or saved_source.get("update_policy") or ""),
                "member_count": _to_int(item.get("member_count", saved_source.get("member_count", 1)), 1, 1),
                "member_skill_preview": _to_str_list(item.get("member_skill_preview", []) or saved_source.get("member_skill_preview", [])),
                "member_skill_overflow": _to_int(item.get("member_skill_overflow", saved_source.get("member_skill_overflow", 0)), 0, 0),
                "management_hint": str(item.get("management_hint") or saved_source.get("management_hint") or ""),
                "source_exists": _to_bool(item.get("source_exists", saved_source.get("source_exists", False)), False),
                "last_seen_at": str(item.get("last_seen_at") or saved_source.get("last_seen_at") or ""),
                "last_refresh_at": str(item.get("last_refresh_at") or saved_source.get("last_refresh_at") or ""),
                "source_age_days": (
                    _to_int(item.get("source_age_days", saved_source.get("source_age_days")), 0)
                    if item.get("source_age_days", saved_source.get("source_age_days")) is not None
                    else None
                ),
                "freshness_status": str(item.get("freshness_status") or saved_source.get("freshness_status") or "missing"),
                "registry_package_name": str(item.get("registry_package_name") or saved_source.get("registry_package_name") or ""),
                "registry_package_manager": str(item.get("registry_package_manager") or saved_source.get("registry_package_manager") or ""),
                "sync_auth_token": str(item.get("sync_auth_token") or saved_source.get("sync_auth_token") or ""),
                "sync_auth_header": str(item.get("sync_auth_header") or saved_source.get("sync_auth_header") or ""),
                "sync_api_base": str(item.get("sync_api_base") or saved_source.get("sync_api_base") or ""),
                "sync_status": str(item.get("sync_status") or saved_source.get("sync_status") or ""),
                "sync_checked_at": str(item.get("sync_checked_at") or saved_source.get("sync_checked_at") or ""),
                "sync_kind": str(item.get("sync_kind") or saved_source.get("sync_kind") or ""),
                "sync_message": str(item.get("sync_message") or saved_source.get("sync_message") or ""),
                "sync_local_revision": str(item.get("sync_local_revision") or saved_source.get("sync_local_revision") or ""),
                "sync_remote_revision": str(item.get("sync_remote_revision") or saved_source.get("sync_remote_revision") or ""),
                "sync_resolved_revision": str(item.get("sync_resolved_revision") or saved_source.get("sync_resolved_revision") or ""),
                "sync_branch": str(item.get("sync_branch") or saved_source.get("sync_branch") or ""),
                "sync_dirty": _to_bool(item.get("sync_dirty", saved_source.get("sync_dirty", False)), False),
                "sync_error_code": str(item.get("sync_error_code") or saved_source.get("sync_error_code") or ""),
                "registry_latest_version": str(item.get("registry_latest_version") or saved_source.get("registry_latest_version") or ""),
                "registry_published_at": str(item.get("registry_published_at") or saved_source.get("registry_published_at") or ""),
                "registry_homepage": str(item.get("registry_homepage") or saved_source.get("registry_homepage") or ""),
                "registry_description": str(item.get("registry_description") or saved_source.get("registry_description") or ""),
                "compatible_software_ids": compatible_hosts,
                "compatible_software_families": _to_str_list(item.get("compatible_software_families", []) or saved_source.get("compatible_software_families", [])),
                "tags": _dedupe_keep_order(_to_str_list(item.get("tags", [])) + _to_str_list(saved_source.get("tags", []))),
            }
        source_record.update(enrich_source_aggregation({**saved_source, **item, **source_record}))
        sources.append(source_record)

    discovered_source_ids = {str(item.get("source_id", "")).strip() for item in sources}
    for source_id, saved_source in saved_source_index.items():
        if source_id in discovered_source_ids:
            continue
        source_record = {
                "source_id": source_id,
                "display_name": str(saved_source.get("display_name") or source_id),
                "source_kind": str(saved_source.get("source_kind") or "skill"),
                "provider_key": str(saved_source.get("provider_key") or "generic"),
                "enabled": _to_bool(saved_source.get("enabled", True), True),
                "discovered": False,
                "auto_discovered": _to_bool(saved_source.get("auto_discovered", False), False),
                "source_scope": str(saved_source.get("source_scope") or "global"),
                "source_path": str(saved_source.get("source_path") or ""),
                "locator": str(saved_source.get("locator") or ""),
                "source_subpath": str(saved_source.get("source_subpath") or ""),
                "managed_by": str(saved_source.get("managed_by") or ""),
                "update_policy": str(saved_source.get("update_policy") or ""),
                "member_count": _to_int(saved_source.get("member_count", 1), 1, 1),
                "member_skill_preview": _to_str_list(saved_source.get("member_skill_preview", [])),
                "member_skill_overflow": _to_int(saved_source.get("member_skill_overflow", 0), 0, 0),
                "management_hint": str(saved_source.get("management_hint") or ""),
                "source_exists": _to_bool(saved_source.get("source_exists", False), False),
                "last_seen_at": str(saved_source.get("last_seen_at") or ""),
                "last_refresh_at": str(saved_source.get("last_refresh_at") or ""),
                "source_age_days": (
                    _to_int(saved_source.get("source_age_days"), 0)
                    if saved_source.get("source_age_days") is not None
                    else None
                ),
                "freshness_status": str(saved_source.get("freshness_status") or "missing"),
                "registry_package_name": str(saved_source.get("registry_package_name") or ""),
                "registry_package_manager": str(saved_source.get("registry_package_manager") or ""),
                "sync_auth_token": str(saved_source.get("sync_auth_token") or ""),
                "sync_auth_header": str(saved_source.get("sync_auth_header") or ""),
                "sync_api_base": str(saved_source.get("sync_api_base") or ""),
                "sync_status": str(saved_source.get("sync_status") or ""),
                "sync_checked_at": str(saved_source.get("sync_checked_at") or ""),
                "sync_kind": str(saved_source.get("sync_kind") or ""),
                "sync_message": str(saved_source.get("sync_message") or ""),
                "sync_local_revision": str(saved_source.get("sync_local_revision") or ""),
                "sync_remote_revision": str(saved_source.get("sync_remote_revision") or ""),
                "sync_resolved_revision": str(saved_source.get("sync_resolved_revision") or ""),
                "sync_branch": str(saved_source.get("sync_branch") or ""),
                "sync_dirty": _to_bool(saved_source.get("sync_dirty", False), False),
                "sync_error_code": str(saved_source.get("sync_error_code") or ""),
                "registry_latest_version": str(saved_source.get("registry_latest_version") or ""),
                "registry_published_at": str(saved_source.get("registry_published_at") or ""),
                "registry_homepage": str(saved_source.get("registry_homepage") or ""),
                "registry_description": str(saved_source.get("registry_description") or ""),
                "compatible_software_ids": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_ids", []))),
                "compatible_software_families": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_families", []))),
                "tags": _dedupe_keep_order(_to_str_list(saved_source.get("tags", []))),
            }
        source_record.update(enrich_source_aggregation({**saved_source, **source_record}))
        sources.append(source_record)
    sources = _drop_legacy_root_bundle_sources(sources)

    deploy_targets: list[dict[str, Any]] = []
    for host in software_hosts:
        software_id = str(host.get("host_id") or host.get("id") or "")
        for scope in VALID_DEPLOY_SCOPES:
            target_id = f"{software_id}:{scope}"
            selected_from_inventory = _dedupe_keep_order(
                _to_str_list(binding_map_by_scope.get(scope, {}).get(software_id, [])),
            )
            saved_target = saved_target_index.get(target_id, {})
            saved_target_has_selection = isinstance(saved_target, dict) and "selected_source_ids" in saved_target
            saved_lock_target = saved_lock_target_index.get(target_id, {})
            saved_lock_selected_ids = _dedupe_keep_order(
                _to_str_list(saved_lock_target.get("selected_source_ids", [])),
            )
            selected_ids = (
                _dedupe_keep_order(_to_str_list(saved_target.get("selected_source_ids", [])))
                if saved_target_has_selection
                else (
                    saved_lock_selected_ids
                    if saved_lock_selected_ids
                    else selected_from_inventory
                )
            )
            selected_ids = _expand_legacy_root_bundle_selection(
                selected_ids,
                sources=sources,
                host=host,
                compatibility=compatibility,
            )
            deploy_targets.append(
                {
                    "target_id": target_id,
                    "software_id": software_id,
                    "software_display_name": str(host.get("display_name") or software_id),
                    "software_family": str(host.get("family") or host.get("software_family") or software_id),
                    "provider_key": str(host.get("provider_key") or "generic"),
                    "scope": scope,
                    "installed": _to_bool(host.get("installed", False), False),
                    "managed": _to_bool(host.get("managed", False), False),
                    "linked_target_name": str(host.get("linked_target_name") or ""),
                    "target_path": resolve_host_target_path(host, scope),
                    "available_source_ids": [
                        str(source.get("source_id", "")).strip()
                        for source in sources
                        if _source_matches_host(source, host, compatibility)
                    ],
                    "selected_source_ids": selected_ids,
                },
            )

    return {
        "version": 1,
        "generated_at": ts,
        "software_hosts": software_hosts,
        "sources": sorted(sources, key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("source_id", "")).lower())),
        "deploy_targets": deploy_targets,
    }


def build_skills_lock(
    manifest: dict[str, Any],
    inventory_snapshot: dict[str, Any],
    *,
    registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    source_index = {
        str(item.get("source_id", "")).strip(): item
        for item in manifest.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }
    normalized_registry = normalize_skills_registry(registry or {}) if isinstance(registry, dict) else {"sources": []}
    registry_source_index = {
        str(item.get("source_id", "")).strip(): item
        for item in normalized_registry.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }

    source_locks: list[dict[str, Any]] = []
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", "")).strip()
        resolved_source = _merge_overlay_row(copy.deepcopy(source), registry_source_index.get(source_id, {}))
        resolved_source.update(derive_source_provenance_fields(resolved_source))
        resolved_source.update(enrich_source_aggregation(resolved_source))
        resolved_source = _refresh_source_freshness_from_sync(resolved_source, now_iso=ts)
        deployed_target_ids = [
            str(target.get("target_id", "")).strip()
            for target in manifest.get("deploy_targets", [])
            if isinstance(target, dict) and source_id in _to_str_list(target.get("selected_source_ids", []))
        ]
        status = "ready" if _to_bool(resolved_source.get("discovered", False), False) else "missing"
        source_locks.append(
            {
                **resolved_source,
                "status": status,
                "deployed_target_ids": _dedupe_keep_order(deployed_target_ids),
                "deployed_target_count": len(_dedupe_keep_order(deployed_target_ids)),
                "resolution_hash": _stable_hash(
                    {
                        "source_id": source_id,
                        "source_path": resolved_source.get("source_path"),
                        "member_count": resolved_source.get("member_count"),
                        "compatible_software_ids": resolved_source.get("compatible_software_ids"),
                    },
                ),
                "last_synced_at": ts,
            },
        )

    deploy_locks: list[dict[str, Any]] = []
    for target in manifest.get("deploy_targets", []):
        if not isinstance(target, dict):
            continue
        selected_source_ids = _dedupe_keep_order(_to_str_list(target.get("selected_source_ids", [])))
        available_source_ids = _dedupe_keep_order(_to_str_list(target.get("available_source_ids", [])))
        selected_sources = [source_index[source_id] for source_id in selected_source_ids if source_id in source_index]
        missing_sources = [
            str(source.get("source_id", "")).strip()
            for source in selected_sources
            if not _to_bool(source.get("discovered", False), False)
        ]
        incompatible_sources = [
            source_id
            for source_id in selected_source_ids
            if source_id not in available_source_ids
        ]
        ready_sources = [
            source_id
            for source_id in selected_source_ids
            if source_id not in missing_sources and source_id not in incompatible_sources
        ]
        target_installed = _to_bool(target.get("installed", False), False)
        target_path = str(target.get("target_path", "") or "")
        target_path_exists = _target_path_exists(target_path)
        repair_actions: list[str] = []

        if not selected_source_ids:
            status = "idle"
            drift_status = "ok"
        elif not target_installed:
            status = "unavailable"
            drift_status = "target_uninstalled"
        elif target_path and not target_path_exists:
            status = "stale"
            drift_status = "missing_target_path"
        elif missing_sources:
            status = "stale"
            drift_status = "missing_source"
        elif incompatible_sources:
            status = "stale"
            drift_status = "incompatible_selection"
        else:
            status = "ready"
            drift_status = "ok"

        if selected_source_ids and target_installed and target_path and not target_path_exists:
            repair_actions.append("create_target_path")
        if missing_sources:
            repair_actions.append("drop_missing_sources")
        if incompatible_sources:
            repair_actions.append("drop_incompatible_sources")

        deploy_locks.append(
            {
                **target,
                "status": status,
                "drift_status": drift_status,
                "target_path_exists": target_path_exists,
                "ready_source_ids": ready_sources,
                "missing_source_ids": missing_sources,
                "incompatible_source_ids": incompatible_sources,
                "available_source_count": len(available_source_ids),
                "selected_source_count": len(selected_source_ids),
                "ready_source_count": len(ready_sources),
                "repair_actions": repair_actions,
                "deployment_hash": _stable_hash(
                    {
                        "target_id": target.get("target_id"),
                        "selected_source_ids": selected_source_ids,
                        "target_path": target.get("target_path"),
                        "status": status,
                    },
                ),
                "last_synced_at": ts,
            },
        )

    return {
        "version": 1,
        "generated_at": ts,
        "sources": source_locks,
        "deploy_targets": deploy_locks,
    }


def _merge_overlay_row(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    clearable_empty_string_keys = {
        "sync_error_code",
        "sync_message",
        "sync_local_revision",
        "sync_remote_revision",
        "sync_resolved_revision",
        "sync_branch",
        "registry_latest_version",
        "registry_published_at",
        "registry_homepage",
        "registry_description",
        "git_checkout_path",
        "git_checkout_error",
    }
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key not in merged:
            merged[key] = value
            continue
        if isinstance(value, bool):
            merged[key] = value
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            if key in clearable_empty_string_keys:
                merged[key] = ""
            continue
        if isinstance(value, list) and not value:
            continue
        merged[key] = value
    return merged


def _derive_host_rows_from_saved_lock(saved_lock: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for target in saved_lock.get("deploy_targets", []):
        if not isinstance(target, dict):
            continue
        software_id = str(target.get("software_id") or "").strip()
        if not software_id:
            continue
        bucket = grouped.setdefault(
            software_id,
            {
                "id": software_id,
                "host_id": software_id,
                "display_name": str(target.get("software_display_name") or software_id),
                "software_kind": str(target.get("software_kind") or "other"),
                "kind": str(target.get("software_kind") or "other"),
                "software_family": str(target.get("software_family") or target.get("provider_key") or software_id),
                "family": str(target.get("software_family") or target.get("provider_key") or software_id),
                "provider_key": str(target.get("provider_key") or "generic"),
                "enabled": True,
                "installed": _to_bool(target.get("installed", False), False),
                "managed": _to_bool(target.get("managed", False), False),
                "linked_target_name": str(target.get("linked_target_name") or ""),
                "declared_skill_roots": [],
                "resolved_skill_roots": [],
                "supports_source_kinds": ["npx_bundle", "npx_single", "manual_local", "manual_git"],
                "capabilities": [],
                "runtime_state_backend": "astrbot"
                if str(target.get("provider_key") or "").strip() == "astrbot"
                else "",
                "runtime_state_summary": {},
                "runtime_state_warning_count": 0,
                "target_paths": {"global": "", "workspace": ""},
            },
        )
        bucket["installed"] = bucket["installed"] or _to_bool(target.get("installed", False), False)
        bucket["managed"] = bucket["managed"] or _to_bool(target.get("managed", False), False)
        scope = _normalize_scope(target.get("scope", "global"))
        target_path = str(target.get("target_path") or "")
        if target_path and not bucket["target_paths"].get(scope):
            bucket["target_paths"][scope] = target_path
        for root in _to_str_list(target.get("declared_skill_roots", [])):
            if root not in bucket["declared_skill_roots"]:
                bucket["declared_skill_roots"].append(root)
        for root in _to_str_list(target.get("resolved_skill_roots", [])):
            if root not in bucket["resolved_skill_roots"]:
                bucket["resolved_skill_roots"].append(root)
        if target_path:
            target_key = "resolved_skill_roots" if _to_bool(target.get("target_path_exists", False), False) else "declared_skill_roots"
            if target_path not in bucket[target_key]:
                bucket[target_key].append(target_path)

    hosts: list[dict[str, Any]] = []
    for item in grouped.values():
        item["target_path"] = item["target_paths"].get("global") or item["target_paths"].get("workspace") or ""
        hosts.append(item)
    hosts.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("host_id", "")).lower()))
    return hosts


def _merge_host_rows_with_saved_lock(
    host_rows: list[dict[str, Any]],
    saved_lock: dict[str, Any],
) -> list[dict[str, Any]]:
    merged_rows: list[dict[str, Any]] = []
    seen_host_ids: set[str] = set()
    saved_host_rows = _derive_host_rows_from_saved_lock(saved_lock)
    saved_host_index = {
        str(item.get("host_id") or item.get("id") or "").strip(): item
        for item in saved_host_rows
        if isinstance(item, dict) and str(item.get("host_id") or item.get("id") or "").strip()
    }

    for host in host_rows:
        if not isinstance(host, dict):
            continue
        merged = copy.deepcopy(host)
        host_id = str(merged.get("host_id") or merged.get("id") or "").strip()
        if not host_id:
            continue
        seen_host_ids.add(host_id)
        saved_host = saved_host_index.get(host_id, {})
        if isinstance(saved_host, dict) and saved_host:
            current_declared_roots = _to_str_list(merged.get("declared_skill_roots", []))
            current_resolved_roots = _to_str_list(merged.get("resolved_skill_roots", []))
            current_target_paths = (
                copy.deepcopy(merged.get("target_paths", {}))
                if isinstance(merged.get("target_paths", {}), dict)
                else {}
            )
            current_runtime_missing = (
                not any(str(current_target_paths.get(scope) or "").strip() for scope in VALID_DEPLOY_SCOPES)
                and not current_declared_roots
                and not current_resolved_roots
            )
            declared_roots = _dedupe_keep_order(
                current_declared_roots
                + _to_str_list(saved_host.get("declared_skill_roots", [])),
            )
            resolved_roots = _dedupe_keep_order(
                current_resolved_roots
                + _to_str_list(saved_host.get("resolved_skill_roots", [])),
            )
            merged["declared_skill_roots"] = declared_roots
            merged["resolved_skill_roots"] = resolved_roots

            saved_target_paths = (
                saved_host.get("target_paths", {})
                if isinstance(saved_host.get("target_paths", {}), dict)
                else {}
            )
            merged_target_paths = {
                "global": str(current_target_paths.get("global") or saved_target_paths.get("global") or "").strip(),
                "workspace": str(current_target_paths.get("workspace") or saved_target_paths.get("workspace") or "").strip(),
            }

            if current_runtime_missing and _to_bool(saved_host.get("installed", False), False):
                merged["installed"] = True
            merged["managed"] = _to_bool(merged.get("managed", False), False) or _to_bool(saved_host.get("managed", False), False)
            if not str(merged.get("linked_target_name") or "").strip():
                merged["linked_target_name"] = str(saved_host.get("linked_target_name") or "").strip()
            if not str(merged.get("runtime_state_backend") or "").strip():
                merged["runtime_state_backend"] = str(saved_host.get("runtime_state_backend") or "").strip()

            if str(merged.get("provider_key") or "").strip().lower() == "astrbot":
                resolution_host = {
                    **merged,
                    "declared_skill_roots": declared_roots,
                    "resolved_skill_roots": resolved_roots,
                }
                normalized_global_target_path = resolve_host_target_path(resolution_host, "global")
                normalized_workspace_target_path = resolve_host_target_path(resolution_host, "workspace")
                if normalized_global_target_path:
                    merged_target_paths["global"] = normalized_global_target_path
                merged_target_paths["workspace"] = normalized_workspace_target_path

            if not merged_target_paths["global"]:
                merged_target_paths["global"] = resolve_host_target_path(merged, "global")
            if not merged_target_paths["workspace"]:
                merged_target_paths["workspace"] = resolve_host_target_path(merged, "workspace")
            merged["target_paths"] = merged_target_paths
            merged["target_path"] = merged_target_paths["global"] or merged_target_paths["workspace"] or ""

        merged_rows.append(merged)

    for saved_host in saved_host_rows:
        host_id = str(saved_host.get("host_id") or saved_host.get("id") or "").strip()
        if not host_id or host_id in seen_host_ids:
            continue
        merged_rows.append(copy.deepcopy(saved_host))

    merged_rows.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("host_id", "")).lower()))
    return merged_rows


def _apply_saved_lock_fallback(
    computed_lock: dict[str, Any],
    manifest: dict[str, Any],
    saved_lock: dict[str, Any],
    *,
    generated_at: str,
    prefer_saved_targets: bool = False,
) -> dict[str, Any]:
    normalized_saved_lock = normalize_saved_skills_lock(saved_lock)
    computed_source_index, computed_target_index = _saved_lock_index(computed_lock)
    saved_source_index, saved_target_index = _saved_lock_index(normalized_saved_lock)

    source_rows: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    manifest_sources = manifest.get("sources", []) if isinstance(manifest.get("sources", []), list) else []
    for source in manifest_sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", "")).strip()
        if not source_id:
            continue
        row = copy.deepcopy(computed_source_index.get(source_id, source))
        if source_id in saved_source_index:
            row = _merge_overlay_row(row, saved_source_index[source_id])
        source_rows.append(row)
        seen_source_ids.add(source_id)

    for source_id, saved_source in saved_source_index.items():
        if source_id in seen_source_ids:
            continue
        source_rows.append(copy.deepcopy(saved_source))

    deploy_rows: list[dict[str, Any]] = []
    if prefer_saved_targets:
        deploy_rows = [
            copy.deepcopy(item)
            for item in normalized_saved_lock.get("deploy_targets", [])
            if isinstance(item, dict)
        ]
    elif computed_target_index:
        for target in computed_lock.get("deploy_targets", []):
            if not isinstance(target, dict):
                continue
            target_id = str(target.get("target_id", "")).strip()
            if not target_id:
                continue
            row = copy.deepcopy(target)
            if target_id in saved_target_index:
                row = _merge_overlay_row(row, saved_target_index[target_id])
            deploy_rows.append(row)
    else:
        deploy_rows = [
            copy.deepcopy(item)
            for item in normalized_saved_lock.get("deploy_targets", [])
            if isinstance(item, dict)
        ]

    return normalize_saved_skills_lock(
        {
            "version": max(
                _to_int(computed_lock.get("version", 1), 1, 1),
                _to_int(normalized_saved_lock.get("version", 1), 1, 1),
            ),
            "generated_at": generated_at,
            "sources": source_rows,
            "deploy_targets": deploy_rows,
        },
    )


def _overview_rows(overview: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = overview.get(key, []) if isinstance(overview, dict) else []
    return [
        item
        for item in rows
        if isinstance(item, dict)
    ]


def _find_overview_row(overview: dict[str, Any], key: str, field: str, value: str) -> dict[str, Any] | None:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        return None
    return next(
        (
            copy.deepcopy(item)
            for item in _overview_rows(overview, key)
            if str(item.get(field, "")).strip() == normalized_value
        ),
        None,
    )


def _related_deploy_rows_for_sources(
    overview: dict[str, Any],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    related_source_ids = {
        str(item or "").strip()
        for item in source_ids
        if str(item or "").strip()
    }
    if not related_source_ids:
        return []

    selected_deploy_rows: list[dict[str, Any]] = []
    related_deploy_rows: list[dict[str, Any]] = []
    for item in _overview_rows(overview, "deploy_rows"):
        selected_source_ids = set(_to_str_list(item.get("selected_source_ids", [])))
        if related_source_ids.intersection(selected_source_ids):
            selected_deploy_rows.append(copy.deepcopy(item))
            continue

        candidate_source_ids = set(
            _dedupe_keep_order(
                _to_str_list(item.get("available_source_ids", []))
                + _to_str_list(item.get("ready_source_ids", []))
                + _to_str_list(item.get("missing_source_ids", []))
                + _to_str_list(item.get("incompatible_source_ids", [])),
            ),
        )
        if related_source_ids.intersection(candidate_source_ids):
            related_deploy_rows.append(copy.deepcopy(item))
    return selected_deploy_rows or related_deploy_rows


def build_install_unit_detail_payload(overview: dict[str, Any], install_unit_id: str) -> dict[str, Any]:
    normalized_install_unit_id = str(install_unit_id or "").strip()
    if not normalized_install_unit_id:
        return {"ok": False, "message": "install_unit_id is required"}

    install_unit = _find_overview_row(
        overview,
        "install_unit_rows",
        "install_unit_id",
        normalized_install_unit_id,
    )
    if not install_unit:
        return {"ok": False, "message": f"install_unit_id not found: {normalized_install_unit_id}"}

    source_ids = _dedupe_keep_order(_to_str_list(install_unit.get("source_ids", [])))
    source_rows = [
        copy.deepcopy(item)
        for item in _overview_rows(overview, "source_rows")
        if str(item.get("source_id", "")).strip() in source_ids
    ]
    collection_group = _find_overview_row(
        overview,
        "collection_group_rows",
        "collection_group_id",
        str(install_unit.get("collection_group_id", "")).strip(),
    ) or {}
    deploy_rows = _related_deploy_rows_for_sources(overview, source_ids)
    update_plan = build_install_unit_update_plan(install_unit, source_rows)

    return {
        "ok": True,
        "generated_at": overview.get("generated_at"),
        "install_unit": install_unit,
        "collection_group": collection_group,
        "source_rows": source_rows,
        "deploy_rows": deploy_rows,
        "update_plan": update_plan,
        "warnings": copy.deepcopy(overview.get("warnings", [])),
    }


def build_collection_group_detail_payload(overview: dict[str, Any], collection_group_id: str) -> dict[str, Any]:
    normalized_collection_group_id = str(collection_group_id or "").strip()
    if not normalized_collection_group_id:
        return {"ok": False, "message": "collection_group_id is required"}

    collection_group = _find_overview_row(
        overview,
        "collection_group_rows",
        "collection_group_id",
        normalized_collection_group_id,
    )
    if not collection_group:
        return {"ok": False, "message": f"collection_group_id not found: {normalized_collection_group_id}"}

    install_unit_ids = _dedupe_keep_order(_to_str_list(collection_group.get("install_unit_ids", [])))
    install_unit_rows = [
        copy.deepcopy(item)
        for item in _overview_rows(overview, "install_unit_rows")
        if str(item.get("install_unit_id", "")).strip() in install_unit_ids
    ]

    source_ids = _dedupe_keep_order(
        _to_str_list(collection_group.get("source_ids", []))
        + [
            source_id
            for install_unit in install_unit_rows
            for source_id in _to_str_list(install_unit.get("source_ids", []))
        ],
    )
    source_rows = [
        copy.deepcopy(item)
        for item in _overview_rows(overview, "source_rows")
        if str(item.get("source_id", "")).strip() in source_ids
    ]
    deploy_rows = _related_deploy_rows_for_sources(overview, source_ids)
    update_plan = build_collection_group_update_plan(collection_group, install_unit_rows, source_rows)

    return {
        "ok": True,
        "generated_at": overview.get("generated_at"),
        "collection_group": collection_group,
        "install_unit_rows": install_unit_rows,
        "source_rows": source_rows,
        "deploy_rows": deploy_rows,
        "update_plan": update_plan,
        "warnings": copy.deepcopy(overview.get("warnings", [])),
    }


def build_skills_overview(
    inventory_snapshot: dict[str, Any],
    *,
    saved_manifest: dict[str, Any] | None = None,
    saved_registry: dict[str, Any] | None = None,
    saved_lock: dict[str, Any] | None = None,
    saved_install_atom_registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    normalized_saved_manifest = normalize_saved_skills_manifest(saved_manifest or {})
    normalized_saved_lock = normalize_saved_skills_lock(saved_lock or {})
    normalized_saved_install_atom_registry = normalize_install_atom_registry(saved_install_atom_registry or {})
    software_rows = [
        copy.deepcopy(item)
        for item in inventory_snapshot.get("software_rows", [])
        if isinstance(item, dict)
    ]
    skill_rows = [
        copy.deepcopy(item)
        for item in inventory_snapshot.get("skill_rows", [])
        if isinstance(item, dict)
    ]
    host_rows = build_host_adapters(software_rows)
    if host_rows and normalized_saved_lock.get("deploy_targets"):
        host_rows = _merge_host_rows_with_saved_lock(host_rows, normalized_saved_lock)
    elif not host_rows and normalized_saved_lock.get("deploy_targets"):
        host_rows = _derive_host_rows_from_saved_lock(normalized_saved_lock)
    registry = build_skills_registry(skill_rows, saved_registry=saved_registry, generated_at=ts)
    manifest = build_skills_manifest(
        inventory_snapshot,
        saved_manifest=normalized_saved_manifest,
        saved_registry=saved_registry,
        saved_lock=normalized_saved_lock,
        registry=registry,
        host_rows=host_rows,
        generated_at=ts,
    )
    if not manifest.get("deploy_targets") and normalized_saved_manifest.get("deploy_targets"):
        manifest = {
            **manifest,
            "software_hosts": copy.deepcopy(host_rows),
            "deploy_targets": copy.deepcopy(normalized_saved_manifest.get("deploy_targets", [])),
        }
    lock = build_skills_lock(manifest, inventory_snapshot, registry=registry, generated_at=ts)
    inventory_unavailable = not bool(inventory_snapshot.get("ok", True))
    if inventory_unavailable and (
        normalized_saved_lock.get("sources") or normalized_saved_lock.get("deploy_targets")
    ):
        lock = _apply_saved_lock_fallback(
            lock,
            manifest,
            normalized_saved_lock,
            generated_at=ts,
            prefer_saved_targets=not software_rows,
        )

    source_rows = [
        enrich_source_aggregation(copy.deepcopy(item))
        for item in lock.get("sources", [])
        if isinstance(item, dict)
    ]
    deploy_rows = [
        copy.deepcopy(item)
        for item in lock.get("deploy_targets", [])
        if isinstance(item, dict)
    ]
    software_hosts = [
        copy.deepcopy(item)
        for item in host_rows
        if isinstance(item, dict)
    ]
    astrbot_state_index = build_astrbot_state_index(software_hosts)
    astrbot_state_by_host = astrbot_state_index.get("by_host", {})
    astrbot_state_rows = astrbot_state_index.get("rows", [])
    astrbot_state_warnings = astrbot_state_index.get("warnings", [])
    astrbot_neo_source_rows = build_astrbot_neo_source_rows(astrbot_state_rows)
    for host in software_hosts:
        host_id = str(host.get("host_id") or host.get("id") or "").strip()
        state = astrbot_state_by_host.get(host_id, {})
        if not isinstance(state, dict) or not state:
            continue
        host["runtime_state_backend"] = str(
            state.get("runtime_state_backend")
            or host.get("runtime_state_backend")
            or "",
        )
        host["runtime_state_summary"] = copy.deepcopy(state.get("summary", {}))
        host["runtime_state_warning_count"] = len(_to_str_list(state.get("warnings", [])))

    warnings = list(inventory_snapshot.get("warnings", [])) if isinstance(inventory_snapshot.get("warnings", []), list) else []
    warnings.extend(astrbot_state_warnings)
    for source in source_rows:
        if str(source.get("status", "")) == "missing":
            warnings.append(f"source[{source.get('source_id')}] is declared but not discovered")
        elif str(source.get("freshness_status", "")) == "stale":
            warnings.append(
                f"source[{source.get('source_id')}] looks stale: age={source.get('source_age_days')}d last_seen={source.get('last_seen_at')}",
            )
        if str(source.get("sync_status", "")) == "error":
            warnings.append(
                f"source[{source.get('source_id')}] sync failed: {source.get('sync_message')}",
            )
    unresolved_provenance_total = sum(
        1
        for item in source_rows
        if str(item.get("provenance_state", "")).strip().lower() == "unresolved"
    )
    if unresolved_provenance_total:
        warnings.append(
            f"source provenance unresolved for {unresolved_provenance_total} sources; these items are still anchored only by fallback/root heuristics",
        )
    for target in deploy_rows:
        if str(target.get("drift_status", "")) == "missing_source":
            warnings.append(
                f"deploy[{target.get('target_id')}] references missing sources: "
                + ", ".join(_to_str_list(target.get("missing_source_ids", []))),
            )
        elif str(target.get("drift_status", "")) == "incompatible_selection":
            warnings.append(
                f"deploy[{target.get('target_id')}] contains incompatible sources: "
                + ", ".join(_to_str_list(target.get("incompatible_source_ids", []))),
            )
        elif str(target.get("drift_status", "")) == "missing_target_path":
            warnings.append(f"deploy[{target.get('target_id')}] target path is missing: {target.get('target_path')}")
        elif str(target.get("drift_status", "")) == "target_uninstalled":
            warnings.append(f"deploy[{target.get('target_id')}] selected while software is not installed")

    source_rows.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("source_id", "")).lower()))
    deploy_rows.sort(key=lambda item: (str(item.get("software_display_name", "")).lower(), str(item.get("scope", "")).lower()))

    compatibility_raw = inventory_snapshot.get("compatibility", {})
    binding_projection = _project_binding_state_from_manifest(
        manifest,
        source_rows=source_rows,
        software_hosts=software_hosts,
        inventory_compatibility=compatibility_raw if isinstance(compatibility_raw, dict) else {},
    )
    projected_compatibility = (
        binding_projection.get("compatibility", {})
        if isinstance(binding_projection.get("compatibility", {}), dict)
        else {}
    )
    warnings.extend(_to_str_list(binding_projection.get("warnings", [])))
    source_row_index = {
        str(item.get("source_id", "")).strip(): item
        for item in source_rows
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }
    compatible_source_rows_by_software: dict[str, list[dict[str, Any]]] = {}
    for software_id, source_ids in projected_compatibility.items():
        software_key = str(software_id or "").strip()
        if not software_key:
            continue
        compatible_source_rows_by_software[software_key] = [
            copy.deepcopy(source_row_index[source_id])
            for source_id in _to_str_list(source_ids)
            if source_id in source_row_index
        ]

    install_unit_rows = build_install_unit_rows(source_rows, deploy_rows)
    install_atom_registry = build_install_atom_registry(
        install_unit_rows,
        source_rows,
        saved_registry=normalized_saved_install_atom_registry,
        generated_at=ts,
    )
    install_unit_rows = apply_install_atom_registry(install_unit_rows, install_atom_registry)
    collection_group_rows = build_collection_group_rows(install_unit_rows)
    meaningful_collection_group_rows = build_meaningful_collection_group_rows(collection_group_rows)
    compatible_install_unit_rows_by_software = build_compatible_aggregate_rows_by_software(
        install_unit_rows,
        compatible_source_rows_by_software,
    )
    compatible_collection_group_rows_by_software = build_compatible_aggregate_rows_by_software(
        collection_group_rows,
        compatible_source_rows_by_software,
    )
    compatible_meaningful_collection_group_rows_by_software = build_compatible_aggregate_rows_by_software(
        meaningful_collection_group_rows,
        compatible_source_rows_by_software,
    )

    inventory_counts = inventory_snapshot.get("counts", {})
    counts = dict(inventory_counts) if isinstance(inventory_counts, dict) else {}
    counts.update(
        {
            "bindings_total": int(binding_projection.get("counts", {}).get("bindings_total", 0) or 0),
            "bindings_valid": int(binding_projection.get("counts", {}).get("bindings_valid", 0) or 0),
            "bindings_invalid": int(binding_projection.get("counts", {}).get("bindings_invalid", 0) or 0),
            "source_total": len(source_rows),
            "source_bundle_total": sum(
                1
                for item in source_rows
                if str(item.get("source_kind", "")) in {"skill_bundle", "npx_bundle"}
            ),
            "source_missing_total": sum(1 for item in source_rows if str(item.get("status", "")) == "missing"),
            "source_fresh_total": sum(1 for item in source_rows if str(item.get("freshness_status", "")) == "fresh"),
            "source_aging_total": sum(1 for item in source_rows if str(item.get("freshness_status", "")) == "aging"),
            "source_stale_total": sum(1 for item in source_rows if str(item.get("freshness_status", "")) == "stale"),
            "source_syncable_total": _count_syncable_rows(source_rows),
            "source_synced_total": _count_rows_by_field(source_rows, "sync_status", "ok"),
            "source_sync_error_total": _count_rows_by_field(source_rows, "sync_status", "error"),
            "source_sync_dirty_total": _count_sync_dirty_rows(source_rows),
            "source_sync_revision_drift_total": _count_sync_revision_drift_rows(source_rows),
            "source_sync_pending_total": sum(
                1
                for item in source_rows
                if is_source_syncable(item)
                and str(item.get("sync_status", "")).strip() not in {"ok", "error"}
            ),
            "source_provenance_resolved_total": sum(
                1
                for item in source_rows
                if str(item.get("provenance_confidence", "")).strip().lower() in {"high", "medium"}
            ),
            "source_provenance_unresolved_total": sum(
                1
                for item in source_rows
                if str(item.get("provenance_confidence", "")).strip().lower() not in {"high", "medium"}
            ),
            "registry_total": len(registry.get("sources", [])),
            "install_atom_total": int(install_atom_registry.get("counts", {}).get("install_atom_total", len(install_unit_rows)) or len(install_unit_rows)),
            "install_atom_resolved_total": int(install_atom_registry.get("counts", {}).get("resolved_total", 0) or 0),
            "install_atom_partial_total": int(install_atom_registry.get("counts", {}).get("partial_total", 0) or 0),
            "install_atom_unresolved_total": int(install_atom_registry.get("counts", {}).get("unresolved_total", 0) or 0),
            "install_atom_explicit_total": int(install_atom_registry.get("counts", {}).get("explicit_total", 0) or 0),
            "install_atom_strong_total": int(install_atom_registry.get("counts", {}).get("strong_total", 0) or 0),
            "install_atom_heuristic_total": int(install_atom_registry.get("counts", {}).get("heuristic_total", 0) or 0),
            "install_unit_total": len(install_unit_rows),
            "install_unit_ready_total": _count_rows_by_field(install_unit_rows, "status", "ready"),
            "install_unit_missing_total": _count_rows_by_field(install_unit_rows, "status", "missing"),
            "install_unit_fresh_total": _count_rows_by_field(install_unit_rows, "freshness_status", "fresh"),
            "install_unit_aging_total": _count_rows_by_field(install_unit_rows, "freshness_status", "aging"),
            "install_unit_stale_total": _count_rows_by_field(install_unit_rows, "freshness_status", "stale"),
            "install_unit_syncable_total": _count_syncable_rows(install_unit_rows),
            "install_unit_synced_total": _count_rows_by_field(install_unit_rows, "sync_status", "ok"),
            "install_unit_sync_error_total": _count_rows_by_field(install_unit_rows, "sync_status", "error"),
            "install_unit_sync_pending_total": sum(
                1
                for item in install_unit_rows
                if is_source_syncable(item)
                and str(item.get("sync_status", "")).strip() not in {"ok", "error"}
            ),
            "collection_group_total": len(collection_group_rows),
            "meaningful_collection_group_total": len(meaningful_collection_group_rows),
            "collection_group_ready_total": _count_rows_by_field(collection_group_rows, "status", "ready"),
            "collection_group_missing_total": _count_rows_by_field(collection_group_rows, "status", "missing"),
            "collection_group_fresh_total": _count_rows_by_field(collection_group_rows, "freshness_status", "fresh"),
            "collection_group_aging_total": _count_rows_by_field(collection_group_rows, "freshness_status", "aging"),
            "collection_group_stale_total": _count_rows_by_field(collection_group_rows, "freshness_status", "stale"),
            "collection_group_syncable_total": _count_syncable_rows(collection_group_rows),
            "collection_group_synced_total": _count_rows_by_field(collection_group_rows, "sync_status", "ok"),
            "collection_group_sync_error_total": _count_rows_by_field(collection_group_rows, "sync_status", "error"),
            "collection_group_sync_pending_total": sum(
                1
                for item in collection_group_rows
                if is_source_syncable(item)
                and str(item.get("sync_status", "")).strip() not in {"ok", "error"}
            ),
            "host_total": len(software_hosts),
            "astrbot_host_total": len(astrbot_state_by_host),
            "astrbot_state_row_total": len(astrbot_state_rows),
            "astrbot_local_skill_total": sum(
                _to_int(item.get("summary", {}).get("local_skill_total", 0), 0, 0)
                for item in astrbot_state_by_host.values()
                if isinstance(item, dict)
            ),
            "astrbot_synced_total": sum(
                _to_int(item.get("summary", {}).get("synced_total", 0), 0, 0)
                for item in astrbot_state_by_host.values()
                if isinstance(item, dict)
            ),
            "astrbot_sandbox_only_total": sum(
                _to_int(item.get("summary", {}).get("sandbox_only_total", 0), 0, 0)
                for item in astrbot_state_by_host.values()
                if isinstance(item, dict)
            ),
            "astrbot_neo_managed_total": sum(
                _to_int(item.get("summary", {}).get("neo_managed_total", 0), 0, 0)
                for item in astrbot_state_by_host.values()
                if isinstance(item, dict)
            ),
            "astrbot_drifted_total": sum(
                _to_int(item.get("summary", {}).get("drifted_total", 0), 0, 0)
                for item in astrbot_state_by_host.values()
                if isinstance(item, dict)
            ),
            "astrbot_warning_total": len(astrbot_state_warnings),
            "astrbot_neo_source_total": len(astrbot_neo_source_rows),
            "astrbot_neo_source_ready_total": sum(
                1
                for item in astrbot_neo_source_rows
                if str(item.get("status", "")).strip().lower() == "ready"
            ),
            "astrbot_neo_source_missing_total": sum(
                1
                for item in astrbot_neo_source_rows
                if str(item.get("status", "")).strip().lower() == "missing"
            ),
            "deploy_target_total": len(deploy_rows),
            "deploy_ready_total": sum(1 for item in deploy_rows if str(item.get("status", "")) == "ready"),
            "deploy_idle_total": sum(1 for item in deploy_rows if str(item.get("status", "")) == "idle"),
            "deploy_unavailable_total": sum(1 for item in deploy_rows if str(item.get("status", "")) == "unavailable"),
            "deploy_stale_total": sum(1 for item in deploy_rows if str(item.get("status", "")) == "stale"),
            "deploy_repairable_total": sum(1 for item in deploy_rows if _to_str_list(item.get("repair_actions", []))),
        },
    )

    doctor = {
        "ok": not warnings,
        "warning_count": len(warnings),
        "source_health": {
            "ready": sum(1 for item in source_rows if str(item.get("status", "")) == "ready"),
            "missing": sum(1 for item in source_rows if str(item.get("status", "")) == "missing"),
        },
        "source_freshness": {
            "fresh": counts.get("source_fresh_total", 0),
            "aging": counts.get("source_aging_total", 0),
            "stale": counts.get("source_stale_total", 0),
            "missing": counts.get("source_missing_total", 0),
        },
        "source_sync": {
            "syncable": counts.get("source_syncable_total", 0),
            "ok": counts.get("source_synced_total", 0),
            "error": counts.get("source_sync_error_total", 0),
            "dirty": counts.get("source_sync_dirty_total", 0),
            "revision_drift": counts.get("source_sync_revision_drift_total", 0),
            "pending": counts.get("source_sync_pending_total", 0),
        },
        "provenance_health": {
            "resolved": counts.get("source_provenance_resolved_total", 0),
            "partial": sum(
                1
                for item in source_rows
                if str(item.get("provenance_state", "")).strip().lower() == "partial"
            ),
            "unresolved": counts.get("source_provenance_unresolved_total", 0),
        },
        "install_unit_health": {
            "ready": counts.get("install_unit_ready_total", 0),
            "missing": counts.get("install_unit_missing_total", 0),
        },
        "install_unit_sync": {
            "syncable": counts.get("install_unit_syncable_total", 0),
            "ok": counts.get("install_unit_synced_total", 0),
            "error": counts.get("install_unit_sync_error_total", 0),
            "pending": counts.get("install_unit_sync_pending_total", 0),
        },
        "install_atom_health": {
            "total": counts.get("install_atom_total", 0),
            "resolved": counts.get("install_atom_resolved_total", 0),
            "partial": counts.get("install_atom_partial_total", 0),
            "unresolved": counts.get("install_atom_unresolved_total", 0),
            "explicit": counts.get("install_atom_explicit_total", 0),
            "strong": counts.get("install_atom_strong_total", 0),
            "heuristic": counts.get("install_atom_heuristic_total", 0),
        },
        "collection_group_health": {
            "ready": counts.get("collection_group_ready_total", 0),
            "missing": counts.get("collection_group_missing_total", 0),
        },
        "collection_group_sync": {
            "syncable": counts.get("collection_group_syncable_total", 0),
            "ok": counts.get("collection_group_synced_total", 0),
            "error": counts.get("collection_group_sync_error_total", 0),
            "pending": counts.get("collection_group_sync_pending_total", 0),
        },
        "deploy_health": {
            "ready": counts.get("deploy_ready_total", 0),
            "idle": counts.get("deploy_idle_total", 0),
            "stale": counts.get("deploy_stale_total", 0),
            "unavailable": counts.get("deploy_unavailable_total", 0),
        },
        "astrbot_runtime_health": {
            "host_total": counts.get("astrbot_host_total", 0),
            "state_row_total": counts.get("astrbot_state_row_total", 0),
            "local_skill_total": counts.get("astrbot_local_skill_total", 0),
            "synced_total": counts.get("astrbot_synced_total", 0),
            "sandbox_only_total": counts.get("astrbot_sandbox_only_total", 0),
            "neo_managed_total": counts.get("astrbot_neo_managed_total", 0),
            "drifted_total": counts.get("astrbot_drifted_total", 0),
            "warning_count": counts.get("astrbot_warning_total", 0),
            "neo_source_total": counts.get("astrbot_neo_source_total", 0),
            "neo_source_ready_total": counts.get("astrbot_neo_source_ready_total", 0),
            "neo_source_missing_total": counts.get("astrbot_neo_source_missing_total", 0),
        },
        "warnings": warnings,
    }

    return {
        "ok": bool(inventory_snapshot.get("ok", True)),
        "generated_at": ts,
        "manifest": manifest,
        "lock": lock,
        "registry": registry,
        "install_atom_registry": install_atom_registry,
        "host_rows": software_hosts,
        "software_hosts": software_hosts,
        "astrbot_state_by_host": astrbot_state_by_host,
        "astrbot_state_rows": astrbot_state_rows,
        "astrbot_neo_source_rows": astrbot_neo_source_rows,
        "source_rows": source_rows,
        "install_unit_rows": install_unit_rows,
        "collection_group_rows": collection_group_rows,
        "meaningful_collection_group_rows": meaningful_collection_group_rows,
        "deploy_rows": deploy_rows,
        "doctor": doctor,
        "counts": counts,
        "warnings": warnings,
        "software_rows": copy.deepcopy(inventory_snapshot.get("software_rows", [])),
        "skill_rows": copy.deepcopy(inventory_snapshot.get("skill_rows", [])),
        "compatible_source_rows_by_software": compatible_source_rows_by_software,
        "compatible_install_unit_rows_by_software": compatible_install_unit_rows_by_software,
        "compatible_collection_group_rows_by_software": compatible_collection_group_rows_by_software,
        "compatible_meaningful_collection_group_rows_by_software": compatible_meaningful_collection_group_rows_by_software,
        "binding_rows": copy.deepcopy(binding_projection.get("binding_rows", [])),
        "binding_map": copy.deepcopy(binding_projection.get("binding_map", {})),
        "binding_map_by_scope": copy.deepcopy(binding_projection.get("binding_map_by_scope", {})),
        "compatibility": copy.deepcopy(projected_compatibility),
    }
