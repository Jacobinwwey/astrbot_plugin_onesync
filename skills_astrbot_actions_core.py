from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ASTRBOT_SCOPE_ORDER = ("global", "workspace")
_IGNORED_ZIP_BASENAMES = {".DS_Store"}


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


def _normalize_scope(value: Any, default: str = "global") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in ASTRBOT_SCOPE_ORDER:
        return normalized
    return default


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


def _is_ignored_zip_entry(name: str) -> bool:
    normalized = name.replace("\\", "/").strip()
    if not normalized:
        return True
    if normalized.startswith("__MACOSX/"):
        return True
    basename = PurePosixPath(normalized).name
    return basename in _IGNORED_ZIP_BASENAMES


def _set_skills_active_flags(
    skills_config_path: Path,
    skill_names: list[str],
) -> tuple[bool, str]:
    config, config_error = _read_json_dict(skills_config_path)
    if config_error and skills_config_path.exists():
        return False, config_error
    skills_payload = config.get("skills", {})
    if not isinstance(skills_payload, dict):
        skills_payload = {}
    for skill_name in skill_names:
        normalized_skill_name = _normalize_skill_name(skill_name)
        if not normalized_skill_name:
            continue
        skills_payload[normalized_skill_name] = {"active": True}
    config["skills"] = skills_payload
    _write_json_dict(skills_config_path, config)
    return True, ""


def _safe_extract_zip(zf: zipfile.ZipFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for member in zf.infolist():
        member_name = member.filename.replace("\\", "/").strip()
        if _is_ignored_zip_entry(member_name):
            continue
        if member_name.startswith("/") or re.match(r"^[A-Za-z]:", member_name):
            raise ValueError("Zip archive contains absolute paths.")
        parts = PurePosixPath(member_name).parts
        if ".." in parts:
            raise ValueError("Zip archive contains invalid relative paths.")
        target_path = destination.joinpath(*parts)
        if member.is_dir() or member_name.endswith("/"):
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as src, target_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _resolve_scoped_layout(layout: dict[str, Any], scope: str | None = None) -> tuple[dict[str, Any], str]:
    requested_scope = _normalize_scope(
        scope,
        default=_normalize_scope(layout.get("selected_scope") or layout.get("scope"), default="global"),
    )
    scoped_layouts = layout.get("scoped_layouts", {}) if isinstance(layout.get("scoped_layouts", {}), dict) else {}
    if scoped_layouts:
        scoped = scoped_layouts.get(requested_scope, {})
        if not isinstance(scoped, dict) or not _to_bool(scoped.get("state_available"), False):
            return {}, "scope_unavailable"
        return {
            **layout,
            **scoped,
            "scope": requested_scope,
        }, ""
    if scope is not None:
        return {}, "scope_unavailable"
    return {
        **layout,
        "scope": requested_scope,
    }, ""


def _validate_astrbot_layout(
    layout: dict[str, Any] | None,
    *,
    scope: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized = layout if isinstance(layout, dict) else {}
    if not _to_bool(normalized.get("is_astrbot"), False):
        return {}, "host_is_not_astrbot"
    scoped_layout, scope_error = _resolve_scoped_layout(normalized, scope)
    if scope_error:
        return {}, scope_error
    paths = _skills_paths(scoped_layout)
    skills_root = paths["skills_root"]
    if not str(skills_root):
        return {}, "skills_root_unavailable"
    if not str(paths["skills_config_path"]):
        return {}, "skills_config_path_unavailable"
    if not str(paths["sandbox_cache_path"]):
        return {}, "sandbox_cache_path_unavailable"
    return {
        **scoped_layout,
        **paths,
    }, ""


def set_astrbot_skill_active(
    layout: dict[str, Any] | None,
    skill_name: str,
    active: bool,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout, scope=scope)
    normalized_skill_name = _normalize_skill_name(skill_name)
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "skill_name": normalized_skill_name,
            "scope": _normalize_scope(scope),
        }
    if not normalized_skill_name or not _SKILL_NAME_RE.fullmatch(normalized_skill_name):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name or '<empty>'}",
            "reason_code": "invalid_skill_name",
            "skill_name": normalized_skill_name,
            "scope": str(context.get("scope") or _normalize_scope(scope)),
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
            "scope": str(context.get("scope") or ""),
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
            "scope": str(context.get("scope") or ""),
        }

    config, config_error = _read_json_dict(skills_config_path)
    if config_error and skills_config_path.exists():
        return {
            "ok": False,
            "message": f"skills.json is unreadable: {config_error}",
            "reason_code": "invalid_skills_config",
            "skill_name": normalized_skill_name,
            "scope": str(context.get("scope") or ""),
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
        "scope": str(context.get("scope") or ""),
        "skill_name": normalized_skill_name,
        "active": next_active,
        "changed": previous_active != next_active,
        "local_exists": local_exists,
        "sandbox_exists": sandbox_exists,
        "skills_config_path": str(skills_config_path),
    }


