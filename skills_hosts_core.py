from __future__ import annotations

import re
from typing import Any

VALID_HOST_KINDS = {"cli", "gui", "claw", "other"}
SUPPORTED_SOURCE_KINDS = ["npx_bundle", "npx_single", "manual_local", "manual_git"]
ASTRBOT_HOST_CAPABILITIES = [
    "local_skill_scan",
    "local_skill_toggle",
    "local_skill_delete",
    "local_zip_import",
    "local_zip_export",
    "sandbox_cache_read",
    "sandbox_sync_trigger",
    "neo_release_read",
    "neo_release_sync",
]

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "claude_code": {
        "display_name": "Claude Code",
        "software_kind": "cli",
        "detect_paths": ["~/.claude"],
        "detect_commands": ["claude"],
        "skill_roots": ["~/.claude/skills"],
    },
    "codex": {
        "display_name": "Codex",
        "software_kind": "cli",
        "detect_paths": ["~/.codex"],
        "detect_commands": ["codex"],
        "skill_roots": ["~/.codex/skills"],
    },
    "zeroclaw": {
        "display_name": "ZeroClaw",
        "software_kind": "claw",
        "detect_paths": ["~/zeroclaw"],
        "detect_commands": ["zeroclaw"],
        "skill_roots": ["~/zeroclaw/.claude/skills", "~/zeroclaw/src/skills"],
    },
    "astrbot": {
        "display_name": "AstrBot",
        "software_kind": "claw",
        "detect_paths": ["~/astrbot", "~/.astrbot"],
        "detect_commands": ["astrbot"],
        "skill_roots": ["~/astrbot/data/skills", "~/.astrbot/data/skills"],
    },
    "antigravity": {
        "display_name": "Antigravity",
        "software_kind": "gui",
        "detect_paths": ["~/antigravity"],
        "detect_commands": ["antigravity"],
        "skill_roots": ["~/antigravity/skills"],
    },
    "cursor_agent": {
        "display_name": "Cursor Agent",
        "software_kind": "gui",
        "detect_paths": ["~/.cursor"],
        "detect_commands": ["cursor-agent"],
        "skill_roots": ["~/.cursor/skills"],
    },
    "opencode": {
        "display_name": "OpenCode",
        "software_kind": "cli",
        "detect_paths": ["~/.opencode"],
        "detect_commands": ["opencode"],
        "skill_roots": ["~/.opencode/skills"],
    },
    "aider": {
        "display_name": "Aider",
        "software_kind": "cli",
        "detect_paths": ["~/.aider"],
        "detect_commands": ["aider"],
        "skill_roots": ["~/.aider/skills"],
    },
    "gemini_cli": {
        "display_name": "Gemini CLI",
        "software_kind": "cli",
        "detect_paths": ["~/.gemini"],
        "detect_commands": ["gemini-cli", "gemini"],
        "skill_roots": ["~/.gemini/skills"],
    },
    "qwen_code": {
        "display_name": "Qwen Code",
        "software_kind": "cli",
        "detect_paths": ["~/.qwen"],
        "detect_commands": ["qwen-code", "qwen"],
        "skill_roots": ["~/.qwen/skills"],
    },
    "roo_code": {
        "display_name": "Roo Code",
        "software_kind": "cli",
        "detect_paths": ["~/.roo"],
        "detect_commands": ["roo-code", "roo"],
        "skill_roots": ["~/.roo/skills"],
    },
    "windsurf": {
        "display_name": "Windsurf",
        "software_kind": "gui",
        "detect_paths": ["~/.windsurf"],
        "detect_commands": ["windsurf"],
        "skill_roots": ["~/.windsurf/skills"],
    },
    "openhands": {
        "display_name": "OpenHands",
        "software_kind": "cli",
        "detect_paths": ["~/.openhands"],
        "detect_commands": ["openhands"],
        "skill_roots": ["~/.openhands/skills"],
    },
    "continue": {
        "display_name": "Continue",
        "software_kind": "gui",
        "detect_paths": ["~/.continue"],
        "detect_commands": ["continue"],
        "skill_roots": ["~/.continue/skills"],
    },
    "goose": {
        "display_name": "Goose",
        "software_kind": "cli",
        "detect_paths": ["~/.config/goose"],
        "detect_commands": ["goose"],
        "skill_roots": ["~/.config/goose/skills"],
    },
    "kiro": {
        "display_name": "Kiro",
        "software_kind": "cli",
        "detect_paths": ["~/.kiro"],
        "detect_commands": ["kiro"],
        "skill_roots": ["~/.kiro/skills"],
    },
    "crush": {
        "display_name": "Crush",
        "software_kind": "cli",
        "detect_paths": ["~/.crush"],
        "detect_commands": ["crush"],
        "skill_roots": ["~/.crush/skills"],
    },
    "amp": {
        "display_name": "Amp",
        "software_kind": "cli",
        "detect_paths": ["~/.amp"],
        "detect_commands": ["amp"],
        "skill_roots": ["~/.amp/skills"],
    },
}

