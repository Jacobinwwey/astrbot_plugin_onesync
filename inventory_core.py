from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

try:
    from .skills_hosts_core import DEFAULT_SOFTWARE_CATALOG, PROVIDER_DEFAULTS
    from .skills_aggregation_core import derive_source_aggregation_fields, derive_source_provenance_fields
except ImportError:  # pragma: no cover - direct test imports
    from skills_hosts_core import DEFAULT_SOFTWARE_CATALOG, PROVIDER_DEFAULTS
    from skills_aggregation_core import derive_source_aggregation_fields, derive_source_provenance_fields

VALID_SOFTWARE_KINDS = {"cli", "gui", "claw", "other"}
VALID_BINDING_SCOPES = {"global", "workspace"}
VALID_SKILL_MANAGEMENT_MODES = {"npx", "filesystem", "hybrid"}
SOURCE_FRESH_MAX_AGE_DAYS = 7
SOURCE_AGING_MAX_AGE_DAYS = 30

DEFAULT_PRIORITY_CLI_COMMANDS = [
    "claude",
    "codex",
    "zeroclaw",
    "cursor-agent",
    "opencode",
    "aider",
    "gemini",
    "gemini-cli",
    "qwen",
    "qwen-code",
    "roo",
    "roo-code",
    "windsurf",
    "openhands",
    "continue",
    "goose",
    "kiro",
    "crush",
    "amp",
    "cursor",
]

AUTO_CLI_DISPLAY_NAME_OVERRIDES = {
    "claude": "Claude Code",
    "codex": "Codex",
    "zeroclaw": "ZeroClaw",
    "cursor-agent": "Cursor Agent",
    "opencode": "OpenCode",
    "aider": "Aider",
    "gemini-cli": "Gemini CLI",
    "qwen-code": "Qwen Code",
    "roo-code": "Roo Code",
    "openhands": "OpenHands",
}

KNOWN_SKILL_CAPABLE_SOFTWARE_FAMILIES = {
    "claude",
    "claude_code",
    "codex",
    "zeroclaw",
    "antigravity",
    "cursor",
    "cursor_agent",
    "opencode",
    "aider",
    "gemini",
    "gemini_cli",
    "qwen",
    "qwen_code",
    "roo",
    "roo_code",
    "windsurf",
    "openhands",
    "continue",
    "goose",
    "kiro",
    "crush",
    "amp",
}

AGENT_SOFTWARE_FAMILY_ALIASES = {
    "claude": "claude_code",
    "claude code": "claude_code",
    "codex": "codex",
    "zeroclaw": "zeroclaw",
    "antigravity": "antigravity",
    "cursor": "cursor",
    "cursor agent": "cursor_agent",
    "opencode": "opencode",
    "aider": "aider",
    "gemini": "gemini",
    "gemini cli": "gemini_cli",
    "qwen": "qwen",
    "qwen code": "qwen_code",
    "roo": "roo",
    "roo code": "roo_code",
    "windsurf": "windsurf",
    "openhands": "openhands",
    "continue": "continue",
    "goose": "goose",
    "kiro": "kiro",
    "crush": "crush",
    "amp": "amp",
}

NPX_NAMESPACE_BUNDLE_RULES = [
    {
        "prefix": "ce:",
        "bundle_key": "compound_engineering",
        "display_name": "Compound Engineering",
        "provider_key": "compound_engineering",
        "management_hint": "bunx @every-env/compound-plugin",
        "registry_package_name": "@every-env/compound-plugin",
        "registry_package_manager": "npm",
    },
]

# Root-directory aggregation is intentionally disabled. Shared roots like
# ~/.codex/skills or ~/.agents/skills can contain many unrelated npx packages,
# and collapsing them into a synthetic "skill pack" hides real package
# boundaries from the management UI.
NPX_ROOT_BUNDLE_RULES: list[dict[str, Any]] = []

NPX_ROOT_BUNDLE_THRESHOLD = 8

DEFAULT_AUTO_CLI_EXCLUDE = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "dash",
    "cat",
    "ls",
    "cp",
    "mv",
    "rm",
    "mkdir",
    "rmdir",
    "grep",
    "sed",
    "awk",
    "sort",
    "uniq",
    "find",
    "xargs",
    "head",
    "tail",
    "wc",
    "chmod",
    "chown",
    "sudo",
    "su",
    "env",
    "printenv",
    "date",
    "sleep",
    "pwd",
    "which",
    "whereis",
    "whoami",
    "ps",
    "kill",
    "pkill",
    "nohup",
    "tar",
    "gzip",
    "gunzip",
    "unzip",
    "zip",
    "curl",
    "wget",
    "ssh",
    "scp",
    "sftp",
}


def _slug(value: Any, default: str = "item") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text or default


def _to_bool(value: Any, default: bool) -> bool:
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


def _to_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        parsed = min_value
    if max_value is not None and parsed > max_value:
        parsed = max_value
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
                return _to_str_list(parsed)
            except Exception:
                pass
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


