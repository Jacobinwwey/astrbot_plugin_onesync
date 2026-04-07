from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CURATED_NPX_AGGREGATION_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "compound_engineering",
        "registry_packages": ["@every-env/compound-plugin"],
        "prefixes": ["ce:"],
        "tag_prefixes": ["bundle:compound_engineering"],
        "install_unit_id": "npm:@every-env/compound-plugin",
        "install_unit_kind": "npm_package",
        "install_ref": "@every-env/compound-plugin",
        "install_manager": "bunx",
        "install_unit_display_name": "Compound Engineering",
        "collection_group_id": "collection:compound_engineering",
        "collection_group_name": "Compound Engineering",
        "collection_group_kind": "package",
    },
    {
        "rule_id": "design_review_pack",
        "names": [
            "design-implementation-reviewer",
            "design-iterator",
            "design-lens-reviewer",
        ],
        "install_unit_id": "curated:design_review_pack",
        "install_unit_kind": "curated_npx_pack",
        "install_ref": "design-review-pack",
        "install_manager": "npx",
        "install_unit_display_name": "Design Review Pack",
        "collection_group_id": "collection:design_review",
        "collection_group_name": "Design Review",
        "collection_group_kind": "curated",
    },
    {
        "rule_id": "dhh_rails_pack",
        "prefixes": ["dhh-rails-"],
        "install_unit_id": "curated:dhh_rails_pack",
        "install_unit_kind": "curated_npx_pack",
        "install_ref": "dhh-rails-pack",
        "install_manager": "npx",
        "install_unit_display_name": "DHH Rails Pack",
        "collection_group_id": "collection:dhh_rails",
        "collection_group_name": "DHH Rails",
        "collection_group_kind": "curated",
    },
]

_SOURCE_STATUS_RANK = {
    "missing": 4,
    "unavailable": 3,
    "stale": 2,
    "ready": 1,
    "idle": 0,
}
_FRESHNESS_RANK = {
    "missing": 4,
    "stale": 3,
    "aging": 2,
    "fresh": 1,
}
_SYNC_STATUS_RANK = {
    "error": 3,
    "pending": 2,
    "ok": 1,
    "": 0,
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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_expand_path(path_text: Any) -> Path | None:
    text = str(path_text or "").strip()
    if not text:
        return None
    try:
        return Path(os.path.expanduser(text))
    except Exception:
        return None


def _infer_manager_from_hint(management_hint: str, default: str = "") -> str:
    hint = str(management_hint or "").strip().lower()
    if not hint:
        return default
    if hint.startswith("bunx "):
        return "bunx"
    if hint.startswith("pnpm dlx "):
        return "pnpm"
    if hint.startswith("npx "):
        return "npx"
    return default


def _match_curated_rule(source: dict[str, Any]) -> dict[str, Any] | None:
    registry_package_name = str(source.get("registry_package_name") or "").strip().lower()
    names = {
        str(source.get("display_name") or "").strip().lower(),
        *[str(item or "").strip().lower() for item in _to_str_list(source.get("member_skill_preview", []))],
    }
    names = {item for item in names if item}
    tags = {
        str(item or "").strip().lower()
        for item in _to_str_list(source.get("tags", []))
    }
    for rule in CURATED_NPX_AGGREGATION_RULES:
        registry_packages = {
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("registry_packages", []))
        }
        if registry_package_name and registry_package_name in registry_packages:
            return dict(rule)

        rule_names = {
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("names", []))
        }
        if rule_names and names.intersection(rule_names):
            return dict(rule)

        prefixes = [
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("prefixes", []))
            if str(item or "").strip()
        ]
        if prefixes and any(any(name.startswith(prefix) for prefix in prefixes) for name in names):
            return dict(rule)

        tag_prefixes = [
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("tag_prefixes", []))
            if str(item or "").strip()
        ]
        if tag_prefixes and any(any(tag.startswith(prefix) for prefix in tag_prefixes) for tag in tags):
            return dict(rule)
    return None