DEFAULT_SOFTWARE_CATALOG: list[dict[str, Any]] = [
    {"id": "claude_code", "provider_key": "claude_code", "enabled": True},
    {"id": "codex", "provider_key": "codex", "enabled": True},
    {"id": "zeroclaw", "provider_key": "zeroclaw", "enabled": True, "linked_target_name": "zeroclaw"},
    {"id": "astrbot", "provider_key": "astrbot", "enabled": True},
    {"id": "antigravity", "provider_key": "antigravity", "enabled": True},
    {"id": "cursor_agent", "provider_key": "cursor_agent", "enabled": True},
    {"id": "opencode", "provider_key": "opencode", "enabled": True},
    {"id": "aider", "provider_key": "aider", "enabled": True},
    {"id": "gemini_cli", "provider_key": "gemini_cli", "enabled": True},
    {"id": "qwen_code", "provider_key": "qwen_code", "enabled": True},
    {"id": "roo_code", "provider_key": "roo_code", "enabled": True},
    {"id": "windsurf", "provider_key": "windsurf", "enabled": True},
    {"id": "openhands", "provider_key": "openhands", "enabled": True},
    {"id": "continue", "provider_key": "continue", "enabled": True},
    {"id": "goose", "provider_key": "goose", "enabled": True},
    {"id": "kiro", "provider_key": "kiro", "enabled": True},
    {"id": "crush", "provider_key": "crush", "enabled": True},
    {"id": "amp", "provider_key": "amp", "enabled": True},
]


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


def _build_host_capabilities(host_id: str, provider_key: str) -> list[str]:
    host_key = _slug(provider_key or host_id, default=_slug(host_id, default="generic"))
    if host_key == "astrbot":
        return list(ASTRBOT_HOST_CAPABILITIES)
    return []


def _runtime_state_backend(host_id: str, provider_key: str) -> str:
    host_key = _slug(provider_key or host_id, default=_slug(host_id, default="generic"))
    if host_key == "astrbot":
        return "astrbot"
    return ""


def resolve_host_target_path(host: dict[str, Any], scope: str) -> str:
    scope_name = _slug(scope or "global", default="global")
    resolved_roots = _to_str_list(host.get("resolved_skill_roots", []))
    declared_roots = _to_str_list(host.get("declared_skill_roots", []))
    candidates = resolved_roots or declared_roots
    if not candidates:
        return ""
    if scope_name == "workspace" and len(candidates) > 1:
        return candidates[1]
    return candidates[0]


def build_host_adapters(software_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adapters: list[dict[str, Any]] = []
    for item in software_rows:
        if not isinstance(item, dict):
            continue
        host_id = str(item.get("id", "")).strip()
        if not host_id:
            continue
        kind = _slug(item.get("software_kind"), default="other")
        if kind not in VALID_HOST_KINDS:
            kind = "other"
        family = _slug(item.get("software_family") or item.get("provider_key") or host_id, default=host_id)
        adapter = {
            "id": host_id,
            "host_id": host_id,
            "display_name": str(item.get("display_name") or host_id),
            "software_kind": kind,
            "kind": kind,
            "software_family": family,
            "family": family,
            "provider_key": str(item.get("provider_key") or family or "generic"),
            "enabled": _to_bool(item.get("enabled", True), True),
            "installed": _to_bool(item.get("installed", False), False),
            "managed": _to_bool(item.get("managed", False), False),
            "linked_target_name": str(item.get("linked_target_name") or ""),
            "declared_skill_roots": _to_str_list(item.get("declared_skill_roots", [])),
            "resolved_skill_roots": _to_str_list(item.get("resolved_skill_roots", [])),
            "supports_source_kinds": list(SUPPORTED_SOURCE_KINDS),
            "capabilities": _build_host_capabilities(host_id, str(item.get("provider_key") or family or "generic")),
            "runtime_state_backend": _runtime_state_backend(host_id, str(item.get("provider_key") or family or "generic")),
            "runtime_state_summary": {},
            "runtime_state_warning_count": 0,
        }
        adapter["target_paths"] = {
            "global": resolve_host_target_path(adapter, "global"),
            "workspace": resolve_host_target_path(adapter, "workspace"),
        }
        adapter["target_path"] = adapter["target_paths"]["global"]
        adapters.append(adapter)
    adapters.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("host_id", "")).lower()))
    return adapters