def delete_astrbot_local_skill(
    layout: dict[str, Any] | None,
    skill_name: str,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout, scope=scope)
    normalized_skill_name = _normalize_skill_name(skill_name)
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "skill_name": normalized_skill_name,
            "scope": _normalize_scope(scope),
        }
    if not normalized_skill_name or not _SKILL_NAME_RE.fullmatch(normalized_skill_name):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name or '<empty>'}",
            "reason_code": "invalid_skill_name",
            "skill_name": normalized_skill_name,
            "scope": str(context.get("scope") or _normalize_scope(scope)),
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
            "scope": str(context.get("scope") or ""),
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
            "scope": str(context.get("scope") or ""),
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
            "scope": str(context.get("scope") or ""),
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
                "scope": str(context.get("scope") or ""),
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
        "scope": str(context.get("scope") or ""),
        "skill_name": normalized_skill_name,
        "deleted_local_dir": deleted_local_dir,
        "removed_from_config": removed_from_config,
        "removed_from_sandbox_cache": removed_from_sandbox_cache,
        "local_exists": local_exists,
        "sandbox_exists": sandbox_exists,
    }


def import_astrbot_skill_zip(
    layout: dict[str, Any] | None,
    zip_path: str,
    *,
    scope: str | None = None,
    overwrite: bool = False,
    skill_name_hint: str | None = None,
) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout, scope=scope)
    archive_path = Path(str(zip_path or "").strip()).expanduser()
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "archive_path": str(archive_path),
            "scope": _normalize_scope(scope),
        }
    if not str(archive_path):
        return {
            "ok": False,
            "message": "zip_path is required",
            "reason_code": "zip_path_required",
            "archive_path": "",
            "scope": str(context.get("scope") or ""),
        }
    if not archive_path.exists():
        return {
            "ok": False,
            "message": f"zip file not found: {archive_path}",
            "reason_code": "zip_not_found",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }
    if not zipfile.is_zipfile(archive_path):
        return {
            "ok": False,
            "message": "uploaded file is not a valid zip archive",
            "reason_code": "invalid_zip_archive",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }

    normalized_skill_name_hint = _normalize_skill_name(skill_name_hint)
    if normalized_skill_name_hint and not _SKILL_NAME_RE.fullmatch(normalized_skill_name_hint):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name_hint}",
            "reason_code": "invalid_skill_name",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }

    skills_root = context["skills_root"]
    skills_config_path = context["skills_config_path"]
    installed_skill_names: list[str] = []
    overwritten_skill_names: list[str] = []

    try:
        with zipfile.ZipFile(archive_path) as zf:
            names = [
                name.replace("\\", "/").strip()
                for name in zf.namelist()
                if not _is_ignored_zip_entry(name)
            ]
            file_names = [name for name in names if name and not name.endswith("/")]
            if not file_names:
                return {
                    "ok": False,
                    "message": "zip archive is empty",
                    "reason_code": "empty_zip_archive",
                    "archive_path": str(archive_path),
                    "scope": str(context.get("scope") or ""),
                }

            has_root_skill_md = any(
                len(parts := PurePosixPath(name).parts) == 1 and parts[0] in {"SKILL.md", "skill.md"}
                for name in file_names
            )
            root_mode = has_root_skill_md

            top_dirs = sorted(
                {
                    PurePosixPath(name).parts[0]
                    for name in file_names
                    if PurePosixPath(name).parts
                }
            )

            if not root_mode and not overwrite:
                conflict_dirs: list[str] = []
                for top_dir in top_dirs:
                    normalized_top_dir = _normalize_skill_name(top_dir)
                    if (
                        f"{top_dir}/SKILL.md" not in file_names
                        and f"{top_dir}/skill.md" not in file_names
                    ):
                        continue
                    if not normalized_top_dir or not _SKILL_NAME_RE.fullmatch(normalized_top_dir):
                        continue
                    target_name = (
                        normalized_skill_name_hint
                        if normalized_skill_name_hint and len(top_dirs) == 1
                        else normalized_top_dir
                    )
                    if (skills_root / target_name).exists():
                        conflict_dirs.append(str(skills_root / target_name))
                if conflict_dirs:
                    return {
                        "ok": False,
                        "message": (
                            "one or more skills from the archive already exist and overwrite=false"
                        ),
                        "reason_code": "skill_already_exists",
                        "archive_path": str(archive_path),
                        "scope": str(context.get("scope") or ""),
                        "conflict_paths": conflict_dirs,
                    }

            with tempfile.TemporaryDirectory(prefix="onesync-astrbot-zip-") as temp_dir:
                extract_root = Path(temp_dir) / "extract"
                _safe_extract_zip(zf, extract_root)

                if root_mode:
                    target_name = _normalize_skill_name(normalized_skill_name_hint or archive_path.stem)
                    if not target_name or not _SKILL_NAME_RE.fullmatch(target_name):
                        return {
                            "ok": False,
                            "message": f"invalid skill_name: {target_name or archive_path.stem}",
                            "reason_code": "invalid_skill_name",
                            "archive_path": str(archive_path),
                            "scope": str(context.get("scope") or ""),
                        }
                    if _skill_markdown_path(extract_root) is None:
                        return {
                            "ok": False,
                            "message": "SKILL.md not found in the root of the zip archive",
                            "reason_code": "missing_skill_markdown",
                            "archive_path": str(archive_path),
                            "scope": str(context.get("scope") or ""),
                        }
                    destination = skills_root / target_name
                    if destination.exists():
                        if not overwrite:
                            return {
                                "ok": False,
                                "message": f"skill already exists: {target_name}",
                                "reason_code": "skill_already_exists",
                                "archive_path": str(archive_path),
                                "scope": str(context.get("scope") or ""),
                            }
                        shutil.rmtree(destination)
                        overwritten_skill_names.append(target_name)
                    shutil.move(str(extract_root), str(destination))
                    installed_skill_names.append(target_name)
                else:
                    for top_dir in top_dirs:
                        normalized_top_dir = _normalize_skill_name(top_dir)
                        if (
                            f"{top_dir}/SKILL.md" not in file_names
                            and f"{top_dir}/skill.md" not in file_names
                        ):
                            continue
                        if not normalized_top_dir or not _SKILL_NAME_RE.fullmatch(normalized_top_dir):
                            continue
                        target_name = (
                            normalized_skill_name_hint
                            if normalized_skill_name_hint and len(top_dirs) == 1
                            else normalized_top_dir
                        )
                        source_dir = extract_root / top_dir
                        if _skill_markdown_path(source_dir) is None:
                            continue
                        destination = skills_root / target_name
                        if destination.exists():
                            if not overwrite:
                                return {
                                    "ok": False,
                                    "message": f"skill already exists: {target_name}",
                                    "reason_code": "skill_already_exists",
                                    "archive_path": str(archive_path),
                                    "scope": str(context.get("scope") or ""),
                                }
                            shutil.rmtree(destination)
                            overwritten_skill_names.append(target_name)
                        shutil.move(str(source_dir), str(destination))
                        installed_skill_names.append(target_name)
    except ValueError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "reason_code": "invalid_zip_archive",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"astrbot zip import failed: {exc}",
            "reason_code": "zip_import_failed",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }

    if not installed_skill_names:
        return {
            "ok": False,
            "message": "no valid SKILL.md found in any folder of the zip archive",
            "reason_code": "missing_skill_markdown",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
        }

    saved, config_error = _set_skills_active_flags(skills_config_path, installed_skill_names)
    if not saved:
        return {
            "ok": False,
            "message": f"skills.json is unreadable: {config_error}",
            "reason_code": "invalid_skills_config",
            "archive_path": str(archive_path),
            "scope": str(context.get("scope") or ""),
            "installed_skill_names": installed_skill_names,
        }

    return {
        "ok": True,
        "message": f"astrbot zip imported: {', '.join(installed_skill_names)}",
        "reason_code": "",
        "scope": str(context.get("scope") or ""),
        "archive_path": str(archive_path),
        "installed_skill_names": installed_skill_names,
        "installed_count": len(installed_skill_names),
        "overwritten_skill_names": overwritten_skill_names,
        "skills_config_path": str(skills_config_path),
    }