def _package_name_from_path_heuristic(path_text: str) -> str:
    normalized = str(path_text or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    match = re.search(r"/node_modules/((?:@[^/]+/)?[^/]+)", normalized)
    if match:
        return str(match.group(1) or "").strip()
    return ""


def _package_name_from_nearest_package_json(path_text: str) -> str:
    path = _safe_expand_path(path_text)
    if not path or not path.exists():
        return ""

    current = path if path.is_dir() else path.parent
    max_hops = 4
    for _ in range(max_hops + 1):
        package_json = current / "package.json"
        if package_json.exists() and package_json.is_file():
            try:
                payload = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            package_name = str(payload.get("name") or "").strip()
            if package_name:
                return package_name
        if current.parent == current:
            break
        current = current.parent
    return ""


def _infer_npx_package(source: dict[str, Any]) -> tuple[str, str]:
    for candidate in (
        str(source.get("source_path") or "").strip(),
        str(source.get("locator") or "").strip(),
    ):
        package_name = _package_name_from_path_heuristic(candidate)
        if package_name:
            return package_name, "path_heuristic"
        package_name = _package_name_from_nearest_package_json(candidate)
        if package_name:
            return package_name, "package_json"
    return "", ""


def derive_source_aggregation_fields(source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("source_id") or source.get("id") or "").strip()
    display_name = str(source.get("display_name") or source_id).strip() or source_id
    source_kind = str(source.get("source_kind") or source.get("skill_kind") or "").strip().lower()
    locator = _first_non_empty(source.get("locator"), source.get("source_path"), source_id)
    management_hint = str(source.get("management_hint") or "").strip()
    registry_package_name = str(source.get("registry_package_name") or "").strip()
    registry_package_manager = str(source.get("registry_package_manager") or "").strip()

    existing_install_unit_id = str(source.get("install_unit_id") or "").strip()
    existing_install_unit_kind = str(source.get("install_unit_kind") or "").strip()
    existing_install_ref = str(source.get("install_ref") or "").strip()
    existing_install_manager = str(source.get("install_manager") or "").strip()
    existing_install_display_name = str(source.get("install_unit_display_name") or "").strip()
    existing_strategy = str(source.get("aggregation_strategy") or "").strip()

    rule = _match_curated_rule(source)
    install_unit_id = existing_install_unit_id
    install_unit_kind = existing_install_unit_kind
    install_ref = existing_install_ref
    install_manager = existing_install_manager
    install_unit_display_name = existing_install_display_name
    aggregation_strategy = existing_strategy

    if not install_unit_id:
        if registry_package_name:
            install_unit_id = f"npm:{registry_package_name}"
            install_unit_kind = "npm_package"
            install_ref = registry_package_name
            install_manager = registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
            install_unit_display_name = str(rule.get("install_unit_display_name") or display_name) if rule else display_name
            aggregation_strategy = "explicit_rule" if rule else "registry_package"
        elif source_kind == "manual_git":
            install_unit_id = f"git:{locator}"
            install_unit_kind = "git_source"
            install_ref = locator
            install_manager = "git"
            install_unit_display_name = display_name
            aggregation_strategy = "source_locator"
        elif source_kind == "manual_local":
            install_unit_id = f"local:{locator}"
            install_unit_kind = "local_source"
            install_ref = locator
            install_manager = "filesystem"
            install_unit_display_name = display_name
            aggregation_strategy = "source_locator"
        elif source_kind == "npx_bundle":
            if rule:
                install_unit_id = str(rule.get("install_unit_id") or f"bundle:{source_id}")
                install_unit_kind = str(rule.get("install_unit_kind") or "curated_npx_pack")
                install_ref = str(rule.get("install_ref") or locator or source_id)
                install_manager = str(rule.get("install_manager") or _infer_manager_from_hint(management_hint, "npx"))
                install_unit_display_name = str(rule.get("install_unit_display_name") or display_name)
                aggregation_strategy = "explicit_rule"
            else:
                install_unit_id = f"bundle:{source_id}"
                install_unit_kind = "npx_bundle"
                install_ref = locator or source_id
                install_manager = _infer_manager_from_hint(management_hint, "npx")
                install_unit_display_name = display_name
                aggregation_strategy = "source_bundle"
        elif source_kind == "npx_single":
            inferred_package_name, inferred_strategy = _infer_npx_package(source)
            if inferred_package_name:
                install_unit_id = f"npm:{inferred_package_name}"
                install_unit_kind = "npm_package"
                install_ref = inferred_package_name
                install_manager = registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
                install_unit_display_name = display_name
                aggregation_strategy = inferred_strategy
            elif rule:
                install_unit_id = str(rule.get("install_unit_id") or f"curated:{_slug(display_name, default='pack')}")
                install_unit_kind = str(rule.get("install_unit_kind") or "curated_npx_pack")
                install_ref = str(rule.get("install_ref") or display_name)
                install_manager = str(rule.get("install_manager") or _infer_manager_from_hint(management_hint, "npx"))
                install_unit_display_name = str(rule.get("install_unit_display_name") or display_name)
                aggregation_strategy = "curated_override"
            else:
                install_unit_id = f"synthetic_single:{source_id}"
                install_unit_kind = "synthetic_single"
                install_ref = source_id or display_name
                install_manager = _infer_manager_from_hint(management_hint, "npx")
                install_unit_display_name = display_name
                aggregation_strategy = "fallback_single"
        else:
            install_unit_id = f"source:{source_id}"
            install_unit_kind = source_kind or "source"
            install_ref = locator or source_id
            install_manager = _infer_manager_from_hint(management_hint, "")
            install_unit_display_name = display_name
            aggregation_strategy = "source_identity"

    collection_group_id = str(source.get("collection_group_id") or "").strip()
    collection_group_name = str(source.get("collection_group_name") or "").strip()
    collection_group_kind = str(source.get("collection_group_kind") or "").strip()
    if not collection_group_id:
        if rule:
            collection_group_id = str(rule.get("collection_group_id") or f"collection:{_slug(install_unit_display_name, default='group')}")
            collection_group_name = str(rule.get("collection_group_name") or install_unit_display_name or display_name)
            collection_group_kind = str(rule.get("collection_group_kind") or "curated")
        else:
            group_name = install_unit_display_name or display_name or install_ref or source_id
            collection_group_id = f"collection:{_slug(group_name, default='group')}"
            collection_group_name = group_name
            collection_group_kind = "install_unit"

    return {
        "install_unit_id": install_unit_id,
        "install_unit_kind": install_unit_kind,
        "install_ref": install_ref,
        "install_manager": install_manager,
        "install_unit_display_name": install_unit_display_name or display_name,
        "aggregation_strategy": aggregation_strategy or "fallback_single",
        "collection_group_id": collection_group_id,
        "collection_group_name": collection_group_name or install_unit_display_name or display_name,
        "collection_group_kind": collection_group_kind or "install_unit",
    }


def enrich_source_aggregation(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **source,
        **derive_source_aggregation_fields(source),
    }


def _aggregate_status(values: list[str], ranks: dict[str, int], default: str) -> str:
    best_value = default
    best_rank = -1
    for value in values:
        key = str(value or "").strip().lower()
        rank = ranks.get(key, -1)
        if rank > best_rank:
            best_rank = rank
            best_value = key or default
    return best_value


def _build_member_preview(values: list[str], limit: int = 6) -> tuple[list[str], int]:
    preview = _dedupe_keep_order([str(item or "").strip() for item in values if str(item or "").strip()])
    kept = preview[:limit]
    overflow = max(0, len(preview) - len(kept))
    return kept, overflow


def _build_deployed_target_map(deploy_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in deploy_rows:
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "").strip()
        if not target_id:
            continue
        for source_id in _to_str_list(row.get("selected_source_ids", [])):
            result.setdefault(source_id, []).append(target_id)
    return {
        source_id: _dedupe_keep_order(target_ids)
        for source_id, target_ids in result.items()
    }


def build_install_unit_rows(source_rows: list[dict[str, Any]], deploy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deployed_target_map = _build_deployed_target_map(deploy_rows)
    grouped: dict[str, dict[str, Any]] = {}

    for raw_source in source_rows:
        if not isinstance(raw_source, dict):
            continue
        source = enrich_source_aggregation(raw_source)
        install_unit_id = str(source.get("install_unit_id") or "").strip()
        if not install_unit_id:
            continue
        row = grouped.setdefault(
            install_unit_id,
            {
                "install_unit_id": install_unit_id,
                "install_unit_kind": str(source.get("install_unit_kind") or ""),
                "display_name": str(source.get("install_unit_display_name") or source.get("display_name") or install_unit_id),
                "install_ref": str(source.get("install_ref") or ""),
                "install_manager": str(source.get("install_manager") or ""),
                "aggregation_strategy": str(source.get("aggregation_strategy") or ""),
                "collection_group_id": str(source.get("collection_group_id") or ""),
                "collection_group_name": str(source.get("collection_group_name") or ""),
                "collection_group_kind": str(source.get("collection_group_kind") or ""),
                "registry_package_name": str(source.get("registry_package_name") or ""),
                "registry_package_manager": str(source.get("registry_package_manager") or ""),
                "management_hint": str(source.get("management_hint") or ""),
                "managed_by": str(source.get("managed_by") or ""),
                "update_policy": str(source.get("update_policy") or ""),
                "source_ids": [],
                "scopes": [],
                "member_names": [],
                "member_total": 0,
                "compatible_software_ids": [],
                "compatible_software_families": [],
                "status_values": [],
                "freshness_values": [],
                "sync_status_values": [],
                "deployed_target_ids": [],
            },
        )
        source_id = str(source.get("source_id") or source.get("id") or "").strip()
        if source_id:
            row["source_ids"].append(source_id)
            row["deployed_target_ids"].extend(deployed_target_map.get(source_id, []))
        row["scopes"].append(str(source.get("source_scope") or "global"))
        row["member_names"].extend(_to_str_list(source.get("member_skill_preview", [])) or [str(source.get("display_name") or source_id)])
        row["member_total"] += max(1, int(source.get("member_count", 1) or 1))
        row["compatible_software_ids"].extend(_to_str_list(source.get("compatible_software_ids", [])))
        row["compatible_software_families"].extend(_to_str_list(source.get("compatible_software_families", [])))
        row["status_values"].append(str(source.get("status") or ""))
        row["freshness_values"].append(str(source.get("freshness_status") or ""))
        row["sync_status_values"].append(str(source.get("sync_status") or ""))
        if not row["registry_package_name"]:
            row["registry_package_name"] = str(source.get("registry_package_name") or "")
        if not row["registry_package_manager"]:
            row["registry_package_manager"] = str(source.get("registry_package_manager") or "")
        if not row["management_hint"]:
            row["management_hint"] = str(source.get("management_hint") or "")
        if not row["managed_by"]:
            row["managed_by"] = str(source.get("managed_by") or "")
        if not row["update_policy"]:
            row["update_policy"] = str(source.get("update_policy") or "")

    result: list[dict[str, Any]] = []
    for row in grouped.values():
        source_ids = sorted(_dedupe_keep_order(row.pop("source_ids")))
        member_preview, member_overflow = _build_member_preview(row.pop("member_names"))
        deployed_target_ids = _dedupe_keep_order(row.pop("deployed_target_ids"))
        compatible_software_ids = _dedupe_keep_order(row.pop("compatible_software_ids"))
        compatible_software_families = _dedupe_keep_order(row.pop("compatible_software_families"))
        scopes = _dedupe_keep_order(row.pop("scopes"))
        member_total = int(row.pop("member_total") or 0)
        status = _aggregate_status(row.pop("status_values"), _SOURCE_STATUS_RANK, "ready")
        freshness_status = _aggregate_status(row.pop("freshness_values"), _FRESHNESS_RANK, "missing")
        sync_status = _aggregate_status(row.pop("sync_status_values"), _SYNC_STATUS_RANK, "")

        result.append(
            {
                **row,
                "source_ids": source_ids,
                "source_count": len(source_ids),
                "primary_source_id": source_ids[0] if len(source_ids) == 1 else "",
                "scope": scopes[0] if len(scopes) == 1 else "mixed",
                "scopes": scopes,
                "member_count": member_total or max(1, len(member_preview) + member_overflow),
                "member_skill_preview": member_preview,
                "member_skill_overflow": member_overflow,
                "compatible_software_ids": compatible_software_ids,
                "compatible_software_families": compatible_software_families,
                "status": status,
                "freshness_status": freshness_status,
                "sync_status": sync_status,
                "deployed_target_ids": deployed_target_ids,
                "deployed_target_count": len(deployed_target_ids),
            },
        )

    result.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("install_unit_id", "")).lower()))
    return result


