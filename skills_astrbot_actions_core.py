from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_skill_name(value: Any) -> str:
    return str(value or "").strip()


def _read_json_dict(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)
    if isinstance(payload, dict):
        return payload, ""
    return {}, "json_payload_is_not_object"


def _write_json_dict(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _skills_paths(layout: dict[str, Any] | None) -> dict[str, Path]:
    normalized = layout if isinstance(layout, dict) else {}
    return {
        "skills_root": Path(str(normalized.get("skills_root") or "").strip()).expanduser(),
        "skills_config_path": Path(str(normalized.get("skills_config_path") or "").strip()).expanduser(),
        "sandbox_cache_path": Path(str(normalized.get("sandbox_cache_path") or "").strip()).expanduser(),
    }


def _skill_markdown_path(skill_dir: Path) -> Path | None:
    canonical = skill_dir / "SKILL.md"
    if canonical.is_file():
        return canonical
    legacy = skill_dir / "skill.md"
    if legacy.is_file():
        return legacy
    return None


def _load_sandbox_cache_names(sandbox_cache_path: Path) -> tuple[set[str], str]:
    payload, error = _read_json_dict(sandbox_cache_path)
    if error:
        return set(), error
    items = payload.get("skills", [])
    if not isinstance(items, list):
        return set(), ""
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        skill_name = _normalize_skill_name(item.get("name"))
        if skill_name:
            names.add(skill_name)
    return names, ""


def _validate_astrbot_layout(layout: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    normalized = layout if isinstance(layout, dict) else {}
    if not _to_bool(normalized.get("is_astrbot"), False):
        return {}, "host_is_not_astrbot"
    paths = _skills_paths(normalized)
    skills_root = paths["skills_root"]
    if not str(skills_root):
        return {}, "skills_root_unavailable"
    if not str(paths["skills_config_path"]):
        return {}, "skills_config_path_unavailable"
    if not str(paths["sandbox_cache_path"]):
        return {}, "sandbox_cache_path_unavailable"
    return {
        **normalized,
        **paths,
    }, ""


def set_astrbot_skill_active(
    layout: dict[str, Any] | None,
    skill_name: str,
    active: bool,
) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout)
    normalized_skill_name = _normalize_skill_name(skill_name)
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "skill_name": normalized_skill_name,
        }
    if not normalized_skill_name or not _SKILL_NAME_RE.fullmatch(normalized_skill_name):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name or '<empty>'}",
            "reason_code": "invalid_skill_name",
            "skill_name": normalized_skill_name,
        }

    skills_root = context["skills_root"]
    skills_config_path = context["skills_config_path"]
    sandbox_cache_path = context["sandbox_cache_path"]
    skill_dir = skills_root / normalized_skill_name
    local_exists = _skill_markdown_path(skill_dir) is not None
    sandbox_names, sandbox_error = _load_sandbox_cache_names(sandbox_cache_path)
    if sandbox_error:
        return {
            "ok": False,
            "message": f"sandbox cache is unreadable: {sandbox_error}",
            "reason_code": "invalid_sandbox_cache",
            "skill_name": normalized_skill_name,
        }
    sandbox_exists = normalized_skill_name in sandbox_names
    if (not local_exists) and sandbox_exists:
        return {
            "ok": False,
            "message": (
                "sandbox preset skill cannot be enabled/disabled from local skill management"
            ),
            "reason_code": "sandbox_only_skill",
            "skill_name": normalized_skill_name,
            "local_exists": local_exists,
            "sandbox_exists": sandbox_exists,
        }

    config, config_error = _read_json_dict(skills_config_path)
    if config_error and skills_config_path.exists():
        return {
            "ok": False,
            "message": f"skills.json is unreadable: {config_error}",
            "reason_code": "invalid_skills_config",
            "skill_name": normalized_skill_name,
        }
    skills_payload = config.get("skills", {})
    if not isinstance(skills_payload, dict):
        skills_payload = {}
    previous = skills_payload.get(normalized_skill_name, {})
    previous_active = _to_bool(previous.get("active"), True) if isinstance(previous, dict) else True
    next_active = bool(active)
    skills_payload[normalized_skill_name] = {"active": next_active}
    config["skills"] = skills_payload
    _write_json_dict(skills_config_path, config)

    return {
        "ok": True,
        "message": f"astrbot skill active state updated: {normalized_skill_name}",
        "reason_code": "",
        "skill_name": normalized_skill_name,
        "active": next_active,
        "changed": previous_active != next_active,
        "local_exists": local_exists,
        "sandbox_exists": sandbox_exists,
        "skills_config_path": str(skills_config_path),
    }