def _parse_list_payload(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            raise ValueError("expected JSON array payload") from None
        if not isinstance(parsed, list):
            raise ValueError("payload must be a JSON array")
        return parsed
    raise ValueError("payload must be a list or JSON array string")


def _provider_defaults(provider_key: str) -> dict[str, Any]:
    key = str(provider_key or "").strip().lower()
    return dict(PROVIDER_DEFAULTS.get(key, {}))


def normalize_software_catalog_payload(
    raw: Any,
    *,
    fallback_defaults: bool = True,
) -> list[dict[str, Any]]:
    rows = _parse_list_payload(raw)
    if not rows and fallback_defaults:
        rows = DEFAULT_SOFTWARE_CATALOG

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        provider_key = _slug(item.get("provider_key") or item.get("id") or f"software_{index}")
        defaults = _provider_defaults(provider_key)

        software_id = _slug(item.get("id") or provider_key or f"software_{index}")
        if software_id in seen_ids:
            raise ValueError(f"duplicated software id: {software_id}")
        seen_ids.add(software_id)

        software_kind = _slug(item.get("software_kind") or defaults.get("software_kind") or "other")
        if software_kind not in VALID_SOFTWARE_KINDS:
            software_kind = "other"

        detect = item.get("detect", {})
        if not isinstance(detect, dict):
            detect = {}

        detect_paths = _dedupe_keep_order(
            _to_str_list(item.get("detect_paths"))
            + _to_str_list(detect.get("paths"))
            + _to_str_list(defaults.get("detect_paths"))
        )
        detect_commands = _dedupe_keep_order(
            _to_str_list(item.get("detect_commands"))
            + _to_str_list(detect.get("commands"))
            + _to_str_list(defaults.get("detect_commands"))
        )
        skill_roots = _dedupe_keep_order(
            _to_str_list(item.get("skill_roots"))
            + _to_str_list(defaults.get("skill_roots"))
        )
        normalized.append(
            {
                "id": software_id,
                "display_name": str(item.get("display_name") or defaults.get("display_name") or software_id),
                "software_kind": software_kind,
                "provider_key": provider_key,
                "linked_target_name": str(item.get("linked_target_name", "")).strip(),
                "enabled": _to_bool(item.get("enabled", True), True),
                "detect_paths": detect_paths,
                "detect_commands": detect_commands,
                "skill_roots": skill_roots,
                "tags": _to_str_list(item.get("tags")),
            },
        )
    return normalized


def normalize_skill_catalog_payload(raw: Any) -> list[dict[str, Any]]:
    rows = _parse_list_payload(raw)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        skill_id = _slug(item.get("id") or item.get("name") or f"skill_{index}")
        if skill_id in seen_ids:
            raise ValueError(f"duplicated skill id: {skill_id}")
        seen_ids.add(skill_id)

        detect = item.get("detect", {})
        if not isinstance(detect, dict):
            detect = {}
        source_path = str(item.get("source_path", "")).strip()
        detect_paths = _dedupe_keep_order(
            _to_str_list(item.get("detect_paths"))
            + _to_str_list(detect.get("paths"))
            + ([source_path] if source_path else [])
        )
        compatible = _dedupe_keep_order(
            _to_str_list(item.get("compatible_software_kinds") or item.get("compatible_kinds"))
        )
        compatible = [
            _slug(kind)
            for kind in compatible
            if _slug(kind) in VALID_SOFTWARE_KINDS
        ]
        normalized.append(
            {
                "id": skill_id,
                "display_name": str(item.get("display_name") or item.get("name") or skill_id),
                "provider_key": _slug(item.get("provider_key") or "generic"),
                "skill_kind": str(item.get("skill_kind") or "skill"),
                "enabled": _to_bool(item.get("enabled", True), True),
                "source_path": source_path,
                "detect_paths": detect_paths,
                "compatible_software_kinds": compatible,
                "compatible_software_families": _dedupe_keep_order(
                    [_slug(name, default="") for name in _to_str_list(item.get("compatible_software_families", [])) if _slug(name, default="")],
                ),
                "tags": _to_str_list(item.get("tags")),
                "auto_discovered": False,
                "source_scope": str(item.get("source_scope") or "global"),
                "management_hint": str(item.get("management_hint") or ""),
                "registry_package_name": str(item.get("registry_package_name") or ""),
                "registry_package_manager": str(item.get("registry_package_manager") or ""),
            },
        )
    return normalized


def normalize_skill_bindings_payload(raw: Any) -> list[dict[str, Any]]:
    rows = _parse_list_payload(raw)
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        software_id = _slug(item.get("software_id"))
        skill_id = _slug(item.get("skill_id"))
        if not software_id or not skill_id:
            continue
        scope = _slug(item.get("scope") or "global")
        if scope not in VALID_BINDING_SCOPES:
            scope = "global"
        key = (software_id, skill_id, scope)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized.append(
            {
                "software_id": software_id,
                "skill_id": skill_id,
                "scope": scope,
                "enabled": _to_bool(item.get("enabled", True), True),
                "settings": item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {},
            },
        )
    return normalized


def replace_bindings_for_scope(
    current_bindings: Any,
    *,
    software_id: Any,
    skill_ids: Any,
    scope: Any = "global",
) -> list[dict[str, Any]]:
    software_key = _slug(software_id)
    if not software_key:
        return normalize_skill_bindings_payload(current_bindings)

    scope_key = _slug(scope or "global")
    if scope_key not in VALID_BINDING_SCOPES:
        scope_key = "global"

    normalized_current = normalize_skill_bindings_payload(current_bindings)
    normalized_skill_ids = _dedupe_keep_order(
        [_slug(item) for item in _to_str_list(skill_ids) if _slug(item)],
    )

    next_bindings = [
        row
        for row in normalized_current
        if not (
            str(row.get("software_id", "")).strip() == software_key
            and str(row.get("scope", "global")).strip() == scope_key
        )
    ]
    for skill_id in normalized_skill_ids:
        next_bindings.append(
            {
                "software_id": software_key,
                "skill_id": skill_id,
                "scope": scope_key,
                "enabled": True,
                "settings": {},
            },
        )
    return normalize_skill_bindings_payload(next_bindings)


def _resolve_path(path_text: str) -> str:
    text = str(path_text or "").strip()
    if not text:
        return ""
    return str(Path(os.path.expanduser(text)).resolve())


def _source_freshness_status(age_days: int | None, *, exists: bool) -> str:
    if not exists:
        return "missing"
    if age_days is None:
        return "fresh"
    if age_days <= SOURCE_FRESH_MAX_AGE_DAYS:
        return "fresh"
    if age_days <= SOURCE_AGING_MAX_AGE_DAYS:
        return "aging"
    return "stale"


def _source_last_seen_timestamp(path: Path) -> float | None:
    try:
        latest_ts = path.stat().st_mtime
    except Exception:
        return None
    if path.is_dir():
        skill_md = path / "SKILL.md"
        if skill_md.exists():
            try:
                latest_ts = max(latest_ts, skill_md.stat().st_mtime)
            except Exception:
                pass
    return latest_ts


def _build_source_diagnostics(
    source_path: str,
    detect_paths: list[str] | tuple[str, ...] | None = None,
    *,
    now_dt: datetime,
) -> dict[str, Any]:
    raw_candidates = [str(source_path or "").strip()] + _to_str_list(detect_paths or [])
    candidates = _dedupe_keep_order(
        [_resolve_path(item) for item in raw_candidates if str(item or "").strip()],
    )

    existing_paths: list[str] = []
    latest_ts: float | None = None
    for candidate in candidates:
        path = Path(candidate)
        if not path.exists():
            continue
        existing_paths.append(candidate)
        candidate_ts = _source_last_seen_timestamp(path)
        if candidate_ts is None:
            continue
        if latest_ts is None or candidate_ts > latest_ts:
            latest_ts = candidate_ts

    source_exists = bool(existing_paths)
    last_seen_at = ""
    source_age_days: int | None = None
    if source_exists and latest_ts is not None:
        last_seen_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        last_seen_at = last_seen_dt.isoformat()
        age_seconds = max(0.0, (now_dt - last_seen_dt).total_seconds())
        source_age_days = int(age_seconds // 86400)

    return {
        "source_exists": source_exists,
        "last_seen_at": last_seen_at,
        "source_age_days": source_age_days,
        "freshness_status": _source_freshness_status(source_age_days, exists=source_exists),
    }


def _attach_source_diagnostics(row: dict[str, Any], *, now_dt: datetime) -> dict[str, Any]:
    diagnostics = _build_source_diagnostics(
        str(row.get("source_path", "")).strip(),
        row.get("detect_paths", []),
        now_dt=now_dt,
    )
    row.update(diagnostics)
    row["discovered"] = bool(row.get("discovered", False) or diagnostics["source_exists"])
    return row


def _display_name_from_command(command_name: str) -> str:
    text = str(command_name or "").strip()
    if not text:
        return "CLI"
    override = AUTO_CLI_DISPLAY_NAME_OVERRIDES.get(text.lower())
    if override:
        return override
    text = re.sub(r"[_\-]+", " ", text)
    return " ".join(seg.capitalize() for seg in text.split(" "))


def _software_family_from_item(item: dict[str, Any]) -> str:
    provider_key = _slug(item.get("provider_key"), default="")
    if provider_key and provider_key not in {"generic", "auto_cli"}:
        return provider_key
    detect_commands = _to_str_list(item.get("detect_commands", []))
    if detect_commands:
        return _slug(detect_commands[0], default="software")
    return _slug(item.get("id"), default="software")


def _is_skill_capable_auto_cli_command(command_name: str, include_commands: set[str]) -> bool:
    text = str(command_name or "").strip()
    if not text:
        return False
    family = _slug(text, default="")
    if text in include_commands:
        return True
    return family in KNOWN_SKILL_CAPABLE_SOFTWARE_FAMILIES


def _software_can_call_skills(item: dict[str, Any]) -> bool:
    software_kind = _slug(item.get("software_kind"), default="other")
    if software_kind not in {"cli", "gui", "claw"}:
        return False
    provider_key = _slug(item.get("provider_key"), default="")
    if provider_key == "auto_cli":
        return True
    if provider_key and provider_key != "auto_cli":
        return True
    return _software_family_from_item(item) in KNOWN_SKILL_CAPABLE_SOFTWARE_FAMILIES


def _map_agents_to_software_families(agents: list[str]) -> list[str]:
    families: list[str] = []
    for agent_name in agents:
        text = str(agent_name or "").strip()
        if not text:
            continue
        family = AGENT_SOFTWARE_FAMILY_ALIASES.get(text.lower()) or _slug(text, default="")
        if family:
            families.append(family)
    return _dedupe_keep_order(families)


def _match_npx_namespace_bundle(skill_name: str) -> dict[str, Any] | None:
    text = str(skill_name or "").strip().lower()
    for rule in NPX_NAMESPACE_BUNDLE_RULES:
        prefix = str(rule.get("prefix", "")).strip().lower()
        if prefix and text.startswith(prefix):
            return dict(rule)
    return None


def _match_npx_root_bundle(source_path: str) -> dict[str, Any] | None:
    normalized = str(source_path or "").replace("\\", "/").lower()
    if not normalized:
        return None
    for rule in NPX_ROOT_BUNDLE_RULES:
        for marker in rule.get("path_markers", []):
            marker_text = str(marker or "").replace("\\", "/").lower()
            if marker_text and marker_text in normalized:
                return dict(rule)
    return None


def _skill_path_root(skill_path: Any) -> str:
    text = str(skill_path or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    if text.lower().endswith("/skill.md"):
        return text[:-9].strip("/")
    if text.lower() == "skill.md":
        return ""
    return text


def _repo_label_from_url(url_text: Any) -> str:
    text = str(url_text or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        parsed = None
    if parsed:
        repo_path = str(parsed.path or "").strip().strip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        if repo_path:
            return repo_path
    return text


def _find_ancestor_file(path_text: Any, filename: str, *, max_hops: int = 4) -> Path | None:
    text = str(path_text or "").strip()
    if not text:
        return None
    try:
        path = Path(os.path.expanduser(text))
    except Exception:
        return None
    current = path if path.is_dir() else path.parent
    for _ in range(max_hops + 1):
        candidate = current / filename
        if candidate.exists() and candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


@lru_cache(maxsize=32)
def _load_skill_lock_index(lock_path: str) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    skills = payload.get("skills", {}) if isinstance(payload, dict) else {}
    if not isinstance(skills, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for skill_name, item in skills.items():
        name = str(skill_name or "").strip()
        if not name or not isinstance(item, dict):
            continue
        result[name] = dict(item)
    return result


def _derive_npx_skill_lock_provenance(skill_name: str, source_path: str) -> dict[str, Any]:
    lock_path = _find_ancestor_file(source_path, ".skill-lock.json", max_hops=4)
    if not lock_path:
        return {}
    lock_index = _load_skill_lock_index(str(lock_path))
    entry = lock_index.get(str(skill_name or "").strip())
    if not isinstance(entry, dict):
        return {}

    source_url = str(entry.get("sourceUrl") or "").strip()
    source_type = str(entry.get("sourceType") or "").strip().lower()
    source_label = str(entry.get("source") or "").strip() or _repo_label_from_url(source_url)
    plugin_name = str(entry.get("pluginName") or "").strip()
    skill_root = _skill_path_root(entry.get("skillPath"))
    repo_slug = _slug(source_label or plugin_name or _repo_label_from_url(source_url), default="")
    install_ref = ""
    if source_url and skill_root:
        install_ref = f"{source_url}#{skill_root}"
    elif source_url and skill_name:
        install_ref = f"{source_url}#{skill_name}"
    else:
        install_ref = source_url or source_label or plugin_name
    install_unit_id = f"skill_lock:{install_ref}" if install_ref else ""

    tags: list[str] = []
    if repo_slug:
        tags.append(f"source-repo:{repo_slug}")
    if source_type:
        tags.append(f"source-type:{_slug(source_type, default='external')}")

    result = {
        "locator": source_url,
        "source_subpath": skill_root,
        "managed_by": source_type or "skill_lock",
        "update_policy": "source_sync",
        "collection_group_name": source_label or plugin_name,
        "collection_group_kind": "source_repo",
        "tags": tags,
    }
    if install_unit_id:
        result.update(
            {
                "install_unit_id": install_unit_id,
                "install_unit_kind": "skill_lock_entry",
                "install_ref": install_ref,
                "install_manager": source_type or "skill_lock",
                "install_unit_display_name": str(skill_name or "").strip() or plugin_name or source_label,
                "aggregation_strategy": "skill_lock_path" if skill_root else "skill_lock_source",
            },
        )
    if source_label or plugin_name:
        group_label = source_label or plugin_name
        result["collection_group_id"] = f"collection:{_slug(f'source_repo:{group_label}', default='source_repo')}"
        result["collection_group_name"] = group_label
    return {
        key: value
        for key, value in result.items()
        if value not in ("", None) and value != []
    }


def _build_npx_skill_row_from_raw(raw_item: dict[str, Any], *, now_dt: datetime) -> dict[str, Any]:
    name = str(raw_item.get("name", "")).strip()
    source_scope = str(raw_item.get("source_scope", "global")).strip().lower() or "global"
    source_path = str(raw_item.get("source_path", "")).strip()
    agents = _to_str_list(raw_item.get("agents", []))
    compatible_families = _map_agents_to_software_families(agents)
    provenance = _derive_npx_skill_lock_provenance(name, source_path)
    tags = [f"npx-scope:{source_scope}", "npx-managed"]
    tags.extend(_to_str_list(provenance.pop("tags", [])))
    tags.extend([f"agent:{_slug(agent, default='agent')}" for agent in agents if str(agent or "").strip()])
    row = {
        "id": f"npx_{_slug(f'{source_scope}:{name}', default='skill')}",
        "display_name": name,
        "provider_key": "npx_skills",
        "source_kind": "npx_single",
        "skill_kind": "skill",
        "enabled": True,
        "source_path": source_path,
        "locator": str(provenance.get("locator") or ""),
        "source_subpath": str(provenance.get("source_subpath") or ""),
        "detect_paths": [source_path] if source_path else [],
        "compatible_software_kinds": [],
        "compatible_software_families": compatible_families,
        "tags": _dedupe_keep_order(tags),
        "auto_discovered": True,
        "discovered": bool(source_path and Path(source_path).exists()),
        "source_scope": source_scope,
        "managed_by": str(provenance.get("managed_by") or ""),
        "update_policy": str(provenance.get("update_policy") or ""),
        "member_count": 1,
        "member_skill_preview": [name] if name else [],
        "member_skill_overflow": 0,
        "management_hint": "",
        "registry_package_name": "",
        "registry_package_manager": "",
    }
    row.update(provenance)
    row.update(derive_source_provenance_fields(row))
    row.update(derive_source_aggregation_fields(row))
    return _attach_source_diagnostics(row, now_dt=now_dt)


def _build_npx_bundle_row(
    bundle_meta: dict[str, Any],
    scope_name: str,
    members: list[dict[str, Any]],
    *,
    now_dt: datetime,
) -> dict[str, Any]:
    scope = str(scope_name or "global").strip().lower() or "global"
    member_names = sorted(
        {
            str(item.get("name", "")).strip()
            for item in members
            if str(item.get("name", "")).strip()
        },
    )
    source_paths = _dedupe_keep_order(
        [
            str(item.get("source_path", "")).strip()
            for item in members
            if str(item.get("source_path", "")).strip()
        ],
    )
    compatible_families = _dedupe_keep_order(
        [
            family
            for item in members
            for family in _map_agents_to_software_families(_to_str_list(item.get("agents", [])))
        ],
    )
    bundle_key = _slug(bundle_meta.get("bundle_key"), default="bundle")
    preview = member_names[:6]
    overflow = max(0, len(member_names) - len(preview))
    row = {
        "id": f"npx_bundle_{bundle_key}_{scope}",
        "display_name": str(bundle_meta.get("display_name") or bundle_key),
        "provider_key": str(bundle_meta.get("provider_key") or bundle_key),
        "source_kind": "npx_bundle",
        "skill_kind": "skill_bundle",
        "enabled": True,
        "source_path": source_paths[0] if source_paths else "",
        "detect_paths": source_paths[:4],
        "compatible_software_kinds": [],
        "compatible_software_families": compatible_families,
        "tags": _dedupe_keep_order(
            [f"npx-scope:{scope}", "npx-managed", f"bundle:{bundle_key}"]
            + [f"agent:{family}" for family in compatible_families],
        ),
        "auto_discovered": True,
        "discovered": any(Path(path).exists() for path in source_paths),
        "source_scope": scope,
        "member_count": len(member_names),
        "member_skill_preview": preview,
        "member_skill_overflow": overflow,
        "management_hint": str(bundle_meta.get("management_hint", "")).strip(),
        "registry_package_name": str(bundle_meta.get("registry_package_name") or "").strip(),
        "registry_package_manager": str(bundle_meta.get("registry_package_manager") or "").strip(),
    }
    row.update(derive_source_provenance_fields(row))
    row.update(derive_source_aggregation_fields(row))
    return _attach_source_diagnostics(row, now_dt=now_dt)


def _normalize_inventory_options(raw: Any) -> dict[str, Any]:
    options = raw if isinstance(raw, dict) else {}
    mode = _slug(options.get("skill_management_mode") or "npx")
    if mode not in VALID_SKILL_MANAGEMENT_MODES:
        mode = "npx"
    npx_workdir = _resolve_path(options.get("npx_workdir", ""))
    include_names = _dedupe_keep_order(_to_str_list(options.get("auto_cli_include_commands", [])))
    exclude_names = {_slug(item) for item in _to_str_list(options.get("auto_cli_exclude_commands", []))}
    return {
        "skill_management_mode": mode,
        "npx_command": str(options.get("npx_command") or "npx").strip() or "npx",
        "npx_timeout_s": _to_int(options.get("npx_timeout_s", 12), 12, 1, 120),
        "npx_include_project": _to_bool(options.get("npx_include_project", True), True),
        "npx_include_global": _to_bool(options.get("npx_include_global", True), True),
        "npx_workdir": npx_workdir or str(Path.cwd()),
        "auto_discover_cli": _to_bool(options.get("auto_discover_cli", True), True),
        "auto_discover_cli_max": _to_int(options.get("auto_discover_cli_max", 120), 120, 20, 500),
        "auto_cli_only_known": _to_bool(options.get("auto_cli_only_known", True), True),
        "auto_cli_include_commands": include_names,
        "auto_cli_exclude_commands": exclude_names,
    }


def _parse_json_array_with_fallback(raw_text: str) -> list[Any]:
    text = str(raw_text or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            raise ValueError("stdout is not a JSON array") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except Exception:
            raise ValueError("stdout is not a valid JSON array") from None
    if not isinstance(parsed, list):
        raise ValueError("stdout JSON root must be an array")
    return parsed


def _run_json_command(
    command: list[str],
    *,
    cwd: str,
    timeout_s: int,
    command_runner: Callable[..., Any],
) -> list[Any]:
    completed = command_runner(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "")
    return_code = int(getattr(completed, "returncode", 1) or 0)
    if return_code != 0:
        tail = stderr.strip() or stdout.strip() or "unknown error"
        if len(tail) > 300:
            tail = tail[:300]
        raise RuntimeError(f"command failed rc={return_code}: {tail}")
    return _parse_json_array_with_fallback(stdout)


def _discover_skills_from_npx(
    *,
    npx_command: str,
    timeout_s: int,
    workdir: str,
    include_project: bool,
    include_global: bool,
    command_runner: Callable[..., Any],
    now_dt: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    raw_items: list[dict[str, Any]] = []

    scopes: list[tuple[str, list[str]]] = []
    if include_project:
        scopes.append(("project", [npx_command, "skills", "ls", "--json"]))
    if include_global:
        scopes.append(("global", [npx_command, "skills", "ls", "-g", "--json"]))

    for scope_name, command in scopes:
        try:
            items = _run_json_command(
                command,
                cwd=workdir,
                timeout_s=timeout_s,
                command_runner=command_runner,
            )
        except Exception as exc:
            warnings.append(f"npx skills ({scope_name}) discovery failed: {exc}")
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            source_scope = str(item.get("scope", scope_name)).strip().lower() or scope_name
            source_path = _resolve_path(item.get("path", ""))
            raw_items.append(
                {
                    "name": name,
                    "source_scope": source_scope,
                    "source_path": source_path,
                    "agents": _to_str_list(item.get("agents", [])),
                },
            )

    explicit_groups: dict[tuple[str, str], dict[str, Any]] = {}
    remaining_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        bundle_meta = _match_npx_namespace_bundle(raw_item.get("name", ""))
        if not bundle_meta:
            remaining_items.append(raw_item)
            continue
        group_key = (_slug(bundle_meta.get("bundle_key"), default="bundle"), raw_item["source_scope"])
        group = explicit_groups.setdefault(
            group_key,
            {"meta": bundle_meta, "scope": raw_item["source_scope"], "members": []},
        )
        group["members"].append(raw_item)

    root_candidates: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough_items: list[dict[str, Any]] = []
    for raw_item in remaining_items:
        bundle_meta = _match_npx_root_bundle(raw_item.get("source_path", ""))
        if not bundle_meta:
            passthrough_items.append(raw_item)
            continue
        group_key = (_slug(bundle_meta.get("bundle_key"), default="bundle"), raw_item["source_scope"])
        group = root_candidates.setdefault(
            group_key,
            {"meta": bundle_meta, "scope": raw_item["source_scope"], "members": []},
        )
        group["members"].append(raw_item)

    result_rows: list[dict[str, Any]] = []
    for group in explicit_groups.values():
        result_rows.append(
            _build_npx_bundle_row(group["meta"], group["scope"], group["members"], now_dt=now_dt),
        )

    grouped_passthrough_keys = {
        key
        for key, group in root_candidates.items()
        if len(group["members"]) >= NPX_ROOT_BUNDLE_THRESHOLD
    }
    for key, group in root_candidates.items():
        if key not in grouped_passthrough_keys:
            passthrough_items.extend(group["members"])
            continue
        result_rows.append(
            _build_npx_bundle_row(group["meta"], group["scope"], group["members"], now_dt=now_dt),
        )

    for raw_item in passthrough_items:
        result_rows.append(_build_npx_skill_row_from_raw(raw_item, now_dt=now_dt))

    result_rows.sort(key=lambda item: str(item.get("display_name", "")).lower())
    return result_rows, warnings


def _discover_cli_commands_from_path(
    *,
    max_hits: int,
    include_commands: list[str],
    exclude_commands: set[str],
    only_known: bool,
) -> list[tuple[str, str]]:
    result: dict[str, str] = {}
    include_set = {str(item).strip() for item in include_commands if str(item).strip()}

    priority_commands = _dedupe_keep_order(DEFAULT_PRIORITY_CLI_COMMANDS + list(include_set))
    for cmd in priority_commands:
        path = shutil.which(cmd)
        if not path:
            continue
        result[cmd] = path
        if len(result) >= max_hits:
            break
    if only_known:
        ordered_known = [(name, result[name]) for name in priority_commands if name in result]
        return ordered_known[:max_hits]

    path_env = os.getenv("PATH", "")
    scan_roots = _dedupe_keep_order(path_env.split(os.pathsep))
    name_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{1,63}$")
    excluded = set(DEFAULT_AUTO_CLI_EXCLUDE)
    excluded.update(exclude_commands)

    for root in scan_roots:
        if len(result) >= max_hits:
            break
        root_path = Path(root or "").expanduser()
        if not root_path.exists() or not root_path.is_dir():
            continue
        try:
            iterator = os.scandir(root_path)
        except Exception:
            continue
        with iterator:
            for entry in iterator:
                if len(result) >= max_hits:
                    break
                name = str(getattr(entry, "name", "") or "").strip()
                if not name or name in result:
                    continue
                if not name_pattern.match(name):
                    continue
                slug_name = _slug(name, default="")
                if slug_name in excluded and name not in include_set:
                    continue
                if not _is_skill_capable_auto_cli_command(name, include_set):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        continue
                except Exception:
                    continue
                entry_path = str(getattr(entry, "path", "") or "")
                if not entry_path:
                    continue
                if not os.access(entry_path, os.X_OK):
                    continue
                result[name] = entry_path

    ordered_names: list[str] = []
    seen: set[str] = set()
    for name in priority_commands:
        if name in result and name not in seen:
            seen.add(name)
            ordered_names.append(name)
    for name in sorted(result):
        if name in seen:
            continue
        seen.add(name)
        ordered_names.append(name)
    return [(name, result[name]) for name in ordered_names[:max_hits]]


def _append_auto_cli_software_catalog(
    software_catalog: list[dict[str, Any]],
    *,
    max_hits: int,
    include_commands: list[str],
    exclude_commands: set[str],
    only_known: bool,
) -> list[dict[str, Any]]:
    base_rows = [dict(item) for item in software_catalog]
    existing_ids = {str(item.get("id", "")).strip() for item in base_rows}
    existing_commands = {
        str(cmd).strip()
        for item in base_rows
        for cmd in _to_str_list(item.get("detect_commands", []))
        if str(cmd).strip()
    }

    auto_commands = _discover_cli_commands_from_path(
        max_hits=max_hits,
        include_commands=include_commands,
        exclude_commands=exclude_commands,
        only_known=only_known,
    )
    for command_name, _command_path in auto_commands:
        if command_name in existing_commands:
            continue
        if not _is_skill_capable_auto_cli_command(command_name, set(include_commands)):
            continue
        software_id_base = f"cli_{_slug(command_name, default='tool')}"
        software_id = software_id_base
        suffix = 2
        while software_id in existing_ids:
            software_id = f"{software_id_base}_{suffix}"
            suffix += 1
        existing_ids.add(software_id)
        existing_commands.add(command_name)
        base_rows.append(
            {
                "id": software_id,
                "display_name": _display_name_from_command(command_name),
                "software_kind": "cli",
                "provider_key": "auto_cli",
                "linked_target_name": "",
                "enabled": True,
                "detect_paths": [],
                "detect_commands": [command_name],
                "skill_roots": [],
                "tags": ["auto-cli"],
            },
        )
    return base_rows


def _is_skill_compatible(skill_row: dict[str, Any], software_row: dict[str, Any]) -> bool:
    compatible_ids = {_slug(item, default="") for item in _to_str_list(skill_row.get("compatible_software_ids", []))}
    software_id = _slug(software_row.get("id"), default="")
    if compatible_ids:
        return software_id in compatible_ids

    compatible_families = {
        _slug(item, default="")
        for item in _to_str_list(skill_row.get("compatible_software_families", []))
    }
    software_family = _slug(software_row.get("software_family"), default="")
    if compatible_families:
        return software_family in compatible_families or software_id in compatible_families

    compatible_kinds = _to_str_list(skill_row.get("compatible_software_kinds", []))
    if not compatible_kinds:
        return True
    software_kind = str(software_row.get("software_kind", "other"))
    return software_kind in compatible_kinds


def _discover_skills_from_roots(
    software_rows: list[dict[str, Any]],
    *,
    max_depth: int = 4,
    max_hits: int = 300,
    now_dt: datetime,
) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for software in software_rows:
        software_id = str(software.get("id", "")).strip()
        software_kind = str(software.get("software_kind", "other")).strip() or "other"
        provider_key = str(software.get("provider_key", "generic")).strip() or "generic"
        roots = software.get("resolved_skill_roots", [])
        if not isinstance(roots, list):
            continue
        for root in roots:
            root_path = Path(str(root))
            if not root_path.exists() or not root_path.is_dir():
                continue
            root_depth = len(root_path.parts)
            try:
                iterator = os.walk(root_path)
            except Exception:
                continue
            for current_dir, dirnames, filenames in iterator:
                current_depth = len(Path(current_dir).parts) - root_depth
                if current_depth > max_depth:
                    dirnames[:] = []
                    continue
                if "SKILL.md" not in filenames:
                    continue
                source_path = str(Path(current_dir).resolve())
                if source_path in seen_paths:
                    continue
                seen_paths.add(source_path)
                skill_name = Path(current_dir).name
                skill_id = "auto_" + hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:12]
                row = {
                    "id": skill_id,
                    "display_name": skill_name,
                    "provider_key": provider_key,
                    "skill_kind": "skill",
                    "enabled": True,
                    "source_path": source_path,
                    "detect_paths": [source_path],
                    "compatible_software_kinds": [software_kind] if software_kind in VALID_SOFTWARE_KINDS else [],
                    "compatible_software_families": [_slug(provider_key, default="")] if provider_key else [],
                    "tags": [software_id, "auto-discovered"],
                    "auto_discovered": True,
                    "discovered": True,
                    "source_scope": "global",
                    "member_count": 1,
                    "member_skill_preview": [skill_name],
                    "member_skill_overflow": 0,
                    "management_hint": "",
                    "registry_package_name": "",
                    "registry_package_manager": "",
                }
                row.update(derive_source_provenance_fields(row))
                row.update(derive_source_aggregation_fields(row))
                discovered.append(
                    _attach_source_diagnostics(row, now_dt=now_dt),
                )
                if len(discovered) >= max_hits:
                    return discovered
    return discovered


def _build_manual_skill_rows(skill_catalog: list[dict[str, Any]], *, now_dt: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in skill_catalog:
        detect_paths = [
            _resolve_path(path)
            for path in _to_str_list(item.get("detect_paths", []))
        ]
        detect_paths = [path for path in detect_paths if path]
        existing_paths = [path for path in detect_paths if Path(path).exists()]
        source_path = _resolve_path(item.get("source_path", ""))
        if not source_path and existing_paths:
            source_path = existing_paths[0]
        row = {
            "id": str(item.get("id", "")),
            "display_name": str(item.get("display_name", "")).strip() or str(item.get("id", "")),
            "provider_key": str(item.get("provider_key", "generic")),
            "skill_kind": str(item.get("skill_kind", "skill")),
            "enabled": _to_bool(item.get("enabled", True), True),
            "source_path": source_path,
            "detect_paths": detect_paths,
            "compatible_software_kinds": _to_str_list(item.get("compatible_software_kinds", [])),
            "compatible_software_families": _to_str_list(item.get("compatible_software_families", [])),
            "tags": _to_str_list(item.get("tags", [])),
            "auto_discovered": False,
            "discovered": bool(existing_paths or (source_path and Path(source_path).exists())),
            "source_scope": str(item.get("source_scope") or "global"),
            "member_count": 1,
            "member_skill_preview": [str(item.get("display_name", "")).strip() or str(item.get("id", ""))],
            "member_skill_overflow": 0,
            "management_hint": str(item.get("management_hint") or ""),
            "registry_package_name": str(item.get("registry_package_name") or ""),
            "registry_package_manager": str(item.get("registry_package_manager") or ""),
        }
        row.update(derive_source_provenance_fields(row))
        row.update(derive_source_aggregation_fields(row))
        rows.append(
            _attach_source_diagnostics(row, now_dt=now_dt),
        )
    return rows


def _dedupe_skill_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_id: set[str] = set()
    seen_source: set[str] = set()
    for row in rows:
        source_path = str(row.get("source_path", "")).strip()
        row_id = _slug(row.get("id"), default="skill")
        if source_path and source_path in seen_source:
            continue
        if row_id in seen_id:
            row_id = f"{row_id}_{len(seen_id) + 1}"
        row["id"] = row_id
        seen_id.add(row_id)
        if source_path:
            seen_source.add(source_path)
        result.append(row)
    return result


def build_inventory_snapshot(
    software_catalog: list[dict[str, Any]],
    skill_catalog: list[dict[str, Any]],
    skill_bindings: list[dict[str, Any]],
    target_rows: dict[str, dict[str, Any]],
    *,
    inventory_options: dict[str, Any] | None = None,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    options = _normalize_inventory_options(inventory_options)
    now_dt = datetime.now(timezone.utc)
    generated_at = now_dt.isoformat()
    warnings: list[str] = []

    runtime_software_catalog = software_catalog
    if options["auto_discover_cli"]:
        runtime_software_catalog = _append_auto_cli_software_catalog(
            runtime_software_catalog,
            max_hits=options["auto_discover_cli_max"],
            include_commands=options["auto_cli_include_commands"],
            exclude_commands=options["auto_cli_exclude_commands"],
            only_known=options["auto_cli_only_known"],
        )

    software_rows: list[dict[str, Any]] = []
    software_index: dict[str, dict[str, Any]] = {}
    for software in runtime_software_catalog:
        software_id = str(software.get("id", "")).strip()
        if not software_id:
            continue
        raw_paths = _to_str_list(software.get("detect_paths", []))
        raw_commands = _to_str_list(software.get("detect_commands", []))
        raw_skill_roots = _to_str_list(software.get("skill_roots", []))

        resolved_paths = [_resolve_path(path) for path in raw_paths]
        resolved_paths = [path for path in resolved_paths if path]
        existing_paths = [path for path in resolved_paths if Path(path).exists()]

        command_hits: dict[str, str] = {}
        for command_name in raw_commands:
            cmd = str(command_name or "").strip()
            if not cmd:
                continue
            cmd_path = shutil.which(cmd)
            if cmd_path:
                command_hits[cmd] = cmd_path

        linked_target_name = str(software.get("linked_target_name", "")).strip()
        target_info = target_rows.get(linked_target_name, {}) if linked_target_name else {}
        managed = bool(linked_target_name and target_info)
        installed = bool(existing_paths or command_hits)
        update_status = str(target_info.get("status", "unknown") if managed else "unmanaged")
        software_family = _software_family_from_item(software)
        skill_capable = _software_can_call_skills(software)

        resolved_skill_roots = [_resolve_path(path) for path in raw_skill_roots]
        resolved_skill_roots = [path for path in resolved_skill_roots if path]
        existing_skill_roots = [
            path for path in resolved_skill_roots
            if Path(path).exists() and Path(path).is_dir()
        ]

        row = {
            "id": software_id,
            "display_name": str(software.get("display_name", software_id)),
            "software_kind": str(software.get("software_kind", "other")),
            "provider_key": str(software.get("provider_key", "generic")),
            "software_family": software_family,
            "skill_capable": skill_capable,
            "enabled": _to_bool(software.get("enabled", True), True),
            "installed": installed,
            "managed": managed,
            "linked_target_name": linked_target_name,
            "current_version": str(target_info.get("current_version", "-") if managed else "-"),
            "latest_version": str(target_info.get("latest_version", "-") if managed else "-"),
            "update_status": update_status,
            "detected_paths": existing_paths,
            "detected_commands": command_hits,
            "resolved_skill_roots": existing_skill_roots,
            "declared_skill_roots": resolved_skill_roots,
            "binding_count": 0,
        }
        if not installed and row["enabled"]:
            warnings.append(f"software[{software_id}] not detected on local machine")
        software_rows.append(row)
        software_index[software_id] = row

    skill_rows_collected: list[dict[str, Any]] = []
    skill_mode = options["skill_management_mode"]
    if skill_mode in {"filesystem", "hybrid"}:
        manual_skill_rows = _build_manual_skill_rows(skill_catalog, now_dt=now_dt)
        auto_skill_rows = _discover_skills_from_roots(software_rows, now_dt=now_dt)
        skill_rows_collected.extend(manual_skill_rows)
        skill_rows_collected.extend(auto_skill_rows)
    if skill_mode in {"npx", "hybrid"}:
        npx_rows, npx_warnings = _discover_skills_from_npx(
            npx_command=options["npx_command"],
            timeout_s=options["npx_timeout_s"],
            workdir=options["npx_workdir"],
            include_project=options["npx_include_project"],
            include_global=options["npx_include_global"],
            command_runner=command_runner,
            now_dt=now_dt,
        )
        warnings.extend(npx_warnings)
        skill_rows_collected.extend(npx_rows)

    skill_rows = _dedupe_skill_rows(skill_rows_collected)

    skill_index = {str(row.get("id")): row for row in skill_rows}
    compatibility: dict[str, list[str]] = {}
    for software in software_rows:
        sid = str(software.get("id", ""))
        compat = [
            str(skill.get("id"))
            for skill in skill_rows
            if _is_skill_compatible(skill, software)
        ]
        compatibility[sid] = compat

    binding_map: dict[str, list[str]] = {str(row.get("id", "")): [] for row in software_rows}
    binding_map_by_scope: dict[str, dict[str, list[str]]] = {
        "global": {str(row.get("id", "")): [] for row in software_rows},
        "workspace": {str(row.get("id", "")): [] for row in software_rows},
    }
    binding_rows: list[dict[str, Any]] = []
    valid_binding_count = 0
    invalid_binding_count = 0
    for binding in skill_bindings:
        software_id = str(binding.get("software_id", "")).strip()
        skill_id = str(binding.get("skill_id", "")).strip()
        scope = str(binding.get("scope", "global")).strip() or "global"
        if scope not in VALID_BINDING_SCOPES:
            scope = "global"
        enabled = _to_bool(binding.get("enabled", True), True)

        software = software_index.get(software_id)
        skill = skill_index.get(skill_id)
        valid = True
        invalid_reason = ""
        if not software:
            valid = False
            invalid_reason = "software_not_found"
        elif not skill:
            valid = False
            invalid_reason = "skill_not_found"
        elif skill_id not in compatibility.get(software_id, []):
            valid = False
            invalid_reason = "incompatible_kind"

        if valid and enabled:
            if skill_id not in binding_map[software_id]:
                binding_map[software_id].append(skill_id)
            scoped_map = binding_map_by_scope.setdefault(scope, {})
            scoped_list = scoped_map.setdefault(software_id, [])
            if skill_id not in scoped_list:
                scoped_list.append(skill_id)
            valid_binding_count += 1
        elif not valid:
            invalid_binding_count += 1
            warnings.append(
                f"binding[{software_id}->{skill_id}] is invalid: {invalid_reason}",
            )

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

    for software_id, skill_ids in binding_map.items():
        software = software_index.get(software_id)
        if not software:
            continue
        software["binding_count"] = len(skill_ids)

    skill_binding_reverse: dict[str, set[str]] = {}
    for software_id, skill_ids in binding_map.items():
        for skill_id in skill_ids:
            owners = skill_binding_reverse.setdefault(skill_id, set())
            owners.add(software_id)

    for skill in skill_rows:
        skill_id = str(skill.get("id", ""))
        owners = sorted(skill_binding_reverse.get(skill_id, set()))
        skill["bound_software_count"] = len(owners)
        skill["bound_software_ids"] = owners
        if str(skill.get("freshness_status", "")).strip().lower() == "stale":
            warnings.append(
                f"source[{skill_id}] is stale: age={skill.get('source_age_days')}d path={skill.get('source_path')}",
            )

    counts = {
        "software_total": len(software_rows),
        "software_enabled": sum(1 for row in software_rows if row.get("enabled")),
        "software_installed": sum(1 for row in software_rows if row.get("installed")),
        "software_managed": sum(1 for row in software_rows if row.get("managed")),
        "software_auto_cli": sum(1 for row in software_rows if str(row.get("provider_key", "")) == "auto_cli"),
        "software_skill_capable": sum(1 for row in software_rows if row.get("skill_capable")),
        "skills_total": len(skill_rows),
        "skills_enabled": sum(1 for row in skill_rows if row.get("enabled")),
        "skills_discovered": sum(1 for row in skill_rows if row.get("discovered")),
        "skills_npx": sum(
            1
            for row in skill_rows
            if "npx-managed" in _to_str_list(row.get("tags", []))
        ),
        "skills_members_total": sum(max(1, _to_int(row.get("member_count", 1), 1, 1)) for row in skill_rows),
        "skills_fresh_total": sum(1 for row in skill_rows if str(row.get("freshness_status", "")) == "fresh"),
        "skills_aging_total": sum(1 for row in skill_rows if str(row.get("freshness_status", "")) == "aging"),
        "skills_stale_total": sum(1 for row in skill_rows if str(row.get("freshness_status", "")) == "stale"),
        "skills_missing_total": sum(1 for row in skill_rows if str(row.get("freshness_status", "")) == "missing"),
        "bindings_total": len(binding_rows),
        "bindings_valid": valid_binding_count,
        "bindings_invalid": invalid_binding_count,
    }

    return {
        "ok": True,
        "generated_at": generated_at,
        "software_rows": software_rows,
        "skill_rows": skill_rows,
        "binding_rows": binding_rows,
        "binding_map": binding_map,
        "binding_map_by_scope": binding_map_by_scope,
        "compatibility": compatibility,
        "counts": counts,
        "warnings": warnings,
    }