def export_astrbot_skill_zip(
    layout: dict[str, Any] | None,
    skill_name: str,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    context, context_error = _validate_astrbot_layout(layout, scope=scope)
    normalized_skill_name = _normalize_skill_name(skill_name)
    if context_error:
        return {
            "ok": False,
            "message": f"astrbot action is unavailable: {context_error}",
            "reason_code": context_error,
            "skill_name": normalized_skill_name,
            "scope": _normalize_scope(scope),
        }
    if not normalized_skill_name or not _SKILL_NAME_RE.fullmatch(normalized_skill_name):
        return {
            "ok": False,
            "message": f"invalid skill_name: {normalized_skill_name or '<empty>'}",
            "reason_code": "invalid_skill_name",
            "skill_name": normalized_skill_name,
            "scope": str(context.get("scope") or _normalize_scope(scope)),
        }

    skills_root = context["skills_root"]
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
            "scope": str(context.get("scope") or ""),
        }
    sandbox_exists = normalized_skill_name in sandbox_names
    if (not local_exists) and sandbox_exists:
        return {
            "ok": False,
            "message": "sandbox preset skill cannot be exported from local skill management",
            "reason_code": "sandbox_only_skill",
            "skill_name": normalized_skill_name,
            "local_exists": local_exists,
            "sandbox_exists": sandbox_exists,
            "scope": str(context.get("scope") or ""),
        }
    if not local_exists:
        return {
            "ok": False,
            "message": f"skill not found: {normalized_skill_name}",
            "reason_code": "skill_not_found",
            "skill_name": normalized_skill_name,
            "local_exists": local_exists,
            "sandbox_exists": sandbox_exists,
            "scope": str(context.get("scope") or ""),
        }

    temp_dir = tempfile.mkdtemp(prefix="onesync-astrbot-export-")
    archive_base = str(Path(temp_dir) / normalized_skill_name)
    try:
        archive_path = shutil.make_archive(
            archive_base,
            "zip",
            root_dir=str(skills_root),
            base_dir=normalized_skill_name,
        )
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {
            "ok": False,
            "message": f"astrbot zip export failed: {exc}",
            "reason_code": "zip_export_failed",
            "skill_name": normalized_skill_name,
            "scope": str(context.get("scope") or ""),
        }

    return {
        "ok": True,
        "message": f"astrbot zip exported: {normalized_skill_name}",
        "reason_code": "",
        "scope": str(context.get("scope") or ""),
        "skill_name": normalized_skill_name,
        "archive_path": archive_path,
        "filename": f"{normalized_skill_name}.zip",
        "media_type": "application/zip",
        "local_exists": local_exists,
        "sandbox_exists": sandbox_exists,
    }