def delete_astrbot_local_skill(layout: dict[str, Any] | None, skill_name: str) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout)
    normalized_skill_name = _normalize_skill_name(skill_name)
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "skill_name": normalized_skill_name,
        }
    if not normalized_skill_name or not _SKILL_NAME_RE.fullmatch(normalized_skill_name):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name or '<empty>'}",
            "reason_code": "invalid_skill_name",
            "skill_name": normalized_skill_name,
        }

    skills_root = context["skills_root"]
    skills_config_path = context["skills_config_path"]
    sandbox_cache_path = context["sandbox_cache_path"]
    skill_dir = skills_root / normalized_skill_name
    local_exists = _skill_markdown_path(skill_dir) is not None
    sandbox_names, sandbox_error = _load_sandbox_cache_names(sandbox_cache_path)
    if sandbox_error:
        return {
            "ok": False,
            "message": f"sandbox cache is unreadable: {sandbox_error}",
            "reason_code": "invalid_sandbox_cache",
            "skill_name": normalized_skill_name,
        }
    sandbox_exists = normalized_skill_name in sandbox_names
    if (not local_exists) and sandbox_exists:
        return {
            "ok": False,
            "message": "sandbox preset skill cannot be deleted from local skill management",
            "reason_code": "sandbox_only_skill",
            "skill_name": normalized_skill_name,
            "local_exists": local_exists,
            "sandbox_exists": sandbox_exists,
        }

    deleted_local_dir = False
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
        deleted_local_dir = True

    config, config_error = _read_json_dict(skills_config_path)
    if config_error and skills_config_path.exists():
        return {
            "ok": False,
            "message": f"skills.json is unreadable: {config_error}",
            "reason_code": "invalid_skills_config",
            "skill_name": normalized_skill_name,
        }
    skills_payload = config.get("skills", {})
    if not isinstance(skills_payload, dict):
        skills_payload = {}
    removed_from_config = normalized_skill_name in skills_payload
    if removed_from_config:
        skills_payload.pop(normalized_skill_name, None)
        config["skills"] = skills_payload
        _write_json_dict(skills_config_path, config)

    removed_from_sandbox_cache = False
    if sandbox_cache_path.exists():
        cache_payload, cache_error = _read_json_dict(sandbox_cache_path)
        if cache_error:
            return {
                "ok": False,
                "message": f"sandbox cache is unreadable: {cache_error}",
                "reason_code": "invalid_sandbox_cache",
                "skill_name": normalized_skill_name,
            }
        cache_items = cache_payload.get("skills", [])
        if isinstance(cache_items, list):
            filtered = []
            for item in cache_items:
                if (
                    isinstance(item, dict)
                    and _normalize_skill_name(item.get("name")) == normalized_skill_name
                ):
                    removed_from_sandbox_cache = True
                    continue
                filtered.append(item)
            if removed_from_sandbox_cache:
                cache_payload["skills"] = filtered
                _write_json_dict(sandbox_cache_path, cache_payload)

    return {
        "ok": True,
        "message": f"astrbot local skill deleted: {normalized_skill_name}",
        "reason_code": "",
        "skill_name": normalized_skill_name,
        "deleted_local_dir": deleted_local_dir,
        "removed_from_config": removed_from_config,
        "removed_from_sandbox_cache": removed_from_sandbox_cache,
        "local_exists": local_exists,
        "sandbox_exists": sandbox_exists,
    }