def build_collection_group_rows(install_unit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for install_unit in install_unit_rows:
        if not isinstance(install_unit, dict):
            continue
        collection_group_id = str(install_unit.get("collection_group_id") or "").strip()
        if not collection_group_id:
            continue
        row = grouped.setdefault(
            collection_group_id,
            {
                "collection_group_id": collection_group_id,
                "display_name": str(install_unit.get("collection_group_name") or install_unit.get("display_name") or collection_group_id),
                "collection_group_name": str(install_unit.get("collection_group_name") or install_unit.get("display_name") or collection_group_id),
                "collection_group_kind": str(install_unit.get("collection_group_kind") or ""),
                "install_unit_ids": [],
                "source_ids": [],
                "member_names": [],
                "member_total": 0,
                "compatible_software_ids": [],
                "compatible_software_families": [],
                "status_values": [],
                "freshness_values": [],
                "sync_status_values": [],
                "deployed_target_ids": [],
                "management_hint": "",
                "managed_by": "",
                "update_policy": "",
                "registry_package_name": "",
                "registry_package_manager": "",
            },
        )
        row["install_unit_ids"].append(str(install_unit.get("install_unit_id") or ""))
        row["source_ids"].extend(_to_str_list(install_unit.get("source_ids", [])))
        row["member_names"].extend(_to_str_list(install_unit.get("member_skill_preview", [])))
        row["member_total"] += max(1, int(install_unit.get("member_count", 1) or 1))
        row["compatible_software_ids"].extend(_to_str_list(install_unit.get("compatible_software_ids", [])))
        row["compatible_software_families"].extend(_to_str_list(install_unit.get("compatible_software_families", [])))
        row["status_values"].append(str(install_unit.get("status") or ""))
        row["freshness_values"].append(str(install_unit.get("freshness_status") or ""))
        row["sync_status_values"].append(str(install_unit.get("sync_status") or ""))
        row["deployed_target_ids"].extend(_to_str_list(install_unit.get("deployed_target_ids", [])))
        if not row["management_hint"]:
            row["management_hint"] = str(install_unit.get("management_hint") or "")
        if not row["managed_by"]:
            row["managed_by"] = str(install_unit.get("managed_by") or "")
        if not row["update_policy"]:
            row["update_policy"] = str(install_unit.get("update_policy") or "")
        if not row["registry_package_name"]:
            row["registry_package_name"] = str(install_unit.get("registry_package_name") or "")
        if not row["registry_package_manager"]:
            row["registry_package_manager"] = str(install_unit.get("registry_package_manager") or "")

    result: list[dict[str, Any]] = []
    for row in grouped.values():
        source_ids = sorted(_dedupe_keep_order(row.pop("source_ids")))
        install_unit_ids = _dedupe_keep_order(row.pop("install_unit_ids"))
        member_preview, member_overflow = _build_member_preview(row.pop("member_names"))
        deployed_target_ids = _dedupe_keep_order(row.pop("deployed_target_ids"))
        compatible_software_ids = _dedupe_keep_order(row.pop("compatible_software_ids"))
        compatible_software_families = _dedupe_keep_order(row.pop("compatible_software_families"))
        member_total = int(row.pop("member_total") or 0)
        status = _aggregate_status(row.pop("status_values"), _SOURCE_STATUS_RANK, "ready")
        freshness_status = _aggregate_status(row.pop("freshness_values"), _FRESHNESS_RANK, "missing")
        sync_status = _aggregate_status(row.pop("sync_status_values"), _SYNC_STATUS_RANK, "")

        result.append(
            {
                **row,
                "install_unit_ids": install_unit_ids,
                "install_unit_count": len(install_unit_ids),
                "source_ids": source_ids,
                "source_count": len(source_ids),
                "primary_source_id": source_ids[0] if len(source_ids) == 1 else "",
                "member_count": member_total or max(1, len(member_preview) + member_overflow),
                "member_skill_preview": member_preview,
                "member_skill_overflow": member_overflow,
                "compatible_software_ids": compatible_software_ids,
                "compatible_software_families": compatible_software_families,
                "status": status,
                "freshness_status": freshness_status,
                "sync_status": sync_status,
                "deployed_target_ids": deployed_target_ids,
                "deployed_target_count": len(deployed_target_ids),
            },
        )

    result.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("collection_group_id", "")).lower()))
    return result


def build_compatible_aggregate_rows_by_software(
    aggregate_rows: list[dict[str, Any]],
    compatible_source_rows_by_software: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for software_id, source_rows in compatible_source_rows_by_software.items():
        compatible_source_ids = {
            str(item.get("source_id") or item.get("id") or "").strip()
            for item in source_rows
            if isinstance(item, dict) and str(item.get("source_id") or item.get("id") or "").strip()
        }
        result[str(software_id)] = [
            dict(item)
            for item in aggregate_rows
            if compatible_source_ids.intersection(
                {
                    str(source_id or "").strip()
                    for source_id in _to_str_list(item.get("source_ids", []))
                    if str(source_id or "").strip()
                },
            )
        ]
    return result
