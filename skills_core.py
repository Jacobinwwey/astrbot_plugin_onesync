from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .skills_hosts_core import build_host_adapters, resolve_host_target_path
    from .skills_sources_core import build_skills_registry
except ImportError:  # pragma: no cover - direct test imports
    from skills_hosts_core import build_host_adapters, resolve_host_target_path
    from skills_sources_core import build_skills_registry

VALID_DEPLOY_SCOPES = ("global", "workspace")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def normalize_saved_skills_manifest(raw: Any) -> dict[str, Any]:
    manifest = raw if isinstance(raw, dict) else {}
    sources: list[dict[str, Any]] = []
    for item in manifest.get("sources", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        sources.append(
            {
                "source_id": source_id,
                "display_name": str(item.get("display_name") or source_id),
                "source_kind": str(item.get("source_kind") or "skill"),
                "provider_key": str(item.get("provider_key") or "generic"),
                "enabled": _to_bool(item.get("enabled", True), True),
                "discovered": _to_bool(item.get("discovered", False), False),
                "auto_discovered": _to_bool(item.get("auto_discovered", False), False),
                "source_scope": str(item.get("source_scope") or "global"),
                "source_path": str(item.get("source_path") or ""),
                "member_count": _to_int(item.get("member_count", 1), 1, 1),
                "member_skill_preview": _to_str_list(item.get("member_skill_preview", [])),
                "member_skill_overflow": _to_int(item.get("member_skill_overflow", 0), 0, 0),
                "management_hint": str(item.get("management_hint") or ""),
                "source_exists": _to_bool(item.get("source_exists", False), False),
                "last_seen_at": str(item.get("last_seen_at") or ""),
                "source_age_days": _to_int(item.get("source_age_days"), 0) if item.get("source_age_days") is not None else None,
                "freshness_status": str(item.get("freshness_status") or "missing"),
                "registry_package_name": str(item.get("registry_package_name") or ""),
                "registry_package_manager": str(item.get("registry_package_manager") or ""),
                "sync_status": str(item.get("sync_status") or ""),
                "sync_checked_at": str(item.get("sync_checked_at") or ""),
                "sync_kind": str(item.get("sync_kind") or ""),
                "sync_message": str(item.get("sync_message") or ""),
                "registry_latest_version": str(item.get("registry_latest_version") or ""),
                "registry_published_at": str(item.get("registry_published_at") or ""),
                "registry_homepage": str(item.get("registry_homepage") or ""),
                "registry_description": str(item.get("registry_description") or ""),
                "compatible_software_ids": _dedupe_keep_order(_to_str_list(item.get("compatible_software_ids", []))),
                "compatible_software_families": _dedupe_keep_order(_to_str_list(item.get("compatible_software_families", []))),
                "tags": _dedupe_keep_order(_to_str_list(item.get("tags", []))),
            },
        )

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


def build_skills_manifest(
    inventory_snapshot: dict[str, Any],
    *,
    saved_manifest: dict[str, Any] | None = None,
    saved_registry: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    host_rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    normalized_saved_manifest = normalize_saved_skills_manifest(saved_manifest or {})
    saved_source_index, saved_target_index = _saved_manifest_index(normalized_saved_manifest)
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
        compatible_hosts = _dedupe_keep_order(
            compatible_hosts_by_source.get(source_id, [])
            or _to_str_list(item.get("compatible_software_ids", [])),
        )
        saved_source = saved_source_index.get(source_id, {})
        sources.append(
            {
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
                "sync_status": str(item.get("sync_status") or saved_source.get("sync_status") or ""),
                "sync_checked_at": str(item.get("sync_checked_at") or saved_source.get("sync_checked_at") or ""),
                "sync_kind": str(item.get("sync_kind") or saved_source.get("sync_kind") or ""),
                "sync_message": str(item.get("sync_message") or saved_source.get("sync_message") or ""),
                "registry_latest_version": str(item.get("registry_latest_version") or saved_source.get("registry_latest_version") or ""),
                "registry_published_at": str(item.get("registry_published_at") or saved_source.get("registry_published_at") or ""),
                "registry_homepage": str(item.get("registry_homepage") or saved_source.get("registry_homepage") or ""),
                "registry_description": str(item.get("registry_description") or saved_source.get("registry_description") or ""),
                "compatible_software_ids": compatible_hosts,
                "compatible_software_families": _to_str_list(item.get("compatible_software_families", []) or saved_source.get("compatible_software_families", [])),
                "tags": _dedupe_keep_order(_to_str_list(item.get("tags", [])) + _to_str_list(saved_source.get("tags", []))),
            },
        )

    discovered_source_ids = {str(item.get("source_id", "")).strip() for item in sources}
    for source_id, saved_source in saved_source_index.items():
        if source_id in discovered_source_ids:
            continue
        sources.append(
            {
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
                "sync_status": str(saved_source.get("sync_status") or ""),
                "sync_checked_at": str(saved_source.get("sync_checked_at") or ""),
                "sync_kind": str(saved_source.get("sync_kind") or ""),
                "sync_message": str(saved_source.get("sync_message") or ""),
                "registry_latest_version": str(saved_source.get("registry_latest_version") or ""),
                "registry_published_at": str(saved_source.get("registry_published_at") or ""),
                "registry_homepage": str(saved_source.get("registry_homepage") or ""),
                "registry_description": str(saved_source.get("registry_description") or ""),
                "compatible_software_ids": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_ids", []))),
                "compatible_software_families": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_families", []))),
                "tags": _dedupe_keep_order(_to_str_list(saved_source.get("tags", []))),
            },
        )

    deploy_targets: list[dict[str, Any]] = []
    for host in software_hosts:
        software_id = str(host.get("host_id") or host.get("id") or "")
        for scope in VALID_DEPLOY_SCOPES:
            target_id = f"{software_id}:{scope}"
            selected_from_inventory = _dedupe_keep_order(
                _to_str_list(binding_map_by_scope.get(scope, {}).get(software_id, [])),
            )
            saved_target = saved_target_index.get(target_id, {})
            selected_ids = _dedupe_keep_order(
                _to_str_list(saved_target.get("selected_source_ids", []))
                or selected_from_inventory,
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
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    source_index = {
        str(item.get("source_id", "")).strip(): item
        for item in manifest.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }

    source_locks: list[dict[str, Any]] = []
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", "")).strip()
        deployed_target_ids = [
            str(target.get("target_id", "")).strip()
            for target in manifest.get("deploy_targets", [])
            if isinstance(target, dict) and source_id in _to_str_list(target.get("selected_source_ids", []))
        ]
        status = "ready" if _to_bool(source.get("discovered", False), False) else "missing"
        source_locks.append(
            {
                **source,
                "status": status,
                "deployed_target_ids": _dedupe_keep_order(deployed_target_ids),
                "deployed_target_count": len(_dedupe_keep_order(deployed_target_ids)),
                "resolution_hash": _stable_hash(
                    {
                        "source_id": source_id,
                        "source_path": source.get("source_path"),
                        "member_count": source.get("member_count"),
                        "compatible_software_ids": source.get("compatible_software_ids"),
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


def build_skills_overview(
    inventory_snapshot: dict[str, Any],
    *,
    saved_manifest: dict[str, Any] | None = None,
    saved_registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
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
    registry = build_skills_registry(skill_rows, saved_registry=saved_registry, generated_at=ts)
    manifest = build_skills_manifest(
        inventory_snapshot,
        saved_manifest=saved_manifest,
        saved_registry=saved_registry,
        registry=registry,
        host_rows=host_rows,
        generated_at=ts,
    )
    lock = build_skills_lock(manifest, inventory_snapshot, generated_at=ts)

    source_rows = [
        copy.deepcopy(item)
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

    warnings = list(inventory_snapshot.get("warnings", [])) if isinstance(inventory_snapshot.get("warnings", []), list) else []
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

    compatible_source_rows_by_software: dict[str, list[dict[str, Any]]] = {}
    compatibility_raw = inventory_snapshot.get("compatibility", {})
    compatibility = compatibility_raw if isinstance(compatibility_raw, dict) else {}
    for host in software_hosts:
        software_id = str(host.get("host_id") or host.get("id", "")).strip()
        if not software_id:
            continue
        compatible_source_rows_by_software[software_id] = [
            copy.deepcopy(item)
            for item in source_rows
            if _source_matches_host(item, host, compatibility)
        ]

    inventory_counts = inventory_snapshot.get("counts", {})
    counts = dict(inventory_counts) if isinstance(inventory_counts, dict) else {}
    counts.update(
        {
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
            "source_syncable_total": sum(
                1
                for item in source_rows
                if str(item.get("registry_package_name", "")).strip()
                and str(item.get("registry_package_manager", "")).strip().lower() == "npm"
            ),
            "source_synced_total": sum(1 for item in source_rows if str(item.get("sync_status", "")) == "ok"),
            "source_sync_error_total": sum(1 for item in source_rows if str(item.get("sync_status", "")) == "error"),
            "source_sync_pending_total": sum(
                1
                for item in source_rows
                if str(item.get("registry_package_name", "")).strip()
                and str(item.get("registry_package_manager", "")).strip().lower() == "npm"
                and str(item.get("sync_status", "")).strip() not in {"ok", "error"}
            ),
            "registry_total": len(registry.get("sources", [])),
            "host_total": len(software_hosts),
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
            "pending": counts.get("source_sync_pending_total", 0),
        },
        "deploy_health": {
            "ready": counts.get("deploy_ready_total", 0),
            "idle": counts.get("deploy_idle_total", 0),
            "stale": counts.get("deploy_stale_total", 0),
            "unavailable": counts.get("deploy_unavailable_total", 0),
        },
        "warnings": warnings,
    }

    return {
        "ok": bool(inventory_snapshot.get("ok", True)),
        "generated_at": ts,
        "manifest": manifest,
        "lock": lock,
        "registry": registry,
        "host_rows": software_hosts,
        "software_hosts": software_hosts,
        "source_rows": source_rows,
        "deploy_rows": deploy_rows,
        "doctor": doctor,
        "counts": counts,
        "warnings": warnings,
        "software_rows": copy.deepcopy(inventory_snapshot.get("software_rows", [])),
        "skill_rows": copy.deepcopy(inventory_snapshot.get("skill_rows", [])),
        "compatible_source_rows_by_software": compatible_source_rows_by_software,
        "binding_rows": copy.deepcopy(inventory_snapshot.get("binding_rows", [])),
        "binding_map": copy.deepcopy(inventory_snapshot.get("binding_map", {})),
        "binding_map_by_scope": copy.deepcopy(inventory_snapshot.get("binding_map_by_scope", {})),
        "compatibility": copy.deepcopy(inventory_snapshot.get("compatibility", {})),
    }
