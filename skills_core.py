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


def _preferred_target_path(software: dict[str, Any], scope: str) -> str:
    resolved_roots = _to_str_list(software.get("resolved_skill_roots", []))
    declared_roots = _to_str_list(software.get("declared_skill_roots", []))
    candidates = resolved_roots or declared_roots
    if not candidates:
        return ""
    if scope == "workspace" and len(candidates) > 1:
        return candidates[1]
    return candidates[0]


def build_skills_manifest(
    inventory_snapshot: dict[str, Any],
    *,
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
        sources.append(
            {
                "source_id": source_id,
                "display_name": str(item.get("display_name") or source_id),
                "source_kind": str(item.get("skill_kind") or "skill"),
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
                "compatible_software_ids": compatible_hosts,
                "compatible_software_families": _to_str_list(item.get("compatible_software_families", [])),
                "tags": _to_str_list(item.get("tags", [])),
            },
        )

    deploy_targets: list[dict[str, Any]] = []
    for host in software_hosts:
        software_id = str(host.get("id", ""))
        for scope in VALID_DEPLOY_SCOPES:
            selected_ids = _dedupe_keep_order(
                _to_str_list(binding_map_by_scope.get(scope, {}).get(software_id, [])),
            )
            deploy_targets.append(
                {
                    "target_id": f"{software_id}:{scope}",
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
        "sources": sources,
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
        selected_sources = [source_index[source_id] for source_id in selected_source_ids if source_id in source_index]
        missing_sources = [
            str(source.get("source_id", "")).strip()
            for source in selected_sources
            if not _to_bool(source.get("discovered", False), False)
        ]
        target_installed = _to_bool(target.get("installed", False), False)

        if not selected_source_ids:
            status = "idle"
            drift_status = "ok"
        elif not target_installed:
            status = "unavailable"
            drift_status = "target_uninstalled"
        elif missing_sources:
            status = "stale"
            drift_status = "missing_source"
        else:
            status = "ready"
            drift_status = "ok"

        deploy_locks.append(
            {
                **target,
                "status": status,
                "drift_status": drift_status,
                "missing_source_ids": missing_sources,
                "available_source_count": len(_to_str_list(target.get("available_source_ids", []))),
                "selected_source_count": len(selected_source_ids),
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
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = generated_at or str(inventory_snapshot.get("generated_at") or _now_iso())
    manifest = build_skills_manifest(inventory_snapshot, generated_at=ts)
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
