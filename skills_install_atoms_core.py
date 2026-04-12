from __future__ import annotations

import copy
import json
import re
from typing import Any


VALID_EVIDENCE_LEVELS = {"explicit", "strong", "heuristic", "unresolved"}
VALID_RESOLUTION_STATUSES = {"resolved", "partial", "unresolved"}
EVIDENCE_SCORE_MAP = {
    "explicit": 100,
    "strong": 85,
    "heuristic": 60,
    "unresolved": 20,
}


def _slug(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text or default


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


def _normalize_evidence_level(value: Any, default: str = "unresolved") -> str:
    level = _slug(value, default=default)
    if level not in VALID_EVIDENCE_LEVELS:
        return default
    return level


def _normalize_resolution_status(value: Any, default: str = "unresolved") -> str:
    status = _slug(value, default=default)
    if status not in VALID_RESOLUTION_STATUSES:
        return default
    return status


def _resolution_status_from_evidence(level: str) -> str:
    if level in {"explicit", "strong"}:
        return "resolved"
    if level == "heuristic":
        return "partial"
    return "unresolved"


def _infer_evidence_level(install_unit: dict[str, Any]) -> str:
    provenance_state = str(install_unit.get("provenance_state") or "").strip().lower()
    note_kind = str(install_unit.get("provenance_note_kind") or "").strip().lower()
    install_unit_kind = str(install_unit.get("install_unit_kind") or "").strip().lower()
    package_name = str(install_unit.get("provenance_primary_package_name") or "").strip()
    origin_ref = str(install_unit.get("provenance_primary_origin_ref") or "").strip()
    origin_kind = str(install_unit.get("provenance_primary_origin_kind") or "").strip().lower()
    aggregation_strategy = str(install_unit.get("aggregation_strategy") or "").strip().lower()

    if note_kind == "legacy_root_only":
        return "unresolved"

    if provenance_state == "resolved":
        if package_name:
            return "explicit"
        if install_unit_kind in {
            "git_source",
            "local_source",
            "local_plugin_bundle",
            "documented_source_repo",
            "catalog_source_repo",
            "community_source_repo",
        } and origin_ref:
            return "explicit"
        if aggregation_strategy in {"curated_rule", "source_locator_subpath", "provenance_origin"}:
            return "strong"
        if origin_kind and origin_kind != "skills_root":
            return "strong"
        return "strong"

    if provenance_state == "partial":
        return "heuristic"

    return "unresolved"


def _infer_resolver_path(install_unit: dict[str, Any]) -> str:
    package_strategy = str(install_unit.get("provenance_package_strategy") or "").strip()
    aggregation_strategy = str(install_unit.get("aggregation_strategy") or "").strip()
    note_kind = str(install_unit.get("provenance_note_kind") or "").strip()
    origin_kind = str(install_unit.get("provenance_primary_origin_kind") or "").strip()

    if package_strategy:
        return f"provenance:{package_strategy}"
    if aggregation_strategy:
        return f"aggregation:{aggregation_strategy}"
    if note_kind:
        return f"note:{note_kind}"
    if origin_kind:
        return f"origin:{origin_kind}"
    return "fallback"


def _normalize_registry_install_atom(raw: dict[str, Any], *, generated_at: str = "") -> dict[str, Any]:
    install_unit_id = str(raw.get("install_unit_id") or "").strip()
    if not install_unit_id:
        return {}

    evidence_level = _normalize_evidence_level(raw.get("evidence_level"), default="unresolved")
    resolution_status = _normalize_resolution_status(
        raw.get("resolution_status"),
        default=_resolution_status_from_evidence(evidence_level),
    )
    evidence_score = raw.get("evidence_score")
    try:
        parsed_score = int(evidence_score)
    except Exception:
        parsed_score = EVIDENCE_SCORE_MAP.get(evidence_level, 20)

    first_seen_at = str(raw.get("first_seen_at") or generated_at or "").strip()
    last_seen_at = str(raw.get("last_seen_at") or generated_at or "").strip()
    last_changed_at = str(raw.get("last_changed_at") or last_seen_at or first_seen_at).strip()
    last_resolved_at = str(raw.get("last_resolved_at") or "").strip()
    last_unresolved_at = str(raw.get("last_unresolved_at") or "").strip()

    normalized = {
        "install_unit_id": install_unit_id,
        "display_name": str(raw.get("display_name") or install_unit_id).strip() or install_unit_id,
        "install_unit_kind": str(raw.get("install_unit_kind") or "").strip(),
        "collection_group_id": str(raw.get("collection_group_id") or "").strip(),
        "collection_group_name": str(raw.get("collection_group_name") or "").strip(),
        "collection_group_kind": str(raw.get("collection_group_kind") or "").strip(),
        "install_ref": str(raw.get("install_ref") or "").strip(),
        "install_manager": str(raw.get("install_manager") or "").strip(),
        "update_policy": str(raw.get("update_policy") or "").strip(),
        "management_hint": str(raw.get("management_hint") or "").strip(),
        "source_ids": _dedupe_keep_order(_to_str_list(raw.get("source_ids", []))),
        "deployed_target_ids": _dedupe_keep_order(_to_str_list(raw.get("deployed_target_ids", []))),
        "compatible_software_ids": _dedupe_keep_order(_to_str_list(raw.get("compatible_software_ids", []))),
        "compatible_software_families": _dedupe_keep_order(_to_str_list(raw.get("compatible_software_families", []))),
        "source_count": max(0, int(raw.get("source_count", len(_to_str_list(raw.get("source_ids", [])))) or 0)),
        "member_count": max(0, int(raw.get("member_count", 0) or 0)),
        "status": str(raw.get("status") or "").strip(),
        "freshness_status": str(raw.get("freshness_status") or "").strip(),
        "sync_status": str(raw.get("sync_status") or "").strip(),
        "provenance_state": str(raw.get("provenance_state") or "").strip().lower(),
        "provenance_note_kind": str(raw.get("provenance_note_kind") or "").strip(),
        "provenance_primary_origin_kind": str(raw.get("provenance_primary_origin_kind") or "").strip(),
        "provenance_primary_origin_ref": str(raw.get("provenance_primary_origin_ref") or "").strip(),
        "provenance_primary_origin_label": str(raw.get("provenance_primary_origin_label") or "").strip(),
        "provenance_primary_package_name": str(raw.get("provenance_primary_package_name") or "").strip(),
        "evidence_level": evidence_level,
        "resolution_status": resolution_status,
        "evidence_score": parsed_score,
        "resolver_path": str(raw.get("resolver_path") or "").strip(),
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "last_changed_at": last_changed_at,
        "last_resolved_at": last_resolved_at,
        "last_unresolved_at": last_unresolved_at,
    }
    if not normalized["resolver_path"]:
        normalized["resolver_path"] = _infer_resolver_path(normalized)
    return normalized


def normalize_install_atom_registry(raw: Any) -> dict[str, Any]:
    registry = raw if isinstance(raw, dict) else {}
    generated_at = str(registry.get("generated_at") or "").strip()
    install_atoms: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in registry.get("install_atoms", []):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_registry_install_atom(item, generated_at=generated_at)
        install_unit_id = str(normalized.get("install_unit_id") or "").strip()
        if not install_unit_id or install_unit_id in seen_ids:
            continue
        seen_ids.add(install_unit_id)
        install_atoms.append(normalized)

    install_atoms.sort(
        key=lambda item: (
            str(item.get("display_name") or "").lower(),
            str(item.get("install_unit_id") or "").lower(),
        ),
    )

    counts = {
        "install_atom_total": len(install_atoms),
        "resolved_total": sum(
            1
            for item in install_atoms
            if str(item.get("resolution_status") or "").strip().lower() == "resolved"
        ),
        "partial_total": sum(
            1
            for item in install_atoms
            if str(item.get("resolution_status") or "").strip().lower() == "partial"
        ),
        "unresolved_total": sum(
            1
            for item in install_atoms
            if str(item.get("resolution_status") or "").strip().lower() == "unresolved"
        ),
        "explicit_total": sum(
            1
            for item in install_atoms
            if str(item.get("evidence_level") or "").strip().lower() == "explicit"
        ),
        "strong_total": sum(
            1
            for item in install_atoms
            if str(item.get("evidence_level") or "").strip().lower() == "strong"
        ),
        "heuristic_total": sum(
            1
            for item in install_atoms
            if str(item.get("evidence_level") or "").strip().lower() == "heuristic"
        ),
    }

    return {
        "version": max(1, int(registry.get("version", 1) or 1)),
        "generated_at": generated_at,
        "install_atoms": install_atoms,
        "counts": counts,
    }


def _build_install_atom_signature(record: dict[str, Any]) -> str:
    payload = {
        "display_name": str(record.get("display_name") or "").strip(),
        "install_unit_kind": str(record.get("install_unit_kind") or "").strip(),
        "collection_group_id": str(record.get("collection_group_id") or "").strip(),
        "install_ref": str(record.get("install_ref") or "").strip(),
        "source_ids": _dedupe_keep_order(_to_str_list(record.get("source_ids", []))),
        "status": str(record.get("status") or "").strip(),
        "freshness_status": str(record.get("freshness_status") or "").strip(),
        "sync_status": str(record.get("sync_status") or "").strip(),
        "provenance_state": str(record.get("provenance_state") or "").strip(),
        "provenance_note_kind": str(record.get("provenance_note_kind") or "").strip(),
        "evidence_level": str(record.get("evidence_level") or "").strip(),
        "resolution_status": str(record.get("resolution_status") or "").strip(),
        "resolver_path": str(record.get("resolver_path") or "").strip(),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_install_atom_registry(
    install_unit_rows: list[dict[str, Any]] | None,
    source_rows: list[dict[str, Any]] | None = None,
    *,
    saved_registry: dict[str, Any] | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    units = [item for item in (install_unit_rows or []) if isinstance(item, dict)]
    _ = [item for item in (source_rows or []) if isinstance(item, dict)]
    normalized_saved = normalize_install_atom_registry(saved_registry or {})
    saved_index = {
        str(item.get("install_unit_id") or "").strip(): item
        for item in normalized_saved.get("install_atoms", [])
        if isinstance(item, dict) and str(item.get("install_unit_id") or "").strip()
    }

    install_atoms: list[dict[str, Any]] = []
    for unit in units:
        install_unit_id = str(unit.get("install_unit_id") or "").strip()
        if not install_unit_id:
            continue
        previous = copy.deepcopy(saved_index.get(install_unit_id, {}))
        evidence_level = _infer_evidence_level(unit)
        resolution_status = _resolution_status_from_evidence(evidence_level)
        resolver_path = _infer_resolver_path(unit)
        current = _normalize_registry_install_atom(
            {
                "install_unit_id": install_unit_id,
                "display_name": str(unit.get("display_name") or install_unit_id),
                "install_unit_kind": str(unit.get("install_unit_kind") or ""),
                "collection_group_id": str(unit.get("collection_group_id") or ""),
                "collection_group_name": str(unit.get("collection_group_name") or ""),
                "collection_group_kind": str(unit.get("collection_group_kind") or ""),
                "install_ref": str(unit.get("install_ref") or ""),
                "install_manager": str(unit.get("install_manager") or ""),
                "update_policy": str(unit.get("update_policy") or ""),
                "management_hint": str(unit.get("management_hint") or ""),
                "source_ids": _to_str_list(unit.get("source_ids", [])),
                "deployed_target_ids": _to_str_list(unit.get("deployed_target_ids", [])),
                "compatible_software_ids": _to_str_list(unit.get("compatible_software_ids", [])),
                "compatible_software_families": _to_str_list(unit.get("compatible_software_families", [])),
                "source_count": int(unit.get("source_count", len(_to_str_list(unit.get("source_ids", [])))) or 0),
                "member_count": int(unit.get("member_count", 0) or 0),
                "status": str(unit.get("status") or ""),
                "freshness_status": str(unit.get("freshness_status") or ""),
                "sync_status": str(unit.get("sync_status") or ""),
                "provenance_state": str(unit.get("provenance_state") or ""),
                "provenance_note_kind": str(unit.get("provenance_note_kind") or ""),
                "provenance_primary_origin_kind": str(unit.get("provenance_primary_origin_kind") or ""),
                "provenance_primary_origin_ref": str(unit.get("provenance_primary_origin_ref") or ""),
                "provenance_primary_origin_label": str(unit.get("provenance_primary_origin_label") or ""),
                "provenance_primary_package_name": str(unit.get("provenance_primary_package_name") or ""),
                "evidence_level": evidence_level,
                "resolution_status": resolution_status,
                "resolver_path": resolver_path,
                "first_seen_at": str(previous.get("first_seen_at") or generated_at or ""),
                "last_seen_at": generated_at,
                "last_changed_at": str(previous.get("last_changed_at") or generated_at or ""),
                "last_resolved_at": str(previous.get("last_resolved_at") or ""),
                "last_unresolved_at": str(previous.get("last_unresolved_at") or ""),
            },
            generated_at=generated_at,
        )

        prev_signature = _build_install_atom_signature(previous) if previous else ""
        cur_signature = _build_install_atom_signature(current)
        if not previous:
            current["last_changed_at"] = generated_at
        elif prev_signature != cur_signature:
            current["last_changed_at"] = generated_at
        else:
            current["last_changed_at"] = str(previous.get("last_changed_at") or current.get("last_changed_at") or "")

        if current["resolution_status"] == "resolved":
            current["last_resolved_at"] = generated_at
            current["last_unresolved_at"] = str(previous.get("last_unresolved_at") or "")
        elif current["resolution_status"] == "unresolved":
            current["last_unresolved_at"] = generated_at
            current["last_resolved_at"] = str(previous.get("last_resolved_at") or "")
        else:
            current["last_resolved_at"] = str(previous.get("last_resolved_at") or "")
            current["last_unresolved_at"] = str(previous.get("last_unresolved_at") or "")
        install_atoms.append(current)

    return normalize_install_atom_registry(
        {
            "version": 1,
            "generated_at": generated_at,
            "install_atoms": install_atoms,
        },
    )


def apply_install_atom_registry(
    install_unit_rows: list[dict[str, Any]] | None,
    install_atom_registry: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(item) for item in (install_unit_rows or []) if isinstance(item, dict)]
    registry = normalize_install_atom_registry(install_atom_registry or {})
    atom_index = {
        str(item.get("install_unit_id") or "").strip(): item
        for item in registry.get("install_atoms", [])
        if isinstance(item, dict) and str(item.get("install_unit_id") or "").strip()
    }
    for row in rows:
        install_unit_id = str(row.get("install_unit_id") or "").strip()
        atom = atom_index.get(install_unit_id)
        if not atom:
            continue
        row["aggregation_evidence_level"] = str(atom.get("evidence_level") or "")
        row["aggregation_resolution_status"] = str(atom.get("resolution_status") or "")
        row["aggregation_resolver_path"] = str(atom.get("resolver_path") or "")
        row["aggregation_evidence_score"] = int(atom.get("evidence_score", 0) or 0)
        row["aggregation_last_changed_at"] = str(atom.get("last_changed_at") or "")
        row["aggregation_first_seen_at"] = str(atom.get("first_seen_at") or "")
    return rows
