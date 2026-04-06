from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _preferred_target_path(software: dict[str, Any], scope: str) -> str:
    resolved_roots = _to_str_list(software.get("resolved_skill_roots", []))
    declared_roots = _to_str_list(software.get("declared_skill_roots", []))
    candidates = resolved_roots or declared_roots
    if not candidates:
        return ""
    if scope == "workspace" and len(candidates) > 1:
        return candidates[1]
    return candidates[0]


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


def build_skills_manifest(
    inventory_snapshot: dict[str, Any],
    *,
    saved_manifest: dict[str, Any] | None = None,
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

    compatible_hosts_by_source: dict[str, list[str]] = {}
    for software_id, skill_ids in compatibility.items():
        host_id = str(software_id or "").strip()
        for skill_id in _to_str_list(skill_ids):
            compatible_hosts_by_source.setdefault(skill_id, []).append(host_id)

    software_hosts: list[dict[str, Any]] = []
    for item in software_rows:
        software_id = str(item.get("id", "")).strip()
        if not software_id:
            continue
        software_hosts.append(
            {
                "id": software_id,
                "display_name": str(item.get("display_name") or software_id),
                "software_kind": str(item.get("software_kind") or "other"),
                "software_family": str(item.get("software_family") or software_id),
                "provider_key": str(item.get("provider_key") or "generic"),
                "enabled": _to_bool(item.get("enabled", True), True),
                "installed": _to_bool(item.get("installed", False), False),
                "managed": _to_bool(item.get("managed", False), False),
                "linked_target_name": str(item.get("linked_target_name") or ""),
                "compatible_source_ids": _dedupe_keep_order(_to_str_list(compatibility.get(software_id, []))),
                "declared_skill_roots": _to_str_list(item.get("declared_skill_roots", [])),
                "resolved_skill_roots": _to_str_list(item.get("resolved_skill_roots", [])),
            },
        )

    sources: list[dict[str, Any]] = []
    for item in skill_rows:
        source_id = str(item.get("id", "")).strip()
        if not source_id:
            continue
        compatible_hosts = _dedupe_keep_order(compatible_hosts_by_source.get(source_id, []))
        saved_source = saved_source_index.get(source_id, {})
        sources.append(
            {
                "source_id": source_id,
                "display_name": str(item.get("display_name") or saved_source.get("display_name") or source_id),
                "source_kind": str(item.get("skill_kind") or saved_source.get("source_kind") or "skill"),
                "provider_key": str(item.get("provider_key") or saved_source.get("provider_key") or "generic"),
                "enabled": _to_bool(saved_source.get("enabled", item.get("enabled", True)), True),
                "discovered": _to_bool(item.get("discovered", False), False),
                "auto_discovered": _to_bool(item.get("auto_discovered", False), False),
                "source_scope": str(item.get("source_scope") or saved_source.get("source_scope") or "global"),
                "source_path": str(item.get("source_path") or saved_source.get("source_path") or ""),
                "member_count": _to_int(item.get("member_count", saved_source.get("member_count", 1)), 1, 1),
                "member_skill_preview": _to_str_list(item.get("member_skill_preview", []) or saved_source.get("member_skill_preview", [])),
                "member_skill_overflow": _to_int(item.get("member_skill_overflow", saved_source.get("member_skill_overflow", 0)), 0, 0),
                "management_hint": str(item.get("management_hint") or saved_source.get("management_hint") or ""),
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
                "member_count": _to_int(saved_source.get("member_count", 1), 1, 1),
                "member_skill_preview": _to_str_list(saved_source.get("member_skill_preview", [])),
                "member_skill_overflow": _to_int(saved_source.get("member_skill_overflow", 0), 0, 0),
                "management_hint": str(saved_source.get("management_hint") or ""),
                "compatible_software_ids": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_ids", []))),
                "compatible_software_families": _dedupe_keep_order(_to_str_list(saved_source.get("compatible_software_families", []))),
                "tags": _dedupe_keep_order(_to_str_list(saved_source.get("tags", []))),
            },
        )

    deploy_targets: list[dict[str, Any]] = []
    for host in software_hosts:
        software_id = str(host.get("id", ""))
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
                    "software_family": str(host.get("software_family") or software_id),
                    "provider_key": str(host.get("provider_key") or "generic"),
                    "scope": scope,
                    "installed": _to_bool(host.get("installed", False), False),
                    "managed": _to_bool(host.get("managed", False), False),
                    "linked_target_name": str(host.get("linked_target_name") or ""),
                    "target_path": _preferred_target_path(host, scope),
                    "available_source_ids": _dedupe_keep_order(_to_str_list(host.get("compatible_source_ids", []))),
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
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    manifest = build_skills_manifest(inventory_snapshot, saved_manifest=saved_manifest, generated_at=ts)
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
        for item in manifest.get("software_hosts", [])
        if isinstance(item, dict)
    ]

    warnings = list(inventory_snapshot.get("warnings", [])) if isinstance(inventory_snapshot.get("warnings", []), list) else []
    for source in source_rows:
        if str(source.get("status", "")) == "missing":
            warnings.append(f"source[{source.get('source_id')}] is declared but not discovered")
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

    inventory_counts = inventory_snapshot.get("counts", {})
    counts = dict(inventory_counts) if isinstance(inventory_counts, dict) else {}
    counts.update(
        {
            "source_total": len(source_rows),
            "source_bundle_total": sum(1 for item in source_rows if str(item.get("source_kind", "")) == "skill_bundle"),
            "source_missing_total": sum(1 for item in source_rows if str(item.get("status", "")) == "missing"),
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
        "software_hosts": software_hosts,
        "source_rows": source_rows,
        "deploy_rows": deploy_rows,
        "doctor": doctor,
        "counts": counts,
        "warnings": warnings,
        "software_rows": copy.deepcopy(inventory_snapshot.get("software_rows", [])),
        "skill_rows": copy.deepcopy(inventory_snapshot.get("skill_rows", [])),
        "binding_rows": copy.deepcopy(inventory_snapshot.get("binding_rows", [])),
        "binding_map": copy.deepcopy(inventory_snapshot.get("binding_map", {})),
        "binding_map_by_scope": copy.deepcopy(inventory_snapshot.get("binding_map_by_scope", {})),
        "compatibility": copy.deepcopy(inventory_snapshot.get("compatibility", {})),
    }
