from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from .skills_aggregation_core import PROVENANCE_FIELD_KEYS, derive_source_aggregation_fields, derive_source_provenance_fields
except ImportError:  # pragma: no cover - direct test imports
    from skills_aggregation_core import PROVENANCE_FIELD_KEYS, derive_source_aggregation_fields, derive_source_provenance_fields

VALID_SOURCE_KINDS = {"npx_bundle", "npx_single", "manual_local", "manual_git"}
VALID_SOURCE_SCOPES = {"global", "workspace"}


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


def _resolve_path(path_text: Any) -> str:
    text = str(path_text or "").strip()
    if not text:
        return ""
    return str(Path(os.path.expanduser(text)).resolve())


def _build_generated_source_id(kind: str, locator: str, scope: str) -> str:
    digest = hashlib.sha1(f"{kind}|{scope}|{locator}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}_{digest}"


def _normalize_scope(value: Any, default: str = "global") -> str:
    scope = _slug(value, default=default)
    if scope not in VALID_SOURCE_SCOPES:
        return default
    return scope


def _normalize_source_kind(value: Any, default: str = "manual_local") -> str:
    kind = _slug(value, default=default)
    if kind not in VALID_SOURCE_KINDS:
        return default
    return kind


def _normalize_locator(
    kind: str,
    locator: Any,
    *,
    source_path: Any = "",
    registry_package_name: Any = "",
    source_id: Any = "",
) -> str:
    if kind == "manual_local":
        return _resolve_path(locator or source_path)
    if kind in {"npx_bundle", "npx_single"}:
        return str(registry_package_name or locator or source_path or source_id or "").strip()
    return str(locator or source_path or source_id or "").strip()


def _default_managed_by(kind: str) -> str:
    if kind.startswith("npx_"):
        return "npx"
    return "manual"


def _default_update_policy(kind: str, registry_package_name: str) -> str:
    if kind.startswith("npx_") or registry_package_name:
        return "registry"
    return "manual"


def _normalize_source_subpath(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    text = text.strip("/")
    return text


def _infer_source_kind(discovered_row: dict[str, Any]) -> str:
    tags = set(_to_str_list(discovered_row.get("tags", [])))
    skill_kind = str(discovered_row.get("skill_kind") or discovered_row.get("source_kind") or "").strip().lower()
    if "npx-managed" in tags or str(discovered_row.get("provider_key") or "") == "npx_skills":
        return "npx_bundle" if skill_kind == "skill_bundle" else "npx_single"
    source_path = str(discovered_row.get("source_path") or "").strip()
    if source_path:
        return "manual_local"
    return "manual_git"


def _normalize_registry_source(raw: dict[str, Any], *, generated_at: str = "") -> dict[str, Any]:
    source_kind = _normalize_source_kind(raw.get("source_kind") or raw.get("kind") or _infer_source_kind(raw))
    locator = _normalize_locator(
        source_kind,
        raw.get("locator", ""),
        source_path=raw.get("source_path", ""),
        registry_package_name=raw.get("registry_package_name", ""),
        source_id=raw.get("source_id") or raw.get("id"),
    )
    source_scope = _normalize_scope(raw.get("source_scope") or raw.get("scope"), default="global")
    source_id = str(raw.get("source_id") or raw.get("id") or "").strip()
    if not source_id:
        source_id = _build_generated_source_id(source_kind, locator or "source", source_scope)

    display_name = str(raw.get("display_name") or raw.get("name") or source_id).strip() or source_id
    registry_package_name = str(raw.get("registry_package_name") or "").strip()
    registry_package_manager = str(raw.get("registry_package_manager") or "").strip()
    source_path = str(raw.get("source_path") or "").strip()
    if not source_path and source_kind == "manual_local":
        source_path = locator
    source_subpath = _normalize_source_subpath(raw.get("source_subpath") or raw.get("subpath"))

    normalized = {
        "source_id": source_id,
        "display_name": display_name,
        "source_kind": source_kind,
        "locator": locator,
        "source_subpath": source_subpath,
        "source_scope": source_scope,
        "provider_key": str(raw.get("provider_key") or "generic").strip() or "generic",
        "enabled": _to_bool(raw.get("enabled", True), True),
        "discovered": _to_bool(raw.get("discovered", False), False),
        "auto_discovered": _to_bool(raw.get("auto_discovered", False), False),
        "source_path": source_path,
        "member_count": _to_int(raw.get("member_count", 1), 1, 1),
        "member_skill_preview": _to_str_list(raw.get("member_skill_preview", [])),
        "member_skill_overflow": _to_int(raw.get("member_skill_overflow", 0), 0, 0),
        "management_hint": str(raw.get("management_hint") or "").strip(),
        "managed_by": str(raw.get("managed_by") or _default_managed_by(source_kind)).strip(),
        "update_policy": str(raw.get("update_policy") or _default_update_policy(source_kind, registry_package_name)).strip(),
        "source_exists": _to_bool(raw.get("source_exists", False), False),
        "last_seen_at": str(raw.get("last_seen_at") or "").strip(),
        "last_refresh_at": str(raw.get("last_refresh_at") or raw.get("sync_checked_at") or generated_at or "").strip(),
        "source_age_days": raw.get("source_age_days"),
        "freshness_status": str(raw.get("freshness_status") or ("fresh" if raw.get("source_exists") else "missing")).strip(),
        "registry_package_name": registry_package_name,
        "registry_package_manager": registry_package_manager,
        "sync_auth_token": str(raw.get("sync_auth_token") or "").strip(),
        "sync_auth_header": str(raw.get("sync_auth_header") or "").strip(),
        "sync_api_base": str(raw.get("sync_api_base") or "").strip(),
        "sync_status": str(raw.get("sync_status") or "").strip(),
        "sync_checked_at": str(raw.get("sync_checked_at") or "").strip(),
        "sync_kind": str(raw.get("sync_kind") or "").strip(),
        "sync_message": str(raw.get("sync_message") or "").strip(),
        "sync_local_revision": str(raw.get("sync_local_revision") or "").strip(),
        "sync_remote_revision": str(raw.get("sync_remote_revision") or "").strip(),
        "sync_resolved_revision": str(raw.get("sync_resolved_revision") or "").strip(),
        "sync_branch": str(raw.get("sync_branch") or "").strip(),
        "sync_dirty": _to_bool(raw.get("sync_dirty", False), False),
        "sync_error_code": str(raw.get("sync_error_code") or "").strip(),
        "git_checkout_path": str(raw.get("git_checkout_path") or "").strip(),
        "git_checkout_managed": _to_bool(raw.get("git_checkout_managed", False), False),
        "git_checkout_error": str(raw.get("git_checkout_error") or "").strip(),
        "registry_latest_version": str(raw.get("registry_latest_version") or "").strip(),
        "registry_published_at": str(raw.get("registry_published_at") or "").strip(),
        "registry_homepage": str(raw.get("registry_homepage") or "").strip(),
        "registry_description": str(raw.get("registry_description") or "").strip(),
        "compatible_software_ids": _dedupe_keep_order(_to_str_list(raw.get("compatible_software_ids", []))),
        "compatible_software_families": _dedupe_keep_order(_to_str_list(raw.get("compatible_software_families", []))),
        "tags": _dedupe_keep_order(_to_str_list(raw.get("tags", []))),
        "install_unit_id": str(raw.get("install_unit_id") or "").strip(),
        "install_unit_kind": str(raw.get("install_unit_kind") or "").strip(),
        "install_ref": str(raw.get("install_ref") or "").strip(),
        "install_manager": str(raw.get("install_manager") or "").strip(),
        "install_unit_display_name": str(raw.get("install_unit_display_name") or "").strip(),
        "aggregation_strategy": str(raw.get("aggregation_strategy") or "").strip(),
        "collection_group_id": str(raw.get("collection_group_id") or "").strip(),
        "collection_group_name": str(raw.get("collection_group_name") or "").strip(),
        "collection_group_kind": str(raw.get("collection_group_kind") or "").strip(),
    }
    for field_name in PROVENANCE_FIELD_KEYS:
        normalized[field_name] = str(raw.get(field_name) or "").strip()
    normalized.update(derive_source_provenance_fields(normalized))
    normalized.update(derive_source_aggregation_fields(normalized))
    return normalized


def normalize_skills_registry(raw: Any) -> dict[str, Any]:
    registry = raw if isinstance(raw, dict) else {}
    sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in registry.get("sources", []):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_registry_source(item, generated_at=str(registry.get("generated_at") or ""))
        source_id = str(normalized.get("source_id", "")).strip()
        if not source_id or source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        sources.append(normalized)
    sources.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("source_id", "")).lower()))
    return {
        "version": _to_int(registry.get("version", 1), 1, 1),
        "generated_at": str(registry.get("generated_at") or ""),
        "sources": sources,
    }


