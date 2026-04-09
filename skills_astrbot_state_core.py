from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None


def _slug(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_") or default


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
    text = str(value or "").strip()
    return [text] if text else []


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


def _read_json_file(path: Path, *, label: str, warnings: list[str]) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"{label} is unreadable: {exc}")
        return {}


def _parse_frontmatter_description(text: str) -> str:
    if not text.startswith("---"):
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return ""

    frontmatter = "\n".join(lines[1:end_idx])
    if yaml is None:
        for line in lines[1:end_idx]:
            if line.strip().startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
        return ""
    try:
        payload = yaml.safe_load(frontmatter) or {}
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    description = payload.get("description", "")
    return description.strip() if isinstance(description, str) else ""


def _find_skill_markdown(skill_dir: Path) -> Path | None:
    canonical = skill_dir / "SKILL.md"
    if canonical.is_file():
        return canonical
    legacy = skill_dir / "skill.md"
    if legacy.is_file():
        return legacy
    return None


def _collect_local_skills(skills_root: Path, warnings: list[str]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    if not skills_root.exists() or not skills_root.is_dir():
        return items

    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = _find_skill_markdown(entry)
        if skill_md is None:
            warnings.append(f"local skill directory missing SKILL.md: {entry.name}")
            continue
        description = ""
        try:
            description = _parse_frontmatter_description(skill_md.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"failed reading {skill_md}: {exc}")
        items[entry.name] = {
            "name": entry.name,
            "local_path": str(skill_md),
            "description": description,
        }
    return items


def _collect_active_flags(skills_config_path: Path, warnings: list[str]) -> dict[str, bool]:
    payload = _read_json_file(skills_config_path, label="skills.json", warnings=warnings)
    if not isinstance(payload, dict):
        return {}
    items = payload.get("skills", {})
    if not isinstance(items, dict):
        return {}
    result: dict[str, bool] = {}
    for name, config in items.items():
        skill_name = str(name or "").strip()
        if not skill_name or not isinstance(config, dict):
            continue
        result[skill_name] = _to_bool(config.get("active", True), True)
    return result


def _collect_sandbox_cache(sandbox_cache_path: Path, warnings: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    payload = _read_json_file(
        sandbox_cache_path,
        label="sandbox_skills_cache.json",
        warnings=warnings,
    )
    if not isinstance(payload, dict):
        return {}, ""
    items = payload.get("skills", [])
    if not isinstance(items, list):
        items = []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        result[name] = {
            "name": name,
            "description": str(item.get("description", "") or ""),
            "sandbox_path": str(item.get("path", "") or ""),
        }
    updated_at = str(payload.get("updated_at", "") or "")
    return result, updated_at


def _collect_neo_map(neo_map_path: Path, warnings: list[str]) -> dict[str, dict[str, Any]]:
    payload = _read_json_file(neo_map_path, label="neo_skill_map.json", warnings=warnings)
    if not isinstance(payload, dict):
        return {}
    items = payload.get("items", {})
    if not isinstance(items, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for skill_key, item in items.items():
        if not isinstance(item, dict):
            continue
        local_skill_name = str(item.get("local_skill_name", "")).strip()
        if not local_skill_name:
            continue
        result[local_skill_name] = {
            "skill_key": str(skill_key or "").strip(),
            "local_skill_name": local_skill_name,
            "latest_release_id": str(item.get("latest_release_id", "") or ""),
            "latest_candidate_id": str(item.get("latest_candidate_id", "") or ""),
            "latest_payload_ref": str(item.get("latest_payload_ref", "") or ""),
            "updated_at": str(item.get("updated_at", "") or ""),
        }
    return result


def _skills_root_candidates(host: dict[str, Any]) -> list[Path]:
    candidates: list[str] = []
    target_paths = host.get("target_paths", {})
    if isinstance(target_paths, dict):
        candidates.extend(_to_str_list(target_paths.get("global", "")))
        candidates.extend(_to_str_list(target_paths.get("workspace", "")))
    candidates.extend(_to_str_list(host.get("resolved_skill_roots", [])))
    candidates.extend(_to_str_list(host.get("declared_skill_roots", [])))
    unique = _dedupe_keep_order(candidates)
    return [Path(Path(text).expanduser()) for text in unique if text]


def _derive_astrbot_layout(skills_root: Path) -> tuple[Path, Path]:
    normalized = skills_root.expanduser()
    if normalized.name == "skills" and normalized.parent.name == "data":
        data_dir = normalized.parent
        root_dir = data_dir.parent
        return root_dir, data_dir
    data_dir = normalized.parent if normalized.parent.name == "data" else normalized.parent
    root_dir = data_dir.parent if data_dir.name == "data" else data_dir.parent
    return root_dir, data_dir


def build_astrbot_host_runtime_state(host: dict[str, Any]) -> dict[str, Any]:
    host_id = str(host.get("host_id") or host.get("id") or "").strip()
    provider_key = str(host.get("provider_key") or host_id).strip()
    if _slug(provider_key or host_id, default="") != "astrbot":
        return {}

    warnings: list[str] = []
    installed = _to_bool(host.get("installed", False), False)
    candidates = _skills_root_candidates(host)
    selected_skills_root = candidates[0] if candidates else Path()
    root_dir = Path()
    data_dir = Path()
    if str(selected_skills_root):
        root_dir, data_dir = _derive_astrbot_layout(selected_skills_root)

    skills_root = selected_skills_root
    skills_config_path = data_dir / "skills.json" if str(data_dir) else Path()
    sandbox_cache_path = data_dir / "sandbox_skills_cache.json" if str(data_dir) else Path()
    neo_map_path = skills_root / "neo_skill_map.json" if str(skills_root) else Path()

    local_skills = _collect_local_skills(skills_root, warnings) if str(skills_root) else {}
    active_flags = _collect_active_flags(skills_config_path, warnings) if str(skills_config_path) else {}
    sandbox_cache, sandbox_updated_at = (
        _collect_sandbox_cache(sandbox_cache_path, warnings) if str(sandbox_cache_path) else ({}, "")
    )
    neo_map = _collect_neo_map(neo_map_path, warnings) if str(neo_map_path) else {}

    state_rows: list[dict[str, Any]] = []
    all_names = sorted(set(local_skills) | set(sandbox_cache) | set(neo_map))
    for skill_name in all_names:
        local_entry = local_skills.get(skill_name, {})
        sandbox_entry = sandbox_cache.get(skill_name, {})
        neo_entry = neo_map.get(skill_name, {})
        local_exists = bool(local_entry)
        sandbox_exists = bool(sandbox_entry)
        neo_managed = bool(neo_entry)
        active = active_flags.get(skill_name, True)

        drift_reasons: list[str] = []
        if neo_managed and not local_exists:
            drift_reasons.append("neo_missing_local_skill")
        if not local_exists and sandbox_exists and skill_name in active_flags:
            drift_reasons.append("sandbox_only_has_local_active_flag")

        if drift_reasons:
            state_classification = "drifted"
        elif neo_managed:
            state_classification = "neo_managed"
        elif local_exists and sandbox_exists:
            state_classification = "synced"
        elif sandbox_exists:
            state_classification = "sandbox_only"
        else:
            state_classification = "local_only"

        row = {
            "host_id": host_id,
            "provider_key": provider_key,
            "skill_name": skill_name,
            "active": active,
            "local_exists": local_exists,
            "sandbox_exists": sandbox_exists,
            "neo_managed": neo_managed,
            "state_classification": state_classification,
            "drift_reasons": drift_reasons,
            "description": str(local_entry.get("description") or sandbox_entry.get("description") or ""),
            "local_path": str(local_entry.get("local_path") or ""),
            "sandbox_path": str(sandbox_entry.get("sandbox_path") or ""),
            "neo_skill_key": str(neo_entry.get("skill_key") or ""),
            "neo_release_id": str(neo_entry.get("latest_release_id") or ""),
            "neo_candidate_id": str(neo_entry.get("latest_candidate_id") or ""),
            "neo_payload_ref": str(neo_entry.get("latest_payload_ref") or ""),
            "neo_updated_at": str(neo_entry.get("updated_at") or ""),
        }
        if drift_reasons:
            warnings.append(f"state drift for {skill_name}: {', '.join(drift_reasons)}")
        state_rows.append(row)

    summary = {
        "host_installed": installed,
        "state_available": bool(candidates),
        "skills_root": str(skills_root) if str(skills_root) else "",
        "astrbot_root": str(root_dir) if str(root_dir) else "",
        "astrbot_data_dir": str(data_dir) if str(data_dir) else "",
        "skills_config_exists": bool(skills_config_path) and skills_config_path.exists(),
        "sandbox_cache_exists": bool(sandbox_cache_path) and sandbox_cache_path.exists(),
        "sandbox_cache_ready": bool(sandbox_cache),
        "sandbox_cache_updated_at": sandbox_updated_at,
        "neo_map_exists": bool(neo_map_path) and neo_map_path.exists(),
        "local_skill_total": sum(1 for item in state_rows if item["local_exists"]),
        "active_skill_total": sum(1 for item in state_rows if item["active"]),
        "sandbox_cached_total": sum(1 for item in state_rows if item["sandbox_exists"]),
        "local_only_total": sum(1 for item in state_rows if item["state_classification"] == "local_only"),
        "synced_total": sum(1 for item in state_rows if item["state_classification"] == "synced"),
        "sandbox_only_total": sum(1 for item in state_rows if item["state_classification"] == "sandbox_only"),
        "neo_managed_total": sum(1 for item in state_rows if item["state_classification"] == "neo_managed"),
        "drifted_total": sum(1 for item in state_rows if item["state_classification"] == "drifted"),
        "state_row_total": len(state_rows),
    }

    return {
        "host_id": host_id,
        "provider_key": provider_key,
        "runtime_state_backend": "astrbot",
        "available": bool(candidates),
        "summary": summary,
        "state_rows": state_rows,
        "warnings": warnings,
    }


def build_astrbot_state_index(host_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_host: dict[str, dict[str, Any]] = {}
    state_rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for host in host_rows:
        if not isinstance(host, dict):
            continue
        state = build_astrbot_host_runtime_state(host)
        if not state:
            continue
        host_id = str(state.get("host_id", "")).strip()
        if not host_id:
            continue
        by_host[host_id] = copy.deepcopy(state)
        state_rows.extend(copy.deepcopy(state.get("state_rows", [])))
        warnings.extend(
            f"astrbot[{host_id}] {warning}"
            for warning in _to_str_list(state.get("warnings", []))
        )

    return {
        "by_host": by_host,
        "rows": state_rows,
        "warnings": warnings,
    }