def _merge_registry_source(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    sync_authority_keys = {
        "sync_status",
        "sync_checked_at",
        "sync_kind",
        "sync_message",
        "sync_local_revision",
        "sync_remote_revision",
        "sync_resolved_revision",
        "sync_branch",
        "sync_dirty",
        "sync_error_code",
        "registry_latest_version",
        "registry_published_at",
        "registry_homepage",
        "registry_description",
        "git_checkout_path",
        "git_checkout_managed",
        "git_checkout_error",
    }
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key not in merged:
            merged[key] = value
            continue
        if key in sync_authority_keys:
            if str(merged.get("sync_status") or "").strip():
                continue
            current = merged.get(key)
            if isinstance(current, bool):
                continue
            if current is not None and not (isinstance(current, str) and not current.strip()):
                continue
        if isinstance(value, bool):
            merged[key] = value
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        merged[key] = value
    return merged


def build_skills_registry(
    discovered_rows: list[dict[str, Any]],
    *,
    saved_registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    ts = str(generated_at or "")
    normalized_saved = normalize_skills_registry(saved_registry or {})
    merged_index: dict[str, dict[str, Any]] = {
        str(item.get("source_id", "")).strip(): copy.deepcopy(item)
        for item in normalized_saved.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_id", "")).strip()
    }

    for row in discovered_rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_registry_source(
            {
                **row,
                "source_id": row.get("source_id") or row.get("id"),
                "source_kind": row.get("source_kind") or _infer_source_kind(row),
            },
            generated_at=ts,
        )
        source_id = str(normalized.get("source_id", "")).strip()
        if not source_id:
            continue
        existing = merged_index.get(source_id, {})
        merged_index[source_id] = _merge_registry_source(existing, normalized) if existing else normalized

    result = normalize_skills_registry(
        {
            "version": max(1, int(normalized_saved.get("version", 1) or 1)),
            "generated_at": ts or normalized_saved.get("generated_at", ""),
            "sources": list(merged_index.values()),
        },
    )
    return result


def register_registry_source(
    registry: dict[str, Any],
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    normalized_registry = normalize_skills_registry(registry)
    source = _normalize_registry_source(payload, generated_at=str(generated_at or ""))
    if not str(source.get("locator", "")).strip():
        raise ValueError("locator is required")

    source_id = str(source.get("source_id", "")).strip()
    duplicate = next(
        (
            item
            for item in normalized_registry.get("sources", [])
            if str(item.get("source_id", "")).strip() == source_id
            or (
                str(item.get("source_kind", "")).strip() == str(source.get("source_kind", "")).strip()
                and str(item.get("source_scope", "")).strip() == str(source.get("source_scope", "")).strip()
                and str(item.get("locator", "")).strip() == str(source.get("locator", "")).strip()
            )
        ),
        None,
    )
    if duplicate:
        raise ValueError(f"source already exists: {source_id}")

    next_sources = list(normalized_registry.get("sources", [])) + [source]
    return normalize_skills_registry(
        {
            "version": normalized_registry.get("version", 1),
            "generated_at": str(generated_at or normalized_registry.get("generated_at") or ""),
            "sources": next_sources,
        },
    )


def refresh_registry_source(
    registry: dict[str, Any],
    source_id: str,
    updates: dict[str, Any] | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    sync_override_keys = {
        "sync_status",
        "sync_checked_at",
        "sync_kind",
        "sync_message",
        "sync_local_revision",
        "sync_remote_revision",
        "sync_resolved_revision",
        "sync_branch",
        "sync_dirty",
        "sync_error_code",
        "registry_latest_version",
        "registry_published_at",
        "registry_homepage",
        "registry_description",
        "git_checkout_path",
        "git_checkout_managed",
        "git_checkout_error",
    }
    normalized_registry = normalize_skills_registry(registry)
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        raise ValueError("source_id is required")
    update_payload = updates if isinstance(updates, dict) else {}

    found = False
    next_sources: list[dict[str, Any]] = []
    for item in normalized_registry.get("sources", []):
        if str(item.get("source_id", "")).strip() != normalized_source_id:
            next_sources.append(copy.deepcopy(item))
            continue
        found = True
        normalized_updates = _normalize_registry_source(
            {**item, **update_payload, "source_id": normalized_source_id, "last_refresh_at": str(generated_at or "")},
            generated_at=str(generated_at or ""),
        )
        merged = _merge_registry_source(
            item,
            normalized_updates,
        )
        for key in sync_override_keys:
            if key in update_payload or key in normalized_updates:
                merged[key] = normalized_updates.get(key)
        merged["last_refresh_at"] = str(generated_at or merged.get("last_refresh_at") or "")
        next_sources.append(merged)
    if not found:
        raise ValueError(f"source_id not found: {normalized_source_id}")
    return normalize_skills_registry(
        {
            "version": normalized_registry.get("version", 1),
            "generated_at": str(generated_at or normalized_registry.get("generated_at") or ""),
            "sources": next_sources,
        },
    )


def remove_registry_source(
    registry: dict[str, Any],
    source_id: str,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized_registry = normalize_skills_registry(registry)
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        raise ValueError("source_id is required")

    next_sources = [
        copy.deepcopy(item)
        for item in normalized_registry.get("sources", [])
        if str(item.get("source_id", "")).strip() != normalized_source_id
    ]
    if len(next_sources) == len(normalized_registry.get("sources", [])):
        raise ValueError(f"source_id not found: {normalized_source_id}")
    return normalize_skills_registry(
        {
            "version": normalized_registry.get("version", 1),
            "generated_at": str(generated_at or normalized_registry.get("generated_at") or ""),
            "sources": next_sources,
        },
    )
