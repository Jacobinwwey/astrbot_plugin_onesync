from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import json
import re
import secrets
import shlex
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .inventory_core import (
    build_inventory_snapshot,
    normalize_skill_bindings_payload,
    normalize_skill_catalog_payload,
    normalize_software_catalog_payload,
    replace_bindings_for_scope,
)
from .skills_projection_core import (
    build_generated_target_diff,
    read_generated_target_payload,
)
from .skills_runtime_health import build_skills_runtime_health
from .skills_update_core import (
    build_git_rollback_preview,
    build_collection_group_update_plan,
    build_install_unit_update_plan,
    summarize_revision_capture_delta,
)
from .skills_core import (
    build_collection_group_detail_payload,
    build_install_unit_detail_payload,
    build_skills_overview,
    manifest_to_binding_rows,
    normalize_saved_skills_manifest,
    normalize_saved_skills_lock,
    project_inventory_snapshot_bindings_from_manifest,
)
from .skills_sources_core import (
    normalize_skills_registry,
    refresh_registry_source,
    register_registry_source,
    remove_registry_source,
)
from .skills_install_atoms_core import normalize_install_atom_registry
from .skills_astrbot_actions_core import (
    delete_astrbot_local_skill,
    export_astrbot_skill_zip,
    import_astrbot_skill_zip,
    set_astrbot_skill_active,
)
from .skills_astrbot_state_core import resolve_astrbot_host_layout
from .source_sync_core import build_source_sync_cache_key, build_source_sync_record, is_source_syncable
from .updater_core import (
    CheckResult,
    CommandRunner,
    UpdateResult,
    build_strategy,
)
from .webui_server import OneSyncWebUIServer

PLUGIN_NAME = "astrbot_plugin_onesync"
SKILLS_ROLLBACK_CONFIRM_TOKEN = "ROLLBACK_ACCEPT_RISK"
SKILLS_AGGREGATE_UPDATE_ACTIVE_STATUSES = {
    "planning",
    "improving_atoms_planning",
    "improving_atoms_refreshing",
    "executing_command",
    "executing_source_sync",
    "refreshing_snapshot",
}

DEFAULT_GITHUB_MIRROR_PREFIXES = [
    "",
    "https://edgeone.gh-proxy.com/",
    "https://hk.gh-proxy.com/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghfast.top/",
]

DEFAULT_TARGETS: dict[str, dict[str, Any]] = {
    "zeroclaw": {
        "enabled": True,
        "strategy": "cargo_path_git",
        "check_interval_hours": 12,
        "repo_path": "/home/jacob/zeroclaw",
        "binary_path": "/root/.cargo/bin/zeroclaw",
        "branch": "",
        "auto_add_safe_directory": True,
        "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
        "mirror_prefixes": DEFAULT_GITHUB_MIRROR_PREFIXES,
        "remote_candidates": [],
        "append_default_mirror_prefixes": True,
        "probe_remotes": True,
        "probe_timeout_s": 15,
        "probe_parallelism": 4,
        "probe_cache_ttl_minutes": 30,
        "build_commands": ["cargo install --path {repo_path}"],
        "verify_cmd": "{binary_path} --version",
        "check_timeout_s": 120,
        "update_timeout_s": 1800,
        "verify_timeout_s": 120,
        "current_version_pattern": "(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.\\-]+)?)",
        "required_commands": ["git", "cargo", "zeroclaw"],
    },
}

SYSTEM_PACKAGE_MANAGER_ALIASES: dict[str, str] = {
    "apt": "apt_get",
    "apt-get": "apt_get",
    "apt_get": "apt_get",
    "yum": "yum",
    "dnf": "dnf",
    "pacman": "pacman",
    "zypper": "zypper",
    "choco": "choco",
    "chocolatey": "choco",
    "winget": "winget",
    "brew": "brew",
    "homebrew": "brew",
}

SYSTEM_PACKAGE_REQUIRED_COMMANDS: dict[str, list[str]] = {
    "apt_get": ["apt-get", "apt-cache", "dpkg-query"],
    "yum": ["yum", "rpm"],
    "dnf": ["dnf", "rpm"],
    "pacman": ["pacman"],
    "zypper": ["zypper", "rpm"],
    "choco": ["choco"],
    "winget": ["winget"],
    "brew": ["brew"],
}

STRATEGY_ALIASES: dict[str, str] = {
    "command": "command",
    "cmd": "command",
    "cargo_path_git": "cargo_path_git",
    "git_cargo": "cargo_path_git",
    "system_package": "system_package",
    "package": "system_package",
    "pkg": "system_package",
    "system_pkg": "system_package",
}


def _normalize_system_package_manager(value: Any) -> str:
    manager = str(value or "").strip().lower().replace("-", "_")
    return SYSTEM_PACKAGE_MANAGER_ALIASES.get(manager, manager)


def _normalize_strategy_name(value: Any, default: str = "command") -> str:
    strategy = str(value or "").strip().lower()
    return STRATEGY_ALIASES.get(strategy, default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


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


def _to_jsonable_like(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_jsonable_like(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable_like(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable_like(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
        except Exception:
            dumped = None
        if dumped is not None:
            return _to_jsonable_like(dumped)
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes, bytearray)):
        try:
            payload = dict(vars(value))
        except Exception:
            payload = None
        if payload is not None:
            return _to_jsonable_like(payload)
    return value


def _to_int(value: Any, default: int, min_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        return min_value
    return parsed


def _to_float(value: Any, default: float, min_value: float | None = None) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        return min_value
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
        parts = [seg.strip() for seg in re.split(r"[\n,]+", text) if seg.strip()]
        return parts
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


def _first_non_empty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _short_text(text: str, max_len: int = 180) -> str:
    content = str(text or "").strip()
    if len(content) <= max_len:
        return content
    return content[: max_len - 3] + "..."


def _normalize_inventory_id(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text or default


def _normalize_astrbot_scope(value: Any, default: str = "global") -> str:
    normalized = _normalize_inventory_id(value, default=default)
    if normalized in {"global", "workspace"}:
        return normalized
    return default


def _normalize_update_manager(value: Any) -> str:
    manager = str(value or "").strip().lower()
    if manager in {"pnpm dlx"}:
        return "pnpm"
    if manager in {"github"}:
        return "git"
    return manager


def _shell_quote(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return shlex.quote(text)


def _build_registry_update_command(manager: str, install_ref: str) -> str:
    normalized_manager = _normalize_update_manager(manager)
    install_ref_text = str(install_ref or "").strip()
    if not install_ref_text:
        return ""
    install_ref_token = _shell_quote(install_ref_text)
    if normalized_manager == "bunx":
        return f"bunx {install_ref_token}"
    if normalized_manager == "npx":
        return f"npx {install_ref_token}"
    if normalized_manager == "pnpm":
        return f"pnpm dlx {install_ref_token}"
    if normalized_manager == "npm":
        return f"npm install -g {_shell_quote(f'{install_ref_text}@latest')}"
    return ""


def _replace_registry_command_runner(command: str, manager: str) -> str:
    text = str(command or "").strip()
    normalized_manager = _normalize_update_manager(manager)
    if not text or normalized_manager not in {"bunx", "npx", "pnpm", "npm"}:
        return ""
    prefix_map = {
        "bunx": "bunx ",
        "npx": "npx ",
        "pnpm": "pnpm dlx ",
    }
    matched_prefix = ""
    remainder = ""
    for prefix in ("bunx ", "npx ", "pnpm dlx "):
        if text.startswith(prefix):
            matched_prefix = prefix
            remainder = text[len(prefix):].strip()
            break
    if not matched_prefix or not remainder:
        return ""
    try:
        remainder_tokens = shlex.split(remainder, posix=True)
    except Exception:
        remainder_tokens = []
    if not remainder_tokens:
        return ""
    if normalized_manager == "npm":
        package_token = remainder_tokens[0]
        arg_tokens = remainder_tokens[1:]
        option_index = next(
            (index for index, token in enumerate(arg_tokens) if str(token).startswith("-")),
            -1,
        )
        command_tokens = ["npm", "exec", "--yes", package_token]
        if option_index >= 0:
            command_tokens.extend(arg_tokens[:option_index])
            command_tokens.append("--")
            command_tokens.extend(arg_tokens[option_index:])
        else:
            command_tokens.extend(arg_tokens)
        return " ".join(_shell_quote(token) for token in command_tokens if str(token).strip())
    next_prefix = prefix_map.get(normalized_manager, "")
    if not next_prefix:
        return ""
    return f"{next_prefix}{' '.join(_shell_quote(token) for token in remainder_tokens)}".strip()


def _registry_manager_from_command(command: str) -> str:
    lowered = str(command or "").strip().lower()
    if lowered.startswith("bunx "):
        return "bunx"
    if lowered.startswith("npx "):
        return "npx"
    if lowered.startswith("pnpm dlx "):
        return "pnpm"
    if lowered.startswith("npm "):
        return "npm"
    return ""


def _build_registry_fallback_commands(plan: dict[str, Any], attempted_command: str) -> list[str]:
    if not isinstance(plan, dict):
        return []
    install_ref = str(plan.get("install_ref") or "").strip()
    if not install_ref:
        return []
    attempted_manager = _registry_manager_from_command(attempted_command)
    preferred_manager = _normalize_update_manager(plan.get("manager"))
    manager_candidates = _dedupe_keep_order(
        [
            preferred_manager,
            "bunx",
            "npx",
            "pnpm",
            "npm",
        ],
    )
    commands: list[str] = []
    for candidate in manager_candidates:
        if candidate == attempted_manager:
            continue
        command = _replace_registry_command_runner(attempted_command, candidate)
        if not command:
            command = _build_registry_update_command(candidate, install_ref)
        if command and command != str(attempted_command or "").strip():
            commands.append(command)
    return _dedupe_keep_order(commands)


def _looks_like_command_not_found(result_payload: dict[str, Any]) -> bool:
    if not isinstance(result_payload, dict):
        return False
    if int(result_payload.get("exit_code") or 0) == 127:
        return True
    stderr = str(result_payload.get("stderr") or "").strip().lower()
    if "command not found" in stderr:
        return True
    if "not found" in stderr and "git repository" not in stderr:
        return True
    return False


def _is_env_assignment_token(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", str(token or "")))


def _extract_primary_executable(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        tokens = shlex.split(text, posix=True)
    except Exception:
        return ""
    if not tokens:
        return ""

    wrappers = {"sudo", "command", "builtin", "nohup", "time"}
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if _is_env_assignment_token(token):
            idx += 1
            continue
        if token == "env":
            idx += 1
            while idx < len(tokens):
                probe = tokens[idx]
                if probe.startswith("-") or _is_env_assignment_token(probe):
                    idx += 1
                    continue
                break
            continue
        if token in wrappers:
            idx += 1
            continue
        return token
    return ""


class OneSyncPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._config_obj = config if hasattr(config, "save_config") else None
        self.runner = CommandRunner()

        self.plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.state_path = self.plugin_data_dir / "state.json"
        self.events_path = self.plugin_data_dir / "events.jsonl"
        self.skills_state_dir = self.plugin_data_dir / "skills"
        self.skills_manifest_path = self.skills_state_dir / "manifest.json"
        self.skills_lock_path = self.skills_state_dir / "lock.json"
        self.skills_registry_path = self.skills_state_dir / "registry.json"
        self.skills_install_atom_registry_path = self.skills_state_dir / "install_atom_registry.json"
        self.skills_audit_path = self.skills_state_dir / "audit.log.jsonl"
        self.skills_sources_dir = self.skills_state_dir / "sources"
        self.skills_generated_dir = self.skills_state_dir / "generated"
        self.skills_git_repos_dir = self.skills_state_dir / "git_repos"

        self.state: dict[str, Any] = {"targets": {}, "env": {}, "inventory": {}, "skills": {}}
        self._run_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._web_job_lock = asyncio.Lock()
        self._skills_update_all_lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task | None = None
        self._webui_server: OneSyncWebUIServer | None = None
        self._web_jobs: dict[str, dict[str, Any]] = {}
        self._web_job_tasks: dict[str, asyncio.Task] = {}
        self._git_checkout_prewarm_tasks: dict[str, asyncio.Task] = {}
        self._max_web_jobs = 40
        self._debug_logs: list[dict[str, Any]] = []
        self._debug_log_seq = 0
        self._max_debug_logs = 1200
        self._skills_update_all_progress: dict[str, Any] = self._build_skills_update_all_progress_snapshot()

    async def initialize(self) -> None:
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
        self._bootstrap_human_targets_if_needed()
        self._refresh_software_overview()
        self._refresh_inventory_snapshot()
        self._push_debug_log(
            "info",
            "plugin initialize start",
            source="lifecycle",
        )
        await self._init_webui_if_enabled()

        if _to_bool(self.config.get("enabled", True), True):
            poll_interval = _to_int(self.config.get("poll_interval_minutes", 30), 30, 1)
            self._worker_task = asyncio.create_task(
                self._scheduled_loop(poll_interval),
                name="onesync-updater-loop",
            )
            logger.info(
                "[onesync] scheduled loop started, poll_interval=%s min",
                poll_interval,
            )
        else:
            logger.info("[onesync] plugin is disabled by config")
            self._push_debug_log(
                "warn",
                "plugin is disabled by config",
                source="lifecycle",
            )

    async def terminate(self) -> None:
        self._push_debug_log("info", "plugin terminate start", source="lifecycle")
        self._stop_event.set()

        web_tasks = list(self._web_job_tasks.values())
        for task in web_tasks:
            if task.done():
                continue
            task.cancel()
        if web_tasks:
            await asyncio.gather(*web_tasks, return_exceptions=True)
        self._web_job_tasks.clear()

        git_checkout_tasks = list(self._git_checkout_prewarm_tasks.values())
        for task in git_checkout_tasks:
            if task.done():
                continue
            task.cancel()
        if git_checkout_tasks:
            await asyncio.gather(*git_checkout_tasks, return_exceptions=True)
        self._git_checkout_prewarm_tasks.clear()

        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("[onesync] scheduled loop exit error: %s", exc)

        if self._webui_server:
            try:
                await self._webui_server.stop()
            except Exception as exc:
                logger.warning("[onesync] webui stop failed: %s", exc)
                self._push_debug_log(
                    "warn",
                    f"webui stop failed: {exc}",
                    source="lifecycle",
                )
            self._webui_server = None
        await self._save_state()

    def _load_targets_from_json(self) -> dict[str, dict[str, Any]]:
        raw = self.config.get("targets_json", "")
        if isinstance(raw, dict):
            parsed = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                logger.error(
                    "[onesync] invalid targets_json, fallback to empty: %s",
                    exc,
                )
                parsed = {}
        else:
            parsed = {}

        normalized: dict[str, dict[str, Any]] = {}
        if not isinstance(parsed, dict):
            return normalized
        for name, cfg in parsed.items():
            if not isinstance(cfg, dict):
                continue
            target_name = str(name).strip()
            if not target_name:
                continue
            normalized[target_name] = dict(cfg)
        return normalized

    def _normalize_human_target_config(
        self,
        raw_cfg: Any,
        *,
        forced_name: str | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(raw_cfg, dict):
            return None

        target_name = forced_name or str(raw_cfg.get("name", "")).strip()
        if not target_name:
            return None

        template_key = str(raw_cfg.get("__template_key", "")).strip().lower()
        strategy = _normalize_strategy_name(
            raw_cfg.get("strategy", template_key or "command"),
            default="command",
        )

        check_interval_default = _to_float(
            self.config.get("default_check_interval_hours", 24),
            24.0,
            0.0,
        )
        cfg: dict[str, Any] = {
            "enabled": _to_bool(raw_cfg.get("enabled", True), True),
            "strategy": strategy,
            "check_interval_hours": _to_float(
                raw_cfg.get("check_interval_hours", check_interval_default),
                check_interval_default,
                0.0,
            ),
            "check_timeout_s": _to_int(raw_cfg.get("check_timeout_s", 120), 120, 1),
            "update_timeout_s": _to_int(raw_cfg.get("update_timeout_s", 900), 900, 1),
            "verify_timeout_s": _to_int(raw_cfg.get("verify_timeout_s", 120), 120, 1),
            "verify_cmd": str(raw_cfg.get("verify_cmd", "")).strip(),
            "current_version_pattern": str(raw_cfg.get("current_version_pattern", "")).strip(),
            "required_commands": _to_str_list(raw_cfg.get("required_commands", [])),
        }

        if strategy == "cargo_path_git":
            mirror_prefixes = _to_str_list(raw_cfg.get("mirror_prefixes", DEFAULT_GITHUB_MIRROR_PREFIXES))
            if not mirror_prefixes:
                mirror_prefixes = [""]
            cfg.update(
                {
                    "repo_path": str(raw_cfg.get("repo_path", "")).strip(),
                    "binary_path": str(raw_cfg.get("binary_path", "")).strip(),
                    "branch": str(raw_cfg.get("branch", "")).strip(),
                    "auto_add_safe_directory": _to_bool(raw_cfg.get("auto_add_safe_directory", True), True),
                    "upstream_repo": str(raw_cfg.get("upstream_repo", "")).strip(),
                    "mirror_prefixes": mirror_prefixes,
                    "remote_candidates": _to_str_list(raw_cfg.get("remote_candidates", [])),
                    "append_default_mirror_prefixes": _to_bool(raw_cfg.get("append_default_mirror_prefixes", True), True),
                    "probe_remotes": _to_bool(raw_cfg.get("probe_remotes", True), True),
                    "probe_timeout_s": _to_int(raw_cfg.get("probe_timeout_s", 15), 15, 1),
                    "probe_parallelism": _to_int(raw_cfg.get("probe_parallelism", 4), 4, 1),
                    "probe_cache_ttl_minutes": _to_float(raw_cfg.get("probe_cache_ttl_minutes", 30), 30.0, 0.0),
                    "build_commands": _to_str_list(raw_cfg.get("build_commands", ["cargo install --path {repo_path}"])),
                    "current_version_cmd": str(raw_cfg.get("current_version_cmd", "")).strip(),
                },
            )
        elif strategy == "system_package":
            manager = _normalize_system_package_manager(raw_cfg.get("manager", "apt_get"))
            if not manager:
                manager = "apt_get"
            cfg.update(
                {
                    "manager": manager,
                    "package_name": str(raw_cfg.get("package_name", target_name)).strip() or target_name,
                    "require_sudo": _to_bool(raw_cfg.get("require_sudo", True), True),
                    "sudo_prefix": str(raw_cfg.get("sudo_prefix", "sudo")).strip() or "sudo",
                    "current_version_cmd": str(raw_cfg.get("current_version_cmd", "")).strip(),
                    "latest_version_cmd": str(raw_cfg.get("latest_version_cmd", "")).strip(),
                    "latest_version_pattern": str(raw_cfg.get("latest_version_pattern", "")).strip(),
                    "update_commands": _to_str_list(raw_cfg.get("update_commands", [])),
                },
            )
        else:
            cfg.update(
                {
                    "current_version_cmd": str(raw_cfg.get("current_version_cmd", "")).strip(),
                    "latest_version_cmd": str(raw_cfg.get("latest_version_cmd", "")).strip(),
                    "latest_version_pattern": str(raw_cfg.get("latest_version_pattern", "")).strip(),
                    "update_commands": _to_str_list(raw_cfg.get("update_commands", [])),
                },
            )
        return target_name, cfg

    def _target_cfg_to_human_template_entry(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = _normalize_strategy_name(target_cfg.get("strategy", "command"), default="command")
        entry: dict[str, Any] = {
            "name": target_name,
            "enabled": _to_bool(target_cfg.get("enabled", True), True),
            "check_interval_hours": _to_float(target_cfg.get("check_interval_hours", 24), 24.0, 0.0),
            "check_timeout_s": _to_int(target_cfg.get("check_timeout_s", 120), 120, 1),
            "update_timeout_s": _to_int(target_cfg.get("update_timeout_s", 900), 900, 1),
            "verify_timeout_s": _to_int(target_cfg.get("verify_timeout_s", 120), 120, 1),
            "verify_cmd": str(target_cfg.get("verify_cmd", "")).strip(),
            "current_version_pattern": str(target_cfg.get("current_version_pattern", "")).strip(),
            "required_commands": _to_str_list(target_cfg.get("required_commands", [])),
        }

        if strategy == "cargo_path_git":
            entry["__template_key"] = "cargo_path_git"
            entry["strategy"] = "cargo_path_git"
            entry.update(
                {
                    "repo_path": str(target_cfg.get("repo_path", "")).strip(),
                    "binary_path": str(target_cfg.get("binary_path", "")).strip(),
                    "branch": str(target_cfg.get("branch", "")).strip(),
                    "auto_add_safe_directory": _to_bool(target_cfg.get("auto_add_safe_directory", True), True),
                    "upstream_repo": str(target_cfg.get("upstream_repo", "")).strip(),
                    "mirror_prefixes": _to_str_list(target_cfg.get("mirror_prefixes", DEFAULT_GITHUB_MIRROR_PREFIXES)),
                    "remote_candidates": _to_str_list(target_cfg.get("remote_candidates", [])),
                    "append_default_mirror_prefixes": _to_bool(target_cfg.get("append_default_mirror_prefixes", True), True),
                    "probe_remotes": _to_bool(target_cfg.get("probe_remotes", True), True),
                    "probe_timeout_s": _to_int(target_cfg.get("probe_timeout_s", 15), 15, 1),
                    "probe_parallelism": _to_int(target_cfg.get("probe_parallelism", 4), 4, 1),
                    "probe_cache_ttl_minutes": _to_float(target_cfg.get("probe_cache_ttl_minutes", 30), 30.0, 0.0),
                    "build_commands": _to_str_list(target_cfg.get("build_commands", ["cargo install --path {repo_path}"])),
                    "current_version_cmd": str(target_cfg.get("current_version_cmd", "")).strip(),
                },
            )
        elif strategy == "system_package":
            manager = _normalize_system_package_manager(target_cfg.get("manager", "apt_get"))
            if not manager:
                manager = "apt_get"
            entry["__template_key"] = "system_package"
            entry["strategy"] = "system_package"
            entry.update(
                {
                    "manager": manager,
                    "package_name": str(target_cfg.get("package_name", target_name)).strip() or target_name,
                    "require_sudo": _to_bool(target_cfg.get("require_sudo", True), True),
                    "sudo_prefix": str(target_cfg.get("sudo_prefix", "sudo")).strip() or "sudo",
                    "current_version_cmd": str(target_cfg.get("current_version_cmd", "")).strip(),
                    "latest_version_cmd": str(target_cfg.get("latest_version_cmd", "")).strip(),
                    "latest_version_pattern": str(target_cfg.get("latest_version_pattern", "")).strip(),
                    "update_commands": _to_str_list(target_cfg.get("update_commands", [])),
                },
            )
        else:
            entry["__template_key"] = "command"
            entry["strategy"] = "command"
            entry.update(
                {
                    "current_version_cmd": str(target_cfg.get("current_version_cmd", "")).strip(),
                    "latest_version_cmd": str(target_cfg.get("latest_version_cmd", "")).strip(),
                    "latest_version_pattern": str(target_cfg.get("latest_version_pattern", "")).strip(),
                    "update_commands": _to_str_list(target_cfg.get("update_commands", [])),
                },
            )
        return entry

    def _persist_plugin_config(self) -> None:
        cfg_obj = self._config_obj
        if cfg_obj is None:
            return
        try:
            cfg_obj.save_config(replace_config=dict(self.config))
        except Exception as exc:
            logger.warning("[onesync] persist plugin config failed: %s", exc)

    def _bootstrap_human_targets_if_needed(self) -> None:
        mode = str(self.config.get("target_config_mode", "human")).strip().lower()
        if mode != "human":
            return

        existing = self.config.get("human_targets", [])
        if isinstance(existing, list) and existing:
            return

        source_targets = self._load_targets_from_json() or DEFAULT_TARGETS
        entries: list[dict[str, Any]] = []
        for name, cfg in source_targets.items():
            if not isinstance(cfg, dict):
                continue
            target_name = str(name).strip()
            if not target_name:
                continue
            entries.append(self._target_cfg_to_human_template_entry(target_name, cfg))

        if not entries:
            return

        self.config["human_targets"] = entries
        self._persist_plugin_config()
        logger.info(
            "[onesync] initialized human_targets from existing targets (%d entries)",
            len(entries),
        )

    def _load_targets_from_human_config(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}

        entries = self.config.get("human_targets", [])
        if isinstance(entries, list):
            for index, entry in enumerate(entries):
                parsed = self._normalize_human_target_config(entry)
                if not parsed:
                    continue
                name, cfg = parsed
                if name in result:
                    logger.warning(
                        "[onesync] duplicated target name in human_targets: %s (index=%s)",
                        name,
                        index,
                    )
                result[name] = cfg

        # 兼容旧版固定槽位配置
        zeroclaw_cfg = self._normalize_human_target_config(
            self.config.get("target_zeroclaw", {}),
            forced_name="zeroclaw",
        )
        if zeroclaw_cfg and zeroclaw_cfg[0] not in result:
            result[zeroclaw_cfg[0]] = zeroclaw_cfg[1]
        for slot_key in ("target_slot_1", "target_slot_2", "target_slot_3"):
            parsed = self._normalize_human_target_config(self.config.get(slot_key, {}))
            if not parsed:
                continue
            name, cfg = parsed
            if name in result:
                logger.warning(
                    "[onesync] duplicated target name in human mode: %s (slot=%s)",
                    name,
                    slot_key,
                )
            result[name] = cfg

        return result

    def _load_targets(self) -> dict[str, dict[str, Any]]:
        mode = str(self.config.get("target_config_mode", "human")).strip().lower()

        if mode == "developer":
            parsed = self._load_targets_from_json()
            return parsed or DEFAULT_TARGETS

        human_targets = self._load_targets_from_human_config()
        if human_targets:
            return human_targets

        json_targets = self._load_targets_from_json()
        if json_targets:
            return json_targets

        return DEFAULT_TARGETS

    def _set_web_admin_url(self, url: str) -> None:
        current = str(self.config.get("web_admin_url", "") or "")
        if current == url:
            return
        self.config["web_admin_url"] = url
        self._persist_plugin_config()

    @staticmethod
    def _overview_status(current_version: str, latest_version: str, enabled: bool) -> str:
        if not enabled:
            return "disabled"
        current = str(current_version or "").strip().lower()
        latest = str(latest_version or "").strip().lower()
        if (
            not current
            or not latest
            or current in {"-", "unknown"}
            or latest in {"-", "unknown"}
        ):
            return "unknown"
        if current == latest:
            return "up_to_date"
        return "outdated"

    def _build_webui_rows(self) -> list[dict[str, Any]]:
        targets = self._load_targets()
        rows: list[dict[str, Any]] = []
        for name, cfg in sorted(targets.items(), key=lambda item: str(item[0])):
            st = self._target_state(name)
            current = str(st.get("current_version", "-") or "-")
            latest = str(st.get("latest_version", "-") or "-")
            enabled = _to_bool(cfg.get("enabled", True), True)
            rows.append(
                {
                    "software_name": name,
                    "current_version": current,
                    "latest_version": latest,
                    "strategy": str(cfg.get("strategy", "command") or "command"),
                    "enabled": enabled,
                    "last_checked_at": str(st.get("last_checked_at", "-") or "-"),
                    "status": self._overview_status(current, latest, enabled),
                }
            )
        return rows

    def _push_debug_log(
        self,
        level: str,
        message: str,
        *,
        target: str = "",
        source: str = "system",
    ) -> None:
        level_key = str(level or "info").strip().lower()
        if level_key not in {"debug", "info", "warn", "error"}:
            level_key = "info"
        self._debug_log_seq += 1
        item = {
            "id": self._debug_log_seq,
            "timestamp": _now_iso(),
            "level": level_key,
            "source": str(source or "system"),
            "target": str(target or ""),
            "message": str(message or "").strip(),
        }
        self._debug_logs.append(item)
        if len(self._debug_logs) > self._max_debug_logs:
            self._debug_logs = self._debug_logs[-self._max_debug_logs :]

    def webui_get_debug_logs(
        self,
        *,
        since_id: int = 0,
        limit: int = 200,
        level: str = "all",
        keyword: str = "",
        source_group: str = "all",
    ) -> dict[str, Any]:
        try:
            since = max(0, int(since_id))
        except Exception:
            since = 0
        try:
            lim = max(1, min(int(limit), 500))
        except Exception:
            lim = 200
        level_key = str(level or "all").strip().lower()
        keyword_key = str(keyword or "").strip().lower()
        source_group_key = str(source_group or "all").strip().lower()

        run_sources = {"webui-run", "webui-job"}
        target_sources = {"target-run"}
        scheduler_sources = {"scheduler"}
        system_sources = {"system", "lifecycle", "webui"}

        items: list[dict[str, Any]] = []
        for raw in self._debug_logs:
            log_id = _to_int(raw.get("id", 0), 0, 0)
            if log_id <= since:
                continue
            log_source = str(raw.get("source", "system")).strip().lower()
            log_level = str(raw.get("level", "info")).strip().lower()
            if level_key not in {"", "all"} and log_level != level_key:
                continue
            if keyword_key:
                payload = (
                    f"{raw.get('message', '')} {raw.get('target', '')} {raw.get('source', '')}"
                ).lower()
                if keyword_key not in payload:
                    continue
            if source_group_key not in {"", "all"}:
                if source_group_key == "run" and log_source not in run_sources:
                    continue
                if source_group_key == "target" and log_source not in target_sources:
                    continue
                if source_group_key == "scheduler" and log_source not in scheduler_sources:
                    continue
                if source_group_key == "system" and log_source not in system_sources:
                    continue
            items.append(raw)

        if len(items) > lim:
            items = items[-lim:]
        last_id = _to_int(self._debug_log_seq, 0, 0)
        return {
            "ok": True,
            "items": json.loads(json.dumps(items, ensure_ascii=False)),
            "last_id": last_id,
            "buffer_size": len(self._debug_logs),
        }

    def webui_clear_debug_logs(self) -> dict[str, Any]:
        removed = len(self._debug_logs)
        self._debug_logs.clear()
        self._push_debug_log(
            "info",
            f"debug logs cleared (removed={removed})",
            source="webui",
        )
        return {"ok": True, "removed": removed}

    def webui_get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self._web_jobs.get(job_id)
        if not isinstance(job, dict):
            return None
        return json.loads(json.dumps(job, ensure_ascii=False))

    def webui_get_latest_job(self) -> dict[str, Any] | None:
        if not self._web_jobs:
            return None
        ordered = sorted(
            self._web_jobs.values(),
            key=lambda item: str(item.get("created_at", "")),
            reverse=True,
        )
        if not ordered:
            return None
        return json.loads(json.dumps(ordered[0], ensure_ascii=False))

    def webui_get_overview_payload(self) -> dict[str, Any]:
        rows = self._build_webui_rows()
        counts = {"up_to_date": 0, "outdated": 0, "unknown": 0, "disabled": 0}
        for row in rows:
            status = str(row.get("status", "unknown"))
            if status in counts:
                counts[status] += 1
        return {
            "ok": True,
            "generated_at": _now_iso(),
            "rows": rows,
            "counts": counts,
            "latest_job": self.webui_get_latest_job(),
        }

    def _target_rows_for_inventory(self) -> dict[str, dict[str, Any]]:
        targets = self._load_targets()
        rows: dict[str, dict[str, Any]] = {}
        for name, cfg in targets.items():
            st = self._target_state(name)
            current = str(st.get("current_version", "-") or "-")
            latest = str(st.get("latest_version", "-") or "-")
            enabled = _to_bool(cfg.get("enabled", True), True)
            rows[name] = {
                "target_name": name,
                "enabled": enabled,
                "current_version": current,
                "latest_version": latest,
                "status": self._overview_status(current, latest, enabled),
                "last_checked_at": str(st.get("last_checked_at", "-") or "-"),
            }
        return rows

    def _inventory_runtime_options(self) -> dict[str, Any]:
        mode = str(self.config.get("skill_management_mode", "npx")).strip().lower()
        if mode not in {"npx", "filesystem", "hybrid"}:
            mode = "npx"
        include_commands = _to_str_list(self.config.get("auto_cli_include_commands", []))
        exclude_commands = _to_str_list(self.config.get("auto_cli_exclude_commands", []))
        return {
            "skill_management_mode": mode,
            "npx_command": str(self.config.get("npx_skills_command", "npx") or "npx").strip() or "npx",
            "npx_timeout_s": _to_int(self.config.get("npx_skills_timeout_s", 12), 12, 1),
            "npx_include_project": _to_bool(self.config.get("npx_skills_include_project", True), True),
            "npx_include_global": _to_bool(self.config.get("npx_skills_include_global", True), True),
            "npx_workdir": str(self.config.get("npx_skills_workdir", "") or "").strip(),
            "auto_discover_cli": _to_bool(self.config.get("auto_discover_cli", True), True),
            "auto_discover_cli_max": _to_int(self.config.get("auto_discover_cli_max", 120), 120, 20),
            "auto_cli_only_known": _to_bool(self.config.get("auto_cli_only_known", True), True),
            "auto_cli_include_commands": include_commands,
            "auto_cli_exclude_commands": exclude_commands,
        }

    def _inventory_catalogs(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        try:
            software_catalog = normalize_software_catalog_payload(
                self.config.get("software_catalog", []),
                fallback_defaults=True,
            )
        except Exception as exc:
            logger.error("[onesync] invalid software_catalog, fallback to defaults: %s", exc)
            software_catalog = normalize_software_catalog_payload([], fallback_defaults=True)

        try:
            skill_catalog = normalize_skill_catalog_payload(self.config.get("skill_catalog", []))
        except Exception as exc:
            logger.error("[onesync] invalid skill_catalog, fallback to empty: %s", exc)
            skill_catalog = []

        try:
            skill_bindings = normalize_skill_bindings_payload(self.config.get("skill_bindings", []))
        except Exception as exc:
            logger.error("[onesync] invalid skill_bindings, fallback to empty: %s", exc)
            skill_bindings = []

        return software_catalog, skill_catalog, skill_bindings, self._inventory_runtime_options()

    def _build_inventory_snapshot(
        self,
        *,
        skill_bindings_override: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        software_catalog, skill_catalog, skill_bindings, inventory_options = self._inventory_catalogs()
        if skill_bindings_override is not None:
            skill_bindings = normalize_skill_bindings_payload(skill_bindings_override)
        target_rows = self._target_rows_for_inventory()
        return build_inventory_snapshot(
            software_catalog=software_catalog,
            skill_catalog=skill_catalog,
            skill_bindings=skill_bindings,
            target_rows=target_rows,
            inventory_options=inventory_options,
        )

    def _build_skills_snapshot(
        self,
        inventory_snapshot: dict[str, Any] | None = None,
        *,
        saved_manifest: dict[str, Any] | None = None,
        saved_registry: dict[str, Any] | None = None,
        saved_lock: dict[str, Any] | None = None,
        saved_install_atom_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = inventory_snapshot if isinstance(inventory_snapshot, dict) else self._build_inventory_snapshot()
        return build_skills_overview(
            snapshot,
            saved_manifest=saved_manifest,
            saved_registry=saved_registry,
            saved_lock=saved_lock,
            saved_install_atom_registry=saved_install_atom_registry,
        )

    def _read_json_file(self, path: Path) -> Any:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _load_saved_skills_manifest(self) -> dict[str, Any]:
        skills_state = self._skills_state()
        cached = skills_state.get("saved_manifest")
        if isinstance(cached, dict) and cached:
            return normalize_saved_skills_manifest(cached)
        manifest = normalize_saved_skills_manifest(self._read_json_file(self.skills_manifest_path))
        if manifest:
            skills_state["saved_manifest"] = manifest
        return manifest

    def _load_saved_skills_registry(self) -> dict[str, Any]:
        skills_state = self._skills_state()
        cached = skills_state.get("saved_registry")
        if isinstance(cached, dict) and cached:
            return normalize_skills_registry(cached)
        registry = normalize_skills_registry(self._read_json_file(self.skills_registry_path))
        if registry:
            skills_state["saved_registry"] = registry
        return registry

    def _load_saved_skills_lock(self) -> dict[str, Any]:
        skills_state = self._skills_state()
        cached = skills_state.get("saved_lock")
        if isinstance(cached, dict) and cached:
            return normalize_saved_skills_lock(cached)
        lock = normalize_saved_skills_lock(self._read_json_file(self.skills_lock_path))
        if lock:
            skills_state["saved_lock"] = lock
        return lock

    def _load_saved_install_atom_registry(self) -> dict[str, Any]:
        skills_state = self._skills_state()
        cached = skills_state.get("saved_install_atom_registry")
        if isinstance(cached, dict) and cached:
            return normalize_install_atom_registry(cached)
        registry = normalize_install_atom_registry(self._read_json_file(self.skills_install_atom_registry_path))
        if registry:
            skills_state["saved_install_atom_registry"] = registry
        return registry

    def _save_skills_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_saved_skills_manifest(manifest)
        skills_state = self._skills_state()
        skills_state["saved_manifest"] = normalized
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_file(self.skills_manifest_path, normalized)
        return normalized

    def _save_skills_registry(self, registry: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_skills_registry(registry)
        skills_state = self._skills_state()
        skills_state["saved_registry"] = normalized
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_file(self.skills_registry_path, normalized)
        return normalized

    def _save_skills_lock(self, lock: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_saved_skills_lock(lock)
        skills_state = self._skills_state()
        skills_state["saved_lock"] = normalized
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_file(self.skills_lock_path, normalized)
        return normalized

    def _save_install_atom_registry(self, registry: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_install_atom_registry(registry)
        skills_state = self._skills_state()
        skills_state["saved_install_atom_registry"] = normalized
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_file(self.skills_install_atom_registry_path, normalized)
        return normalized

    def _append_skills_audit_event(
        self,
        action: str,
        *,
        source_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = f"audit_{uuid.uuid4().hex}"
        event = {
            "event_id": event_id,
            "timestamp": _now_iso(),
            "action": str(action or "").strip(),
            "source_id": str(source_id or "").strip(),
            "payload": payload if isinstance(payload, dict) else {},
        }
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self.skills_audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("[onesync] append skills audit failed: %s", exc)
            return ""
        return event_id

    def _sync_skill_bindings_projection(self, manifest: dict[str, Any]) -> bool:
        projected_bindings = normalize_skill_bindings_payload(manifest_to_binding_rows(manifest))
        current_bindings = normalize_skill_bindings_payload(self.config.get("skill_bindings", []))
        if current_bindings == projected_bindings:
            return False
        self.config["skill_bindings"] = projected_bindings
        self._persist_plugin_config()
        return True

    @staticmethod
    def _skills_snapshot_compatibility_map(skills_snapshot: dict[str, Any] | None) -> dict[str, list[str]]:
        snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else {}
        compatibility: dict[str, list[str]] = {}

        compatibility_raw = snapshot.get("compatibility", {})
        if isinstance(compatibility_raw, dict):
            for software_id, source_ids in compatibility_raw.items():
                software_key = _normalize_inventory_id(software_id, default="")
                if not software_key:
                    continue
                compatibility[software_key] = _dedupe_keep_order(_to_str_list(source_ids))

        compatible_rows_raw = snapshot.get("compatible_source_rows_by_software", {})
        if isinstance(compatible_rows_raw, dict):
            for software_id, rows in compatible_rows_raw.items():
                software_key = _normalize_inventory_id(software_id, default="")
                if not software_key or not isinstance(rows, list):
                    continue
                current_ids = list(compatibility.get(software_key, []))
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    source_id = _normalize_inventory_id(
                        row.get("source_id") or row.get("id") or row.get("skill_id"),
                        default="",
                    )
                    if source_id:
                        current_ids.append(source_id)
                compatibility[software_key] = _dedupe_keep_order(current_ids)

        return compatibility

    @classmethod
    def _skills_snapshot_known_software_ids(cls, skills_snapshot: dict[str, Any] | None) -> list[str]:
        snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else {}
        software_ids: list[str] = []

        for row in snapshot.get("software_rows", []):
            if not isinstance(row, dict):
                continue
            software_id = _normalize_inventory_id(row.get("id"), default="")
            if software_id:
                software_ids.append(software_id)

        for row in snapshot.get("host_rows", []):
            if not isinstance(row, dict):
                continue
            software_id = _normalize_inventory_id(row.get("host_id") or row.get("id"), default="")
            if software_id:
                software_ids.append(software_id)

        software_ids.extend(cls._skills_snapshot_compatibility_map(snapshot).keys())
        return _dedupe_keep_order([item for item in software_ids if item])

    @classmethod
    def _skills_snapshot_compatible_source_ids(
        cls,
        skills_snapshot: dict[str, Any] | None,
        software_id: str,
    ) -> list[str]:
        software_key = _normalize_inventory_id(software_id, default="")
        if not software_key:
            return []
        compatibility = cls._skills_snapshot_compatibility_map(skills_snapshot)
        return _dedupe_keep_order(_to_str_list(compatibility.get(software_key, [])))

    def _store_saved_skills_payloads(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        registry: dict[str, Any] | None = None,
        lock: dict[str, Any] | None = None,
        install_atom_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skills_state = self._skills_state()
        stored: dict[str, Any] = {}
        can_persist_files = hasattr(self, "skills_state_dir")

        if manifest is not None:
            normalized_manifest = normalize_saved_skills_manifest(manifest)
            if can_persist_files and hasattr(self, "skills_manifest_path"):
                normalized_manifest = self._save_skills_manifest(normalized_manifest)
            else:
                skills_state["saved_manifest"] = normalized_manifest
            stored["manifest"] = normalized_manifest

        if registry is not None:
            normalized_registry = normalize_skills_registry(registry)
            if can_persist_files and hasattr(self, "skills_registry_path"):
                normalized_registry = self._save_skills_registry(normalized_registry)
            else:
                skills_state["saved_registry"] = normalized_registry
            stored["registry"] = normalized_registry

        if lock is not None:
            normalized_lock = normalize_saved_skills_lock(lock)
            if can_persist_files and hasattr(self, "skills_lock_path"):
                normalized_lock = self._save_skills_lock(normalized_lock)
            else:
                skills_state["saved_lock"] = normalized_lock
            stored["lock"] = normalized_lock

        if install_atom_registry is not None:
            normalized_install_atom_registry = normalize_install_atom_registry(install_atom_registry)
            if can_persist_files and hasattr(self, "skills_install_atom_registry_path"):
                normalized_install_atom_registry = self._save_install_atom_registry(normalized_install_atom_registry)
            else:
                skills_state["saved_install_atom_registry"] = normalized_install_atom_registry
            stored["install_atom_registry"] = normalized_install_atom_registry

        return stored

    def _replace_saved_manifest_target_selections_from_bindings(
        self,
        manifest: dict[str, Any] | None,
        binding_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_manifest = normalize_saved_skills_manifest(manifest if isinstance(manifest, dict) else {})
        deploy_targets = [
            dict(item)
            for item in normalized_manifest.get("deploy_targets", [])
            if isinstance(item, dict)
        ]
        target_index = {
            str(item.get("target_id") or "").strip(): item
            for item in deploy_targets
            if str(item.get("target_id") or "").strip()
        }

        target_selection_map: dict[str, list[str]] = {}
        incoming_target_ids: list[str] = []
        for binding in normalize_skill_bindings_payload(binding_rows):
            if not _to_bool(binding.get("enabled", True), True):
                continue
            software_id = _normalize_inventory_id(binding.get("software_id"), default="")
            skill_id = _normalize_inventory_id(binding.get("skill_id"), default="")
            scope = _normalize_inventory_id(binding.get("scope", "global"), default="global")
            if scope not in {"global", "workspace"}:
                scope = "global"
            if not software_id or not skill_id:
                continue
            target_id = f"{software_id}:{scope}"
            incoming_target_ids.append(target_id)
            selected_source_ids = target_selection_map.setdefault(target_id, [])
            if skill_id not in selected_source_ids:
                selected_source_ids.append(skill_id)

        ordered_target_ids = _dedupe_keep_order(
            [
                str(item.get("target_id") or "").strip()
                for item in deploy_targets
                if str(item.get("target_id") or "").strip()
            ] + incoming_target_ids,
        )

        next_deploy_targets: list[dict[str, Any]] = []
        for target_id in ordered_target_ids:
            software_text, _, scope_text = target_id.partition(":")
            software_id = _normalize_inventory_id(software_text, default="")
            scope = _normalize_inventory_id(scope_text or "global", default="global")
            if scope not in {"global", "workspace"}:
                scope = "global"
            current = dict(target_index.get(target_id, {}))
            current["target_id"] = target_id
            current["software_id"] = software_id
            current["scope"] = scope
            current["selected_source_ids"] = list(target_selection_map.get(target_id, []))
            next_deploy_targets.append(current)

        normalized_manifest["deploy_targets"] = next_deploy_targets
        stored = self._store_saved_skills_payloads(manifest=normalized_manifest)
        return stored.get("manifest", normalized_manifest)

    def _inventory_projection_base_snapshot(
        self,
        *,
        skills_snapshot: dict[str, Any] | None = None,
        inventory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = inventory_snapshot if isinstance(inventory_snapshot, dict) else {}
        skills = skills_snapshot if isinstance(skills_snapshot, dict) else {}

        software_rows = [
            dict(item)
            for item in snapshot.get("software_rows", [])
            if isinstance(item, dict)
        ]
        if not software_rows:
            software_rows = [
                dict(item)
                for item in skills.get("software_rows", [])
                if isinstance(item, dict)
            ]
        if not software_rows:
            for item in skills.get("host_rows", []):
                if not isinstance(item, dict):
                    continue
                software_id = _normalize_inventory_id(item.get("host_id") or item.get("id"), default="")
                if not software_id:
                    continue
                software_rows.append(
                    {
                        "id": software_id,
                        "display_name": str(item.get("display_name") or software_id),
                        "binding_count": _to_int(item.get("binding_count", 0), 0, 0),
                    },
                )

        skill_rows = [
            dict(item)
            for item in snapshot.get("skill_rows", [])
            if isinstance(item, dict)
        ]
        if not skill_rows:
            skill_rows = [
                dict(item)
                for item in skills.get("skill_rows", [])
                if isinstance(item, dict)
            ]
        if not skill_rows:
            for item in skills.get("source_rows", []):
                if not isinstance(item, dict):
                    continue
                source_id = _normalize_inventory_id(item.get("source_id") or item.get("id"), default="")
                if not source_id:
                    continue
                skill_rows.append(
                    {
                        "id": source_id,
                        "display_name": str(item.get("display_name") or source_id),
                    },
                )
        if not skill_rows:
            seen_source_ids: set[str] = set()
            for source_ids in self._skills_snapshot_compatibility_map(skills).values():
                for source_id in source_ids:
                    if source_id in seen_source_ids:
                        continue
                    seen_source_ids.add(source_id)
                    skill_rows.append({"id": source_id, "display_name": source_id})

        compatibility = self._skills_snapshot_compatibility_map(skills)
        if not compatibility:
            compatibility_raw = snapshot.get("compatibility", {})
            if isinstance(compatibility_raw, dict):
                compatibility = {
                    _normalize_inventory_id(software_id, default=""): _dedupe_keep_order(_to_str_list(source_ids))
                    for software_id, source_ids in compatibility_raw.items()
                    if _normalize_inventory_id(software_id, default="")
                }

        counts = snapshot.get("counts", {})
        warnings = snapshot.get("warnings", [])
        return {
            **snapshot,
            "ok": _to_bool(snapshot.get("ok", True), True),
            "generated_at": str(snapshot.get("generated_at") or skills.get("generated_at") or _now_iso()),
            "software_rows": software_rows,
            "skill_rows": skill_rows,
            "compatibility": compatibility,
            "counts": counts if isinstance(counts, dict) else {},
            "warnings": list(warnings) if isinstance(warnings, list) else [],
        }

    def _project_inventory_and_refresh_skills_from_manifest(
        self,
        manifest: dict[str, Any] | None,
        *,
        skills_snapshot: dict[str, Any] | None = None,
        inventory_snapshot: dict[str, Any] | None = None,
        saved_registry: dict[str, Any] | None = None,
        saved_lock: dict[str, Any] | None = None,
        saved_install_atom_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_skills_snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else self.webui_get_skills_payload()
        normalized_manifest = normalize_saved_skills_manifest(manifest if isinstance(manifest, dict) else {})
        base_inventory_snapshot = self._inventory_projection_base_snapshot(
            skills_snapshot=current_skills_snapshot,
            inventory_snapshot=inventory_snapshot if isinstance(inventory_snapshot, dict) else self._inventory_state().get("last_snapshot", {}),
        )
        projected_inventory_snapshot = project_inventory_snapshot_bindings_from_manifest(
            base_inventory_snapshot,
            normalized_manifest,
        )
        inventory_state = self._inventory_state()
        inventory_state["last_snapshot"] = projected_inventory_snapshot
        inventory_state["last_scanned_at"] = projected_inventory_snapshot.get("generated_at", _now_iso())

        resolved_registry = (
            saved_registry if isinstance(saved_registry, dict)
            else current_skills_snapshot.get("registry", {})
            if isinstance(current_skills_snapshot.get("registry", {}), dict)
            else self._load_saved_skills_registry()
        )
        resolved_lock = (
            saved_lock if isinstance(saved_lock, dict)
            else current_skills_snapshot.get("lock", {})
            if isinstance(current_skills_snapshot.get("lock", {}), dict)
            else self._load_saved_skills_lock()
        )
        resolved_install_atom_registry = (
            saved_install_atom_registry if isinstance(saved_install_atom_registry, dict)
            else current_skills_snapshot.get("install_atom_registry", {})
            if isinstance(current_skills_snapshot.get("install_atom_registry", {}), dict)
            else self._load_saved_install_atom_registry()
        )

        refreshed_skills_snapshot = self._refresh_skills_snapshot(
            inventory_snapshot=projected_inventory_snapshot,
            saved_manifest=normalized_manifest,
            saved_registry=resolved_registry,
            saved_lock=resolved_lock,
            saved_install_atom_registry=resolved_install_atom_registry,
        )

        final_manifest = normalize_saved_skills_manifest(
            refreshed_skills_snapshot.get("manifest", normalized_manifest)
            if isinstance(refreshed_skills_snapshot, dict)
            else normalized_manifest,
        )
        final_registry = (
            refreshed_skills_snapshot.get("registry", resolved_registry)
            if isinstance(refreshed_skills_snapshot, dict) and isinstance(refreshed_skills_snapshot.get("registry", resolved_registry), dict)
            else resolved_registry
        )
        final_lock = (
            refreshed_skills_snapshot.get("lock", resolved_lock)
            if isinstance(refreshed_skills_snapshot, dict) and isinstance(refreshed_skills_snapshot.get("lock", resolved_lock), dict)
            else resolved_lock
        )
        final_install_atom_registry = (
            refreshed_skills_snapshot.get("install_atom_registry", resolved_install_atom_registry)
            if isinstance(refreshed_skills_snapshot, dict) and isinstance(refreshed_skills_snapshot.get("install_atom_registry", resolved_install_atom_registry), dict)
            else resolved_install_atom_registry
        )
        self._store_saved_skills_payloads(
            manifest=final_manifest,
            registry=final_registry,
            lock=final_lock,
            install_atom_registry=final_install_atom_registry,
        )

        self._sync_skill_bindings_projection(final_manifest)
        projected_inventory_snapshot = project_inventory_snapshot_bindings_from_manifest(
            base_inventory_snapshot,
            final_manifest,
        )
        inventory_state["last_snapshot"] = projected_inventory_snapshot
        inventory_state["last_scanned_at"] = projected_inventory_snapshot.get("generated_at", _now_iso())

        last_overview = self._skills_state().get("last_overview", {})
        if isinstance(last_overview, dict) and last_overview:
            can_augment_runtime_health = all(
                hasattr(self, attr)
                for attr in (
                    "skills_manifest_path",
                    "skills_lock_path",
                    "skills_sources_dir",
                    "skills_generated_dir",
                )
            )
            if can_augment_runtime_health:
                self._augment_skills_runtime_health(last_overview)
                self._schedule_git_checkout_prewarm(last_overview.get("source_rows", []))
            self._skills_state()["last_overview"] = last_overview

        return {
            "manifest": final_manifest,
            "inventory": projected_inventory_snapshot,
            "skills": self._skills_state().get("last_overview", {}),
            "registry": final_registry,
            "lock": final_lock,
            "install_atom_registry": final_install_atom_registry,
        }

    def _write_json_file(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    @staticmethod
    def _looks_like_git_locator_text(value: Any) -> bool:
        locator = str(value or "").strip().lower()
        if not locator:
            return False
        return (
            locator.startswith("git@")
            or locator.startswith("ssh://")
            or locator.endswith(".git")
            or "github.com/" in locator
            or "gitlab.com/" in locator
            or "bitbucket.org/" in locator
        )

    @staticmethod
    def _strip_repo_locator_prefix(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        for prefix in ("repo:", "documented:", "catalog:", "community:", "source:"):
            if lowered.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    @classmethod
    def _split_git_locator_subpath(cls, value: Any) -> tuple[str, str]:
        raw = cls._strip_repo_locator_prefix(value)
        if not raw:
            return "", ""
        locator, _, subpath = raw.partition("#")
        return locator.strip(), subpath.strip().strip("/")

    def _run_git_probe(
        self,
        args: list[str],
        *,
        cwd: str | Path | None = None,
        timeout_s: int = 30,
    ) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return False, "git command is not available"
        except Exception as exc:  # pragma: no cover - defensive branch
            return False, f"git command execution failed: {exc}"
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "").strip()
            return False, output or f"git command failed with exit code {completed.returncode}"
        return True, (completed.stdout or "").strip()

    def _path_is_git_worktree(self, path: str | Path) -> bool:
        candidate = Path(path)
        if not candidate.exists():
            return False
        ok, _ = self._run_git_probe(
            ["rev-parse", "--is-inside-work-tree"],
            cwd=candidate,
            timeout_s=10,
        )
        return ok

    def _git_remote_origin_url(self, checkout_path: str | Path) -> str:
        ok, output = self._run_git_probe(
            ["remote", "get-url", "origin"],
            cwd=checkout_path,
            timeout_s=15,
        )
        return output.strip() if ok else ""

    def _probe_git_remote_candidate(
        self,
        locator: str,
        *,
        timeout_s: int = 20,
    ) -> dict[str, Any]:
        locator_text = str(locator or "").strip()
        started_at = time.monotonic()
        ok, output = self._run_git_probe(
            ["ls-remote", locator_text, "HEAD"],
            timeout_s=timeout_s,
        )
        duration_ms = int(round((time.monotonic() - started_at) * 1000))
        return {
            "locator": locator_text,
            "ok": ok,
            "message": output,
            "duration_ms": duration_ms,
        }

    def _resolve_preferred_git_remote_locator(
        self,
        locator: str,
        *,
        current_origin: str = "",
    ) -> str:
        normalized_locator = str(locator or "").strip()
        candidates = self._candidate_git_clone_locators(normalized_locator)
        ordered_candidates: list[str] = []
        current_origin_text = str(current_origin or "").strip()
        if current_origin_text and current_origin_text in candidates:
            ordered_candidates.append(current_origin_text)
        for candidate in candidates:
            if candidate and candidate not in ordered_candidates:
                ordered_candidates.append(candidate)
        if not ordered_candidates and normalized_locator:
            ordered_candidates.append(normalized_locator)
        probe_results: list[dict[str, Any]] = []
        for index, candidate in enumerate(ordered_candidates):
            result = self._probe_git_remote_candidate(candidate, timeout_s=20)
            result["index"] = index
            probe_results.append(result)

        reachable_results = [
            item
            for item in probe_results
            if _to_bool(item.get("ok", False), False)
        ]
        if not reachable_results:
            return ordered_candidates[0] if ordered_candidates else normalized_locator

        reachable_results.sort(
            key=lambda item: (
                _to_int(item.get("duration_ms", 0), 0, 0),
                _to_int(item.get("index", 0), 0, 0),
            ),
        )
        best_result = reachable_results[0]
        current_result = next(
            (
                item
                for item in reachable_results
                if str(item.get("locator") or "").strip() == current_origin_text
            ),
            None,
        )
        # Keep the current origin when it is still healthy and not materially slower.
        if current_result and (
            _to_int(current_result.get("duration_ms", 0), 0, 0)
            <= _to_int(best_result.get("duration_ms", 0), 0, 0) + 150
        ):
            return current_origin_text
        return str(best_result.get("locator") or "").strip() or normalized_locator

    def _align_managed_git_checkout_remote(
        self,
        checkout_path: str | Path,
        locator: str,
        *,
        preferred_locator: str = "",
    ) -> dict[str, Any]:
        checkout_dir = Path(checkout_path)
        if not checkout_dir.exists() or not self._path_is_git_worktree(checkout_dir):
            return {
                "ok": False,
                "message": f"managed checkout path is not a git worktree: {checkout_dir}",
                "error_code": "git_checkout_invalid",
                "remote_locator": "",
            }

        locator_text = str(locator or "").strip()
        if not locator_text:
            return {
                "ok": False,
                "message": "git repo locator is unavailable",
                "error_code": "git_repo_locator_missing",
                "remote_locator": "",
            }

        current_origin = self._git_remote_origin_url(checkout_dir)
        target_origin = str(preferred_locator or "").strip() or self._resolve_preferred_git_remote_locator(
            locator_text,
            current_origin=current_origin,
        )
        if not target_origin:
            return {
                "ok": False,
                "message": "preferred git remote locator could not be resolved",
                "error_code": "git_remote_locator_unresolved",
                "remote_locator": "",
            }

        if current_origin == target_origin:
            return {
                "ok": True,
                "message": f"managed git remote already aligned: {target_origin}",
                "error_code": "",
                "remote_locator": target_origin,
            }

        if current_origin:
            ok, output = self._run_git_probe(
                ["remote", "set-url", "origin", target_origin],
                cwd=checkout_dir,
                timeout_s=20,
            )
        else:
            ok, output = self._run_git_probe(
                ["remote", "add", "origin", target_origin],
                cwd=checkout_dir,
                timeout_s=20,
            )
        if not ok:
            return {
                "ok": False,
                "message": output or f"failed to align git remote for {checkout_dir}",
                "error_code": "git_remote_align_failed",
                "remote_locator": current_origin,
            }

        return {
            "ok": True,
            "message": f"managed git remote aligned to {target_origin}",
            "error_code": "",
            "remote_locator": target_origin,
        }

    def _supports_managed_git_checkout(self, source_row: dict[str, Any] | None) -> bool:
        row = source_row if isinstance(source_row, dict) else {}
        spec = self._resolve_source_git_checkout_spec(row)
        locator = str(spec.get("locator") or "").strip()
        if not locator:
            return False
        manager = str(
            row.get("install_manager")
            or row.get("managed_by")
            or row.get("registry_package_manager")
            or ""
        ).strip().lower()
        return manager in {"git", "github"}

    def _git_checkout_prewarm_key(self, source_row: dict[str, Any] | None) -> str:
        row = source_row if isinstance(source_row, dict) else {}
        spec = self._resolve_source_git_checkout_spec(row)
        locator = str(spec.get("locator") or "").strip()
        if locator:
            return locator
        source_id = _normalize_inventory_id(row.get("source_id", ""), default="")
        return source_id

    def _iter_git_checkout_prewarm_candidates(
        self,
        source_rows: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in source_rows or []:
            if not isinstance(row, dict) or not self._supports_managed_git_checkout(row):
                continue
            prewarm_key = self._git_checkout_prewarm_key(row)
            if not prewarm_key or prewarm_key in seen_keys:
                continue
            seen_keys.add(prewarm_key)
            candidates.append(dict(row))
        return candidates

    def _apply_git_checkout_metadata_to_cached_snapshot(
        self,
        source_ids: list[str],
        source_payload_by_id: dict[str, dict[str, Any]],
    ) -> None:
        normalized_source_ids = {
            _normalize_inventory_id(item, default="")
            for item in source_ids
            if _normalize_inventory_id(item, default="")
        }
        if not normalized_source_ids or not isinstance(source_payload_by_id, dict):
            return

        skills_state = self._skills_state()
        snapshot = skills_state.get("last_overview", {})
        if not isinstance(snapshot, dict) or not snapshot:
            return

        registry = snapshot.get("registry", {})
        if isinstance(registry, dict):
            registry_sources = registry.get("sources", [])
            if isinstance(registry_sources, list):
                for index, item in enumerate(registry_sources):
                    if not isinstance(item, dict):
                        continue
                    source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
                    if source_id not in normalized_source_ids:
                        continue
                    payload = source_payload_by_id.get(source_id)
                    if isinstance(payload, dict):
                        registry_sources[index] = payload

        snapshot_source_rows = snapshot.get("source_rows", [])
        if isinstance(snapshot_source_rows, list):
            for item in snapshot_source_rows:
                if not isinstance(item, dict):
                    continue
                source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
                if source_id not in normalized_source_ids:
                    continue
                payload = source_payload_by_id.get(source_id)
                if not isinstance(payload, dict):
                    continue
                for key in (
                    "git_checkout_path",
                    "git_checkout_managed",
                    "git_checkout_error",
                    "last_refresh_at",
                ):
                    item[key] = payload.get(key)
        skills_state["last_overview"] = snapshot

    def _persist_git_checkout_metadata_for_locator(
        self,
        locator: str,
        source_payload: dict[str, Any],
    ) -> None:
        locator_text = str(locator or "").strip()
        if not locator_text or not isinstance(source_payload, dict):
            return

        current_registry = self._load_saved_skills_registry()
        registry_sources = current_registry.get("sources", [])
        updated_registry = current_registry
        updated_source_ids: list[str] = []

        for item in registry_sources:
            if not isinstance(item, dict) or not self._supports_managed_git_checkout(item):
                continue
            spec = self._resolve_source_git_checkout_spec(item)
            item_locator = str(spec.get("locator") or "").strip()
            if item_locator != locator_text:
                continue
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            if not source_id:
                continue
            merged_source_payload = {
                **item,
                **source_payload,
                "source_id": source_id,
            }
            updated_registry = refresh_registry_source(
                updated_registry,
                source_id,
                merged_source_payload,
                generated_at=_now_iso(),
            )
            updated_source_ids.append(source_id)

        if not updated_source_ids:
            return

        saved_registry = self._save_skills_registry(updated_registry)
        payload_by_id: dict[str, dict[str, Any]] = {}
        for item in saved_registry.get("sources", []):
            if not isinstance(item, dict):
                continue
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            if source_id in updated_source_ids:
                payload_by_id[source_id] = item
                if source_id:
                    self._write_json_file(self.skills_sources_dir / f"{source_id}.json", item)

        self._apply_git_checkout_metadata_to_cached_snapshot(updated_source_ids, payload_by_id)

    async def _run_git_checkout_prewarm(self, source_row: dict[str, Any]) -> None:
        row = dict(source_row) if isinstance(source_row, dict) else {}
        if not row:
            return

        source_id = _normalize_inventory_id(row.get("source_id", ""), default="")
        spec = self._resolve_source_git_checkout_spec(row)
        locator = str(spec.get("locator") or "").strip()
        if not locator:
            return

        try:
            ensure_result = await asyncio.to_thread(self._ensure_source_git_checkout, row)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._push_debug_log(
                "warn",
                f"git checkout prewarm failed: source={source_id or locator} error={exc}",
                source="skills",
            )
            return

        next_row = dict(row)
        if ensure_result.get("ok"):
            next_row["git_checkout_path"] = str(ensure_result.get("checkout_path") or "").strip()
            next_row["git_checkout_managed"] = _to_bool(ensure_result.get("managed", False), False)
            next_row["git_checkout_error"] = ""
        else:
            next_row["git_checkout_path"] = ""
            next_row["git_checkout_managed"] = True
            next_row["git_checkout_error"] = str(ensure_result.get("message") or "").strip()

        self._persist_git_checkout_metadata_for_locator(locator, next_row)
        self._push_debug_log(
            "info" if ensure_result.get("ok") else "warn",
            (
                "git checkout prewarm finished: "
                f"source={source_id or locator} ok={bool(ensure_result.get('ok'))} "
                f"path={next_row.get('git_checkout_path') or '-'}"
            ),
            source="skills",
        )

    def _schedule_git_checkout_prewarm(self, source_rows: list[dict[str, Any]] | None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        for row in self._iter_git_checkout_prewarm_candidates(source_rows):
            prewarm_key = self._git_checkout_prewarm_key(row)
            if not prewarm_key:
                continue
            existing_task = self._git_checkout_prewarm_tasks.get(prewarm_key)
            if existing_task and not existing_task.done():
                continue

            task = loop.create_task(
                self._run_git_checkout_prewarm(row),
                name=f"onesync-git-checkout-prewarm-{_normalize_inventory_id(prewarm_key, default='source')}",
            )
            self._git_checkout_prewarm_tasks[prewarm_key] = task

            def _cleanup(done_task: asyncio.Task, *, task_key: str = prewarm_key) -> None:
                current_task = self._git_checkout_prewarm_tasks.get(task_key)
                if current_task is done_task:
                    self._git_checkout_prewarm_tasks.pop(task_key, None)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pragma: no cover - defensive branch
                    logger.warning("[onesync] git checkout prewarm task failed: %s", exc)

            task.add_done_callback(_cleanup)

    def _resolve_source_git_checkout_spec(self, source_row: dict[str, Any] | None) -> dict[str, Any]:
        row = source_row if isinstance(source_row, dict) else {}
        candidates = [
            row.get("locator"),
            row.get("provenance_origin_ref"),
            row.get("install_ref"),
        ]
        source_subpath = str(row.get("source_subpath") or "").strip().strip("/")
        for candidate in candidates:
            locator, subpath = self._split_git_locator_subpath(candidate)
            if not locator or not self._looks_like_git_locator_text(locator):
                continue
            return {
                "locator": locator,
                "subpath": subpath or source_subpath,
            }
        return {"locator": "", "subpath": source_subpath}

    def _managed_git_checkout_dir_for_locator(self, locator: str) -> Path:
        normalized_locator = str(locator or "").strip()
        repo_basename = normalized_locator.rstrip("/").split("/")[-1].strip()
        if repo_basename.endswith(".git"):
            repo_basename = repo_basename[:-4]
        slug = _normalize_inventory_id(repo_basename, default="repo")
        digest = hashlib.sha1(normalized_locator.encode("utf-8")).hexdigest()[:12]
        return self.skills_git_repos_dir / f"{slug}-{digest}"

    def _candidate_git_clone_locators(self, locator: str) -> list[str]:
        normalized_locator = str(locator or "").strip()
        if not normalized_locator:
            return []
        candidates: list[str] = []
        if normalized_locator.startswith("https://github.com/"):
            ordered_prefixes = [
                prefix
                for prefix in DEFAULT_GITHUB_MIRROR_PREFIXES
                if prefix
            ] + [""]
            for prefix in ordered_prefixes:
                candidate = f"{prefix}{normalized_locator}" if prefix else normalized_locator
                if candidate not in candidates:
                    candidates.append(candidate)
            return candidates
        return [normalized_locator]

    def _ensure_source_git_checkout(
        self,
        source_row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = source_row if isinstance(source_row, dict) else {}
        source_path = str(row.get("source_path") or "").strip()
        if source_path and self._path_is_git_worktree(source_path):
            return {
                "ok": True,
                "checkout_path": source_path,
                "managed": False,
                "message": "using existing git checkout from source_path",
            }

        spec = self._resolve_source_git_checkout_spec(row)
        locator = str(spec.get("locator") or "").strip()
        if not locator:
            return {
                "ok": False,
                "checkout_path": "",
                "managed": False,
                "message": "git repo locator is unavailable",
                "error_code": "git_repo_locator_missing",
            }

        checkout_dir = self._managed_git_checkout_dir_for_locator(locator)
        self.skills_git_repos_dir.mkdir(parents=True, exist_ok=True)
        if checkout_dir.exists() and not self._path_is_git_worktree(checkout_dir):
            shutil.rmtree(checkout_dir, ignore_errors=True)

        clone_locator_used = ""
        if not checkout_dir.exists():
            clone_errors: list[str] = []
            clone_candidates = self._candidate_git_clone_locators(locator)
            ok_clone = False
            clone_output = ""
            for clone_locator in clone_candidates:
                ok_clone, clone_output = self._run_git_probe(
                    [
                        "clone",
                        "--depth",
                        "1",
                        "--filter=blob:none",
                        "--single-branch",
                        clone_locator,
                        str(checkout_dir),
                    ],
                    timeout_s=60,
                )
                if ok_clone:
                    clone_locator_used = clone_locator
                    break
                clone_errors.append(f"{clone_locator}: {clone_output}")
                if checkout_dir.exists() and not self._path_is_git_worktree(checkout_dir):
                    shutil.rmtree(checkout_dir, ignore_errors=True)
            if not ok_clone:
                return {
                    "ok": False,
                    "checkout_path": "",
                    "managed": True,
                    "message": f"git checkout bootstrap failed for {locator}: {' | '.join(clone_errors)}",
                    "error_code": "git_checkout_clone_failed",
                }
        elif not self._path_is_git_worktree(checkout_dir):
            return {
                "ok": False,
                "checkout_path": "",
                "managed": True,
                "message": f"managed checkout path is not a git worktree: {checkout_dir}",
                "error_code": "git_checkout_invalid",
            }

        remote_result = self._align_managed_git_checkout_remote(
            checkout_dir,
            locator,
            preferred_locator=clone_locator_used,
        )
        if not remote_result.get("ok"):
            return {
                "ok": False,
                "checkout_path": "",
                "managed": True,
                "message": str(remote_result.get("message") or "").strip() or f"git remote alignment failed for {checkout_dir}",
                "error_code": str(remote_result.get("error_code") or "git_remote_align_failed").strip(),
            }

        return {
            "ok": True,
            "checkout_path": str(checkout_dir),
            "managed": True,
            "message": f"managed git checkout ready: {checkout_dir}",
        }

    def _augment_source_row_with_git_checkout(
        self,
        source_row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = dict(source_row) if isinstance(source_row, dict) else {}
        if not row:
            return {}

        existing_checkout_path = str(row.get("git_checkout_path") or "").strip()
        if existing_checkout_path and self._path_is_git_worktree(existing_checkout_path):
            spec = self._resolve_source_git_checkout_spec(row)
            locator = str(spec.get("locator") or "").strip()
            if locator and _to_bool(row.get("git_checkout_managed", False), False):
                align_result = self._align_managed_git_checkout_remote(existing_checkout_path, locator)
                if not align_result.get("ok"):
                    row["git_checkout_error"] = str(align_result.get("message") or "").strip()
                    return row
            row["git_checkout_path"] = existing_checkout_path
            row["git_checkout_managed"] = _to_bool(row.get("git_checkout_managed", False), False)
            row["git_checkout_error"] = ""
            return row

        spec = self._resolve_source_git_checkout_spec(row)
        locator = str(spec.get("locator") or "").strip()
        manager = str(
            row.get("install_manager")
            or row.get("managed_by")
            or row.get("registry_package_manager")
            or ""
        ).strip().lower()
        if not locator or manager not in {"git", "github"}:
            return row

        ensure_result = self._ensure_source_git_checkout(row)
        if ensure_result.get("ok"):
            row["git_checkout_path"] = str(ensure_result.get("checkout_path") or "").strip()
            row["git_checkout_managed"] = _to_bool(ensure_result.get("managed", False), False)
            row["git_checkout_error"] = ""
        else:
            row["git_checkout_path"] = ""
            row["git_checkout_managed"] = True
            row["git_checkout_error"] = str(ensure_result.get("message") or "").strip()
        return row

    def _augment_source_rows_with_git_checkouts(
        self,
        source_rows: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        return [
            self._augment_source_row_with_git_checkout(item)
            for item in (source_rows or [])
            if isinstance(item, dict)
        ]

    def _persist_skills_state_files(self, skills_snapshot: dict[str, Any]) -> None:
        registry = self._save_skills_registry(skills_snapshot.get("registry", {}))
        install_atom_registry = self._save_install_atom_registry(skills_snapshot.get("install_atom_registry", {}))
        manifest = self._save_skills_manifest(skills_snapshot.get("manifest", {}))
        lock = self._save_skills_lock(skills_snapshot.get("lock", {}))
        _ = install_atom_registry
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self.skills_sources_dir.mkdir(parents=True, exist_ok=True)
        self.skills_generated_dir.mkdir(parents=True, exist_ok=True)

        for existing in self.skills_sources_dir.glob("*.json"):
            try:
                existing.unlink()
            except Exception:
                continue
        for existing in self.skills_generated_dir.glob("*.json"):
            try:
                existing.unlink()
            except Exception:
                continue

        for item in skills_snapshot.get("source_rows", []):
            if not isinstance(item, dict):
                continue
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            if not source_id:
                continue
            self._write_json_file(self.skills_sources_dir / f"{source_id}.json", item)

        for item in skills_snapshot.get("deploy_rows", []):
            if not isinstance(item, dict):
                continue
            target_id = _normalize_inventory_id(item.get("target_id", ""), default="")
            if not target_id:
                continue
            self._write_json_file(self.skills_generated_dir / f"{target_id}.json", item)

    def _augment_skills_runtime_health(self, skills_snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(skills_snapshot, dict):
            return {}

        runtime_health = build_skills_runtime_health(
            skills_snapshot,
            current_bindings=self.config.get("skill_bindings", []),
            manifest_path=self.skills_manifest_path,
            lock_path=self.skills_lock_path,
            sources_dir=self.skills_sources_dir,
            generated_dir=self.skills_generated_dir,
        )

        counts = skills_snapshot.get("counts", {})
        if not isinstance(counts, dict):
            counts = {}
            skills_snapshot["counts"] = counts
        counts.update(runtime_health.get("counts", {}))

        doctor = skills_snapshot.get("doctor", {})
        if not isinstance(doctor, dict):
            doctor = {}
            skills_snapshot["doctor"] = doctor
        doctor["state_health"] = runtime_health.get("state_health", {})
        doctor["projection_health"] = runtime_health.get("projection_health", {})
        doctor["astrbot_runtime_health"] = runtime_health.get("astrbot_runtime_health", {})

        plan_health = self._compute_collection_group_plan_contract_health(skills_snapshot)
        counts["collection_group_plan_checked_total"] = int(plan_health.get("checked_total", 0))
        counts["collection_group_plan_contract_drift_total"] = int(plan_health.get("drift_total", 0))
        doctor["plan_contract_health"] = {
            "checked_total": int(plan_health.get("checked_total", 0)),
            "drift_total": int(plan_health.get("drift_total", 0)),
        }
        skills_snapshot["collection_group_plan_contract_rows"] = [
            item
            for item in plan_health.get("drift_rows", [])
            if isinstance(item, dict)
        ]

        warnings = _dedupe_keep_order(
            [
                str(item or "").strip()
                for item in (
                    list(skills_snapshot.get("warnings", []))
                    + list(runtime_health.get("warnings", []))
                    + list(plan_health.get("warnings", []))
                )
                if str(item or "").strip()
            ],
        )
        skills_snapshot["warnings"] = warnings
        doctor["warnings"] = warnings
        doctor["warning_count"] = len(warnings)
        doctor["ok"] = not warnings
        return skills_snapshot

    def _collection_group_plan_contract_issues(self, plan: dict[str, Any] | None) -> list[str]:
        payload = plan if isinstance(plan, dict) else {}
        mode = str(payload.get("update_mode") or "").strip().lower()
        actionable = _to_bool(payload.get("actionable", False), False)
        supported_install_unit_total = _to_int(payload.get("supported_install_unit_total", 0), 0, 0)
        unsupported_install_unit_total = _to_int(payload.get("unsupported_install_unit_total", 0), 0, 0)
        command_install_unit_total = _to_int(payload.get("command_install_unit_total", 0), 0, 0)
        source_sync_install_unit_total = _to_int(payload.get("source_sync_install_unit_total", 0), 0, 0)
        actionable_install_unit_ids = _to_str_list(payload.get("actionable_install_unit_ids", []))
        skipped_install_unit_ids = _to_str_list(payload.get("skipped_install_unit_ids", []))
        issues: list[str] = []

        valid_modes = {"command", "source_sync", "partial", "manual_only"}
        if mode not in valid_modes:
            issues.append(f"invalid_update_mode:{mode or 'empty'}")

        if mode == "manual_only":
            if actionable:
                issues.append("manual_only_must_not_be_actionable")
            if supported_install_unit_total > 0:
                issues.append("manual_only_must_have_zero_supported_units")
        elif mode in {"command", "source_sync", "partial"}:
            if not actionable:
                issues.append("non_manual_mode_must_be_actionable")

        if mode == "partial" and (
            supported_install_unit_total <= 0 or unsupported_install_unit_total <= 0
        ):
            issues.append("partial_mode_requires_supported_and_unsupported_units")
        if mode == "command" and command_install_unit_total <= 0:
            issues.append("command_mode_requires_command_install_units")
        if mode == "source_sync":
            if source_sync_install_unit_total <= 0:
                issues.append("source_sync_mode_requires_source_sync_install_units")
            if command_install_unit_total > 0:
                issues.append("source_sync_mode_must_not_include_command_install_units")

        if supported_install_unit_total != len(actionable_install_unit_ids):
            issues.append("supported_install_unit_total_mismatch_actionable_install_unit_ids")
        if unsupported_install_unit_total != len(skipped_install_unit_ids):
            issues.append("unsupported_install_unit_total_mismatch_skipped_install_unit_ids")
        return issues

    def _compute_collection_group_plan_contract_health(self, skills_snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else {}
        collection_group_rows = [
            item
            for item in snapshot.get("collection_group_rows", [])
            if isinstance(item, dict)
        ]
        drift_rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        checked_total = 0

        for collection_group in collection_group_rows:
            collection_group_id = str(collection_group.get("collection_group_id") or "").strip()
            if not collection_group_id:
                continue
            checked_total += 1

            detail = build_collection_group_detail_payload(snapshot, collection_group_id)
            if not detail.get("ok"):
                drift_rows.append(
                    {
                        "collection_group_id": collection_group_id,
                        "issues": ["detail_payload_unavailable"],
                    },
                )
                warnings.append(
                    f"plan/execute contract drift: {collection_group_id} (detail_payload_unavailable)",
                )
                continue

            effective_plan = self._build_effective_collection_group_update_plan(
                collection_group=detail.get("collection_group", {}),
                install_unit_rows=detail.get("install_unit_rows", []),
                source_rows=detail.get("source_rows", []),
            )
            issues = self._collection_group_plan_contract_issues(effective_plan)
            if not issues:
                continue
            drift_rows.append(
                {
                    "collection_group_id": collection_group_id,
                    "update_mode": str(effective_plan.get("update_mode") or "").strip(),
                    "issues": issues,
                },
            )
            warnings.append(
                f"plan/execute contract drift: {collection_group_id} ({issues[0]})",
            )

        return {
            "checked_total": checked_total,
            "drift_total": len(drift_rows),
            "drift_rows": drift_rows,
            "warnings": warnings,
        }

    def _refresh_skills_snapshot(
        self,
        inventory_snapshot: dict[str, Any] | None = None,
        *,
        saved_manifest: dict[str, Any] | None = None,
        saved_registry: dict[str, Any] | None = None,
        saved_lock: dict[str, Any] | None = None,
        saved_install_atom_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            skills_snapshot = self._build_skills_snapshot(
                inventory_snapshot,
                saved_manifest=saved_manifest,
                saved_registry=saved_registry,
                saved_lock=saved_lock,
                saved_install_atom_registry=saved_install_atom_registry,
            )
        except Exception as exc:
            logger.error("[onesync] skills snapshot build failed: %s", exc)
            skills_snapshot = {
                "ok": False,
                "generated_at": _now_iso(),
                "registry": {},
                "install_atom_registry": {},
                "manifest": {},
                "lock": {},
                "host_rows": [],
                "software_hosts": [],
                "source_rows": [],
                "deploy_rows": [],
                "doctor": {"ok": False, "warning_count": 1, "warnings": [str(exc)]},
                "counts": {},
                "warnings": [str(exc)],
                "software_rows": [],
                "skill_rows": [],
                "binding_rows": [],
                "binding_map": {},
                "binding_map_by_scope": {},
                "compatibility": {},
            }

        skills_state = self._skills_state()
        skills_state["last_overview"] = skills_snapshot
        skills_state["last_synced_at"] = skills_snapshot.get("generated_at", _now_iso())
        try:
            self._persist_skills_state_files(skills_snapshot)
        except Exception as exc:
            logger.error("[onesync] persist skills state files failed: %s", exc)
            warnings = skills_snapshot.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append(f"persist skills files failed: {exc}")
        return skills_snapshot

    def _refresh_inventory_snapshot(self, *, sync_skills: bool = True) -> dict[str, Any]:
        saved_manifest = self._load_saved_skills_manifest()
        saved_registry = self._load_saved_skills_registry()
        saved_lock = self._load_saved_skills_lock()
        saved_install_atom_registry = self._load_saved_install_atom_registry()
        try:
            snapshot = self._build_inventory_snapshot()
        except Exception as exc:
            logger.error("[onesync] inventory snapshot build failed: %s", exc)
            snapshot = {
                "ok": False,
                "generated_at": _now_iso(),
                "software_rows": [],
                "skill_rows": [],
                "binding_rows": [],
                "binding_map": {},
                "binding_map_by_scope": {},
                "compatibility": {},
                "counts": {},
                "warnings": [str(exc)],
            }
        inventory_state = self._inventory_state()
        inventory_state["last_snapshot"] = snapshot
        inventory_state["last_scanned_at"] = snapshot.get("generated_at", _now_iso())
        if sync_skills:
            skills_snapshot = self._refresh_skills_snapshot(
                inventory_snapshot=snapshot,
                saved_manifest=saved_manifest,
                saved_registry=saved_registry,
                saved_lock=saved_lock,
                saved_install_atom_registry=saved_install_atom_registry,
            )
            manifest = skills_snapshot.get("manifest", {})
            registry = skills_snapshot.get("registry", {})
            lock = skills_snapshot.get("lock", {})
            install_atom_registry = skills_snapshot.get("install_atom_registry", {})
            if isinstance(registry, dict):
                self._save_skills_registry(registry)
            if isinstance(install_atom_registry, dict):
                self._save_install_atom_registry(install_atom_registry)
            if isinstance(manifest, dict) and manifest:
                self._save_skills_manifest(manifest)
            if isinstance(lock, dict):
                self._save_skills_lock(lock)
            if isinstance(manifest, dict) and manifest:
                bindings_changed = self._sync_skill_bindings_projection(manifest)
                if bindings_changed:
                    snapshot = project_inventory_snapshot_bindings_from_manifest(snapshot, manifest)
                    inventory_state["last_snapshot"] = snapshot
                    inventory_state["last_scanned_at"] = snapshot.get("generated_at", _now_iso())
            last_overview = self._skills_state().get("last_overview", {})
            if isinstance(last_overview, dict) and last_overview:
                self._augment_skills_runtime_health(last_overview)
                self._skills_state()["last_overview"] = last_overview
                self._schedule_git_checkout_prewarm(last_overview.get("source_rows", []))
        return snapshot

    def webui_get_inventory_payload(self) -> dict[str, Any]:
        snapshot = self._inventory_state().get("last_snapshot", {})
        if isinstance(snapshot, dict) and snapshot:
            return snapshot
        return self._refresh_inventory_snapshot()

    def webui_get_skills_payload(self) -> dict[str, Any]:
        skills_state = self._skills_state()
        snapshot = skills_state.get("last_overview", {})
        if not isinstance(snapshot, dict) or not snapshot:
            self._refresh_inventory_snapshot(sync_skills=True)
            snapshot = skills_state.get("last_overview", {})
        if isinstance(snapshot, dict) and snapshot:
            self._augment_skills_runtime_health(snapshot)
            skills_state["last_overview"] = snapshot
        return snapshot if isinstance(snapshot, dict) else {}

    @staticmethod
    def _redact_sync_auth_header(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if ":" not in raw:
            return raw
        header_name = raw.split(":", 1)[0].strip()
        if not header_name:
            return "<redacted>"
        return f"{header_name}: <redacted>"

    def webui_redact_sensitive_payload(self, payload: Any) -> Any:
        def _walk(value: Any) -> Any:
            if isinstance(value, list):
                return [_walk(item) for item in value]
            if isinstance(value, tuple):
                return [_walk(item) for item in value]
            if isinstance(value, dict):
                redacted: dict[str, Any] = {}
                for key, item in value.items():
                    normalized_key = str(key or "").strip()
                    if normalized_key == "sync_auth_token":
                        token_text = str(item or "").strip()
                        redacted[normalized_key] = ""
                        redacted["sync_auth_token_configured"] = bool(token_text)
                        continue
                    if normalized_key == "sync_auth_header":
                        header_text = str(item or "").strip()
                        redacted[normalized_key] = self._redact_sync_auth_header(header_text)
                        redacted["sync_auth_header_configured"] = bool(header_text)
                        continue
                    redacted[normalized_key] = _walk(item)
                return redacted
            return value

        return _walk(payload)

    def webui_get_skills_registry_payload(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        registry = snapshot.get("registry", {})
        install_atom_registry = snapshot.get("install_atom_registry", {})
        items = registry.get("sources", []) if isinstance(registry, dict) else []
        install_atoms = (
            install_atom_registry.get("install_atoms", [])
            if isinstance(install_atom_registry, dict)
            else []
        )
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "counts": {
                "registry_total": len(items),
                "install_atom_total": len(install_atoms) if isinstance(install_atoms, list) else 0,
            },
            "items": items,
            "warnings": snapshot.get("warnings", []),
        }

    def webui_get_install_atom_registry_payload(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        install_atom_registry = snapshot.get("install_atom_registry", {})
        if not isinstance(install_atom_registry, dict):
            install_atom_registry = {}
        items = install_atom_registry.get("install_atoms", [])
        counts = install_atom_registry.get("counts", {})
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "counts": counts if isinstance(counts, dict) else {},
            "items": items if isinstance(items, list) else [],
            "warnings": snapshot.get("warnings", []),
        }

    @staticmethod
    def _normalize_install_atom_refresh_strategy(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "high_confidence":
            return "high_confidence"
        return "all"

    @staticmethod
    def _install_atom_is_actionable(item: dict[str, Any] | None) -> bool:
        row = item if isinstance(item, dict) else {}
        status = str(row.get("resolution_status") or "unresolved").strip().lower()
        if status == "resolved":
            return False
        note_kind = str(row.get("provenance_note_kind") or "").strip().lower()
        resolver_path = str(row.get("resolver_path") or "").strip().lower()
        return note_kind != "legacy_root_only" and resolver_path != "aggregation:fallback_single"

    @staticmethod
    def _install_atom_resolution_rank(value: Any) -> int:
        normalized = str(value or "unresolved").strip().lower()
        if normalized == "resolved":
            return 2
        if normalized == "partial":
            return 1
        return 0

    @staticmethod
    def _install_atom_evidence_rank(value: Any) -> int:
        normalized = str(value or "unresolved").strip().lower()
        if normalized == "explicit":
            return 3
        if normalized == "strong":
            return 2
        if normalized == "heuristic":
            return 1
        return 0

    def _install_atom_row_by_install_unit_id(
        self,
        install_atom_registry: dict[str, Any] | None,
        install_unit_id: str,
    ) -> dict[str, Any] | None:
        normalized_install_unit_id = str(install_unit_id or "").strip()
        if not normalized_install_unit_id:
            return None
        registry = normalize_install_atom_registry(install_atom_registry or {})
        for item in registry.get("install_atoms", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("install_unit_id") or "").strip() == normalized_install_unit_id:
                return item
        return None

    def _install_atom_refresh_improved(
        self,
        before_row: dict[str, Any] | None,
        after_row: dict[str, Any] | None,
    ) -> bool:
        before = before_row if isinstance(before_row, dict) else {}
        after = after_row if isinstance(after_row, dict) else {}
        if self._install_atom_resolution_rank(after.get("resolution_status")) > self._install_atom_resolution_rank(
            before.get("resolution_status"),
        ):
            return True
        if self._install_atom_evidence_rank(after.get("evidence_level")) > self._install_atom_evidence_rank(
            before.get("evidence_level"),
        ):
            return True
        before_resolver = str(before.get("resolver_path") or "").strip()
        after_resolver = str(after.get("resolver_path") or "").strip()
        return before_resolver != after_resolver and bool(after_resolver) and after_resolver != "aggregation:fallback_single"

    def _build_install_atom_refresh_candidates(
        self,
        skills_snapshot: dict[str, Any] | None,
        *,
        strategy: str = "all",
    ) -> dict[str, Any]:
        snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else {}
        registry = normalize_install_atom_registry(snapshot.get("install_atom_registry", {}))
        normalized_strategy = self._normalize_install_atom_refresh_strategy(strategy)
        install_atoms = [
            item
            for item in registry.get("install_atoms", [])
            if isinstance(item, dict)
        ]
        unresolved_rows = [
            item
            for item in install_atoms
            if str(item.get("resolution_status") or "unresolved").strip().lower() != "resolved"
        ]
        actionable_rows = [
            item
            for item in unresolved_rows
            if self._install_atom_is_actionable(item)
        ]
        if normalized_strategy == "high_confidence":
            actionable_rows = [
                item
                for item in actionable_rows
                if str(item.get("evidence_level") or "unresolved").strip().lower() in {"explicit", "strong"}
            ]
        rows_by_install_unit_id: dict[str, list[dict[str, Any]]] = {}
        install_unit_ids: list[str] = []
        for item in actionable_rows:
            install_unit_id = str(item.get("install_unit_id") or "").strip()
            if not install_unit_id:
                continue
            if install_unit_id not in rows_by_install_unit_id:
                rows_by_install_unit_id[install_unit_id] = []
                install_unit_ids.append(install_unit_id)
            rows_by_install_unit_id[install_unit_id].append(item)
        return {
            "strategy": normalized_strategy,
            "rows": actionable_rows,
            "install_unit_ids": install_unit_ids,
            "rows_by_install_unit_id": rows_by_install_unit_id,
        }

    @staticmethod
    def _build_install_atom_failure_groups(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        failed_items = [item for item in (items or []) if isinstance(item, dict)]
        failure_group_map: dict[str, dict[str, Any]] = {}
        for item in failed_items:
            resolver_path = str(item.get("resolverPath") or "-").strip() or "-"
            evidence_level = str(item.get("evidenceLevel") or "unresolved").strip().lower() or "unresolved"
            key = f"{resolver_path}::{evidence_level}"
            current = failure_group_map.get(key)
            if not isinstance(current, dict):
                current = {
                    "resolverPath": resolver_path,
                    "evidenceLevel": evidence_level,
                    "installUnitIds": [],
                    "count": 0,
                }
                failure_group_map[key] = current
            install_unit_id = str(item.get("installUnitId") or "").strip()
            if install_unit_id and install_unit_id not in current["installUnitIds"]:
                current["installUnitIds"].append(install_unit_id)
                current["count"] = len(current["installUnitIds"])
        return sorted(
            failure_group_map.values(),
            key=lambda item: (
                -int(item.get("count", 0) or 0),
                str(item.get("resolverPath") or ""),
                str(item.get("evidenceLevel") or ""),
            ),
        )

    def webui_get_skills_audit_payload(
        self,
        *,
        limit: int = 50,
        action: str = "",
        source_id: str = "",
    ) -> dict[str, Any]:
        normalized_limit = _to_int(limit, 50, 1)
        if normalized_limit > 500:
            normalized_limit = 500
        action_keyword = str(action or "").strip().lower()
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        events: deque[dict[str, Any]] = deque(maxlen=normalized_limit)
        warnings: list[str] = []

        if self.skills_audit_path.exists():
            try:
                with self.skills_audit_path.open("r", encoding="utf-8") as f:
                    for line_no, raw_line in enumerate(f, start=1):
                        line = str(raw_line or "").strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(parsed, dict):
                            continue
                        event_action = str(parsed.get("action") or "").strip()
                        event_source_id = str(parsed.get("source_id") or "").strip()
                        event_id = str(parsed.get("event_id") or "").strip()
                        if not event_id:
                            event_id = f"legacy_{line_no}"
                        normalized_event_source_id = _normalize_inventory_id(event_source_id, default="")
                        if action_keyword and action_keyword not in event_action.lower():
                            continue
                        if normalized_source_id and normalized_event_source_id != normalized_source_id:
                            continue
                        payload = parsed.get("payload", {})
                        if not isinstance(payload, dict):
                            payload = {}
                        events.append(
                            {
                                "event_id": event_id,
                                "timestamp": str(parsed.get("timestamp") or "").strip(),
                                "action": event_action,
                                "source_id": event_source_id,
                                "payload": payload,
                            },
                        )
            except Exception as exc:
                logger.error("[onesync] read skills audit failed: %s", exc)
                warnings.append(f"failed to read skills audit: {exc}")

        items = list(events)
        items.reverse()
        return {
            "ok": True,
            "generated_at": _now_iso(),
            "counts": {
                "total": len(items),
            },
            "items": items,
            "warnings": warnings,
        }

    def webui_get_skills_hosts_payload(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        items = snapshot.get("host_rows", [])
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "counts": {
                "host_total": len(items) if isinstance(items, list) else 0,
            },
            "items": items if isinstance(items, list) else [],
            "warnings": snapshot.get("warnings", []),
        }

    def webui_get_astrbot_neo_sources_payload(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        items = [
            item
            for item in snapshot.get("astrbot_neo_source_rows", [])
            if isinstance(item, dict)
        ]
        ready_total = sum(1 for item in items if str(item.get("status", "")).strip().lower() == "ready")
        missing_total = sum(1 for item in items if str(item.get("status", "")).strip().lower() == "missing")
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "counts": {
                "source_total": len(items),
                "ready_total": ready_total,
                "missing_total": missing_total,
            },
            "items": items,
            "warnings": snapshot.get("warnings", []),
        }

    def _build_astrbot_neo_source_detail_contract(self, source_row: dict[str, Any]) -> dict[str, Any]:
        source = source_row if isinstance(source_row, dict) else {}
        skill_key = str(source.get("astrneo_skill_key") or "").strip()
        release_id = str(source.get("astrneo_release_id") or "").strip()
        candidate_id = str(source.get("astrneo_candidate_id") or "").strip()
        return {
            "neo_state": {
                "host_id": str(source.get("astrneo_host_id") or "").strip(),
                "skill_key": skill_key,
                "local_skill_name": str(source.get("astrneo_skill_name") or "").strip(),
                "release_id": release_id,
                "candidate_id": candidate_id,
                "payload_ref": str(source.get("astrneo_payload_ref") or "").strip(),
                "updated_at": str(source.get("astrneo_updated_at") or "").strip(),
            },
            "neo_capabilities": {
                "sync_supported": bool(skill_key),
                "promote_supported": bool(skill_key and candidate_id),
                "rollback_supported": bool(skill_key and release_id),
            },
            "neo_defaults": {
                "candidate_id": candidate_id,
                "release_id": release_id,
                "stage": "stable",
                "sync_to_local": True,
                "require_stable": True,
            },
        }

    def _lookup_astrbot_neo_source_payload(self, source_id: str) -> dict[str, Any]:
        normalized_source_id = str(source_id or "").strip()
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        snapshot = self.webui_get_skills_payload()
        rows = [
            item
            for item in snapshot.get("astrbot_neo_source_rows", [])
            if isinstance(item, dict)
        ]
        source_row = next(
            (
                item
                for item in rows
                if str(item.get("source_id") or "").strip() == normalized_source_id
            ),
            None,
        )
        if not source_row:
            return {"ok": False, "message": f"astrbot neo source not found: {normalized_source_id}"}
        detail_contract = self._build_astrbot_neo_source_detail_contract(source_row)
        return {
            "ok": True,
            "generated_at": snapshot.get("generated_at"),
            "source": source_row,
            **detail_contract,
            "warnings": snapshot.get("warnings", []),
        }

    @staticmethod
    def _summarize_astrbot_neo_release_rows(items: list[Any] | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in items or []:
            payload = _to_jsonable_like(item)
            if not isinstance(payload, dict):
                continue
            stage_raw = payload.get("stage")
            stage_value = getattr(stage_raw, "value", stage_raw)
            rows.append(
                {
                    "id": str(payload.get("id") or "").strip(),
                    "skill_key": str(payload.get("skill_key") or "").strip(),
                    "candidate_id": str(payload.get("candidate_id") or "").strip(),
                    "stage": str(stage_value or "").strip().lower(),
                    "is_active": _to_bool(payload.get("is_active"), _to_bool(payload.get("active"), False)),
                    "created_at": str(payload.get("created_at") or "").strip(),
                    "updated_at": str(payload.get("updated_at") or "").strip(),
                }
            )
        return [item for item in rows if item.get("id")]

    @staticmethod
    def _sort_astrbot_neo_rows_by_recency(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        rows = [item for item in items or [] if isinstance(item, dict)]
        return sorted(
            rows,
            key=lambda item: (
                _parse_iso(str(item.get("updated_at") or "").strip())
                or _parse_iso(str(item.get("created_at") or "").strip())
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )

    @staticmethod
    def _summarize_astrbot_neo_candidate_rows(items: list[Any] | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in items or []:
            payload = _to_jsonable_like(item)
            if not isinstance(payload, dict):
                continue
            status_raw = payload.get("status")
            status_value = getattr(status_raw, "value", status_raw)
            rows.append(
                {
                    "id": str(payload.get("id") or "").strip(),
                    "skill_key": str(payload.get("skill_key") or "").strip(),
                    "status": str(status_value or "").strip().lower(),
                    "payload_ref": str(payload.get("payload_ref") or "").strip(),
                    "created_at": str(payload.get("created_at") or "").strip(),
                    "updated_at": str(payload.get("updated_at") or "").strip(),
                }
            )
        return [item for item in rows if item.get("id")]

    async def _load_astrbot_neo_remote_state(self, source_row: dict[str, Any]) -> dict[str, Any]:
        source = source_row if isinstance(source_row, dict) else {}
        skill_key = str(source.get("astrneo_skill_key") or "").strip()
        remote_state: dict[str, Any] = {
            "configured": False,
            "endpoint": "",
            "access_token_discovered": False,
            "fetched_at": _now_iso(),
            "reason_code": "",
            "message": "",
            "current": {
                "active_stable_release_id": "",
                "active_canary_release_id": "",
                "latest_release_id": str(source.get("astrneo_release_id") or "").strip(),
                "latest_candidate_id": str(source.get("astrneo_candidate_id") or "").strip(),
                "latest_candidate_status": "",
            },
            "releases": {"total": 0, "items": []},
            "candidates": {"total": 0, "items": []},
            "warnings": [],
        }
        if not skill_key:
            remote_state["reason_code"] = "invalid_neo_source"
            remote_state["message"] = "astrbot neo source missing skill key"
            return remote_state

        client_config = self._resolve_astrbot_neo_client_config()
        if not client_config.get("ok"):
            remote_state["reason_code"] = str(client_config.get("reason_code") or "").strip()
            remote_state["message"] = str(client_config.get("message") or "").strip()
            return remote_state

        remote_state["configured"] = True
        remote_state["endpoint"] = str(client_config.get("endpoint") or "").strip()
        remote_state["access_token_discovered"] = bool(client_config.get("access_token_discovered"))

        try:
            from shipyard_neo import BayClient
        except Exception as exc:
            remote_state["reason_code"] = "neo_client_unavailable"
            remote_state["message"] = f"astrbot neo client unavailable: {exc}"
            return remote_state

        try:
            async with BayClient(
                endpoint_url=str(client_config.get("endpoint") or ""),
                access_token=str(client_config.get("access_token") or ""),
            ) as client:
                release_payload = _to_jsonable_like(
                    await client.skills.list_releases(skill_key=skill_key, limit=5, offset=0)
                )
                candidate_payload = _to_jsonable_like(
                    await client.skills.list_candidates(skill_key=skill_key, limit=5, offset=0)
                )
        except Exception as exc:
            remote_state["reason_code"] = "neo_remote_state_failed"
            remote_state["message"] = f"astrbot neo remote state fetch failed: {exc}"
            return remote_state

        release_items = self._sort_astrbot_neo_rows_by_recency(
            self._summarize_astrbot_neo_release_rows(
                release_payload.get("items", []) if isinstance(release_payload, dict) else []
            )
        )
        candidate_items = self._sort_astrbot_neo_rows_by_recency(
            self._summarize_astrbot_neo_candidate_rows(
                candidate_payload.get("items", []) if isinstance(candidate_payload, dict) else []
            )
        )
        remote_state["releases"] = {
            "total": int((release_payload.get("total", len(release_items)) if isinstance(release_payload, dict) else len(release_items)) or 0),
            "items": release_items,
        }
        remote_state["candidates"] = {
            "total": int((candidate_payload.get("total", len(candidate_items)) if isinstance(candidate_payload, dict) else len(candidate_items)) or 0),
            "items": candidate_items,
        }

        active_stable = next(
            (item for item in release_items if str(item.get("stage") or "") == "stable" and _to_bool(item.get("is_active"), False)),
            None,
        )
        active_canary = next(
            (item for item in release_items if str(item.get("stage") or "") == "canary" and _to_bool(item.get("is_active"), False)),
            None,
        )
        latest_release = release_items[0] if release_items else {}
        latest_candidate = candidate_items[0] if candidate_items else {}
        remote_state["current"] = {
            "active_stable_release_id": str((active_stable or {}).get("id") or "").strip(),
            "active_canary_release_id": str((active_canary or {}).get("id") or "").strip(),
            "latest_release_id": str((latest_release or {}).get("id") or remote_state["current"].get("latest_release_id") or "").strip(),
            "latest_candidate_id": str((latest_candidate or {}).get("id") or remote_state["current"].get("latest_candidate_id") or "").strip(),
            "latest_candidate_status": str((latest_candidate or {}).get("status") or "").strip(),
        }
        return remote_state

    def _build_astrbot_neo_activity_payload(self, source_id: str, *, limit: int = 8) -> dict[str, Any]:
        audit_payload = self.webui_get_skills_audit_payload(
            limit=limit,
            action="astrbot_neo_source",
            source_id=source_id,
        )
        return {
            "counts": audit_payload.get("counts", {"total": 0}),
            "items": audit_payload.get("items", []),
            "warnings": audit_payload.get("warnings", []),
        }

    def webui_get_astrbot_neo_source_payload(self, source_id: str) -> Any:
        async def _load() -> dict[str, Any]:
            detail = self._lookup_astrbot_neo_source_payload(source_id)
            if not detail.get("ok"):
                return detail
            source_row = detail.get("source", {}) if isinstance(detail.get("source"), dict) else {}
            normalized_source_id = str(source_row.get("source_id") or source_id or "").strip()
            remote_state = await self._load_astrbot_neo_remote_state(source_row)
            detail["neo_remote_state"] = remote_state
            detail["neo_activity"] = self._build_astrbot_neo_activity_payload(normalized_source_id)
            skill_key = str(source_row.get("astrneo_skill_key") or "").strip()
            remote_current = remote_state.get("current", {}) if isinstance(remote_state.get("current"), dict) else {}
            defaults = detail.get("neo_defaults", {}) if isinstance(detail.get("neo_defaults"), dict) else {}
            capabilities = detail.get("neo_capabilities", {}) if isinstance(detail.get("neo_capabilities"), dict) else {}
            effective_candidate_id = str(
                remote_current.get("latest_candidate_id")
                or defaults.get("candidate_id")
                or ""
            ).strip()
            effective_release_id = str(
                remote_current.get("active_stable_release_id")
                or remote_current.get("latest_release_id")
                or defaults.get("release_id")
                or ""
            ).strip()
            detail["neo_defaults"] = {
                **defaults,
                "candidate_id": effective_candidate_id,
                "release_id": effective_release_id,
            }
            detail["neo_capabilities"] = {
                **capabilities,
                "sync_supported": bool(skill_key),
                "promote_supported": bool(skill_key and effective_candidate_id),
                "rollback_supported": bool(skill_key and effective_release_id),
            }
            return detail

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_load())
        return _load()

    def _resolve_astrbot_neo_client_config(self) -> dict[str, Any]:
        provider_settings = self.config.get("provider_settings", {}) if hasattr(self.config, "get") else {}
        if not isinstance(provider_settings, dict):
            provider_settings = {}
        sandbox_cfg = provider_settings.get("sandbox", {})
        if not isinstance(sandbox_cfg, dict):
            sandbox_cfg = {}
        neo_endpoint = str(sandbox_cfg.get("shipyard_neo_endpoint") or "").strip()
        neo_access_token = str(sandbox_cfg.get("shipyard_neo_access_token") or "").strip()
        access_token_discovered = False
        if neo_endpoint and not neo_access_token:
            try:
                from astrbot.core.computer.computer_client import _discover_bay_credentials
            except Exception:
                _discover_bay_credentials = None
            if callable(_discover_bay_credentials):
                try:
                    discovered_token = str(_discover_bay_credentials(neo_endpoint) or "").strip()
                except Exception:
                    discovered_token = ""
                if discovered_token:
                    neo_access_token = discovered_token
                    access_token_discovered = True
        if not neo_endpoint or not neo_access_token:
            return {
                "ok": False,
                "message": (
                    "astrbot neo endpoint/access token not configured "
                    "(provider_settings.sandbox.shipyard_neo_endpoint / shipyard_neo_access_token)"
                ),
                "reason_code": "neo_client_not_configured",
            }
        return {
            "ok": True,
            "endpoint": neo_endpoint,
            "access_token": neo_access_token,
            "access_token_discovered": access_token_discovered,
        }

    def _resolve_astrbot_neo_sync_manager_kwargs(self, host_id: str) -> dict[str, Any]:
        sync_manager_kwargs: dict[str, Any] = {}
        normalized_host_id = str(host_id or "").strip()
        if not normalized_host_id:
            return sync_manager_kwargs
        host_context = self._resolve_astrbot_host_action_context(normalized_host_id)
        if not host_context.get("ok"):
            return sync_manager_kwargs
        layout = host_context.get("layout", {}) if isinstance(host_context.get("layout"), dict) else {}
        skills_root = str(layout.get("skills_root") or "").strip()
        neo_map_path = str(layout.get("neo_map_path") or "").strip()
        if skills_root:
            sync_manager_kwargs["skills_root"] = skills_root
        if neo_map_path:
            sync_manager_kwargs["map_path"] = neo_map_path
        return sync_manager_kwargs

    def _resolve_astrbot_neo_operation_context(self, source_id: str) -> dict[str, Any]:
        normalized_source_id = str(source_id or "").strip()
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        detail = self._lookup_astrbot_neo_source_payload(normalized_source_id)
        if not detail.get("ok"):
            return detail

        source_row = detail.get("source", {}) if isinstance(detail.get("source"), dict) else {}
        host_id = str(source_row.get("astrneo_host_id") or "").strip()
        skill_key = str(source_row.get("astrneo_skill_key") or "").strip()
        if not skill_key:
            return {
                "ok": False,
                "message": f"astrbot neo source missing skill key: {normalized_source_id}",
                "reason_code": "invalid_neo_source",
            }

        client_config = self._resolve_astrbot_neo_client_config()
        if not client_config.get("ok"):
            return client_config

        try:
            from shipyard_neo import BayClient
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo client unavailable: {exc}",
                "reason_code": "neo_client_unavailable",
            }
        try:
            from astrbot.core.skills.neo_skill_sync import NeoSkillSyncManager
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo sync manager unavailable: {exc}",
                "reason_code": "neo_sync_manager_unavailable",
            }

        try:
            sync_manager = NeoSkillSyncManager(**self._resolve_astrbot_neo_sync_manager_kwargs(host_id))
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo sync manager init failed: {exc}",
                "reason_code": "neo_sync_manager_init_failed",
            }

        return {
            "ok": True,
            "source_id": normalized_source_id,
            "detail": detail,
            "source_row": source_row,
            "host_id": host_id,
            "skill_key": skill_key,
            "BayClient": BayClient,
            "NeoSkillSyncManager": NeoSkillSyncManager,
            "sync_manager": sync_manager,
            "client_config": client_config,
        }

    @staticmethod
    def _coerce_astrbot_neo_sync_payload(
        sync_result: Any,
        *,
        sync_manager_cls: Any,
        fallback_skill_key: str,
        fallback_release_id: str,
    ) -> dict[str, Any]:
        sync_payload: dict[str, Any] = {}
        try:
            if hasattr(sync_manager_cls, "sync_result_to_dict"):
                converted = sync_manager_cls.sync_result_to_dict(sync_result)
                if isinstance(converted, dict):
                    sync_payload = _to_jsonable_like(converted)
        except Exception:
            sync_payload = {}
        if sync_payload:
            return sync_payload
        return {
            "skill_key": str(getattr(sync_result, "skill_key", "") or fallback_skill_key),
            "local_skill_name": str(getattr(sync_result, "local_skill_name", "") or ""),
            "release_id": str(getattr(sync_result, "release_id", "") or fallback_release_id),
            "candidate_id": str(getattr(sync_result, "candidate_id", "") or ""),
            "payload_ref": str(getattr(sync_result, "payload_ref", "") or ""),
            "map_path": str(getattr(sync_result, "map_path", "") or ""),
            "synced_at": str(getattr(sync_result, "synced_at", "") or _now_iso()),
        }

    def _build_astrbot_neo_mutation_response(
        self,
        source_id: str,
        *,
        prior_detail: dict[str, Any],
        prior_source_row: dict[str, Any],
        action: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        refreshed_detail = self._lookup_astrbot_neo_source_payload(source_id)
        refreshed_source = (
            refreshed_detail.get("source", prior_source_row)
            if isinstance(refreshed_detail, dict)
            else prior_source_row
        )
        response = {
            "ok": True,
            "generated_at": (
                refreshed_detail.get("generated_at", skills_snapshot.get("generated_at"))
                if isinstance(refreshed_detail, dict)
                else skills_snapshot.get("generated_at")
            ),
            "source": refreshed_source,
            "warnings": (
                refreshed_detail.get("warnings", [])
                if isinstance(refreshed_detail, dict)
                else prior_detail.get("warnings", [])
            ),
            "action": action,
            "skills": skills_snapshot,
            "inventory": inventory_snapshot,
        }
        if isinstance(refreshed_detail, dict):
            for key in ("neo_state", "neo_capabilities", "neo_defaults"):
                if key in refreshed_detail:
                    response[key] = refreshed_detail.get(key)
        if isinstance(extra, dict):
            response.update(extra)
        return response

    async def webui_sync_astrbot_neo_source(
        self,
        source_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_astrbot_neo_operation_context(source_id)
        if not context.get("ok"):
            return context

        normalized_source_id = str(context.get("source_id") or "").strip()
        detail = context.get("detail", {}) if isinstance(context.get("detail"), dict) else {}
        source_row = context.get("source_row", {}) if isinstance(context.get("source_row"), dict) else {}
        host_id = str(context.get("host_id") or "").strip()
        skill_key = str(context.get("skill_key") or "").strip()
        sync_manager = context.get("sync_manager")
        BayClient = context.get("BayClient")
        NeoSkillSyncManager = context.get("NeoSkillSyncManager")
        client_config = context.get("client_config", {}) if isinstance(context.get("client_config"), dict) else {}
        release_id = str(action_payload.get("release_id") or "").strip()
        require_stable = _to_bool(action_payload.get("require_stable"), True)

        try:
            async with BayClient(
                endpoint_url=str(client_config.get("endpoint") or ""),
                access_token=str(client_config.get("access_token") or ""),
            ) as client:
                sync_result = await sync_manager.sync_release(
                    client,
                    release_id=release_id or None,
                    skill_key=skill_key or None,
                    require_stable=require_stable,
                )
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo source sync failed: {exc}",
                "reason_code": "neo_sync_failed",
            }

        sync_payload = self._coerce_astrbot_neo_sync_payload(
            sync_result,
            sync_manager_cls=NeoSkillSyncManager,
            fallback_skill_key=skill_key,
            fallback_release_id=release_id,
        )
        self._append_skills_audit_event(
            "astrbot_neo_source_sync",
            source_id=normalized_source_id,
            payload={
                "host_id": host_id,
                "skill_key": str(sync_payload.get("skill_key") or skill_key),
                "release_id": str(sync_payload.get("release_id") or release_id),
                "local_skill_name": str(sync_payload.get("local_skill_name") or ""),
                "candidate_id": str(sync_payload.get("candidate_id") or ""),
                "payload_ref": str(sync_payload.get("payload_ref") or ""),
                "map_path": str(sync_payload.get("map_path") or ""),
                "require_stable": require_stable,
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot neo source synced: "
                f"source={normalized_source_id} "
                f"skill_key={str(sync_payload.get('skill_key') or skill_key)} "
                f"release_id={str(sync_payload.get('release_id') or release_id)}"
            ),
            source="webui",
        )
        return self._build_astrbot_neo_mutation_response(
            normalized_source_id,
            prior_detail=detail,
            prior_source_row=source_row,
            action="neo_source_sync",
            extra={
                "sync": sync_payload,
            },
        )

    async def webui_promote_astrbot_neo_source(
        self,
        source_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_astrbot_neo_operation_context(source_id)
        if not context.get("ok"):
            return context

        normalized_source_id = str(context.get("source_id") or "").strip()
        detail = context.get("detail", {}) if isinstance(context.get("detail"), dict) else {}
        source_row = context.get("source_row", {}) if isinstance(context.get("source_row"), dict) else {}
        host_id = str(context.get("host_id") or "").strip()
        skill_key = str(context.get("skill_key") or "").strip()
        sync_manager = context.get("sync_manager")
        BayClient = context.get("BayClient")
        client_config = context.get("client_config", {}) if isinstance(context.get("client_config"), dict) else {}

        default_candidate_id = str(source_row.get("astrneo_candidate_id") or "").strip()
        candidate_id = str(action_payload.get("candidate_id") or default_candidate_id).strip()
        if not candidate_id:
            return {
                "ok": False,
                "message": f"astrbot neo source missing candidate id: {normalized_source_id}",
                "reason_code": "neo_candidate_missing",
            }
        stage = str(action_payload.get("stage") or "stable").strip().lower() or "stable"
        if stage not in {"stable", "canary"}:
            return {
                "ok": False,
                "message": "astrbot neo promote stage must be stable or canary",
                "reason_code": "neo_promote_invalid_stage",
            }
        sync_to_local = _to_bool(action_payload.get("sync_to_local"), stage == "stable")

        try:
            async with BayClient(
                endpoint_url=str(client_config.get("endpoint") or ""),
                access_token=str(client_config.get("access_token") or ""),
            ) as client:
                if hasattr(sync_manager, "promote_with_optional_sync"):
                    promotion_result = await sync_manager.promote_with_optional_sync(
                        client,
                        candidate_id=candidate_id,
                        stage=stage,
                        sync_to_local=sync_to_local,
                    )
                else:
                    release = await client.skills.promote_candidate(candidate_id, stage=stage)
                    release_json = _to_jsonable_like(release)
                    sync_payload = None
                    rollback_payload = None
                    sync_error = None
                    if stage == "stable" and sync_to_local:
                        try:
                            sync_result = await sync_manager.sync_release(
                                client,
                                release_id=str(release_json.get("id") or ""),
                                require_stable=True,
                            )
                            sync_payload = self._coerce_astrbot_neo_sync_payload(
                                sync_result,
                                sync_manager_cls=type(sync_manager),
                                fallback_skill_key=skill_key,
                                fallback_release_id=str(release_json.get("id") or ""),
                            )
                        except Exception as exc:
                            sync_error = str(exc)
                            rollback = await client.skills.rollback_release(str(release_json.get("id") or ""))
                            rollback_payload = _to_jsonable_like(rollback)
                    promotion_result = {
                        "release": release_json,
                        "sync": sync_payload,
                        "rollback": rollback_payload,
                        "sync_error": sync_error,
                    }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo source promote failed: {exc}",
                "reason_code": "neo_promote_failed",
            }

        promotion_payload = {
            "candidate_id": candidate_id,
            "stage": stage,
            "sync_to_local": sync_to_local,
            "release": _to_jsonable_like((promotion_result or {}).get("release")),
            "sync": _to_jsonable_like((promotion_result or {}).get("sync")),
            "rollback": _to_jsonable_like((promotion_result or {}).get("rollback")),
            "sync_error": str((promotion_result or {}).get("sync_error") or "").strip() or None,
        }
        if promotion_payload["sync_error"]:
            return {
                "ok": False,
                "message": (
                    "astrbot neo promote failed during local sync and was rolled back: "
                    f"{promotion_payload['sync_error']}"
                ),
                "reason_code": "neo_promote_sync_rolled_back",
                "promotion": promotion_payload,
            }

        if not promotion_payload["sync"]:
            await self._trigger_astrbot_sandbox_sync()

        release_payload = promotion_payload["release"] if isinstance(promotion_payload["release"], dict) else {}
        self._append_skills_audit_event(
            "astrbot_neo_source_promote",
            source_id=normalized_source_id,
            payload={
                "host_id": host_id,
                "skill_key": skill_key,
                "candidate_id": candidate_id,
                "stage": stage,
                "sync_to_local": sync_to_local,
                "release_id": str(release_payload.get("id") or ""),
                "rolled_back": bool(promotion_payload["rollback"]),
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot neo source promoted: "
                f"source={normalized_source_id} "
                f"candidate_id={candidate_id} "
                f"stage={stage} "
                f"release_id={str(release_payload.get('id') or '')}"
            ),
            source="webui",
        )
        return self._build_astrbot_neo_mutation_response(
            normalized_source_id,
            prior_detail=detail,
            prior_source_row=source_row,
            action="neo_source_promote",
            extra={
                "promotion": promotion_payload,
            },
        )

    async def webui_rollback_astrbot_neo_source(
        self,
        source_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_astrbot_neo_operation_context(source_id)
        if not context.get("ok"):
            return context

        normalized_source_id = str(context.get("source_id") or "").strip()
        detail = context.get("detail", {}) if isinstance(context.get("detail"), dict) else {}
        source_row = context.get("source_row", {}) if isinstance(context.get("source_row"), dict) else {}
        host_id = str(context.get("host_id") or "").strip()
        skill_key = str(context.get("skill_key") or "").strip()
        BayClient = context.get("BayClient")
        client_config = context.get("client_config", {}) if isinstance(context.get("client_config"), dict) else {}

        release_id = str(action_payload.get("release_id") or source_row.get("astrneo_release_id") or "").strip()
        if not release_id:
            return {
                "ok": False,
                "message": f"astrbot neo source missing release id: {normalized_source_id}",
                "reason_code": "neo_release_missing",
            }

        try:
            async with BayClient(
                endpoint_url=str(client_config.get("endpoint") or ""),
                access_token=str(client_config.get("access_token") or ""),
            ) as client:
                rollback_result = await client.skills.rollback_release(release_id)
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot neo source rollback failed: {exc}",
                "reason_code": "neo_rollback_failed",
            }

        rollback_payload = _to_jsonable_like(rollback_result)
        self._append_skills_audit_event(
            "astrbot_neo_source_rollback",
            source_id=normalized_source_id,
            payload={
                "host_id": host_id,
                "skill_key": skill_key,
                "release_id": release_id,
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot neo source rollback executed: "
                f"source={normalized_source_id} "
                f"release_id={release_id}"
            ),
            source="webui",
        )
        return self._build_astrbot_neo_mutation_response(
            normalized_source_id,
            prior_detail=detail,
            prior_source_row=source_row,
            action="neo_source_rollback",
            extra={
                "rollback": rollback_payload,
            },
        )

    def _resolve_astrbot_host_action_context(
        self,
        host_id: str,
        scope: Any = None,
    ) -> dict[str, Any]:
        normalized_host_id = str(host_id or "").strip()
        if not normalized_host_id:
            return {"ok": False, "message": "host_id is required"}

        snapshot = self.webui_get_skills_payload()
        host_rows = [
            item
            for item in snapshot.get("host_rows", [])
            if isinstance(item, dict)
        ]
        host = next(
            (
                item
                for item in host_rows
                if str(item.get("host_id") or item.get("id") or "").strip() == normalized_host_id
            ),
            None,
        )
        if not host:
            return {"ok": False, "message": f"host_id not found: {normalized_host_id}"}

        runtime_state_backend = _normalize_inventory_id(host.get("runtime_state_backend"), default="")
        provider_key = _normalize_inventory_id(host.get("provider_key"), default="")
        if runtime_state_backend != "astrbot" and provider_key != "astrbot":
            return {
                "ok": False,
                "message": f"host is not astrbot-capable: {normalized_host_id}",
            }

        layout = resolve_astrbot_host_layout(host)
        if not _to_bool(layout.get("is_astrbot"), False):
            return {
                "ok": False,
                "message": f"host is not astrbot-capable: {normalized_host_id}",
            }
        requested_scope = _normalize_astrbot_scope(
            scope,
            default=_normalize_astrbot_scope(layout.get("selected_scope"), default="global"),
        )
        scoped_layouts = (
            layout.get("scoped_layouts", {})
            if isinstance(layout.get("scoped_layouts", {}), dict)
            else {}
        )
        action_layout = (
            scoped_layouts.get(requested_scope, {})
            if isinstance(scoped_layouts.get(requested_scope, {}), dict)
            else {}
        )
        if not _to_bool(layout.get("state_available"), False):
            return {
                "ok": False,
                "message": f"astrbot skills root unavailable for host: {normalized_host_id}",
            }
        if scoped_layouts and not _to_bool(action_layout.get("state_available"), False):
            return {
                "ok": False,
                "message": (
                    "astrbot skills root unavailable for "
                    f"host={normalized_host_id} scope={requested_scope}"
                ),
            }

        state_by_host = (
            snapshot.get("astrbot_state_by_host", {})
            if isinstance(snapshot.get("astrbot_state_by_host", {}), dict)
            else {}
        )
        runtime_state = (
            state_by_host.get(normalized_host_id, {})
            if isinstance(state_by_host.get(normalized_host_id, {}), dict)
            else {}
        )
        return {
            "ok": True,
            "host_id": normalized_host_id,
            "scope": requested_scope,
            "host": host,
            "layout": layout,
            "action_layout": {
                **layout,
                **action_layout,
                "scope": requested_scope,
            } if action_layout else {
                **layout,
                "scope": requested_scope,
            },
            "runtime_state": runtime_state,
            "snapshot": snapshot,
        }

    def webui_get_astrbot_host_payload(self, host_id: str) -> dict[str, Any]:
        context = self._resolve_astrbot_host_action_context(host_id)
        if not context.get("ok"):
            return context
        layout = context.get("layout", {}) if isinstance(context.get("layout"), dict) else {}
        runtime_state = (
            context.get("runtime_state", {})
            if isinstance(context.get("runtime_state"), dict)
            else {}
        )
        runtime_summary = (
            runtime_state.get("summary", {})
            if isinstance(runtime_state.get("summary"), dict)
            else {}
        )
        snapshot = context.get("snapshot", {}) if isinstance(context.get("snapshot"), dict) else {}
        selected_workspace_id = str(
            layout.get("selected_workspace_id")
            or runtime_summary.get("selected_workspace_id")
            or "",
        ).strip()
        return {
            "ok": True,
            "generated_at": snapshot.get("generated_at"),
            "host": context.get("host", {}),
            "runtime_state": runtime_state,
            "selected_workspace_id": selected_workspace_id,
            "layout": {
                "host_id": str(layout.get("host_id") or "").strip(),
                "selected_scope": str(layout.get("selected_scope") or "").strip(),
                "available_scopes": list(layout.get("available_scopes", [])) if isinstance(layout.get("available_scopes", []), list) else [],
                "selected_workspace_id": selected_workspace_id,
                "skills_root": str(layout.get("skills_root") or "").strip(),
                "astrbot_data_dir": str(layout.get("astrbot_data_dir") or "").strip(),
                "skills_config_path": str(layout.get("skills_config_path") or "").strip(),
                "sandbox_cache_path": str(layout.get("sandbox_cache_path") or "").strip(),
                "neo_map_path": str(layout.get("neo_map_path") or "").strip(),
                "workspace_profiles": (
                    list(layout.get("workspace_profiles", []))
                    if isinstance(layout.get("workspace_profiles", []), list)
                    else []
                ),
                "scoped_layouts": layout.get("scoped_layouts", {}) if isinstance(layout.get("scoped_layouts", {}), dict) else {},
            },
            "warnings": snapshot.get("warnings", []),
        }

    def webui_get_astrbot_workspaces_payload(self, host_id: str) -> dict[str, Any]:
        context = self._resolve_astrbot_host_action_context(host_id)
        if not context.get("ok"):
            return context
        layout = context.get("layout", {}) if isinstance(context.get("layout"), dict) else {}
        runtime_state = (
            context.get("runtime_state", {})
            if isinstance(context.get("runtime_state"), dict)
            else {}
        )
        runtime_summary = (
            runtime_state.get("summary", {})
            if isinstance(runtime_state.get("summary"), dict)
            else {}
        )
        snapshot = context.get("snapshot", {}) if isinstance(context.get("snapshot"), dict) else {}
        workspace_profiles = (
            list(layout.get("workspace_profiles", []))
            if isinstance(layout.get("workspace_profiles", []), list)
            else []
        )
        workspace_summaries = (
            runtime_summary.get("workspace_summaries", {})
            if isinstance(runtime_summary.get("workspace_summaries"), dict)
            else {}
        )
        selected_workspace_id = str(
            layout.get("selected_workspace_id")
            or runtime_summary.get("selected_workspace_id")
            or "",
        ).strip()
        items: list[dict[str, Any]] = []
        for profile in workspace_profiles:
            if not isinstance(profile, dict):
                continue
            workspace_id = str(profile.get("workspace_id") or "").strip()
            item = {
                "workspace_id": workspace_id,
                "workspace_root": str(profile.get("workspace_root") or "").strip(),
                "skills_root": str(profile.get("skills_root") or "").strip(),
                "extra_prompt_path": str(profile.get("extra_prompt_path") or "").strip(),
                "exists": _to_bool(profile.get("exists"), False),
                "summary": (
                    workspace_summaries.get(workspace_id, {})
                    if isinstance(workspace_summaries.get(workspace_id, {}), dict)
                    else {}
                ),
            }
            items.append(item)

        return {
            "ok": True,
            "generated_at": snapshot.get("generated_at"),
            "host": context.get("host", {}),
            "selected_workspace_id": selected_workspace_id,
            "workspace_profiles": workspace_profiles,
            "workspace_summaries": workspace_summaries,
            "items": items,
            "counts": {
                "workspace_total": len(workspace_profiles),
                "workspace_exists_total": sum(
                    1 for item in workspace_profiles
                    if isinstance(item, dict) and _to_bool(item.get("exists"), False)
                ),
            },
            "warnings": snapshot.get("warnings", []),
        }

    def _build_astrbot_host_mutation_response(
        self,
        host_id: str,
        *,
        inventory_snapshot: dict[str, Any],
        skills_snapshot: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        host_payload = self.webui_get_astrbot_host_payload(host_id)
        response = {
            "ok": True,
            "generated_at": host_payload.get("generated_at", skills_snapshot.get("generated_at")),
            "host": host_payload.get("host", {}),
            "runtime_state": host_payload.get("runtime_state", {}),
            "layout": host_payload.get("layout", {}),
            "warnings": host_payload.get("warnings", []),
            "skills": skills_snapshot,
            "inventory": inventory_snapshot,
        }
        if isinstance(extra, dict):
            response.update(extra)
        return response

    async def _trigger_astrbot_sandbox_sync(self) -> dict[str, Any]:
        try:
            from astrbot.core.computer.computer_client import sync_skills_to_active_sandboxes
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot sandbox sync adapter unavailable: {exc}",
                "reason_code": "sandbox_sync_unavailable",
            }
        try:
            maybe_coro = sync_skills_to_active_sandboxes()
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
        except Exception as exc:
            return {
                "ok": False,
                "message": f"astrbot sandbox sync failed: {exc}",
                "reason_code": "sandbox_sync_failed",
            }
        return {
            "ok": True,
            "message": "astrbot sandbox sync completed",
            "reason_code": "",
        }

    def webui_set_astrbot_skill_active(self, host_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        requested_scope = _normalize_astrbot_scope(action_payload.get("scope"), default="global")
        context = self._resolve_astrbot_host_action_context(host_id, requested_scope)
        if not context.get("ok"):
            return context
        skill_name = str(action_payload.get("skill_name") or action_payload.get("name") or "").strip()
        active = _to_bool(action_payload.get("active"), True)
        result = set_astrbot_skill_active(
            context.get("action_layout", {}),
            skill_name=skill_name,
            active=active,
            scope=requested_scope,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "message": str(result.get("message") or "astrbot toggle action failed"),
                "reason_code": str(result.get("reason_code") or "").strip(),
                "result": result,
            }

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_host_id = str(context.get("host_id") or "").strip()
        self._append_skills_audit_event(
            "astrbot_skill_toggle",
            source_id=normalized_host_id,
            payload={
                "skill_name": str(result.get("skill_name") or "").strip(),
                "active": _to_bool(result.get("active"), active),
                "changed": _to_bool(result.get("changed"), False),
                "scope": str(result.get("scope") or requested_scope),
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot skill toggled: "
                f"host={normalized_host_id} "
                f"scope={str(result.get('scope') or requested_scope)} "
                f"skill={str(result.get('skill_name') or '').strip()} "
                f"active={_to_bool(result.get('active'), active)}"
            ),
            source="webui",
        )
        return self._build_astrbot_host_mutation_response(
            normalized_host_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=skills_snapshot if isinstance(skills_snapshot, dict) else {},
            extra={"action": "toggle_skill", "result": result},
        )

    def webui_delete_astrbot_skill(self, host_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        requested_scope = _normalize_astrbot_scope(action_payload.get("scope"), default="global")
        context = self._resolve_astrbot_host_action_context(host_id, requested_scope)
        if not context.get("ok"):
            return context
        skill_name = str(action_payload.get("skill_name") or action_payload.get("name") or "").strip()
        result = delete_astrbot_local_skill(
            context.get("action_layout", {}),
            skill_name=skill_name,
            scope=requested_scope,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "message": str(result.get("message") or "astrbot delete action failed"),
                "reason_code": str(result.get("reason_code") or "").strip(),
                "result": result,
            }

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_host_id = str(context.get("host_id") or "").strip()
        self._append_skills_audit_event(
            "astrbot_skill_delete",
            source_id=normalized_host_id,
            payload={
                "skill_name": str(result.get("skill_name") or "").strip(),
                "deleted_local_dir": _to_bool(result.get("deleted_local_dir"), False),
                "removed_from_config": _to_bool(result.get("removed_from_config"), False),
                "removed_from_sandbox_cache": _to_bool(result.get("removed_from_sandbox_cache"), False),
                "scope": str(result.get("scope") or requested_scope),
            },
        )
        self._push_debug_log(
            "warn",
            (
                "astrbot skill deleted: "
                f"host={normalized_host_id} "
                f"scope={str(result.get('scope') or requested_scope)} "
                f"skill={str(result.get('skill_name') or '').strip()}"
            ),
            source="webui",
        )
        return self._build_astrbot_host_mutation_response(
            normalized_host_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=skills_snapshot if isinstance(skills_snapshot, dict) else {},
            extra={"action": "delete_skill", "result": result},
        )

    async def webui_sync_astrbot_sandbox(
        self,
        host_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        requested_scope = _normalize_astrbot_scope(action_payload.get("scope"), default="global")
        context = self._resolve_astrbot_host_action_context(host_id, requested_scope)
        if not context.get("ok"):
            return context

        sync_result = await self._trigger_astrbot_sandbox_sync()
        if not sync_result.get("ok"):
            return sync_result

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_host_id = str(context.get("host_id") or "").strip()
        self._append_skills_audit_event(
            "astrbot_sandbox_sync",
            source_id=normalized_host_id,
            payload={"ok": True, "scope": requested_scope},
        )
        self._push_debug_log(
            "info",
            f"astrbot sandbox sync completed: host={normalized_host_id} scope={requested_scope}",
            source="webui",
        )
        return self._build_astrbot_host_mutation_response(
            normalized_host_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=skills_snapshot if isinstance(skills_snapshot, dict) else {},
            extra={"action": "sandbox_sync", "result": sync_result, "scope": requested_scope},
        )

    def webui_import_astrbot_skill_zip(
        self,
        host_id: str,
        zip_path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        requested_scope = _normalize_astrbot_scope(action_payload.get("scope"), default="global")
        context = self._resolve_astrbot_host_action_context(host_id, requested_scope)
        if not context.get("ok"):
            return context

        skill_name_hint = str(action_payload.get("skill_name_hint") or "").strip() or None
        overwrite = _to_bool(action_payload.get("overwrite"), False)
        result = import_astrbot_skill_zip(
            context.get("action_layout", {}),
            zip_path=zip_path,
            scope=requested_scope,
            overwrite=overwrite,
            skill_name_hint=skill_name_hint,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "message": str(result.get("message") or "astrbot zip import failed"),
                "reason_code": str(result.get("reason_code") or "").strip(),
                "result": result,
            }

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_host_id = str(context.get("host_id") or "").strip()
        installed_skill_names = _to_str_list(result.get("installed_skill_names", []))
        self._append_skills_audit_event(
            "astrbot_skill_zip_import",
            source_id=normalized_host_id,
            payload={
                "scope": str(result.get("scope") or requested_scope),
                "overwrite": overwrite,
                "skill_name_hint": skill_name_hint or "",
                "installed_skill_names": installed_skill_names,
                "installed_count": len(installed_skill_names),
                "archive_path": str(result.get("archive_path") or zip_path),
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot zip imported: "
                f"host={normalized_host_id} "
                f"scope={str(result.get('scope') or requested_scope)} "
                f"installed={','.join(installed_skill_names) or '-'}"
            ),
            source="webui",
        )
        return self._build_astrbot_host_mutation_response(
            normalized_host_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=skills_snapshot if isinstance(skills_snapshot, dict) else {},
            extra={"action": "import_zip", "result": result},
        )

    def webui_export_astrbot_skill_zip(
        self,
        host_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_payload = payload if isinstance(payload, dict) else {}
        requested_scope = _normalize_astrbot_scope(action_payload.get("scope"), default="global")
        context = self._resolve_astrbot_host_action_context(host_id, requested_scope)
        if not context.get("ok"):
            return context

        skill_name = str(action_payload.get("skill_name") or action_payload.get("name") or "").strip()
        result = export_astrbot_skill_zip(
            context.get("action_layout", {}),
            skill_name=skill_name,
            scope=requested_scope,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "message": str(result.get("message") or "astrbot zip export failed"),
                "reason_code": str(result.get("reason_code") or "").strip(),
                "result": result,
            }

        normalized_host_id = str(context.get("host_id") or "").strip()
        self._append_skills_audit_event(
            "astrbot_skill_zip_export",
            source_id=normalized_host_id,
            payload={
                "scope": str(result.get("scope") or requested_scope),
                "skill_name": str(result.get("skill_name") or skill_name),
                "archive_path": str(result.get("archive_path") or ""),
                "filename": str(result.get("filename") or ""),
            },
        )
        self._push_debug_log(
            "info",
            (
                "astrbot zip exported: "
                f"host={normalized_host_id} "
                f"scope={str(result.get('scope') or requested_scope)} "
                f"skill={str(result.get('skill_name') or skill_name)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "generated_at": (
                context.get("snapshot", {}).get("generated_at")
                if isinstance(context.get("snapshot"), dict)
                else ""
            ),
            "host": context.get("host", {}),
            "action": "export_zip",
            "result": result,
        }

    def webui_get_skill_sources_payload(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "counts": snapshot.get("counts", {}),
            "items": snapshot.get("source_rows", []),
            "warnings": snapshot.get("warnings", []),
        }

    def webui_get_skill_source_payload(self, source_id: str) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        snapshot = self.webui_get_skills_payload()
        source_rows = snapshot.get("source_rows", [])
        source = next(
            (
                item for item in source_rows
                if isinstance(item, dict) and str(item.get("source_id", "")) == normalized_source_id
            ),
            None,
        )
        if not source:
            return {"ok": False, "message": f"source_id not found: {normalized_source_id}"}
        related_targets = [
            item
            for item in snapshot.get("deploy_rows", [])
            if isinstance(item, dict)
            and (
                normalized_source_id in _to_str_list(item.get("selected_source_ids", []))
                or normalized_source_id in _to_str_list(item.get("available_source_ids", []))
            )
        ]
        return {
            "ok": True,
            "generated_at": snapshot.get("generated_at"),
            "source": source,
            "deploy_rows": related_targets,
            "warnings": snapshot.get("warnings", []),
        }

    def webui_get_install_unit_payload(self, install_unit_id: str) -> dict[str, Any]:
        normalized_install_unit_id = str(install_unit_id or "").strip()
        if not normalized_install_unit_id:
            return {"ok": False, "message": "install_unit_id is required"}
        snapshot = self.webui_get_skills_payload()
        detail = build_install_unit_detail_payload(snapshot, normalized_install_unit_id)
        if not detail.get("ok"):
            return detail
        source_rows = self._augment_source_rows_with_git_checkouts(
            [
                item
                for item in detail.get("source_rows", [])
                if isinstance(item, dict)
            ],
        )
        install_unit = detail.get("install_unit", {}) if isinstance(detail.get("install_unit"), dict) else {}
        detail["update_plan"] = self._augment_update_plan_with_source_sync_fallback_preview(
            detail.get("update_plan"),
            source_rows,
            display_name=str(
                install_unit.get("display_name")
                or normalized_install_unit_id
                or "install unit"
            ).strip(),
        )
        return detail

    def webui_get_collection_group_payload(self, collection_group_id: str) -> dict[str, Any]:
        normalized_collection_group_id = str(collection_group_id or "").strip()
        if not normalized_collection_group_id:
            return {"ok": False, "message": "collection_group_id is required"}
        snapshot = self.webui_get_skills_payload()
        detail = build_collection_group_detail_payload(snapshot, normalized_collection_group_id)
        if not detail.get("ok"):
            return detail

        collection_group = detail.get("collection_group", {}) if isinstance(detail.get("collection_group"), dict) else {}
        install_unit_rows = [
            item
            for item in detail.get("install_unit_rows", [])
            if isinstance(item, dict)
        ]
        source_rows = self._augment_source_rows_with_git_checkouts(
            [
                item
                for item in detail.get("source_rows", [])
                if isinstance(item, dict)
            ],
        )
        detail["update_plan"] = self._build_effective_collection_group_update_plan(
            collection_group=collection_group,
            install_unit_rows=install_unit_rows,
            source_rows=source_rows,
        )
        return detail

    def _resolve_install_unit_action_context(self, install_unit_id: str) -> dict[str, Any]:
        normalized_install_unit_id = str(install_unit_id or "").strip()
        if not normalized_install_unit_id:
            return {"ok": False, "message": "install_unit_id is required"}

        detail = self.webui_get_install_unit_payload(normalized_install_unit_id)
        if not detail.get("ok"):
            return detail

        source_rows = [
            item
            for item in detail.get("source_rows", [])
            if isinstance(item, dict)
        ]
        source_ids = _dedupe_keep_order(
            [
                _normalize_inventory_id(item.get("source_id", ""), default="")
                for item in source_rows
                if _normalize_inventory_id(item.get("source_id", ""), default="")
            ],
        )
        if not source_ids:
            return {
                "ok": False,
                "message": f"install_unit has no source members: {normalized_install_unit_id}",
            }

        return {
            "ok": True,
            "install_unit_id": normalized_install_unit_id,
            "detail": detail,
            "install_unit": detail.get("install_unit", {}),
            "collection_group": detail.get("collection_group", {}),
            "source_rows": source_rows,
            "source_ids": source_ids,
        }

    def _build_install_unit_mutation_response(
        self,
        install_unit_id: str,
        *,
        inventory_snapshot: dict[str, Any],
        skills_snapshot: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        detail = self.webui_get_install_unit_payload(install_unit_id)
        response = {
            "ok": True,
            "generated_at": detail.get("generated_at", skills_snapshot.get("generated_at")),
            "install_unit": detail.get("install_unit", {}),
            "collection_group": detail.get("collection_group", {}),
            "source_rows": detail.get("source_rows", []),
            "deploy_rows": detail.get("deploy_rows", []),
            "warnings": detail.get("warnings", []),
            "skills": skills_snapshot,
            "inventory": inventory_snapshot,
        }
        if isinstance(extra, dict):
            response.update(extra)
        return response

    def _resolve_collection_group_action_context(self, collection_group_id: str) -> dict[str, Any]:
        normalized_collection_group_id = str(collection_group_id or "").strip()
        if not normalized_collection_group_id:
            return {"ok": False, "message": "collection_group_id is required"}

        detail = self.webui_get_collection_group_payload(normalized_collection_group_id)
        if not detail.get("ok"):
            return detail

        install_unit_rows = [
            item
            for item in detail.get("install_unit_rows", [])
            if isinstance(item, dict)
        ]
        source_rows = [
            item
            for item in detail.get("source_rows", [])
            if isinstance(item, dict)
        ]
        source_ids = _dedupe_keep_order(
            [
                _normalize_inventory_id(item.get("source_id", ""), default="")
                for item in source_rows
                if _normalize_inventory_id(item.get("source_id", ""), default="")
            ],
        )
        if not source_ids:
            return {
                "ok": False,
                "message": f"collection_group has no source members: {normalized_collection_group_id}",
            }

        return {
            "ok": True,
            "collection_group_id": normalized_collection_group_id,
            "detail": detail,
            "collection_group": detail.get("collection_group", {}),
            "install_unit_rows": install_unit_rows,
            "source_rows": source_rows,
            "source_ids": source_ids,
        }

    def _build_collection_group_mutation_response(
        self,
        collection_group_id: str,
        *,
        inventory_snapshot: dict[str, Any],
        skills_snapshot: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        detail = self.webui_get_collection_group_payload(collection_group_id)
        response = {
            "ok": True,
            "generated_at": detail.get("generated_at", skills_snapshot.get("generated_at")),
            "collection_group": detail.get("collection_group", {}),
            "install_unit_rows": detail.get("install_unit_rows", []),
            "source_rows": detail.get("source_rows", []),
            "deploy_rows": detail.get("deploy_rows", []),
            "warnings": detail.get("warnings", []),
            "skills": skills_snapshot,
            "inventory": inventory_snapshot,
        }
        if isinstance(extra, dict):
            response.update(extra)
        return response

    def _summarize_related_deploy_targets(self, detail: dict[str, Any] | None) -> dict[str, list[str]]:
        deploy_rows = [
            item
            for item in (detail or {}).get("deploy_rows", [])
            if isinstance(item, dict)
        ]
        target_ids = _dedupe_keep_order(
            [
                str(item.get("target_id", "")).strip()
                for item in deploy_rows
                if str(item.get("target_id", "")).strip()
            ],
        )
        repairable_target_ids = _dedupe_keep_order(
            [
                str(item.get("target_id", "")).strip()
                for item in deploy_rows
                if str(item.get("target_id", "")).strip()
                and _to_str_list(item.get("repair_actions", []))
            ],
        )
        return {
            "target_ids": target_ids,
            "repairable_target_ids": repairable_target_ids,
        }

    def _build_source_index_by_id(self, source_rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        rows = [item for item in (source_rows or []) if isinstance(item, dict)]
        index: dict[str, dict[str, Any]] = {}
        for item in rows:
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            if not source_id:
                continue
            index[source_id] = item
        return index

    def _resolve_plan_source_rows(
        self,
        plan: dict[str, Any] | None,
        source_index: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        source_map = source_index if isinstance(source_index, dict) else {}
        source_ids = [
            _normalize_inventory_id(item, default="")
            for item in _to_str_list((plan or {}).get("source_ids", []))
        ]
        source_ids = [item for item in source_ids if item]
        if source_ids:
            return [source_map[item] for item in source_ids if item in source_map]

        install_unit_id = str((plan or {}).get("install_unit_id") or "").strip()
        source_paths = {
            str(item).strip()
            for item in _to_str_list((plan or {}).get("source_paths", []))
            if str(item).strip()
        }
        rows: list[dict[str, Any]] = []
        for item in source_map.values():
            if not isinstance(item, dict):
                continue
            item_install_unit_id = str(item.get("install_unit_id") or "").strip()
            item_source_path = str(item.get("source_path") or "").strip()
            if install_unit_id and item_install_unit_id == install_unit_id:
                rows.append(item)
                continue
            if source_paths and item_source_path in source_paths:
                rows.append(item)
        return rows

    def _classify_syncable_source_rows(
        self,
        source_rows: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        rows = [item for item in (source_rows or []) if isinstance(item, dict)]
        syncable_rows: list[dict[str, Any]] = []
        non_syncable_rows: list[dict[str, Any]] = []
        for item in rows:
            if is_source_syncable(item):
                syncable_rows.append(item)
            else:
                non_syncable_rows.append(item)
        syncable_source_ids = _dedupe_keep_order(
            [
                str(item.get("source_id") or "").strip()
                for item in syncable_rows
                if str(item.get("source_id") or "").strip()
            ],
        )
        non_syncable_source_ids = _dedupe_keep_order(
            [
                str(item.get("source_id") or "").strip()
                for item in non_syncable_rows
                if str(item.get("source_id") or "").strip()
            ],
        )
        return {
            "rows": rows,
            "syncable_rows": syncable_rows,
            "non_syncable_rows": non_syncable_rows,
            "syncable_source_ids": syncable_source_ids,
            "non_syncable_source_ids": non_syncable_source_ids,
            "all_syncable": bool(rows) and not non_syncable_rows,
        }

    def _augment_update_plan_with_source_sync_fallback_preview(
        self,
        update_plan: dict[str, Any] | None,
        source_rows: list[dict[str, Any]] | None,
        *,
        display_name: str = "",
    ) -> dict[str, Any]:
        plan = update_plan if isinstance(update_plan, dict) else {}
        augmented: dict[str, Any] = {**plan}
        commands = _to_str_list(augmented.get("commands", []))
        precheck_commands = _to_str_list(augmented.get("precheck_commands", []))
        reason_code = str(augmented.get("reason_code") or "").strip().lower()
        augmented["commands"] = commands
        augmented["command_count"] = len(commands)
        augmented["precheck_commands"] = precheck_commands
        augmented["precheck_command_count"] = len(precheck_commands)

        syncable_status = self._classify_syncable_source_rows(source_rows)
        syncable_source_ids = syncable_status.get("syncable_source_ids", [])
        non_syncable_source_ids = syncable_status.get("non_syncable_source_ids", [])
        augmented["syncable_source_ids"] = syncable_source_ids
        augmented["non_syncable_source_ids"] = non_syncable_source_ids

        if not _to_bool(augmented.get("supported"), False) and syncable_status.get("all_syncable"):
            normalized_name = str(display_name or augmented.get("display_name") or "aggregate").strip()
            augmented["supported"] = True
            augmented["fallback_mode"] = "source_sync"
            augmented["message"] = f"update fallback will run source sync for {normalized_name}"
            reason_code = ""

        fallback_mode = str(augmented.get("fallback_mode") or "").strip().lower()
        supported = _to_bool(augmented.get("supported"), False)
        has_commands = len(commands) > 0
        if fallback_mode == "source_sync":
            update_mode = "source_sync"
            actionable = True
        elif supported and has_commands:
            update_mode = "command"
            actionable = True
        else:
            update_mode = "manual_only"
            actionable = False
        if update_mode == "manual_only" and not reason_code:
            if non_syncable_source_ids:
                reason_code = "non_syncable_sources_present"
            else:
                reason_code = "manual_only"
        augmented["update_mode"] = update_mode
        augmented["actionable"] = actionable
        augmented["manual_only"] = update_mode == "manual_only"
        augmented["reason_code"] = reason_code

        return augmented

    def _is_source_sync_update_plan(self, plan: dict[str, Any] | None) -> bool:
        payload = plan if isinstance(plan, dict) else {}
        update_mode = str(payload.get("update_mode") or "").strip().lower()
        if update_mode == "source_sync":
            return True
        fallback_mode = str(payload.get("fallback_mode") or "").strip().lower()
        if fallback_mode == "source_sync":
            return True
        supported = _to_bool(payload.get("supported"), False)
        has_commands = bool(_to_str_list(payload.get("commands", [])))
        has_syncable_sources = bool(_to_str_list(payload.get("syncable_source_ids", [])))
        non_syncable_sources = _to_str_list(payload.get("non_syncable_source_ids", []))
        return supported and not has_commands and has_syncable_sources and not non_syncable_sources

    def _build_install_unit_update_plan_dedupe_key(self, plan: dict[str, Any] | None) -> str:
        payload = plan if isinstance(plan, dict) else {}
        update_mode = str(payload.get("update_mode") or "").strip().lower()
        commands = _dedupe_keep_order(_to_str_list(payload.get("commands", [])))
        precheck_commands = _dedupe_keep_order(_to_str_list(payload.get("precheck_commands", [])))
        source_ids = _dedupe_keep_order(_to_str_list(payload.get("source_ids", [])))
        source_paths = _dedupe_keep_order(_to_str_list(payload.get("source_paths", [])))
        syncable_source_ids = _dedupe_keep_order(_to_str_list(payload.get("syncable_source_ids", [])))
        non_syncable_source_ids = _dedupe_keep_order(_to_str_list(payload.get("non_syncable_source_ids", [])))
        install_ref = str(payload.get("install_ref") or "").strip()
        manager = str(payload.get("manager") or "").strip().lower()
        policy = str(payload.get("policy") or "").strip().lower()
        reason_code = str(payload.get("reason_code") or "").strip().lower()
        install_unit_id = str(payload.get("install_unit_id") or "").strip()
        manual_only = _to_bool(payload.get("manual_only", False), False)

        dedupe_payload = {
            "update_mode": update_mode,
            "manager": manager,
            "policy": policy,
            "install_ref": install_ref,
            "commands": commands,
            "precheck_commands": precheck_commands,
            "syncable_source_ids": syncable_source_ids,
            "non_syncable_source_ids": non_syncable_source_ids,
            "source_paths": source_paths,
            "source_ids": source_ids,
            "reason_code": reason_code,
            "manual_only": manual_only,
            "install_unit_id": install_unit_id if not any(
                [
                    install_ref,
                    commands,
                    precheck_commands,
                    syncable_source_ids,
                    source_paths,
                    source_ids,
                ],
            ) else "",
        }
        return json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True)

    def _build_effective_collection_group_update_plan(
        self,
        *,
        collection_group: dict[str, Any] | None,
        install_unit_rows: list[dict[str, Any]] | None,
        source_rows: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        group = collection_group if isinstance(collection_group, dict) else {}
        unit_rows = [item for item in (install_unit_rows or []) if isinstance(item, dict)]
        rows = [item for item in (source_rows or []) if isinstance(item, dict)]
        base_plan = build_collection_group_update_plan(group, unit_rows, rows)
        display_name = str(
            group.get("display_name")
            or base_plan.get("display_name")
            or base_plan.get("collection_group_id")
            or "collection group"
        ).strip()

        install_unit_display_names: dict[str, str] = {}
        for item in unit_rows:
            install_unit_id = str(item.get("install_unit_id") or "").strip()
            if not install_unit_id:
                continue
            install_unit_display_names[install_unit_id] = str(
                item.get("display_name")
                or item.get("install_unit_display_name")
                or install_unit_id
            ).strip()

        raw_unit_plans = [
            item
            for item in base_plan.get("install_unit_plans", [])
            if isinstance(item, dict)
        ]
        effective_unit_plans: list[dict[str, Any]] = []
        for item in raw_unit_plans:
            install_unit_id = str(item.get("install_unit_id") or "").strip()
            install_unit_source_rows = [
                source
                for source in rows
                if str(source.get("install_unit_id") or "").strip() == install_unit_id
            ]
            effective_unit_plans.append(
                self._augment_update_plan_with_source_sync_fallback_preview(
                    item,
                    install_unit_source_rows,
                    display_name=install_unit_display_names.get(install_unit_id, install_unit_id or "install unit"),
                ),
            )

        actionable_unit_plans = [
            item
            for item in effective_unit_plans
            if _to_bool(item.get("actionable"), False)
        ]
        blocked_unit_plans = [
            item
            for item in effective_unit_plans
            if not _to_bool(item.get("actionable"), False)
        ]
        command_unit_plans = [
            item
            for item in actionable_unit_plans
            if _to_str_list(item.get("commands", []))
        ]
        source_sync_unit_plans = [
            item
            for item in actionable_unit_plans
            if self._is_source_sync_update_plan(item)
            and not _to_str_list(item.get("commands", []))
        ]
        command_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in command_unit_plans
                if str(item.get("install_unit_id") or "").strip()
            ],
        )
        source_sync_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in source_sync_unit_plans
                if str(item.get("install_unit_id") or "").strip()
            ],
        )
        skipped_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in blocked_unit_plans
                if str(item.get("install_unit_id") or "").strip()
            ],
        )
        skipped_manual_only_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in blocked_unit_plans
                if str(item.get("install_unit_id") or "").strip()
                and str(item.get("reason_code") or "").strip().lower()
                in {"manual_managed", "manual_only", "non_syncable_sources_present"}
            ],
        )
        skipped_manual_only_install_unit_id_set = set(skipped_manual_only_install_unit_ids)
        skipped_other_install_unit_ids = _dedupe_keep_order(
            [
                install_unit_id
                for install_unit_id in skipped_install_unit_ids
                if install_unit_id not in skipped_manual_only_install_unit_id_set
            ],
        )

        precheck_commands = [
            command
            for item in command_unit_plans
            for command in _to_str_list(item.get("precheck_commands", []))
        ]
        commands = [
            command
            for item in command_unit_plans
            for command in _to_str_list(item.get("commands", []))
        ]
        managers = _dedupe_keep_order(
            [
                str(item.get("manager") or "").strip()
                for item in actionable_unit_plans
                if str(item.get("manager") or "").strip()
            ],
        )
        policies = _dedupe_keep_order(
            [
                str(item.get("policy") or "").strip()
                for item in actionable_unit_plans
                if str(item.get("policy") or "").strip()
            ],
        )

        supported_install_unit_total = len(actionable_unit_plans)
        unsupported_install_unit_total = len(blocked_unit_plans)
        aggregate_supported = supported_install_unit_total > 0
        fully_supported = aggregate_supported and unsupported_install_unit_total == 0
        partial_supported = aggregate_supported and unsupported_install_unit_total > 0

        if not aggregate_supported:
            update_mode = "manual_only"
            actionable = False
        elif partial_supported:
            update_mode = "partial"
            actionable = True
        elif source_sync_unit_plans and not command_unit_plans:
            update_mode = "source_sync"
            actionable = True
        else:
            update_mode = "command"
            actionable = True

        if not actionable:
            message = f"update unsupported for collection group: {display_name}"
        elif update_mode == "source_sync":
            message = f"update fallback will run source sync for {display_name}"
        elif update_mode == "partial":
            message = (
                f"collection group update prepared for {supported_install_unit_total} install units "
                f"({unsupported_install_unit_total} blocked)"
            )
        else:
            message = f"collection group update prepared for {supported_install_unit_total} install units"

        unsupported_install_units = [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "message": str(item.get("message") or "").strip(),
                "reason_code": str(item.get("reason_code") or "").strip().lower(),
            }
            for item in blocked_unit_plans
            if str(item.get("install_unit_id") or "").strip() or str(item.get("message") or "").strip()
        ]
        blocked_reasons = [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "reason": str(item.get("message") or "").strip(),
                "reason_code": str(item.get("reason_code") or "").strip().lower(),
            }
            for item in blocked_unit_plans
            if str(item.get("install_unit_id") or "").strip() or str(item.get("message") or "").strip()
        ]
        blocked_reason_codes = _dedupe_keep_order(
            [
                str(item.get("reason_code") or "").strip().lower()
                for item in blocked_unit_plans
                if str(item.get("reason_code") or "").strip()
            ],
        )
        if update_mode == "manual_only":
            if len(blocked_reason_codes) == 1:
                reason_code = blocked_reason_codes[0]
            elif blocked_reason_codes:
                reason_code = "mixed_blocked_reasons"
            else:
                reason_code = "manual_only"
        else:
            reason_code = ""
        syncable_source_ids = _dedupe_keep_order(
            [
                source_id
                for item in actionable_unit_plans
                for source_id in _to_str_list(item.get("syncable_source_ids", []))
                if str(source_id).strip()
            ],
        )
        non_syncable_source_ids = _dedupe_keep_order(
            [
                source_id
                for item in blocked_unit_plans
                for source_id in _to_str_list(item.get("non_syncable_source_ids", []))
                if str(source_id).strip()
            ],
        )
        actionable_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in actionable_unit_plans
                if str(item.get("install_unit_id") or "").strip()
            ],
        )

        return {
            **base_plan,
            "display_name": display_name,
            "install_unit_plans": effective_unit_plans,
            "manager": managers[0] if len(managers) == 1 else ("mixed" if managers else ""),
            "policy": policies[0] if len(policies) == 1 else ("mixed" if policies else ""),
            "precheck_commands": precheck_commands,
            "precheck_command_count": len(precheck_commands),
            "commands": commands,
            "command_count": len(commands),
            "supported": aggregate_supported,
            "actionable": actionable,
            "manual_only": update_mode == "manual_only",
            "update_mode": update_mode,
            "fallback_mode": "source_sync" if update_mode == "source_sync" else "",
            "message": message,
            "supported_install_unit_total": supported_install_unit_total,
            "unsupported_install_unit_total": unsupported_install_unit_total,
            "unsupported_install_units": unsupported_install_units,
            "blocked_reasons": blocked_reasons,
            "reason_code": reason_code,
            "aggregate_supported": aggregate_supported,
            "fully_supported": fully_supported,
            "partial_supported": partial_supported,
            "command_install_unit_total": len(command_unit_plans),
            "source_sync_install_unit_total": len(source_sync_unit_plans),
            "command_install_unit_ids": command_install_unit_ids,
            "source_sync_install_unit_ids": source_sync_install_unit_ids,
            "actionable_install_unit_ids": actionable_install_unit_ids,
            "skipped_install_unit_ids": skipped_install_unit_ids,
            "skipped_install_unit_total": len(skipped_install_unit_ids),
            "skipped_manual_only_install_unit_ids": skipped_manual_only_install_unit_ids,
            "skipped_manual_only_install_unit_total": len(skipped_manual_only_install_unit_ids),
            "skipped_other_install_unit_ids": skipped_other_install_unit_ids,
            "skipped_other_install_unit_total": len(skipped_other_install_unit_ids),
            "syncable_source_ids": syncable_source_ids,
            "non_syncable_source_ids": non_syncable_source_ids,
        }

    @staticmethod
    def _empty_install_unit_execution_summary() -> dict[str, Any]:
        return {
            "results": [],
            "install_unit_results": [],
            "executed_install_unit_ids": [],
            "failed_install_units": [],
            "success_count": 0,
            "failure_count": 0,
            "precheck_success_count": 0,
            "precheck_failure_count": 0,
            "update_success_count": 0,
            "update_failure_count": 0,
            "revision_capture_enabled_install_unit_total": 0,
            "revision_changed_source_total": 0,
            "revision_unchanged_source_total": 0,
            "revision_unknown_source_total": 0,
            "revision_capture_failed_source_total": 0,
            "revision_changed_install_unit_ids": [],
            "rollback_preview_install_unit_total": 0,
            "rollback_preview_candidate_total": 0,
            "synced_source_ids": [],
            "failed_sources": [],
            "source_sync_install_unit_total": 0,
            "source_sync_success_count": 0,
            "source_sync_failure_count": 0,
            "source_sync_cache_hit_total": 0,
        }

    def _merge_install_unit_execution_summaries(
        self,
        summaries: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        merged = self._empty_install_unit_execution_summary()
        for summary in summaries or []:
            if not isinstance(summary, dict):
                continue
            merged["results"].extend(
                [item for item in summary.get("results", []) if isinstance(item, dict)],
            )
            merged["install_unit_results"].extend(
                [item for item in summary.get("install_unit_results", []) if isinstance(item, dict)],
            )
            merged["failed_install_units"].extend(
                [item for item in summary.get("failed_install_units", []) if isinstance(item, dict)],
            )
            merged["failed_sources"].extend(
                [item for item in summary.get("failed_sources", []) if isinstance(item, dict)],
            )

            merged["executed_install_unit_ids"] = _dedupe_keep_order(
                merged["executed_install_unit_ids"] + _to_str_list(summary.get("executed_install_unit_ids", [])),
            )
            merged["revision_changed_install_unit_ids"] = _dedupe_keep_order(
                merged["revision_changed_install_unit_ids"] + _to_str_list(summary.get("revision_changed_install_unit_ids", [])),
            )
            merged["synced_source_ids"] = _dedupe_keep_order(
                merged["synced_source_ids"] + _to_str_list(summary.get("synced_source_ids", [])),
            )

            for numeric_key in (
                "success_count",
                "failure_count",
                "precheck_success_count",
                "precheck_failure_count",
                "update_success_count",
                "update_failure_count",
                "revision_capture_enabled_install_unit_total",
                "revision_changed_source_total",
                "revision_unchanged_source_total",
                "revision_unknown_source_total",
                "revision_capture_failed_source_total",
                "rollback_preview_install_unit_total",
                "rollback_preview_candidate_total",
                "source_sync_install_unit_total",
                "source_sync_success_count",
                "source_sync_failure_count",
                "source_sync_cache_hit_total",
            ):
                merged[numeric_key] = int(merged.get(numeric_key, 0) or 0) + int(summary.get(numeric_key, 0) or 0)

        return merged

    @staticmethod
    def _build_update_all_grouped_count_rows(
        rows: list[dict[str, Any]] | None,
        *,
        group_key: str,
        id_key: str = "install_unit_id",
        name_key: str = "display_name",
        fallback_value: str = "unknown",
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            raw_value = str(item.get(group_key) or "").strip().lower()
            bucket_key = raw_value or fallback_value
            bucket = buckets.setdefault(
                bucket_key,
                {
                    group_key: bucket_key,
                    "count": 0,
                    "install_unit_ids": [],
                    "display_names": [],
                },
            )
            bucket["count"] = int(bucket.get("count", 0) or 0) + 1
            install_unit_id = str(item.get(id_key) or "").strip()
            display_name = str(item.get(name_key) or install_unit_id or "").strip()
            if install_unit_id:
                bucket["install_unit_ids"] = _dedupe_keep_order(
                    _to_str_list(bucket.get("install_unit_ids", [])) + [install_unit_id],
                )
            if display_name:
                bucket["display_names"] = _dedupe_keep_order(
                    _to_str_list(bucket.get("display_names", [])) + [display_name],
                )
        return sorted(
            list(buckets.values()),
            key=lambda item: (
                -_to_int(item.get("count", 0), 0, 0),
                str(item.get(group_key) or "").strip(),
            ),
        )

    def _summarize_update_all_failure_taxonomy(
        self,
        *,
        failed_install_units: list[dict[str, Any]] | None,
        install_unit_results: list[dict[str, Any]] | None,
        blocked_unit_plans: list[dict[str, Any]] | None,
        failed_sources: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        failed_install_unit_index: dict[str, dict[str, Any]] = {}
        for item in failed_install_units or []:
            if not isinstance(item, dict):
                continue
            install_unit_id = str(item.get("install_unit_id") or "").strip()
            if install_unit_id:
                failed_install_unit_index[install_unit_id] = item

        failed_install_unit_rows = [
            {
                "install_unit_id": install_unit_id,
                "display_name": str(
                    item.get("display_name")
                    or failed_install_unit_index.get(install_unit_id, {}).get("display_name")
                    or item.get("install_unit_id")
                    or "install unit"
                ).strip(),
                "manager": str(
                    item.get("manager")
                    or failed_install_unit_index.get(install_unit_id, {}).get("manager")
                    or ""
                ).strip().lower()
                or "unknown",
                "policy": str(
                    item.get("policy")
                    or failed_install_unit_index.get(install_unit_id, {}).get("policy")
                    or ""
                ).strip().lower()
                or "unknown",
                "failure_reason": str(
                    item.get("failure_reason")
                    or failed_install_unit_index.get(install_unit_id, {}).get("reason_code")
                    or failed_install_unit_index.get(install_unit_id, {}).get("reason")
                    or ""
                ).strip().lower()
                or "unknown",
            }
            for item in (install_unit_results or [])
            if isinstance(item, dict)
            and not _to_bool(item.get("ok", False), False)
            and str(item.get("install_unit_id") or "").strip()
            for install_unit_id in [str(item.get("install_unit_id") or "").strip()]
        ]
        blocked_rows = [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "display_name": str(
                    item.get("display_name")
                    or item.get("install_unit_display_name")
                    or item.get("install_unit_id")
                    or "install unit"
                ).strip(),
                "reason_code": str(item.get("reason_code") or "").strip().lower() or "unknown",
            }
            for item in (blocked_unit_plans or [])
            if isinstance(item, dict)
        ]
        failed_source_rows = [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "display_name": str(item.get("display_name") or item.get("source_id") or "source").strip(),
                "sync_error_code": str(item.get("sync_error_code") or "").strip().lower()
                or str(item.get("sync_status") or "").strip().lower()
                or "unknown",
            }
            for item in (failed_sources or [])
            if isinstance(item, dict)
        ]
        return {
            "failed_install_unit_total": len(failed_install_unit_rows),
            "failed_install_unit_reason_groups": self._build_update_all_grouped_count_rows(
                failed_install_unit_rows,
                group_key="failure_reason",
            ),
            "failed_install_unit_manager_groups": self._build_update_all_grouped_count_rows(
                failed_install_unit_rows,
                group_key="manager",
            ),
            "blocked_install_unit_total": len(blocked_rows),
            "blocked_reason_groups": self._build_update_all_grouped_count_rows(
                blocked_rows,
                group_key="reason_code",
            ),
            "failed_source_total": len(failed_source_rows),
            "failed_source_sync_error_groups": self._build_update_all_grouped_count_rows(
                failed_source_rows,
                group_key="sync_error_code",
            ),
        }

    def _execute_install_unit_source_sync_plans(
        self,
        update_plans: list[dict[str, Any]] | None,
        source_rows: list[dict[str, Any]] | None,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        plans = [item for item in (update_plans or []) if isinstance(item, dict)]
        if not plans:
            return self._empty_install_unit_execution_summary()

        source_index = self._build_source_index_by_id(source_rows)
        install_unit_results: list[dict[str, Any]] = []
        phase_results: list[dict[str, Any]] = []
        executed_install_unit_ids: list[str] = []
        failed_install_units: list[dict[str, Any]] = []
        synced_source_ids: list[str] = []
        failed_sources: list[dict[str, Any]] = []
        source_sync_record_cache: dict[str, dict[str, Any]] = {}
        source_sync_cache_hit_total = 0
        batch_checked_at = _now_iso()

        for plan in plans:
            install_unit_id = str(plan.get("install_unit_id") or "").strip()
            display_name = str(plan.get("display_name") or install_unit_id or "install unit").strip()
            plan_source_rows = self._resolve_plan_source_rows(plan, source_index)
            plan_results: list[dict[str, Any]] = []

            if not plan_source_rows:
                failed_install_units.append(
                    {
                        "install_unit_id": install_unit_id,
                        "reason": "source_sync_rows_missing",
                        "reason_code": "source_sync_rows_missing",
                        "display_name": display_name,
                        "manager": str(plan.get("manager") or "").strip(),
                        "policy": str(plan.get("policy") or "").strip(),
                        "message": f"source sync failed for {install_unit_id or 'install unit'}: no source members",
                    },
                )
                install_unit_results.append(
                    {
                        "install_unit_id": install_unit_id,
                        "display_name": display_name,
                        "manager": str(plan.get("manager") or "").strip(),
                        "policy": str(plan.get("policy") or "").strip(),
                        "precheck_commands": [],
                        "precheck_command_count": 0,
                        "commands": [],
                        "command_count": 0,
                        "results": [],
                        "ok": False,
                        "failure_reason": "source_sync_rows_missing",
                        "skipped_update_commands": True,
                        "revision_capture": {
                            "enabled": False,
                            "source_total": 0,
                            "changed_source_ids": [],
                            "changed_total": 0,
                            "unchanged_source_ids": [],
                            "unchanged_total": 0,
                            "unknown_source_ids": [],
                            "unknown_total": 0,
                            "changed": False,
                            "before": [],
                            "after": [],
                            "failed_sources": [],
                        },
                        "rollback_preview": {
                            "supported": False,
                            "candidate_total": 0,
                            "candidates": [],
                            "skipped_sources": [],
                            "warning": "",
                        },
                    },
                )
                if install_unit_id:
                    executed_install_unit_ids.append(install_unit_id)
                if callable(progress_callback):
                    try:
                        progress_callback(
                            {
                                "completed_install_unit_total": len(install_unit_results),
                                "failed_install_unit_total": len(failed_install_units),
                                "source_sync_cache_hit_total": source_sync_cache_hit_total,
                            },
                        )
                    except Exception:
                        pass
                continue

            unit_failed_sources: list[dict[str, Any]] = []
            for source in plan_source_rows:
                source_id = _normalize_inventory_id(source.get("source_id", ""), default="")
                if not source_id:
                    continue
                source_with_checkout = self._augment_source_row_with_git_checkout(source)
                cache_key = build_source_sync_cache_key(source_with_checkout)
                sync_record = source_sync_record_cache.get(cache_key) if cache_key else None
                if isinstance(sync_record, dict):
                    source_sync_cache_hit_total += 1
                else:
                    sync_record = build_source_sync_record(
                        source_with_checkout,
                        checked_at=batch_checked_at,
                    )
                    if cache_key:
                        source_sync_record_cache[cache_key] = dict(sync_record)
                self._update_saved_registry_source_metadata(
                    source_id=source_id,
                    source_payload=source_with_checkout,
                    sync_payload=sync_record,
                )
                sync_status = str(sync_record.get("sync_status") or "").strip()
                sync_ok = sync_status == "ok"
                sync_message = str(sync_record.get("sync_message") or "").strip()
                result_payload = {
                    "install_unit_id": install_unit_id,
                    "source_id": source_id,
                    "command": f"source_sync:{source_id}",
                    "phase": "source_sync",
                    "exit_code": 0 if sync_ok else 1,
                    "stdout": "",
                    "stderr": "" if sync_ok else sync_message,
                    "duration_s": 0.0,
                    "timed_out": False,
                    "ok": sync_ok,
                    "sync_status": sync_status,
                    "sync_error_code": str(sync_record.get("sync_error_code") or "").strip(),
                    "sync_message": sync_message,
                }
                plan_results.append(result_payload)
                phase_results.append(result_payload)
                if sync_ok:
                    synced_source_ids.append(source_id)
                    continue
                failed_payload = {
                    "install_unit_id": install_unit_id,
                    "display_name": display_name,
                    "source_id": source_id,
                    "sync_status": sync_status,
                    "sync_error_code": str(sync_record.get("sync_error_code") or "").strip(),
                    "sync_message": sync_message,
                }
                unit_failed_sources.append(failed_payload)
                failed_sources.append(failed_payload)

            plan_ok = bool(plan_results) and not unit_failed_sources
            if install_unit_id:
                executed_install_unit_ids.append(install_unit_id)
            install_unit_results.append(
                {
                    "install_unit_id": install_unit_id,
                    "display_name": display_name,
                    "manager": str(plan.get("manager") or "").strip(),
                    "policy": str(plan.get("policy") or "").strip(),
                    "precheck_commands": [],
                    "precheck_command_count": 0,
                    "commands": [],
                    "command_count": 0,
                    "results": plan_results,
                    "ok": plan_ok,
                    "failure_reason": "" if plan_ok else "source_sync_failed",
                    "skipped_update_commands": True,
                    "revision_capture": {
                        "enabled": False,
                        "source_total": 0,
                        "changed_source_ids": [],
                        "changed_total": 0,
                        "unchanged_source_ids": [],
                        "unchanged_total": 0,
                        "unknown_source_ids": [],
                        "unknown_total": 0,
                        "changed": False,
                        "before": [],
                        "after": [],
                        "failed_sources": [],
                    },
                    "rollback_preview": {
                        "supported": False,
                        "candidate_total": 0,
                        "candidates": [],
                        "skipped_sources": [],
                        "warning": "",
                    },
                },
            )
            if not plan_ok:
                failed_install_units.append(
                    {
                        "install_unit_id": install_unit_id,
                        "reason": "source_sync_failed",
                        "reason_code": "source_sync_failed",
                        "display_name": display_name,
                        "manager": str(plan.get("manager") or "").strip(),
                        "policy": str(plan.get("policy") or "").strip(),
                        "message": f"source sync failed for {install_unit_id or 'install unit'}",
                    },
                )
            if callable(progress_callback):
                try:
                    progress_callback(
                        {
                            "completed_install_unit_total": len(install_unit_results),
                            "failed_install_unit_total": len(failed_install_units),
                            "source_sync_cache_hit_total": source_sync_cache_hit_total,
                        },
                    )
                except Exception:
                    pass

        source_sync_success_count = sum(1 for item in phase_results if item.get("ok"))
        source_sync_failure_count = len(phase_results) - source_sync_success_count
        return {
            "results": phase_results,
            "install_unit_results": install_unit_results,
            "executed_install_unit_ids": executed_install_unit_ids,
            "failed_install_units": failed_install_units,
            "success_count": source_sync_success_count,
            "failure_count": source_sync_failure_count,
            "precheck_success_count": 0,
            "precheck_failure_count": 0,
            "update_success_count": source_sync_success_count,
            "update_failure_count": source_sync_failure_count,
            "revision_capture_enabled_install_unit_total": 0,
            "revision_changed_source_total": 0,
            "revision_unchanged_source_total": 0,
            "revision_unknown_source_total": 0,
            "revision_capture_failed_source_total": 0,
            "revision_changed_install_unit_ids": [],
            "rollback_preview_install_unit_total": 0,
            "rollback_preview_candidate_total": 0,
            "synced_source_ids": synced_source_ids,
            "failed_sources": failed_sources,
            "source_sync_install_unit_total": len(install_unit_results),
            "source_sync_success_count": source_sync_success_count,
            "source_sync_failure_count": source_sync_failure_count,
            "source_sync_cache_hit_total": source_sync_cache_hit_total,
        }

    def _capture_git_revisions_for_sources(
        self,
        source_rows: list[dict[str, Any]] | None,
        *,
        persist_sync_metadata: bool = False,
    ) -> dict[str, Any]:
        rows = [item for item in (source_rows or []) if isinstance(item, dict)]
        captured_rows: list[dict[str, Any]] = []
        failed_sources: list[dict[str, Any]] = []
        for source in rows:
            source_id = _normalize_inventory_id(source.get("source_id", ""), default="")
            if not source_id:
                continue
            source_with_checkout = self._augment_source_row_with_git_checkout(source)
            source_for_capture = {
                **source_with_checkout,
                "source_id": source_id,
                # Revision capture only cares about local checkout state and should not block on remote lookups.
                "locator": "",
                "registry_package_name": "",
                "registry_package_manager": "",
            }
            sync_record = build_source_sync_record(source_for_capture)
            if persist_sync_metadata:
                self._update_saved_registry_source_metadata(
                    source_id=source_id,
                    source_payload=source_with_checkout,
                    sync_payload=sync_record,
                )
            captured = {
                "source_id": source_id,
                "sync_status": str(sync_record.get("sync_status") or ""),
                "sync_error_code": str(sync_record.get("sync_error_code") or ""),
                "sync_message": str(sync_record.get("sync_message") or ""),
                "sync_local_revision": str(sync_record.get("sync_local_revision") or ""),
                "sync_remote_revision": str(sync_record.get("sync_remote_revision") or ""),
                "sync_resolved_revision": str(sync_record.get("sync_resolved_revision") or ""),
                "sync_branch": str(sync_record.get("sync_branch") or ""),
                "sync_dirty": _to_bool(sync_record.get("sync_dirty", False), False),
            }
            captured_rows.append(captured)
            if captured["sync_status"] != "ok":
                failed_sources.append(
                    {
                        "source_id": source_id,
                        "sync_status": captured["sync_status"],
                        "sync_error_code": captured["sync_error_code"],
                        "sync_message": captured["sync_message"],
                    },
                )

        return {
            "rows": captured_rows,
            "failed_sources": failed_sources,
        }

    def _payload_confirms_skills_rollback(self, payload: dict[str, Any] | None) -> bool:
        body = payload if isinstance(payload, dict) else {}
        if not _to_bool(body.get("execute", False), False):
            return False
        provided = str(body.get("confirm") or "").strip()
        return secrets.compare_digest(provided, SKILLS_ROLLBACK_CONFIRM_TOKEN)

    def _extract_before_revision_rows(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        body = payload if isinstance(payload, dict) else {}
        raw_rows = body.get("before_revisions", [])
        if isinstance(raw_rows, dict):
            raw_rows = [
                {
                    "source_id": key,
                    "revision": value,
                }
                for key, value in raw_rows.items()
            ]
        rows = raw_rows if isinstance(raw_rows, list) else []

        if not rows:
            rollback_preview = body.get("rollback_preview", {})
            if isinstance(rollback_preview, dict):
                preview_rows = rollback_preview.get("candidates", [])
                rows = preview_rows if isinstance(preview_rows, list) else []

        normalized_rows: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            revision = str(
                item.get("revision")
                or item.get("before_revision")
                or item.get("sync_resolved_revision")
                or "",
            ).strip()
            if not source_id or not revision or source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            normalized_rows.append(
                {
                    "source_id": source_id,
                    "sync_resolved_revision": revision,
                },
            )
        return normalized_rows

    async def _execute_rollback_preview_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        source_rows: list[dict[str, Any]] | None = None,
        before_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        command_results: list[dict[str, Any]] = []
        source_results: list[dict[str, Any]] = []
        executed_source_ids: list[str] = []
        failed_sources: list[dict[str, Any]] = []

        for item in candidates:
            if not isinstance(item, dict):
                continue
            source_id = _normalize_inventory_id(item.get("source_id", ""), default="")
            command = str(item.get("command") or "").strip()
            precheck_commands = _to_str_list(item.get("precheck_commands", []))
            if not source_id or not command:
                continue
            executed_source_ids.append(source_id)
            source_command_results: list[dict[str, Any]] = []
            precheck_failed = False
            failure_reason = ""

            for precheck in precheck_commands:
                result = await self.runner.run(precheck, timeout_s=180)
                result_payload = {
                    "source_id": source_id,
                    "phase": "precheck",
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_s": result.duration_s,
                    "timed_out": result.timed_out,
                    "ok": result.exit_code == 0 and not result.timed_out,
                }
                source_command_results.append(result_payload)
                command_results.append(result_payload)
                if not result_payload.get("ok"):
                    precheck_failed = True
                    failure_reason = "precheck_failed"
                    break

            if not precheck_failed:
                result = await self.runner.run(command, timeout_s=900)
                result_payload = {
                    "source_id": source_id,
                    "phase": "rollback",
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_s": result.duration_s,
                    "timed_out": result.timed_out,
                    "ok": result.exit_code == 0 and not result.timed_out,
                }
                source_command_results.append(result_payload)
                command_results.append(result_payload)
                if not result_payload.get("ok"):
                    failure_reason = "rollback_failed"

            source_ok = bool(source_command_results) and all(item.get("ok") for item in source_command_results)
            source_result = {
                "source_id": source_id,
                "source_path": str(item.get("source_path") or ""),
                "before_revision": str(item.get("before_revision") or ""),
                "command": command,
                "precheck_commands": precheck_commands,
                "results": source_command_results,
                "ok": source_ok,
                "failure_reason": failure_reason if not source_ok else "",
            }
            source_results.append(source_result)
            if not source_ok:
                if not failure_reason:
                    failure_reason = "rollback_failed"
                failed_sources.append(
                    {
                        "source_id": source_id,
                        "reason": failure_reason,
                        "message": (
                            f"rollback precheck failed for {source_id}"
                            if failure_reason == "precheck_failed"
                            else f"rollback command failed for {source_id}"
                        ),
                    },
                )

        success_count = sum(1 for item in command_results if item.get("ok"))
        failure_count = len(command_results) - success_count

        target_source_ids = {
            _normalize_inventory_id(item.get("source_id", ""), default="")
            for item in candidates
            if isinstance(item, dict) and _normalize_inventory_id(item.get("source_id", ""), default="")
        }
        target_source_rows = [
            item
            for item in (source_rows or [])
            if isinstance(item, dict)
            and _normalize_inventory_id(item.get("source_id", ""), default="") in target_source_ids
        ]
        after_capture = self._capture_git_revisions_for_sources(
            target_source_rows,
            persist_sync_metadata=True,
        )
        restore_delta = summarize_revision_capture_delta(before_rows or [], after_capture.get("rows", []))
        restored_source_ids = _to_str_list(restore_delta.get("unchanged_source_ids", []))
        not_restored_source_ids = _dedupe_keep_order(
            _to_str_list(restore_delta.get("changed_source_ids", []))
            + _to_str_list(restore_delta.get("unknown_source_ids", [])),
        )

        return {
            "results": command_results,
            "source_results": source_results,
            "executed_source_ids": _dedupe_keep_order(executed_source_ids),
            "failed_sources": failed_sources,
            "success_count": success_count,
            "failure_count": failure_count,
            "restore_capture": {
                "before": before_rows or [],
                "after": after_capture.get("rows", []),
                "failed_sources": after_capture.get("failed_sources", []),
                **restore_delta,
            },
            "restored_source_ids": restored_source_ids,
            "restored_source_total": len(restored_source_ids),
            "not_restored_source_ids": not_restored_source_ids,
            "not_restored_source_total": len(not_restored_source_ids),
        }

    async def _execute_install_unit_update_plans(
        self,
        update_plans: list[dict[str, Any]],
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        skills_snapshot = self.webui_get_skills_payload()
        source_index = self._build_source_index_by_id(skills_snapshot.get("source_rows", []))
        install_unit_results: list[dict[str, Any]] = []
        command_results: list[dict[str, Any]] = []
        executed_install_unit_ids: list[str] = []
        failed_install_units: list[dict[str, Any]] = []

        for plan in update_plans:
            if not isinstance(plan, dict) or not plan.get("supported"):
                continue
            precheck_commands = _to_str_list(plan.get("precheck_commands", []))
            commands = _to_str_list(plan.get("commands", []))
            if not commands:
                continue
            install_unit_id = str(plan.get("install_unit_id") or "").strip()
            plan_results: list[dict[str, Any]] = []
            manager = str(plan.get("manager") or "").strip().lower()
            precheck_timeout_s = 180 if manager == "git" else 120
            update_timeout_s = 1800 if manager == "git" else 900
            precheck_failed = False
            failure_reason = ""
            plan_source_rows = self._resolve_plan_source_rows(plan, source_index)
            before_revision_capture = {"rows": [], "failed_sources": []}
            after_revision_capture = {"rows": [], "failed_sources": []}
            revision_delta = summarize_revision_capture_delta([], [])
            rollback_preview = {
                "supported": False,
                "candidate_total": 0,
                "candidates": [],
                "skipped_sources": [],
                "warning": "",
            }

            if manager == "git" and plan_source_rows:
                before_revision_capture = self._capture_git_revisions_for_sources(
                    plan_source_rows,
                    persist_sync_metadata=False,
                )

            for command in precheck_commands:
                result = await self.runner.run(command, timeout_s=precheck_timeout_s)
                result_payload = {
                    "install_unit_id": install_unit_id,
                    "command": result.command,
                    "phase": "precheck",
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_s": result.duration_s,
                    "timed_out": result.timed_out,
                    "ok": result.exit_code == 0 and not result.timed_out,
                }
                plan_results.append(result_payload)
                command_results.append(result_payload)
                if not result_payload.get("ok"):
                    precheck_failed = True
                    failure_reason = "precheck_failed"
                    break

            if not precheck_failed:
                for command in commands:
                    result = await self.runner.run(command, timeout_s=update_timeout_s)
                    result_payload = {
                        "install_unit_id": install_unit_id,
                        "command": result.command,
                        "phase": "update",
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "duration_s": result.duration_s,
                        "timed_out": result.timed_out,
                        "ok": result.exit_code == 0 and not result.timed_out,
                    }
                    plan_results.append(result_payload)
                    command_results.append(result_payload)
                    if result_payload.get("ok"):
                        continue

                    manager_for_fallback = str(plan.get("manager") or "").strip().lower()
                    if (
                        manager_for_fallback in {"bunx", "npx", "pnpm", "npm"}
                        and _looks_like_command_not_found(result_payload)
                    ):
                        result_payload["ignored"] = True
                        result_payload["fallback_reason"] = "primary_command_unavailable"
                        fallback_commands = _build_registry_fallback_commands(plan, command)
                        fallback_succeeded = False
                        fallback_attempt_payloads: list[dict[str, Any]] = []
                        for fallback_command in fallback_commands:
                            fallback_result = await self.runner.run(fallback_command, timeout_s=update_timeout_s)
                            fallback_payload = {
                                "install_unit_id": install_unit_id,
                                "command": fallback_result.command,
                                "phase": "update_fallback",
                                "exit_code": fallback_result.exit_code,
                                "stdout": fallback_result.stdout,
                                "stderr": fallback_result.stderr,
                                "duration_s": fallback_result.duration_s,
                                "timed_out": fallback_result.timed_out,
                                "ok": fallback_result.exit_code == 0 and not fallback_result.timed_out,
                                "fallback_from": result.command,
                            }
                            plan_results.append(fallback_payload)
                            command_results.append(fallback_payload)
                            fallback_attempt_payloads.append(fallback_payload)
                            if fallback_payload.get("ok"):
                                fallback_succeeded = True
                                for prior_attempt in fallback_attempt_payloads:
                                    if prior_attempt is fallback_payload:
                                        continue
                                    prior_attempt["ignored"] = True
                                    prior_attempt["fallback_superseded"] = True
                                break
                        if fallback_succeeded:
                            continue
                    failure_reason = "update_failed"

            if manager == "git" and plan_source_rows:
                after_revision_capture = self._capture_git_revisions_for_sources(
                    plan_source_rows,
                    persist_sync_metadata=True,
                )
                revision_delta = summarize_revision_capture_delta(
                    before_revision_capture.get("rows", []),
                    after_revision_capture.get("rows", []),
                )
                rollback_preview = build_git_rollback_preview(
                    plan_source_rows,
                    before_revision_capture.get("rows", []),
                    _to_str_list(revision_delta.get("changed_source_ids", [])),
                )

            effective_results = [
                item
                for item in plan_results
                if isinstance(item, dict) and not _to_bool(item.get("ignored", False), False)
            ]
            plan_ok = bool(effective_results) and all(item.get("ok") for item in effective_results)
            if plan_ok and plan_source_rows:
                self._stamp_registry_sources_refreshed(
                    plan_source_rows,
                    refreshed_at=_now_iso(),
                )
            if install_unit_id:
                executed_install_unit_ids.append(install_unit_id)
            install_unit_result = {
                "install_unit_id": install_unit_id,
                "display_name": str(plan.get("display_name") or install_unit_id or "").strip(),
                "manager": str(plan.get("manager") or "").strip(),
                "policy": str(plan.get("policy") or "").strip(),
                "precheck_commands": precheck_commands,
                "precheck_command_count": len(precheck_commands),
                "commands": commands,
                "command_count": len(commands),
                "results": plan_results,
                "ok": plan_ok,
                "failure_reason": failure_reason if not plan_ok else "",
                "skipped_update_commands": precheck_failed,
                "revision_capture": {
                    "enabled": bool(manager == "git" and plan_source_rows),
                    "source_total": int(revision_delta.get("source_total", 0)),
                    "changed_source_ids": _to_str_list(revision_delta.get("changed_source_ids", [])),
                    "changed_total": int(revision_delta.get("changed_total", 0)),
                    "unchanged_source_ids": _to_str_list(revision_delta.get("unchanged_source_ids", [])),
                    "unchanged_total": int(revision_delta.get("unchanged_total", 0)),
                    "unknown_source_ids": _to_str_list(revision_delta.get("unknown_source_ids", [])),
                    "unknown_total": int(revision_delta.get("unknown_total", 0)),
                    "changed": _to_bool(revision_delta.get("changed", False), False),
                    "before": before_revision_capture.get("rows", []),
                    "after": after_revision_capture.get("rows", []),
                    "failed_sources": after_revision_capture.get("failed_sources", []),
                },
                "rollback_preview": rollback_preview,
            }
            install_unit_results.append(install_unit_result)
            if not plan_ok:
                if not failure_reason:
                    failure_reason = "update_failed"
                if failure_reason == "precheck_failed":
                    failed_message = f"precheck failed for {install_unit_id or 'install unit'}"
                else:
                    failed_message = f"update command failed for {install_unit_id or 'install unit'}"
                failed_install_units.append(
                    {
                        "install_unit_id": install_unit_id,
                        "reason": failure_reason,
                        "reason_code": failure_reason,
                        "display_name": str(plan.get("display_name") or install_unit_id or "").strip(),
                        "manager": str(plan.get("manager") or "").strip(),
                        "policy": str(plan.get("policy") or "").strip(),
                        "message": failed_message,
                    },
                )
            if callable(progress_callback):
                try:
                    progress_callback(
                        {
                            "completed_install_unit_total": len(install_unit_results),
                            "failed_install_unit_total": len(failed_install_units),
                        },
                    )
                except Exception:
                    pass

        effective_command_results = [
            item
            for item in command_results
            if isinstance(item, dict) and not _to_bool(item.get("ignored", False), False)
        ]
        success_count = sum(1 for item in effective_command_results if item.get("ok"))
        failure_count = len(effective_command_results) - success_count
        precheck_success_count = sum(
            1
            for item in effective_command_results
            if str(item.get("phase") or "").strip() == "precheck" and item.get("ok")
        )
        precheck_failure_count = sum(
            1
            for item in effective_command_results
            if str(item.get("phase") or "").strip() == "precheck" and not item.get("ok")
        )
        update_success_count = sum(
            1
            for item in effective_command_results
            if str(item.get("phase") or "").strip() in {"update", "update_fallback"} and item.get("ok")
        )
        update_failure_count = sum(
            1
            for item in effective_command_results
            if str(item.get("phase") or "").strip() in {"update", "update_fallback"} and not item.get("ok")
        )
        revision_capture_enabled_install_unit_total = sum(
            1
            for item in install_unit_results
            if _to_bool((item.get("revision_capture", {}) or {}).get("enabled", False), False)
        )
        revision_changed_source_total = sum(
            int((item.get("revision_capture", {}) or {}).get("changed_total", 0))
            for item in install_unit_results
        )
        revision_unchanged_source_total = sum(
            int((item.get("revision_capture", {}) or {}).get("unchanged_total", 0))
            for item in install_unit_results
        )
        revision_unknown_source_total = sum(
            int((item.get("revision_capture", {}) or {}).get("unknown_total", 0))
            for item in install_unit_results
        )
        revision_capture_failed_source_total = sum(
            len(
                [
                    str(row.get("source_id") or "").strip()
                    for row in (item.get("revision_capture", {}) or {}).get("failed_sources", [])
                    if isinstance(row, dict) and str(row.get("source_id") or "").strip()
                ],
            )
            for item in install_unit_results
        )
        revision_changed_install_unit_ids = _dedupe_keep_order(
            [
                str(item.get("install_unit_id") or "").strip()
                for item in install_unit_results
                if _to_bool((item.get("revision_capture", {}) or {}).get("changed", False), False)
                and str(item.get("install_unit_id") or "").strip()
            ],
        )
        rollback_preview_install_unit_total = sum(
            1
            for item in install_unit_results
            if _to_bool((item.get("rollback_preview", {}) or {}).get("supported", False), False)
        )
        rollback_preview_candidate_total = sum(
            int((item.get("rollback_preview", {}) or {}).get("candidate_total", 0))
            for item in install_unit_results
        )
        return {
            "results": command_results,
            "install_unit_results": install_unit_results,
            "executed_install_unit_ids": executed_install_unit_ids,
            "failed_install_units": failed_install_units,
            "success_count": success_count,
            "failure_count": failure_count,
            "precheck_success_count": precheck_success_count,
            "precheck_failure_count": precheck_failure_count,
            "update_success_count": update_success_count,
            "update_failure_count": update_failure_count,
            "revision_capture_enabled_install_unit_total": revision_capture_enabled_install_unit_total,
            "revision_changed_source_total": revision_changed_source_total,
            "revision_unchanged_source_total": revision_unchanged_source_total,
            "revision_unknown_source_total": revision_unknown_source_total,
            "revision_capture_failed_source_total": revision_capture_failed_source_total,
            "revision_changed_install_unit_ids": revision_changed_install_unit_ids,
            "rollback_preview_install_unit_total": rollback_preview_install_unit_total,
            "rollback_preview_candidate_total": rollback_preview_candidate_total,
        }

    async def webui_update_install_unit(
        self,
        install_unit_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = payload if isinstance(payload, dict) else {}
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context

        plan = build_install_unit_update_plan(
            context.get("install_unit", {}),
            context.get("source_rows", []),
        )
        if not plan.get("supported"):
            syncable_status = self._classify_syncable_source_rows(context.get("source_rows", []))
            if syncable_status.get("all_syncable"):
                sync_response = self.webui_sync_install_unit(install_unit_id)
                if sync_response.get("ok"):
                    normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
                    sync_update_summary = {
                        **plan,
                        "supported": True,
                        "fallback_mode": "source_sync",
                        "message": (
                            "install unit update fallback executed as source sync: "
                            f"{normalized_install_unit_id}"
                        ),
                        "syncable_source_ids": syncable_status.get("syncable_source_ids", []),
                        "non_syncable_source_ids": syncable_status.get("non_syncable_source_ids", []),
                        "synced_source_ids": sync_response.get("synced_source_ids", []),
                        "failed_sources": sync_response.get("failed_sources", []),
                    }
                    sync_response["update"] = sync_update_summary
                    sync_response["updated_install_unit_ids"] = [normalized_install_unit_id]
                    sync_response["failed_install_units"] = []
                    audit_event_id = self._append_skills_audit_event(
                        "install_unit_update_fallback_sync",
                        source_id=normalized_install_unit_id,
                        payload={
                            "syncable_source_ids": syncable_status.get("syncable_source_ids", []),
                            "failed_sources": sync_response.get("failed_sources", []),
                        },
                    )
                    sync_update_summary["audit_event_id"] = audit_event_id
                    sync_response["audit_event_id"] = audit_event_id
                    return sync_response
            return {
                "ok": False,
                "message": str(plan.get("message") or f"update unsupported for install unit: {install_unit_id}"),
                "update": plan,
                "syncable_source_ids": syncable_status.get("syncable_source_ids", []),
                "non_syncable_source_ids": syncable_status.get("non_syncable_source_ids", []),
            }

        execution = await self._execute_install_unit_update_plans([plan])
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        update_summary = {
            **plan,
            **execution,
            "message": (
                "install unit update finished: "
                f"{execution.get('success_count', 0)} commands ok, "
                f"{execution.get('failure_count', 0)} failed, "
                f"{execution.get('revision_changed_source_total', 0)} source revisions changed"
            ),
        }
        audit_event_id = self._append_skills_audit_event(
            "install_unit_update",
            source_id=normalized_install_unit_id,
            payload={
                "precheck_commands": _to_str_list(plan.get("precheck_commands", [])),
                "commands": _to_str_list(plan.get("commands", [])),
                "success_count": execution.get("success_count", 0),
                "failure_count": execution.get("failure_count", 0),
                "precheck_failure_count": execution.get("precheck_failure_count", 0),
                "revision_changed_source_total": execution.get("revision_changed_source_total", 0),
                "revision_unchanged_source_total": execution.get("revision_unchanged_source_total", 0),
                "revision_unknown_source_total": execution.get("revision_unknown_source_total", 0),
                "rollback_preview_candidate_total": execution.get("rollback_preview_candidate_total", 0),
            },
        )
        update_summary["audit_event_id"] = audit_event_id
        self._push_debug_log(
            "info" if not execution.get("failure_count") else "warn",
            (
                "install unit updated: "
                f"install_unit={normalized_install_unit_id} "
                f"ok={execution.get('success_count', 0)} "
                f"failed={execution.get('failure_count', 0)}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "update": update_summary,
                "updated_install_unit_ids": execution.get("executed_install_unit_ids", []),
                "failed_install_units": execution.get("failed_install_units", []),
                "audit_event_id": audit_event_id,
            },
        )

    async def webui_update_collection_group(
        self,
        collection_group_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = payload if isinstance(payload, dict) else {}
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context

        plan = self._build_effective_collection_group_update_plan(
            collection_group=context.get("collection_group", {}),
            install_unit_rows=context.get("install_unit_rows", []),
            source_rows=context.get("source_rows", []),
        )
        if not _to_bool(plan.get("actionable"), False):
            return {
                "ok": False,
                "message": str(plan.get("message") or f"update unsupported for collection group: {collection_group_id}"),
                "update": plan,
                "syncable_source_ids": _to_str_list(plan.get("syncable_source_ids", [])),
                "non_syncable_source_ids": _to_str_list(plan.get("non_syncable_source_ids", [])),
            }

        actionable_unit_plans = [
            item
            for item in plan.get("install_unit_plans", [])
            if isinstance(item, dict) and _to_bool(item.get("actionable"), False)
        ]
        command_unit_plans = [
            item
            for item in actionable_unit_plans
            if _to_str_list(item.get("commands", []))
        ]
        source_sync_unit_plans = [
            item
            for item in actionable_unit_plans
            if self._is_source_sync_update_plan(item)
            and not _to_str_list(item.get("commands", []))
        ]
        command_execution = (
            await self._execute_install_unit_update_plans(command_unit_plans)
            if command_unit_plans
            else self._empty_install_unit_execution_summary()
        )
        source_sync_execution = self._execute_install_unit_source_sync_plans(
            source_sync_unit_plans,
            context.get("source_rows", []),
        )
        execution = self._merge_install_unit_execution_summaries(
            [command_execution, source_sync_execution],
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        command_install_unit_ids = _to_str_list(plan.get("command_install_unit_ids", []))
        source_sync_install_unit_ids = _to_str_list(plan.get("source_sync_install_unit_ids", []))
        skipped_install_unit_ids = _to_str_list(plan.get("skipped_install_unit_ids", []))
        skipped_manual_only_install_unit_ids = _to_str_list(plan.get("skipped_manual_only_install_unit_ids", []))
        skipped_other_install_unit_ids = _to_str_list(plan.get("skipped_other_install_unit_ids", []))
        executed_install_unit_ids = _to_str_list(execution.get("executed_install_unit_ids", []))
        source_sync_success_count = int(execution.get("source_sync_success_count", 0) or 0)
        source_sync_failure_count = int(execution.get("source_sync_failure_count", 0) or 0)
        update_summary = {
            **plan,
            **execution,
            "executed_install_unit_ids": executed_install_unit_ids,
            "executed_install_unit_total": len(executed_install_unit_ids),
            "command_install_unit_ids": command_install_unit_ids,
            "command_install_unit_total": len(command_install_unit_ids),
            "source_sync_install_unit_ids": source_sync_install_unit_ids,
            "source_sync_install_unit_total": len(source_sync_install_unit_ids),
            "skipped_install_unit_ids": skipped_install_unit_ids,
            "skipped_install_unit_total": len(skipped_install_unit_ids),
            "skipped_manual_only_install_unit_ids": skipped_manual_only_install_unit_ids,
            "skipped_manual_only_install_unit_total": len(skipped_manual_only_install_unit_ids),
            "skipped_other_install_unit_ids": skipped_other_install_unit_ids,
            "skipped_other_install_unit_total": len(skipped_other_install_unit_ids),
            "synced_source_ids": _to_str_list(execution.get("synced_source_ids", [])),
            "failed_sources": [
                item for item in execution.get("failed_sources", [])
                if isinstance(item, dict)
            ],
            "message": (
                "collection group update finished: "
                f"{execution.get('success_count', 0)} commands ok, "
                f"{execution.get('failure_count', 0)} failed, "
                f"{source_sync_success_count} source sync ok, "
                f"{source_sync_failure_count} source sync failed, "
                f"{execution.get('revision_changed_source_total', 0)} source revisions changed, "
                f"{plan.get('unsupported_install_unit_total', 0)} unsupported units"
            ),
        }
        audit_event_id = self._append_skills_audit_event(
            "collection_group_update",
            source_id=normalized_collection_group_id,
            payload={
                "install_unit_ids": execution.get("executed_install_unit_ids", []),
                "success_count": execution.get("success_count", 0),
                "failure_count": execution.get("failure_count", 0),
                "precheck_failure_count": execution.get("precheck_failure_count", 0),
                "revision_changed_source_total": execution.get("revision_changed_source_total", 0),
                "revision_unchanged_source_total": execution.get("revision_unchanged_source_total", 0),
                "revision_unknown_source_total": execution.get("revision_unknown_source_total", 0),
                "rollback_preview_candidate_total": execution.get("rollback_preview_candidate_total", 0),
                "source_sync_success_count": source_sync_success_count,
                "source_sync_failure_count": source_sync_failure_count,
                "unsupported_install_unit_total": plan.get("unsupported_install_unit_total", 0),
                "command_install_unit_total": len(command_install_unit_ids),
                "source_sync_install_unit_total": len(source_sync_install_unit_ids),
                "skipped_install_unit_total": len(skipped_install_unit_ids),
                "skipped_manual_only_install_unit_total": len(skipped_manual_only_install_unit_ids),
                "skipped_other_install_unit_total": len(skipped_other_install_unit_ids),
            },
        )
        update_summary["audit_event_id"] = audit_event_id
        self._push_debug_log(
            (
                "info"
                if (
                    not execution.get("failure_count")
                    and source_sync_failure_count == 0
                    and not plan.get("unsupported_install_unit_total")
                )
                else "warn"
            ),
            (
                "collection group updated: "
                f"collection_group={normalized_collection_group_id} "
                f"ok={execution.get('success_count', 0)} "
                f"failed={execution.get('failure_count', 0)} "
                f"sync_ok={source_sync_success_count} "
                f"sync_failed={source_sync_failure_count} "
                f"unsupported={plan.get('unsupported_install_unit_total', 0)}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "update": update_summary,
                "updated_install_unit_ids": executed_install_unit_ids,
                "failed_install_units": execution.get("failed_install_units", []),
                "unsupported_install_units": plan.get("unsupported_install_units", []),
                "skipped_install_unit_ids": skipped_install_unit_ids,
                "skipped_manual_only_install_unit_ids": skipped_manual_only_install_unit_ids,
                "skipped_other_install_unit_ids": skipped_other_install_unit_ids,
                "audit_event_id": audit_event_id,
            },
        )

    async def webui_update_all_skill_aggregates(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload if isinstance(payload, dict) else {}
        if self._skills_update_all_lock.locked():
            progress_payload = self.webui_get_update_all_aggregate_progress_payload()
            return {
                "ok": False,
                "message": "aggregate update-all already running",
                "progress": progress_payload.get("progress", {}),
            }

        async with self._skills_update_all_lock:
            return await self._webui_update_all_skill_aggregates_locked(
                body,
                workflow_kind="aggregate_update_all",
                reset_progress=True,
            )

    async def webui_improve_all_skills(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload if isinstance(payload, dict) else {}
        if self._skills_update_all_lock.locked():
            progress_payload = self.webui_get_update_all_aggregate_progress_payload()
            return {
                "ok": False,
                "message": "skills improve-all already running",
                "progress": progress_payload.get("progress", {}),
            }

        async with self._skills_update_all_lock:
            run_id = secrets.token_hex(8)
            started_at = _now_iso()
            refresh_strategy = self._normalize_install_atom_refresh_strategy(body.get("atom_refresh_strategy", "all"))
            self._replace_skills_update_all_progress_snapshot(
                self._build_skills_update_all_progress_snapshot(
                    run_id=run_id,
                    status="improving_atoms_planning",
                    workflow_kind="improve_all",
                    started_at=started_at,
                    message="building install atom improve plan",
                ),
            )

            try:
                skills_snapshot = self.webui_get_skills_payload()
                refresh_candidates = self._build_install_atom_refresh_candidates(
                    skills_snapshot,
                    strategy=refresh_strategy,
                )
                install_unit_ids = _to_str_list(refresh_candidates.get("install_unit_ids", []))
                rows_by_install_unit_id = refresh_candidates.get("rows_by_install_unit_id", {})
                if not isinstance(rows_by_install_unit_id, dict):
                    rows_by_install_unit_id = {}
                self._update_skills_update_all_progress_snapshot(
                    run_id=run_id,
                    status="improving_atoms_planning",
                    workflow_kind="improve_all",
                    started_at=started_at,
                    candidate_install_unit_total=len(install_unit_ids),
                    planned_install_unit_total=len(install_unit_ids),
                    actionable_install_unit_total=len(install_unit_ids),
                    command_install_unit_total=len(install_unit_ids),
                    source_sync_install_unit_total=0,
                    completed_command_install_unit_total=0,
                    completed_source_sync_install_unit_total=0,
                    skipped_install_unit_total=0,
                    failure_count=0,
                    success_count=0,
                    source_sync_cache_hit_total=0,
                    atom_candidate_install_unit_total=len(install_unit_ids),
                    atom_improved_count=0,
                    atom_unchanged_count=0,
                    message="install atom improve plan ready",
                )

                refreshed_skills_snapshot = skills_snapshot
                inventory_snapshot = self.webui_get_inventory_payload()
                success = 0
                failed = 0
                improved = 0
                unchanged = 0
                failed_items: list[dict[str, Any]] = []

                if install_unit_ids:
                    self._update_skills_update_all_progress_snapshot(
                        run_id=run_id,
                        status="improving_atoms_refreshing",
                        workflow_kind="improve_all",
                        started_at=started_at,
                        message=f"refreshing install atoms 0/{len(install_unit_ids)}",
                    )

                evidence_order = {
                    "unresolved": 0,
                    "heuristic": 1,
                    "strong": 2,
                    "explicit": 3,
                }
                for install_unit_id in install_unit_ids:
                    before_atom_row = self._install_atom_row_by_install_unit_id(
                        refreshed_skills_snapshot.get("install_atom_registry", {}),
                        install_unit_id,
                    )
                    try:
                        refresh_result = self.webui_refresh_install_unit(install_unit_id, {})
                        if not refresh_result.get("ok"):
                            raise RuntimeError(str(refresh_result.get("message") or f"refresh failed: {install_unit_id}"))
                        inventory_snapshot = refresh_result.get("inventory", inventory_snapshot)
                        refreshed_skills_snapshot = refresh_result.get("skills", refreshed_skills_snapshot)
                        success += 1
                        after_atom_row = self._install_atom_row_by_install_unit_id(
                            refreshed_skills_snapshot.get("install_atom_registry", {}),
                            install_unit_id,
                        )
                        if self._install_atom_refresh_improved(before_atom_row, after_atom_row):
                            improved += 1
                        else:
                            unchanged += 1
                    except Exception as exc:
                        failed += 1
                        candidate_rows = rows_by_install_unit_id.get(install_unit_id, [])
                        resolver_path_values = {
                            str(item.get("resolver_path") or "").strip()
                            for item in candidate_rows
                            if isinstance(item, dict) and str(item.get("resolver_path") or "").strip()
                        }
                        if len(resolver_path_values) == 1:
                            resolver_path = next(iter(resolver_path_values))
                        elif len(resolver_path_values) > 1:
                            resolver_path = "multi-install-units"
                        else:
                            resolver_path = "-"
                        evidence_candidates = [
                            str(item.get("evidence_level") or "unresolved").strip().lower() or "unresolved"
                            for item in candidate_rows
                            if isinstance(item, dict)
                        ]
                        evidence_level = (
                            sorted(evidence_candidates, key=lambda value: evidence_order.get(value, 99))[0]
                            if evidence_candidates
                            else "unresolved"
                        )
                        failed_items.append(
                            {
                                "installUnitId": install_unit_id,
                                "resolverPath": resolver_path,
                                "evidenceLevel": evidence_level,
                            },
                        )
                        self._push_debug_log(
                            "warn",
                            (
                                "install atom improve failed: "
                                f"run_id={run_id} install_unit={install_unit_id} error={exc}"
                            ),
                            source="webui",
                        )
                    finally:
                        self._update_skills_update_all_progress_snapshot(
                            run_id=run_id,
                            status="improving_atoms_refreshing",
                            workflow_kind="improve_all",
                            started_at=started_at,
                            candidate_install_unit_total=len(install_unit_ids),
                            planned_install_unit_total=len(install_unit_ids),
                            actionable_install_unit_total=len(install_unit_ids),
                            command_install_unit_total=len(install_unit_ids),
                            completed_command_install_unit_total=success + failed,
                            completed_source_sync_install_unit_total=0,
                            skipped_install_unit_total=0,
                            failure_count=failed,
                            success_count=success,
                            atom_candidate_install_unit_total=len(install_unit_ids),
                            atom_improved_count=improved,
                            atom_unchanged_count=unchanged,
                            message=f"refreshing install atoms {success + failed}/{len(install_unit_ids)}",
                        )

                failure_groups = self._build_install_atom_failure_groups(failed_items)
                atom_refresh_summary = {
                    "strategy": refresh_strategy,
                    "total": len(install_unit_ids),
                    "success": success,
                    "improved": improved,
                    "unchanged": unchanged,
                    "failed": failed,
                    "failureGroups": failure_groups,
                    "failureItems": failed_items,
                    "completedAt": _now_iso(),
                }
                atom_refresh_audit_event_id = self._append_skills_audit_event(
                    "install_atom_refresh_all",
                    source_id="all",
                    payload={
                        "run_id": run_id,
                        "strategy": refresh_strategy,
                        "total": len(install_unit_ids),
                        "success": success,
                        "improved": improved,
                        "unchanged": unchanged,
                        "failed": failed,
                        "failure_groups": failure_groups,
                    },
                )
                atom_refresh_summary["audit_event_id"] = atom_refresh_audit_event_id

                aggregate_result = await self._webui_update_all_skill_aggregates_locked(
                    body,
                    run_id=run_id,
                    started_at=started_at,
                    workflow_kind="improve_all",
                    reset_progress=False,
                )
                aggregate_result["atom_refresh"] = atom_refresh_summary
                aggregate_result["atom_refresh_audit_event_id"] = atom_refresh_audit_event_id
                return aggregate_result
            except Exception as exc:
                self._update_skills_update_all_progress_snapshot(
                    run_id=run_id,
                    status="failed",
                    workflow_kind="improve_all",
                    started_at=started_at,
                    message=f"improve-all failed: {exc}",
                )
                raise

    async def _webui_update_all_skill_aggregates_locked(
        self,
        payload: dict[str, Any] | None = None,
        *,
        run_id: str = "",
        started_at: str = "",
        workflow_kind: str = "aggregate_update_all",
        reset_progress: bool = True,
    ) -> dict[str, Any]:
        body = payload if isinstance(payload, dict) else {}
        effective_run_id = str(run_id or "").strip() or secrets.token_hex(8)
        effective_started_at = str(started_at or "").strip() or _now_iso()
        normalized_workflow_kind = str(workflow_kind or "aggregate_update_all").strip().lower() or "aggregate_update_all"
        if reset_progress:
            self._replace_skills_update_all_progress_snapshot(
                self._build_skills_update_all_progress_snapshot(
                    run_id=effective_run_id,
                    status="planning",
                    workflow_kind=normalized_workflow_kind,
                    started_at=effective_started_at,
                    message="building aggregate update plan",
                ),
            )
        else:
            self._update_skills_update_all_progress_snapshot(
                run_id=effective_run_id,
                status="planning",
                workflow_kind=normalized_workflow_kind,
                started_at=effective_started_at,
                message="building aggregate update plan",
            )

        try:
            skills_snapshot = self.webui_get_skills_payload()
            install_unit_rows = [
                item
                for item in skills_snapshot.get("install_unit_rows", [])
                if isinstance(item, dict)
            ]
            source_rows = [
                item
                for item in skills_snapshot.get("source_rows", [])
                if isinstance(item, dict)
            ]
            source_rows_by_install_unit_id: dict[str, list[dict[str, Any]]] = {}
            for source_row in source_rows:
                install_unit_id = str(source_row.get("install_unit_id") or "").strip()
                if not install_unit_id:
                    continue
                source_rows_by_install_unit_id.setdefault(install_unit_id, []).append(source_row)

            all_plans: list[dict[str, Any]] = []
            seen_plan_keys: dict[str, str] = {}
            duplicate_install_unit_ids: list[str] = []
            duplicate_install_unit_pairs: list[dict[str, Any]] = []

            for install_unit in install_unit_rows:
                install_unit_id = str(install_unit.get("install_unit_id") or "").strip()
                if not install_unit_id:
                    continue
                plan_source_rows = source_rows_by_install_unit_id.get(install_unit_id, [])
                plan = self._augment_update_plan_with_source_sync_fallback_preview(
                    build_install_unit_update_plan(install_unit, plan_source_rows),
                    plan_source_rows,
                    display_name=str(
                        install_unit.get("display_name")
                        or install_unit.get("install_unit_display_name")
                        or install_unit_id
                        or "install unit"
                    ).strip(),
                )
                dedupe_key = self._build_install_unit_update_plan_dedupe_key(plan)
                previous_install_unit_id = seen_plan_keys.get(dedupe_key, "")
                if previous_install_unit_id:
                    duplicate_install_unit_ids.append(install_unit_id)
                    duplicate_install_unit_pairs.append(
                        {
                            "install_unit_id": install_unit_id,
                            "deduped_into_install_unit_id": previous_install_unit_id,
                        },
                    )
                    continue
                seen_plan_keys[dedupe_key] = install_unit_id
                all_plans.append(plan)

            actionable_unit_plans = [
                item
                for item in all_plans
                if isinstance(item, dict) and _to_bool(item.get("actionable"), False)
            ]
            command_unit_plans = [
                item
                for item in actionable_unit_plans
                if _to_str_list(item.get("commands", []))
            ]
            source_sync_unit_plans = [
                item
                for item in actionable_unit_plans
                if self._is_source_sync_update_plan(item)
                and not _to_str_list(item.get("commands", []))
            ]
            blocked_unit_plans = [
                item
                for item in all_plans
                if isinstance(item, dict) and not _to_bool(item.get("actionable"), False)
            ]

            command_install_unit_ids = _dedupe_keep_order(
                [
                    str(item.get("install_unit_id") or "").strip()
                    for item in command_unit_plans
                    if str(item.get("install_unit_id") or "").strip()
                ],
            )
            source_sync_install_unit_ids = _dedupe_keep_order(
                [
                    str(item.get("install_unit_id") or "").strip()
                    for item in source_sync_unit_plans
                    if str(item.get("install_unit_id") or "").strip()
                ],
            )
            skipped_install_unit_ids = _dedupe_keep_order(
                [
                    str(item.get("install_unit_id") or "").strip()
                    for item in blocked_unit_plans
                    if str(item.get("install_unit_id") or "").strip()
                ],
            )
            skipped_manual_only_install_unit_ids = _dedupe_keep_order(
                [
                    str(item.get("install_unit_id") or "").strip()
                    for item in blocked_unit_plans
                    if str(item.get("install_unit_id") or "").strip()
                    and _to_bool(item.get("manual_only", False), False)
                ],
            )
            skipped_manual_only_install_unit_id_set = set(skipped_manual_only_install_unit_ids)
            skipped_other_install_unit_ids = _dedupe_keep_order(
                [
                    install_unit_id
                    for install_unit_id in skipped_install_unit_ids
                    if install_unit_id not in skipped_manual_only_install_unit_id_set
                ],
            )
            unsupported_install_units = [
                {
                    "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                    "message": str(item.get("message") or "").strip(),
                    "reason_code": str(item.get("reason_code") or "").strip().lower(),
                }
                for item in blocked_unit_plans
                if str(item.get("install_unit_id") or "").strip() or str(item.get("message") or "").strip()
            ]

            self._update_skills_update_all_progress_snapshot(
                run_id=effective_run_id,
                status="planning",
                workflow_kind=normalized_workflow_kind,
                started_at=effective_started_at,
                candidate_install_unit_total=len(install_unit_rows),
                planned_install_unit_total=len(all_plans),
                actionable_install_unit_total=len(actionable_unit_plans),
                command_install_unit_total=len(command_install_unit_ids),
                source_sync_install_unit_total=len(source_sync_install_unit_ids),
                completed_command_install_unit_total=0,
                completed_source_sync_install_unit_total=0,
                skipped_install_unit_total=len(skipped_install_unit_ids),
                failure_count=0,
                success_count=0,
                source_sync_cache_hit_total=0,
                message="aggregate update plan ready",
            )

            def _command_progress(progress_payload: dict[str, Any] | None = None) -> None:
                progress = progress_payload if isinstance(progress_payload, dict) else {}
                completed_total = max(0, int(progress.get("completed_install_unit_total", 0) or 0))
                failed_total = max(0, int(progress.get("failed_install_unit_total", 0) or 0))
                self._update_skills_update_all_progress_snapshot(
                    run_id=effective_run_id,
                    status="executing_command",
                    workflow_kind=normalized_workflow_kind,
                    started_at=effective_started_at,
                    completed_command_install_unit_total=completed_total,
                    failure_count=failed_total,
                    message=f"executing command install units {completed_total}/{len(command_install_unit_ids)}",
                )

            def _source_sync_progress(progress_payload: dict[str, Any] | None = None, base_failures: int = 0) -> None:
                progress = progress_payload if isinstance(progress_payload, dict) else {}
                completed_total = max(0, int(progress.get("completed_install_unit_total", 0) or 0))
                failed_total = max(0, int(progress.get("failed_install_unit_total", 0) or 0))
                cache_hits = max(0, int(progress.get("source_sync_cache_hit_total", 0) or 0))
                self._update_skills_update_all_progress_snapshot(
                    run_id=effective_run_id,
                    status="executing_source_sync",
                    workflow_kind=normalized_workflow_kind,
                    started_at=effective_started_at,
                    completed_source_sync_install_unit_total=completed_total,
                    failure_count=base_failures + failed_total,
                    source_sync_cache_hit_total=cache_hits,
                    message=f"executing source sync install units {completed_total}/{len(source_sync_install_unit_ids)}",
                )

            command_execution = self._empty_install_unit_execution_summary()
            if command_unit_plans:
                self._update_skills_update_all_progress_snapshot(
                    run_id=effective_run_id,
                    status="executing_command",
                    workflow_kind=normalized_workflow_kind,
                    started_at=effective_started_at,
                    message=f"executing command install units 0/{len(command_install_unit_ids)}",
                )
                command_execution = await self._execute_install_unit_update_plans(
                    command_unit_plans,
                    progress_callback=_command_progress,
                )

            source_sync_execution = self._empty_install_unit_execution_summary()
            if source_sync_unit_plans:
                command_failures = int(command_execution.get("failure_count", 0) or 0)
                self._update_skills_update_all_progress_snapshot(
                    run_id=effective_run_id,
                    status="executing_source_sync",
                    workflow_kind=normalized_workflow_kind,
                    started_at=effective_started_at,
                    completed_command_install_unit_total=len(command_execution.get("install_unit_results", [])),
                    failure_count=command_failures,
                    message=f"executing source sync install units 0/{len(source_sync_install_unit_ids)}",
                )
                source_sync_execution = self._execute_install_unit_source_sync_plans(
                    source_sync_unit_plans,
                    source_rows,
                    progress_callback=lambda progress: _source_sync_progress(progress, command_failures),
                )

            execution = self._merge_install_unit_execution_summaries(
                [command_execution, source_sync_execution],
            )
            executed_install_unit_ids = _to_str_list(execution.get("executed_install_unit_ids", []))

            if command_install_unit_ids and source_sync_install_unit_ids:
                update_mode = "partial"
            elif command_install_unit_ids:
                update_mode = "command"
            elif source_sync_install_unit_ids:
                update_mode = "source_sync"
            else:
                update_mode = "manual_only"

            failure_taxonomy = self._summarize_update_all_failure_taxonomy(
                failed_install_units=execution.get("failed_install_units", []),
                install_unit_results=execution.get("install_unit_results", []),
                blocked_unit_plans=blocked_unit_plans,
                failed_sources=execution.get("failed_sources", []),
            )

            self._update_skills_update_all_progress_snapshot(
                run_id=effective_run_id,
                status="refreshing_snapshot",
                workflow_kind=normalized_workflow_kind,
                started_at=effective_started_at,
                completed_command_install_unit_total=len(command_execution.get("install_unit_results", [])),
                completed_source_sync_install_unit_total=len(source_sync_execution.get("install_unit_results", [])),
                failure_count=int(execution.get("failure_count", 0) or 0),
                success_count=int(execution.get("success_count", 0) or 0),
                source_sync_cache_hit_total=int(execution.get("source_sync_cache_hit_total", 0) or 0),
                message="refreshing skills snapshot",
            )

            inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
            await self._save_state()
            refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
            update_summary = {
                "run_id": effective_run_id,
                "supported": bool(actionable_unit_plans),
                "actionable": bool(actionable_unit_plans),
                "manual_only": update_mode == "manual_only",
                "update_mode": update_mode,
                "manager": "mixed" if command_install_unit_ids and source_sync_install_unit_ids else "",
                "policy": "mixed" if command_install_unit_ids and source_sync_install_unit_ids else "",
                "candidate_install_unit_total": len(install_unit_rows),
                "planned_install_unit_total": len(all_plans),
                "deduplicated_install_unit_total": len(duplicate_install_unit_ids),
                "deduplicated_install_unit_ids": duplicate_install_unit_ids,
                "deduplicated_install_unit_pairs": duplicate_install_unit_pairs,
                "actionable_install_unit_ids": _dedupe_keep_order(
                    [
                        str(item.get("install_unit_id") or "").strip()
                        for item in actionable_unit_plans
                        if str(item.get("install_unit_id") or "").strip()
                    ],
                ),
                "actionable_install_unit_total": len(actionable_unit_plans),
                "supported_install_unit_total": len(actionable_unit_plans),
                "unsupported_install_unit_total": len(blocked_unit_plans),
                "unsupported_install_units": unsupported_install_units,
                "command_install_unit_ids": command_install_unit_ids,
                "command_install_unit_total": len(command_install_unit_ids),
                "completed_command_install_unit_total": len(command_execution.get("install_unit_results", [])),
                "source_sync_install_unit_ids": source_sync_install_unit_ids,
                "source_sync_install_unit_total": len(source_sync_install_unit_ids),
                "completed_source_sync_install_unit_total": len(source_sync_execution.get("install_unit_results", [])),
                "skipped_install_unit_ids": skipped_install_unit_ids,
                "skipped_install_unit_total": len(skipped_install_unit_ids),
                "skipped_manual_only_install_unit_ids": skipped_manual_only_install_unit_ids,
                "skipped_manual_only_install_unit_total": len(skipped_manual_only_install_unit_ids),
                "skipped_other_install_unit_ids": skipped_other_install_unit_ids,
                "skipped_other_install_unit_total": len(skipped_other_install_unit_ids),
                "executed_install_unit_ids": executed_install_unit_ids,
                "executed_install_unit_total": len(executed_install_unit_ids),
                "failure_taxonomy": failure_taxonomy,
                **execution,
                "message": (
                    "aggregate update-all finished: "
                    f"{execution.get('success_count', 0)} commands ok, "
                    f"{execution.get('failure_count', 0)} failed, "
                    f"{execution.get('source_sync_success_count', 0)} source sync ok, "
                    f"{execution.get('source_sync_failure_count', 0)} source sync failed, "
                    f"{len(skipped_install_unit_ids)} blocked, "
                    f"{len(duplicate_install_unit_ids)} deduplicated"
                ),
            }
            audit_event_id = self._append_skills_audit_event(
                "aggregates_update_all",
                source_id="all",
                payload={
                    "run_id": effective_run_id,
                    "candidate_install_unit_total": len(install_unit_rows),
                    "planned_install_unit_total": len(all_plans),
                    "deduplicated_install_unit_total": len(duplicate_install_unit_ids),
                    "executed_install_unit_ids": executed_install_unit_ids,
                    "success_count": execution.get("success_count", 0),
                    "failure_count": execution.get("failure_count", 0),
                    "source_sync_success_count": execution.get("source_sync_success_count", 0),
                    "source_sync_failure_count": execution.get("source_sync_failure_count", 0),
                    "source_sync_cache_hit_total": execution.get("source_sync_cache_hit_total", 0),
                    "skipped_install_unit_total": len(skipped_install_unit_ids),
                    "failure_taxonomy": failure_taxonomy,
                },
            )
            update_summary["audit_event_id"] = audit_event_id
            blocked_reason_groups = failure_taxonomy.get("blocked_reason_groups", [])
            failed_reason_groups = failure_taxonomy.get("failed_install_unit_reason_groups", [])
            blocked_reason_tail = ", ".join(
                f"{str(item.get('reason_code') or '')}:{int(item.get('count', 0) or 0)}"
                for item in blocked_reason_groups[:3]
                if isinstance(item, dict)
            )
            failed_reason_tail = ", ".join(
                f"{str(item.get('failure_reason') or '')}:{int(item.get('count', 0) or 0)}"
                for item in failed_reason_groups[:3]
                if isinstance(item, dict)
            )
            self._push_debug_log(
                (
                    "info"
                    if (
                        not execution.get("failure_count")
                        and not execution.get("source_sync_failure_count")
                    )
                    else "warn"
                ),
                (
                    "aggregate update-all: "
                    f"run_id={effective_run_id} "
                    f"workflow={normalized_workflow_kind} "
                    f"planned={len(all_plans)} "
                    f"executed={len(executed_install_unit_ids)} "
                    f"ok={execution.get('success_count', 0)} "
                    f"failed={execution.get('failure_count', 0)} "
                    f"sync_ok={execution.get('source_sync_success_count', 0)} "
                    f"sync_failed={execution.get('source_sync_failure_count', 0)} "
                    f"sync_cache_hits={execution.get('source_sync_cache_hit_total', 0)} "
                    f"skipped={len(skipped_install_unit_ids)} "
                    f"deduped={len(duplicate_install_unit_ids)} "
                    f"failed_reasons=[{failed_reason_tail or '-'}] "
                    f"blocked_reasons=[{blocked_reason_tail or '-'}]"
                ),
                source="webui",
            )
            progress_snapshot = self._update_skills_update_all_progress_snapshot(
                run_id=effective_run_id,
                status="completed",
                workflow_kind=normalized_workflow_kind,
                started_at=effective_started_at,
                completed_command_install_unit_total=len(command_execution.get("install_unit_results", [])),
                completed_source_sync_install_unit_total=len(source_sync_execution.get("install_unit_results", [])),
                failure_count=int(execution.get("failure_count", 0) or 0),
                success_count=int(execution.get("success_count", 0) or 0),
                source_sync_cache_hit_total=int(execution.get("source_sync_cache_hit_total", 0) or 0),
                message=str(update_summary.get("message") or "").strip(),
            )
            return {
                "ok": True,
                "run_id": effective_run_id,
                "progress": progress_snapshot,
                "generated_at": refreshed_skills_snapshot.get("generated_at", skills_snapshot.get("generated_at")),
                "update": update_summary,
                "candidate_install_unit_total": len(install_unit_rows),
                "planned_install_unit_total": len(all_plans),
                "executed_install_unit_total": len(executed_install_unit_ids),
                "success_count": execution.get("success_count", 0),
                "failure_count": execution.get("failure_count", 0),
                "precheck_failure_count": execution.get("precheck_failure_count", 0),
                "skipped_install_unit_total": len(skipped_install_unit_ids),
                "source_sync_cache_hit_total": execution.get("source_sync_cache_hit_total", 0),
                "failure_taxonomy": failure_taxonomy,
                "updated_install_unit_ids": executed_install_unit_ids,
                "failed_install_units": execution.get("failed_install_units", []),
                "unsupported_install_units": unsupported_install_units,
                "skipped_install_unit_ids": skipped_install_unit_ids,
                "skipped_manual_only_install_unit_ids": skipped_manual_only_install_unit_ids,
                "skipped_other_install_unit_ids": skipped_other_install_unit_ids,
                "deduplicated_install_unit_ids": duplicate_install_unit_ids,
                "skills": refreshed_skills_snapshot,
                "inventory": inventory_snapshot,
                "audit_event_id": audit_event_id,
            }
        except Exception as exc:
            self._update_skills_update_all_progress_snapshot(
                run_id=effective_run_id,
                status="failed",
                workflow_kind=normalized_workflow_kind,
                started_at=effective_started_at,
                message=f"aggregate update-all failed: {exc}",
            )
            raise

    async def webui_rollback_install_unit(
        self,
        install_unit_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rollback_payload = payload if isinstance(payload, dict) else {}
        request_source = str(rollback_payload.get("request_source") or "").strip().lower() or "manual"
        if request_source not in {"manual", "audit_retry"}:
            request_source = "manual"
        retry_of_event_id = str(rollback_payload.get("retry_of_event_id") or "").strip()
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context
        if not self._payload_confirms_skills_rollback(rollback_payload):
            return {
                "ok": False,
                "message": (
                    "rollback confirmation is required: set payload.execute=true "
                    f"and payload.confirm='{SKILLS_ROLLBACK_CONFIRM_TOKEN}'"
                ),
            }

        before_rows = self._extract_before_revision_rows(rollback_payload)
        if not before_rows:
            return {
                "ok": False,
                "message": "before_revisions is required for rollback",
            }

        source_index = self._build_source_index_by_id(context.get("source_rows", []))
        target_before_rows = [
            item
            for item in before_rows
            if isinstance(item, dict)
            and _normalize_inventory_id(item.get("source_id", ""), default="") in source_index
        ]
        if not target_before_rows:
            return {
                "ok": False,
                "message": "before_revisions has no matching source members for this install unit",
            }

        target_source_ids = _dedupe_keep_order(
            [
                _normalize_inventory_id(item.get("source_id", ""), default="")
                for item in target_before_rows
                if _normalize_inventory_id(item.get("source_id", ""), default="")
            ],
        )
        target_source_rows = [source_index[item] for item in target_source_ids if item in source_index]
        rollback_preview = build_git_rollback_preview(
            target_source_rows,
            target_before_rows,
            target_source_ids,
        )
        if not rollback_preview.get("supported"):
            return {
                "ok": False,
                "message": "rollback preview cannot build executable candidates for this install unit",
                "rollback_preview": rollback_preview,
            }

        execution = await self._execute_rollback_preview_candidates(
            [item for item in rollback_preview.get("candidates", []) if isinstance(item, dict)],
            source_rows=target_source_rows,
            before_rows=target_before_rows,
        )
        retry_source_ids = _dedupe_keep_order(
            _to_str_list(execution.get("not_restored_source_ids", []))
            + [
                _normalize_inventory_id(item.get("source_id", ""), default="")
                for item in execution.get("failed_sources", [])
                if isinstance(item, dict) and _normalize_inventory_id(item.get("source_id", ""), default="")
            ],
        )
        retry_source_id_set = set(retry_source_ids)
        retry_before_revisions = [
            item
            for item in target_before_rows
            if isinstance(item, dict)
            and _normalize_inventory_id(item.get("source_id", ""), default="") in retry_source_id_set
        ]
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        rollback_summary = {
            **rollback_preview,
            **execution,
            "retry_before_revisions": retry_before_revisions,
            "request_source": request_source,
            "retry_of_event_id": retry_of_event_id,
            "message": (
                "install unit rollback finished: "
                f"{execution.get('success_count', 0)} commands ok, "
                f"{execution.get('failure_count', 0)} failed, "
                f"{execution.get('restored_source_total', 0)} sources restored"
            ),
        }
        audit_event_id = self._append_skills_audit_event(
            "install_unit_rollback",
            source_id=normalized_install_unit_id,
            payload={
                "source_ids": target_source_ids,
                "candidate_total": rollback_preview.get("candidate_total", 0),
                "success_count": execution.get("success_count", 0),
                "failure_count": execution.get("failure_count", 0),
                "restored_source_total": execution.get("restored_source_total", 0),
                "not_restored_source_total": execution.get("not_restored_source_total", 0),
                "failed_sources": execution.get("failed_sources", []),
                "not_restored_source_ids": execution.get("not_restored_source_ids", []),
                "retry_before_revisions": retry_before_revisions,
                "request_source": request_source,
                "retry_of_event_id": retry_of_event_id,
            },
        )
        rollback_summary["audit_event_id"] = audit_event_id
        self._push_debug_log(
            "info" if not execution.get("failure_count") else "warn",
            (
                "install unit rollback: "
                f"install_unit={normalized_install_unit_id} "
                f"restored={execution.get('restored_source_total', 0)} "
                f"not_restored={execution.get('not_restored_source_total', 0)}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "rollback": rollback_summary,
                "rolled_back_source_ids": execution.get("restored_source_ids", []),
                "failed_rollback_sources": execution.get("failed_sources", []),
            },
        )

    async def webui_rollback_collection_group(
        self,
        collection_group_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rollback_payload = payload if isinstance(payload, dict) else {}
        request_source = str(rollback_payload.get("request_source") or "").strip().lower() or "manual"
        if request_source not in {"manual", "audit_retry"}:
            request_source = "manual"
        retry_of_event_id = str(rollback_payload.get("retry_of_event_id") or "").strip()
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context
        if not self._payload_confirms_skills_rollback(rollback_payload):
            return {
                "ok": False,
                "message": (
                    "rollback confirmation is required: set payload.execute=true "
                    f"and payload.confirm='{SKILLS_ROLLBACK_CONFIRM_TOKEN}'"
                ),
            }

        before_rows = self._extract_before_revision_rows(rollback_payload)
        if not before_rows:
            return {
                "ok": False,
                "message": "before_revisions is required for rollback",
            }

        source_index = self._build_source_index_by_id(context.get("source_rows", []))
        install_unit_rows = [
            item
            for item in context.get("install_unit_rows", [])
            if isinstance(item, dict)
        ]
        source_rows = [
            item
            for item in context.get("source_rows", [])
            if isinstance(item, dict)
        ]
        before_by_source_id = {
            _normalize_inventory_id(item.get("source_id", ""), default=""): item
            for item in before_rows
            if isinstance(item, dict) and _normalize_inventory_id(item.get("source_id", ""), default="")
        }

        install_unit_results: list[dict[str, Any]] = []
        executed_install_unit_ids: list[str] = []
        failed_install_units: list[dict[str, Any]] = []
        skipped_install_units: list[str] = []
        command_results: list[dict[str, Any]] = []
        success_count = 0
        failure_count = 0
        rollback_preview_candidate_total = 0
        restored_source_total = 0
        not_restored_source_total = 0
        all_not_restored_source_ids: list[str] = []
        all_failed_sources: list[dict[str, Any]] = []

        for install_unit in install_unit_rows:
            install_unit_id = str(install_unit.get("install_unit_id") or "").strip()
            if not install_unit_id:
                continue
            unit_source_rows = [
                item
                for item in source_rows
                if str(item.get("install_unit_id") or "").strip() == install_unit_id
            ]
            unit_source_ids = _dedupe_keep_order(
                [
                    _normalize_inventory_id(item.get("source_id", ""), default="")
                    for item in unit_source_rows
                    if _normalize_inventory_id(item.get("source_id", ""), default="")
                ],
            )
            unit_before_rows = [
                before_by_source_id[item]
                for item in unit_source_ids
                if item in before_by_source_id
            ]
            if not unit_before_rows:
                skipped_install_units.append(install_unit_id)
                continue

            rollback_preview = build_git_rollback_preview(
                unit_source_rows,
                unit_before_rows,
                [
                    _normalize_inventory_id(item.get("source_id", ""), default="")
                    for item in unit_before_rows
                    if _normalize_inventory_id(item.get("source_id", ""), default="")
                ],
            )
            if not rollback_preview.get("supported"):
                unit_result = {
                    "install_unit_id": install_unit_id,
                    "display_name": str(install_unit.get("display_name") or install_unit_id),
                    "ok": False,
                    "rollback_preview": rollback_preview,
                    "message": "rollback preview cannot build executable candidates",
                }
                install_unit_results.append(unit_result)
                failed_install_units.append(
                    {
                        "install_unit_id": install_unit_id,
                        "reason": "rollback_preview_unsupported",
                        "message": "rollback preview cannot build executable candidates",
                    },
                )
                continue

            execution = await self._execute_rollback_preview_candidates(
                [item for item in rollback_preview.get("candidates", []) if isinstance(item, dict)],
                source_rows=unit_source_rows,
                before_rows=unit_before_rows,
            )
            unit_ok = not execution.get("failure_count") and not execution.get("not_restored_source_total")
            unit_result = {
                "install_unit_id": install_unit_id,
                "display_name": str(install_unit.get("display_name") or install_unit_id),
                "ok": unit_ok,
                "rollback_preview": rollback_preview,
                **execution,
            }
            install_unit_results.append(unit_result)
            command_results.extend([item for item in execution.get("results", []) if isinstance(item, dict)])
            success_count += int(execution.get("success_count", 0))
            failure_count += int(execution.get("failure_count", 0))
            rollback_preview_candidate_total += int(rollback_preview.get("candidate_total", 0))
            restored_source_total += int(execution.get("restored_source_total", 0))
            not_restored_source_total += int(execution.get("not_restored_source_total", 0))
            all_not_restored_source_ids.extend(
                _to_str_list(execution.get("not_restored_source_ids", [])),
            )
            for failed_source in execution.get("failed_sources", []):
                if not isinstance(failed_source, dict):
                    continue
                failed_source_id = _normalize_inventory_id(failed_source.get("source_id", ""), default="")
                if not failed_source_id:
                    continue
                all_failed_sources.append(
                    {
                        "install_unit_id": install_unit_id,
                        "source_id": failed_source_id,
                        "reason": str(failed_source.get("reason") or "").strip(),
                        "message": str(failed_source.get("message") or "").strip(),
                    },
                )
            if unit_ok:
                executed_install_unit_ids.append(install_unit_id)
            else:
                failed_install_units.append(
                    {
                        "install_unit_id": install_unit_id,
                        "reason": "rollback_failed",
                        "message": f"rollback failed for install unit: {install_unit_id}",
                    },
                )

        if not install_unit_results:
            return {
                "ok": False,
                "message": "before_revisions has no matching rollback candidates for this collection group",
            }

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        deduped_not_restored_source_ids = _dedupe_keep_order(all_not_restored_source_ids)
        retry_source_ids = _dedupe_keep_order(
            deduped_not_restored_source_ids
            + [
                _normalize_inventory_id(item.get("source_id", ""), default="")
                for item in all_failed_sources
                if _normalize_inventory_id(item.get("source_id", ""), default="")
            ],
        )
        retry_source_id_set = set(retry_source_ids)
        retry_before_revisions = [
            item
            for item in before_rows
            if isinstance(item, dict)
            and _normalize_inventory_id(item.get("source_id", ""), default="") in retry_source_id_set
        ]
        rollback_summary = {
            "collection_group_id": normalized_collection_group_id,
            "install_unit_results": install_unit_results,
            "executed_install_unit_ids": executed_install_unit_ids,
            "failed_install_units": failed_install_units,
            "skipped_install_units": skipped_install_units,
            "results": command_results,
            "success_count": success_count,
            "failure_count": failure_count,
            "rollback_preview_candidate_total": rollback_preview_candidate_total,
            "restored_source_total": restored_source_total,
            "not_restored_source_total": not_restored_source_total,
            "not_restored_source_ids": deduped_not_restored_source_ids,
            "failed_sources": all_failed_sources,
            "retry_before_revisions": retry_before_revisions,
            "request_source": request_source,
            "retry_of_event_id": retry_of_event_id,
            "message": (
                "collection group rollback finished: "
                f"{success_count} commands ok, "
                f"{failure_count} failed, "
                f"{restored_source_total} sources restored"
            ),
        }
        audit_event_id = self._append_skills_audit_event(
            "collection_group_rollback",
            source_id=normalized_collection_group_id,
            payload={
                "install_unit_ids": executed_install_unit_ids,
                "failed_install_units": failed_install_units,
                "candidate_total": rollback_preview_candidate_total,
                "success_count": success_count,
                "failure_count": failure_count,
                "restored_source_total": restored_source_total,
                "not_restored_source_total": not_restored_source_total,
                "failed_sources": all_failed_sources,
                "not_restored_source_ids": deduped_not_restored_source_ids,
                "retry_before_revisions": retry_before_revisions,
                "request_source": request_source,
                "retry_of_event_id": retry_of_event_id,
            },
        )
        rollback_summary["audit_event_id"] = audit_event_id
        self._push_debug_log(
            "info" if not failure_count else "warn",
            (
                "collection group rollback: "
                f"collection_group={normalized_collection_group_id} "
                f"restored={restored_source_total} not_restored={not_restored_source_total}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "rollback": rollback_summary,
                "rolled_back_install_unit_ids": executed_install_unit_ids,
                "failed_install_units": failed_install_units,
                "skipped_install_units": skipped_install_units,
            },
        )

    def webui_get_deploy_target_payload(self, target_id: str) -> dict[str, Any]:
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            return {"ok": False, "message": "target_id is required"}

        snapshot = self.webui_get_skills_payload()
        deploy_rows = snapshot.get("deploy_rows", [])
        deploy_target = next(
            (
                item for item in deploy_rows
                if isinstance(item, dict) and str(item.get("target_id", "")) == normalized_target_id
            ),
            None,
        )
        if not deploy_target:
            return {"ok": False, "message": f"target_id not found: {normalized_target_id}"}

        source_rows = snapshot.get("source_rows", [])
        source_index = {
            str(item.get("source_id", "")).strip(): item
            for item in source_rows
            if isinstance(item, dict) and str(item.get("source_id", "")).strip()
        }
        selected_source_ids = _to_str_list(deploy_target.get("selected_source_ids", []))
        available_source_ids = _to_str_list(deploy_target.get("available_source_ids", []))
        target_file_id = _normalize_inventory_id(normalized_target_id, default="")
        generated_projection_path = self.skills_generated_dir / f"{target_file_id}.json" if target_file_id else self.skills_generated_dir / ".json"
        generated_projection_payload = read_generated_target_payload(generated_projection_path)
        generated_projection_diff = build_generated_target_diff(deploy_target, generated_projection_payload)

        return {
            "ok": True,
            "generated_at": snapshot.get("generated_at"),
            "deploy_target": deploy_target,
            "selected_sources": [
                source_index[source_id]
                for source_id in selected_source_ids
                if source_id in source_index
            ],
            "available_sources": [
                source_index[source_id]
                for source_id in available_source_ids
                if source_id in source_index
            ],
            "generated_projection": {
                "path": str(generated_projection_path),
                "exists": generated_projection_payload is not None,
                "payload": generated_projection_payload or {},
                "diff": generated_projection_diff,
            },
            "warnings": snapshot.get("warnings", []),
        }

    async def webui_scan_inventory(self) -> dict[str, Any]:
        snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        self._push_debug_log(
            "info",
            (
                "inventory scan completed: "
                f"software={snapshot.get('counts', {}).get('software_total', 0)} "
                f"skills={snapshot.get('counts', {}).get('skills_total', 0)}"
            ),
            source="webui",
        )
        return snapshot

    async def webui_import_skills(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        await self._save_state()
        skills_snapshot = self._skills_state().get("last_overview", {})
        self._push_debug_log(
            "info",
            (
                "skills import completed: "
                f"sources={skills_snapshot.get('counts', {}).get('source_total', 0)} "
                f"deploy_targets={skills_snapshot.get('counts', {}).get('deploy_target_total', 0)}"
            ),
            source="webui",
        )
        source_ids = [
            str(item.get("source_id", "")).strip()
            for item in skills_snapshot.get("source_rows", [])
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "inventory": inventory_snapshot,
            "skills": skills_snapshot,
            "imported_source_ids": [item for item in source_ids if item],
        }

    def webui_register_skill_source(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        source_payload = payload if isinstance(payload, dict) else {}
        current_registry = self._load_saved_skills_registry()
        current_ids = {
            str(item.get("source_id", "")).strip()
            for item in current_registry.get("sources", [])
            if isinstance(item, dict)
        }
        try:
            updated_registry = register_registry_source(current_registry, source_payload, generated_at=_now_iso())
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        self._save_skills_registry(updated_registry)
        source = next(
            (
                item
                for item in updated_registry.get("sources", [])
                if str(item.get("source_id", "")).strip() not in current_ids
            ),
            None,
        )
        source_id = str(source.get("source_id", "")).strip() if isinstance(source, dict) else ""
        audit_event_id = self._append_skills_audit_event(
            "register",
            source_id=source_id,
            payload={
                "source_kind": str(source_payload.get("source_kind") or source_payload.get("kind") or ""),
                "locator": str(source_payload.get("locator") or ""),
            },
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        registry_payload = refreshed_skills_snapshot.get("registry", updated_registry)
        if source_id:
            source = next(
                (
                    item
                    for item in registry_payload.get("sources", [])
                    if isinstance(item, dict) and str(item.get("source_id", "")).strip() == source_id
                ),
                source,
            )
        return {
            "ok": True,
            "source": source or {},
            "registry": registry_payload,
            "skills": refreshed_skills_snapshot,
            "inventory": inventory_snapshot,
            "audit_event_id": audit_event_id,
        }

    def webui_refresh_skill_registry_source(self, source_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        source_payload = payload if isinstance(payload, dict) else {}
        current_snapshot = self.webui_get_skills_payload()
        current_registry = current_snapshot.get("registry", {})
        registry_source = next(
            (
                item
                for item in current_registry.get("sources", [])
                if isinstance(item, dict) and str(item.get("source_id", "")).strip() == normalized_source_id
            ),
            None,
        )
        if not isinstance(registry_source, dict):
            return {"ok": False, "message": f"source_id not found: {normalized_source_id}"}
        try:
            updated_registry = refresh_registry_source(
                current_registry,
                normalized_source_id,
                {**registry_source, **source_payload},
                generated_at=_now_iso(),
            )
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        self._save_skills_registry(updated_registry)
        audit_event_id = self._append_skills_audit_event(
            "refresh",
            source_id=normalized_source_id,
            payload=source_payload,
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        registry_payload = refreshed_skills_snapshot.get("registry", updated_registry)
        refreshed_source = next(
            (
                item
                for item in registry_payload.get("sources", [])
                if isinstance(item, dict) and str(item.get("source_id", "")).strip() == normalized_source_id
            ),
            registry_source,
        )
        return {
            "ok": True,
            "source": refreshed_source,
            "registry": registry_payload,
            "skills": refreshed_skills_snapshot,
            "inventory": inventory_snapshot,
            "audit_event_id": audit_event_id,
        }

    def webui_refresh_install_unit(
        self,
        install_unit_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context

        updated_registry = self._load_saved_skills_registry()
        refreshed_source_ids: list[str] = []
        for source_row in context.get("source_rows", []):
            if not isinstance(source_row, dict):
                continue
            source_id = _normalize_inventory_id(source_row.get("source_id", ""), default="")
            if not source_id:
                continue
            registry_source = next(
                (
                    item
                    for item in updated_registry.get("sources", [])
                    if isinstance(item, dict) and str(item.get("source_id", "")).strip() == source_id
                ),
                None,
            )
            merged_source = {
                **(registry_source if isinstance(registry_source, dict) else {}),
                **source_row,
                **source_payload,
                "source_id": source_id,
            }
            if isinstance(registry_source, dict):
                updated_registry = refresh_registry_source(
                    updated_registry,
                    source_id,
                    merged_source,
                    generated_at=_now_iso(),
                )
            else:
                updated_registry = register_registry_source(
                    updated_registry,
                    merged_source,
                    generated_at=_now_iso(),
                )
            refreshed_source_ids.append(source_id)

        self._save_skills_registry(updated_registry)
        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "install_unit_refresh",
            source_id=normalized_install_unit_id,
            payload={
                "source_ids": refreshed_source_ids,
                **source_payload,
            },
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        self._push_debug_log(
            "info",
            (
                "install unit refreshed: "
                f"install_unit={normalized_install_unit_id} sources={','.join(refreshed_source_ids)}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "registry": updated_registry,
                "refreshed_source_ids": refreshed_source_ids,
                "audit_event_id": audit_event_id,
            },
        )

    def webui_sync_skill_source(self, source_id: str) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}

        skills_snapshot = self.webui_get_skills_payload()
        source_rows = skills_snapshot.get("source_rows", [])
        source = next(
            (
                item for item in source_rows
                if isinstance(item, dict) and str(item.get("source_id", "")) == normalized_source_id
            ),
            None,
        )
        if not isinstance(source, dict):
            return {"ok": False, "message": f"source_id not found: {normalized_source_id}"}

        source_with_checkout = self._augment_source_row_with_git_checkout(source)
        sync_record = build_source_sync_record(source_with_checkout)
        registry = self._update_saved_registry_source_metadata(
            source_id=normalized_source_id,
            source_payload=source_with_checkout,
            sync_payload=sync_record,
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        source_payload = self.webui_get_skill_source_payload(normalized_source_id)
        message = str(sync_record.get("sync_message") or "").strip() or f"source sync finished: {normalized_source_id}"
        audit_event_id = self._append_skills_audit_event(
            "source_sync",
            source_id=normalized_source_id,
            payload={
                "sync_status": str(sync_record.get("sync_status") or ""),
                "sync_message": message,
                "sync_kind": str(sync_record.get("sync_kind") or ""),
                "sync_checked_at": str(sync_record.get("sync_checked_at") or ""),
                "sync_local_revision": str(sync_record.get("sync_local_revision") or ""),
                "sync_remote_revision": str(sync_record.get("sync_remote_revision") or ""),
                "sync_resolved_revision": str(sync_record.get("sync_resolved_revision") or ""),
                "sync_branch": str(sync_record.get("sync_branch") or ""),
                "sync_dirty": _to_bool(sync_record.get("sync_dirty", False), False),
                "sync_error_code": str(sync_record.get("sync_error_code") or ""),
            },
        )
        level = "info" if str(sync_record.get("sync_status") or "") == "ok" else "warn"
        self._push_debug_log(
            level,
            (
                "skill source sync: "
                f"source={normalized_source_id} status={sync_record.get('sync_status') or 'unknown'} "
                f"message={message}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "generated_at": source_payload.get("generated_at", refreshed_skills_snapshot.get("generated_at")),
            "manifest": refreshed_skills_snapshot.get("manifest", {}),
            "registry": registry,
            "inventory": inventory_snapshot,
            "skills": refreshed_skills_snapshot,
            "source": source_payload.get("source", source),
            "deploy_rows": source_payload.get("deploy_rows", []),
            "warnings": source_payload.get("warnings", []),
            "sync": sync_record,
            "audit_event_id": audit_event_id,
        }

    def webui_sync_install_unit(self, install_unit_id: str) -> dict[str, Any]:
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context

        synced_source_ids: list[str] = []
        failed_sources: list[dict[str, Any]] = []
        registry = self._load_saved_skills_registry()

        for source in context.get("source_rows", []):
            if not isinstance(source, dict):
                continue
            source_id = _normalize_inventory_id(source.get("source_id", ""), default="")
            if not source_id:
                continue
            source_with_checkout = self._augment_source_row_with_git_checkout(source)
            sync_record = build_source_sync_record(source_with_checkout)
            registry = self._update_saved_registry_source_metadata(
                source_id=source_id,
                source_payload=source_with_checkout,
                sync_payload=sync_record,
            )
            if str(sync_record.get("sync_status") or "") == "ok":
                synced_source_ids.append(source_id)
            else:
                failed_sources.append(
                    {
                        "source_id": source_id,
                        "sync_status": str(sync_record.get("sync_status") or ""),
                        "sync_message": str(sync_record.get("sync_message") or ""),
                    },
                )

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "install_unit_sync",
            source_id=normalized_install_unit_id,
            payload={
                "synced_source_ids": synced_source_ids,
                "failed_sources": failed_sources,
                "success_count": len(synced_source_ids),
                "failure_count": len(failed_sources),
            },
        )
        self._push_debug_log(
            "info" if not failed_sources else "warn",
            (
                "install unit synced: "
                f"install_unit={normalized_install_unit_id} ok={len(synced_source_ids)} failed={len(failed_sources)}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "registry": registry,
                "synced_source_ids": synced_source_ids,
                "failed_sources": failed_sources,
                "audit_event_id": audit_event_id,
            },
        )

    def webui_refresh_collection_group(
        self,
        collection_group_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context

        updated_registry = self._load_saved_skills_registry()
        refreshed_source_ids: list[str] = []
        for source_row in context.get("source_rows", []):
            if not isinstance(source_row, dict):
                continue
            source_id = _normalize_inventory_id(source_row.get("source_id", ""), default="")
            if not source_id:
                continue
            registry_source = next(
                (
                    item
                    for item in updated_registry.get("sources", [])
                    if isinstance(item, dict) and str(item.get("source_id", "")).strip() == source_id
                ),
                None,
            )
            merged_source = {
                **(registry_source if isinstance(registry_source, dict) else {}),
                **source_row,
                **source_payload,
                "source_id": source_id,
            }
            if isinstance(registry_source, dict):
                updated_registry = refresh_registry_source(
                    updated_registry,
                    source_id,
                    merged_source,
                    generated_at=_now_iso(),
                )
            else:
                updated_registry = register_registry_source(
                    updated_registry,
                    merged_source,
                    generated_at=_now_iso(),
                )
            refreshed_source_ids.append(source_id)

        self._save_skills_registry(updated_registry)
        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "collection_group_refresh",
            source_id=normalized_collection_group_id,
            payload={
                "source_ids": refreshed_source_ids,
                **source_payload,
            },
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        self._push_debug_log(
            "info",
            (
                "collection group refreshed: "
                f"collection_group={normalized_collection_group_id} sources={','.join(refreshed_source_ids)}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "registry": updated_registry,
                "refreshed_source_ids": refreshed_source_ids,
                "audit_event_id": audit_event_id,
            },
        )

    def webui_sync_collection_group(self, collection_group_id: str) -> dict[str, Any]:
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context

        synced_source_ids: list[str] = []
        failed_sources: list[dict[str, Any]] = []
        registry = self._load_saved_skills_registry()

        for source in context.get("source_rows", []):
            if not isinstance(source, dict):
                continue
            source_id = _normalize_inventory_id(source.get("source_id", ""), default="")
            if not source_id:
                continue
            source_with_checkout = self._augment_source_row_with_git_checkout(source)
            sync_record = build_source_sync_record(source_with_checkout)
            registry = self._update_saved_registry_source_metadata(
                source_id=source_id,
                source_payload=source_with_checkout,
                sync_payload=sync_record,
            )
            if str(sync_record.get("sync_status") or "") == "ok":
                synced_source_ids.append(source_id)
            else:
                failed_sources.append(
                    {
                        "source_id": source_id,
                        "sync_status": str(sync_record.get("sync_status") or ""),
                        "sync_message": str(sync_record.get("sync_message") or ""),
                    },
                )

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "collection_group_sync",
            source_id=normalized_collection_group_id,
            payload={
                "synced_source_ids": synced_source_ids,
                "failed_sources": failed_sources,
                "success_count": len(synced_source_ids),
                "failure_count": len(failed_sources),
            },
        )
        self._push_debug_log(
            "info" if not failed_sources else "warn",
            (
                "collection group synced: "
                f"collection_group={normalized_collection_group_id} ok={len(synced_source_ids)} failed={len(failed_sources)}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=inventory_snapshot,
            skills_snapshot=refreshed_skills_snapshot,
            extra={
                "registry": registry,
                "synced_source_ids": synced_source_ids,
                "failed_sources": failed_sources,
                "audit_event_id": audit_event_id,
            },
        )

    def webui_repair_install_unit(
        self,
        install_unit_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repair_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context

        target_summary = self._summarize_related_deploy_targets(context.get("detail", {}))
        related_target_ids = _to_str_list(target_summary.get("target_ids", []))
        requested_target_ids = [
            target_id
            for target_id in _to_str_list(repair_payload.get("target_ids", []))
            if target_id in related_target_ids
        ]
        target_ids = requested_target_ids or related_target_ids

        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        if not target_ids:
            inventory_snapshot = self.webui_get_inventory_payload()
            skills_snapshot = self.webui_get_skills_payload()
            return self._build_install_unit_mutation_response(
                normalized_install_unit_id,
                inventory_snapshot=inventory_snapshot,
                skills_snapshot=skills_snapshot,
                extra={
                    "target_ids": [],
                    "repaired_target_ids": [],
                    "repair_results": [],
                    "failed_targets": [],
                    "remaining_repairable_total": 0,
                    "remaining_repairable_target_ids": [],
                },
            )

        repair_result = self.webui_repair_all_deploy_targets(
            {
                **repair_payload,
                "target_ids": target_ids,
            },
        )
        if not repair_result.get("ok"):
            return repair_result

        refreshed_detail = self.webui_get_install_unit_payload(normalized_install_unit_id)
        refreshed_target_summary = self._summarize_related_deploy_targets(refreshed_detail)
        self._push_debug_log(
            "info",
            (
                "install unit repaired: "
                f"install_unit={normalized_install_unit_id} targets={','.join(target_ids)} "
                f"repaired={len(_to_str_list(repair_result.get('repaired_target_ids', [])))}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=repair_result.get("inventory", {}),
            skills_snapshot=repair_result.get("skills", {}),
            extra={
                "target_ids": target_ids,
                "repaired_target_ids": _to_str_list(repair_result.get("repaired_target_ids", [])),
                "repair_results": repair_result.get("results", []),
                "failed_targets": repair_result.get("failed_targets", []),
                "remaining_repairable_total": len(_to_str_list(refreshed_target_summary.get("repairable_target_ids", []))),
                "remaining_repairable_target_ids": _to_str_list(refreshed_target_summary.get("repairable_target_ids", [])),
            },
        )

    def webui_repair_collection_group(
        self,
        collection_group_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repair_payload = payload if isinstance(payload, dict) else {}
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context

        target_summary = self._summarize_related_deploy_targets(context.get("detail", {}))
        related_target_ids = _to_str_list(target_summary.get("target_ids", []))
        requested_target_ids = [
            target_id
            for target_id in _to_str_list(repair_payload.get("target_ids", []))
            if target_id in related_target_ids
        ]
        target_ids = requested_target_ids or related_target_ids

        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        if not target_ids:
            inventory_snapshot = self.webui_get_inventory_payload()
            skills_snapshot = self.webui_get_skills_payload()
            return self._build_collection_group_mutation_response(
                normalized_collection_group_id,
                inventory_snapshot=inventory_snapshot,
                skills_snapshot=skills_snapshot,
                extra={
                    "target_ids": [],
                    "repaired_target_ids": [],
                    "repair_results": [],
                    "failed_targets": [],
                    "remaining_repairable_total": 0,
                    "remaining_repairable_target_ids": [],
                },
            )

        repair_result = self.webui_repair_all_deploy_targets(
            {
                **repair_payload,
                "target_ids": target_ids,
            },
        )
        if not repair_result.get("ok"):
            return repair_result

        refreshed_detail = self.webui_get_collection_group_payload(normalized_collection_group_id)
        refreshed_target_summary = self._summarize_related_deploy_targets(refreshed_detail)
        self._push_debug_log(
            "info",
            (
                "collection group repaired: "
                f"collection_group={normalized_collection_group_id} targets={','.join(target_ids)} "
                f"repaired={len(_to_str_list(repair_result.get('repaired_target_ids', [])))}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=repair_result.get("inventory", {}),
            skills_snapshot=repair_result.get("skills", {}),
            extra={
                "target_ids": target_ids,
                "repaired_target_ids": _to_str_list(repair_result.get("repaired_target_ids", [])),
                "repair_results": repair_result.get("results", []),
                "failed_targets": repair_result.get("failed_targets", []),
                "remaining_repairable_total": len(_to_str_list(refreshed_target_summary.get("repairable_target_ids", []))),
                "remaining_repairable_target_ids": _to_str_list(refreshed_target_summary.get("repairable_target_ids", [])),
            },
        )

    def webui_sync_all_skill_sources(self) -> dict[str, Any]:
        skills_snapshot = self.webui_get_skills_payload()
        source_rows = [
            item
            for item in skills_snapshot.get("source_rows", [])
            if isinstance(item, dict)
        ]
        syncable_sources = [
            item
            for item in source_rows
            if is_source_syncable(item)
        ]

        synced_source_ids: list[str] = []
        failed_sources: list[dict[str, Any]] = []
        registry = self._load_saved_skills_registry()

        for source in syncable_sources:
            source_id = _normalize_inventory_id(source.get("source_id", ""), default="")
            if not source_id:
                continue
            source_with_checkout = self._augment_source_row_with_git_checkout(source)
            sync_record = build_source_sync_record(source_with_checkout)
            registry = self._update_saved_registry_source_metadata(
                source_id=source_id,
                source_payload=source_with_checkout,
                sync_payload=sync_record,
            )
            if str(sync_record.get("sync_status") or "") == "ok":
                synced_source_ids.append(source_id)
            else:
                failed_sources.append(
                    {
                        "source_id": source_id,
                        "sync_status": str(sync_record.get("sync_status") or ""),
                        "sync_message": str(sync_record.get("sync_message") or ""),
                    },
                )

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        audit_event_id = self._append_skills_audit_event(
            "sources_sync_all",
            source_id="all",
            payload={
                "candidate_source_total": len(syncable_sources),
                "synced_source_ids": synced_source_ids,
                "failed_sources": failed_sources,
                "success_count": len(synced_source_ids),
                "failure_count": len(failed_sources),
            },
        )
        self._push_debug_log(
            "info" if not failed_sources else "warn",
            (
                "skill source batch sync: "
                f"syncable={len(syncable_sources)} ok={len(synced_source_ids)} failed={len(failed_sources)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "manifest": refreshed_skills_snapshot.get("manifest", {}),
            "registry": registry,
            "inventory": inventory_snapshot,
            "skills": refreshed_skills_snapshot,
            "synced_source_ids": synced_source_ids,
            "failed_sources": failed_sources,
            "audit_event_id": audit_event_id,
        }

    def _update_saved_registry_source_metadata(
        self,
        *,
        source_id: str,
        source_payload: dict[str, Any] | None = None,
        sync_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {}

        source_row = source_payload if isinstance(source_payload, dict) else {}
        sync_row = sync_payload if isinstance(sync_payload, dict) and sync_payload else None
        current_registry = self._load_saved_skills_registry()
        registry_source = next(
            (
                item
                for item in current_registry.get("sources", [])
                if isinstance(item, dict) and str(item.get("source_id", "")).strip() == normalized_source_id
            ),
            None,
        )
        merged_fields = {
            "source_id": normalized_source_id,
            "display_name": str(source_row.get("display_name") or normalized_source_id),
            "source_kind": str(source_row.get("source_kind") or source_row.get("skill_kind") or "skill"),
            "provider_key": str(source_row.get("provider_key") or "generic"),
            "enabled": _to_bool(source_row.get("enabled", True), True),
            "discovered": _to_bool(source_row.get("discovered", False), False),
            "auto_discovered": _to_bool(source_row.get("auto_discovered", False), False),
            "source_scope": str(source_row.get("source_scope") or "global"),
            "source_path": str(source_row.get("source_path") or ""),
            "locator": str(source_row.get("locator") or source_row.get("source_path") or source_row.get("registry_package_name") or ""),
            "source_subpath": str(source_row.get("source_subpath") or ""),
            "member_count": _to_int(source_row.get("member_count", 1), 1, 1),
            "member_skill_preview": _to_str_list(source_row.get("member_skill_preview", [])),
            "member_skill_overflow": _to_int(source_row.get("member_skill_overflow", 0), 0, 0),
            "management_hint": str(source_row.get("management_hint") or ""),
            "managed_by": str(source_row.get("managed_by") or ""),
            "update_policy": str(source_row.get("update_policy") or ""),
            "source_exists": _to_bool(source_row.get("source_exists", False), False),
            "last_seen_at": str(source_row.get("last_seen_at") or ""),
            "last_refresh_at": str((sync_row or {}).get("sync_checked_at") or _now_iso()),
            "source_age_days": source_row.get("source_age_days"),
            "freshness_status": str(source_row.get("freshness_status") or "missing"),
            "registry_package_name": str(source_row.get("registry_package_name") or ""),
            "registry_package_manager": str(source_row.get("registry_package_manager") or ""),
            "sync_auth_token": str(source_row.get("sync_auth_token") or ""),
            "sync_auth_header": str(source_row.get("sync_auth_header") or ""),
            "sync_api_base": str(source_row.get("sync_api_base") or ""),
            "compatible_software_ids": _to_str_list(source_row.get("compatible_software_ids", [])),
            "compatible_software_families": _to_str_list(source_row.get("compatible_software_families", [])),
            "tags": _to_str_list(source_row.get("tags", [])),
            "sync_status": str((sync_row or {}).get("sync_status") or ""),
            "sync_checked_at": str((sync_row or {}).get("sync_checked_at") or ""),
            "sync_kind": str((sync_row or {}).get("sync_kind") or ""),
            "sync_message": str((sync_row or {}).get("sync_message") or ""),
            "sync_local_revision": str((sync_row or {}).get("sync_local_revision") or ""),
            "sync_remote_revision": str((sync_row or {}).get("sync_remote_revision") or ""),
            "sync_resolved_revision": str((sync_row or {}).get("sync_resolved_revision") or ""),
            "sync_branch": str((sync_row or {}).get("sync_branch") or ""),
            "sync_dirty": _to_bool((sync_row or {}).get("sync_dirty", False), False),
            "sync_error_code": str((sync_row or {}).get("sync_error_code") or ""),
            "git_checkout_path": str(source_row.get("git_checkout_path") or ""),
            "git_checkout_managed": _to_bool(source_row.get("git_checkout_managed", False), False),
            "git_checkout_error": str(source_row.get("git_checkout_error") or ""),
            "registry_latest_version": str((sync_row or {}).get("registry_latest_version") or ""),
            "registry_published_at": str((sync_row or {}).get("registry_published_at") or ""),
            "registry_homepage": str((sync_row or {}).get("registry_homepage") or ""),
            "registry_description": str((sync_row or {}).get("registry_description") or ""),
        }

        if sync_row is None and isinstance(registry_source, dict):
            for key in (
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
            ):
                merged_fields[key] = registry_source.get(key)
            merged_fields["last_refresh_at"] = str(
                source_row.get("last_refresh_at")
                or registry_source.get("last_refresh_at")
                or _now_iso()
            )

        if isinstance(registry_source, dict):
            updated_registry = refresh_registry_source(
                current_registry,
                normalized_source_id,
                {**registry_source, **merged_fields},
                generated_at=_now_iso(),
            )
        else:
            updated_registry = register_registry_source(
                current_registry,
                merged_fields,
                generated_at=_now_iso(),
            )
        return self._save_skills_registry(updated_registry)

    def _stamp_registry_sources_refreshed(
        self,
        source_rows: list[dict[str, Any]] | None,
        *,
        refreshed_at: str = "",
    ) -> dict[str, Any]:
        rows = [item for item in (source_rows or []) if isinstance(item, dict)]
        if not rows:
            return self._load_saved_skills_registry()

        ts = str(refreshed_at or _now_iso()).strip() or _now_iso()
        registry = self._load_saved_skills_registry()
        refreshed_source_ids: list[str] = []

        for source_row in rows:
            source_id = _normalize_inventory_id(source_row.get("source_id"), default="")
            if not source_id:
                continue
            refreshed_payload = {
                **source_row,
                "source_id": source_id,
                "source_exists": _to_bool(source_row.get("source_exists", True), True),
                "last_seen_at": ts,
                "last_refresh_at": ts,
                "source_age_days": 0,
                "freshness_status": "fresh",
            }
            try:
                registry = refresh_registry_source(
                    registry,
                    source_id,
                    refreshed_payload,
                    generated_at=ts,
                )
            except Exception:
                registry = register_registry_source(
                    registry,
                    refreshed_payload,
                    generated_at=ts,
                )
            refreshed_source_ids.append(source_id)

        if refreshed_source_ids:
            registry = self._save_skills_registry(registry)
        return registry

    def _remove_source_from_saved_manifest(self, source_id: str) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {}
        manifest = self._load_saved_skills_manifest()
        sources = [
            item
            for item in manifest.get("sources", [])
            if isinstance(item, dict) and str(item.get("source_id", "")).strip() != normalized_source_id
        ]
        deploy_targets: list[dict[str, Any]] = []
        for item in manifest.get("deploy_targets", []):
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            next_item["selected_source_ids"] = [
                selected
                for selected in _to_str_list(item.get("selected_source_ids", []))
                if str(selected).strip() != normalized_source_id
            ]
            deploy_targets.append(next_item)
        manifest["sources"] = sources
        manifest["deploy_targets"] = deploy_targets
        return self._save_skills_manifest(manifest)

    def _deploy_source_ids_to_targets(
        self,
        source_ids: list[str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_source_ids = _dedupe_keep_order(
            [
                _normalize_inventory_id(item, default="")
                for item in source_ids
                if _normalize_inventory_id(item, default="")
            ],
        )
        if not normalized_source_ids:
            return {"ok": False, "message": "source_ids is required"}
        if not isinstance(payload, dict):
            payload = {}

        scope = _normalize_inventory_id(payload.get("scope", "global"), default="global")
        if scope not in {"global", "workspace"}:
            scope = "global"

        requested_software_ids = [
            _normalize_inventory_id(item, default="")
            for item in _to_str_list(payload.get("software_ids", []))
        ]
        target_ids = _to_str_list(payload.get("target_ids", []))
        for target_id in target_ids:
            software_text, _, scope_text = str(target_id).partition(":")
            software_id = _normalize_inventory_id(software_text, default="")
            if not software_id:
                continue
            requested_software_ids.append(software_id)
            if scope_text.strip():
                parsed_scope = _normalize_inventory_id(scope_text, default="global")
                if parsed_scope in {"global", "workspace"}:
                    scope = parsed_scope
        requested_software_ids = _dedupe_keep_order([item for item in requested_software_ids if item])
        if not requested_software_ids:
            return {"ok": False, "message": "software_ids or target_ids is required"}

        snapshot = self.webui_get_skills_payload()
        compatibility = snapshot.get("compatibility", {})
        for software_id in requested_software_ids:
            compatible_ids = set(_to_str_list(compatibility.get(software_id, [])))
            incompatible_sources = [
                source_id
                for source_id in normalized_source_ids
                if source_id not in compatible_ids
            ]
            if incompatible_sources:
                return {
                    "ok": False,
                    "message": (
                        "some sources are incompatible with software "
                        f"{software_id}: {', '.join(incompatible_sources)}"
                    ),
                }

        manifest = self._load_saved_skills_manifest()
        resolved_target_ids: list[str] = []
        for software_id in requested_software_ids:
            target_id = f"{software_id}:{scope}"
            resolved_target_ids.append(target_id)
            current_target = next(
                (
                    item for item in manifest.get("deploy_targets", [])
                    if isinstance(item, dict) and str(item.get("target_id", "")) == target_id
                ),
                None,
            )
            next_source_ids = _dedupe_keep_order(
                _to_str_list(current_target.get("selected_source_ids", [])) + normalized_source_ids,
            ) if isinstance(current_target, dict) else normalized_source_ids
            manifest = self._update_saved_manifest_target_selection(
                target_id=target_id,
                selected_source_ids=next_source_ids,
            )

        refresh_result = self._project_inventory_and_refresh_skills_from_manifest(
            manifest,
            skills_snapshot=snapshot,
        )
        inventory_snapshot = refresh_result.get("inventory", {})
        skills_snapshot = refresh_result.get("skills", {})
        manifest = refresh_result.get("manifest", manifest)
        return {
            "ok": True,
            "scope": scope,
            "source_ids": normalized_source_ids,
            "target_ids": resolved_target_ids,
            "manifest": manifest,
            "inventory": inventory_snapshot,
            "skills": skills_snapshot,
        }

    def _update_saved_manifest_target_selection(
        self,
        *,
        target_id: str,
        selected_source_ids: list[str],
    ) -> dict[str, Any]:
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            return {}
        manifest = self._load_saved_skills_manifest()
        deploy_targets = manifest.get("deploy_targets", [])
        if not isinstance(deploy_targets, list):
            deploy_targets = []

        selected_ids = _dedupe_keep_order([
            _normalize_inventory_id(item, default="")
            for item in selected_source_ids
            if _normalize_inventory_id(item, default="")
        ])

        software_id, _, scope_text = normalized_target_id.partition(":")
        software_key = _normalize_inventory_id(software_id, default="")
        scope = _normalize_inventory_id(scope_text or "global", default="global")
        if scope not in {"global", "workspace"}:
            scope = "global"

        updated = False
        for item in deploy_targets:
            if not isinstance(item, dict):
                continue
            if str(item.get("target_id", "")).strip() != normalized_target_id:
                continue
            item["software_id"] = software_key
            item["scope"] = scope
            item["selected_source_ids"] = selected_ids
            updated = True
            break
        if not updated:
            deploy_targets.append(
                {
                    "target_id": normalized_target_id,
                    "software_id": software_key,
                    "scope": scope,
                    "selected_source_ids": selected_ids,
                },
            )
        manifest["deploy_targets"] = deploy_targets
        return self._save_skills_manifest(manifest)

    def webui_remove_skill_source(self, source_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = payload
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        current_registry = self.webui_get_skills_payload().get("registry", {})
        try:
            updated_registry = remove_registry_source(current_registry, normalized_source_id, generated_at=_now_iso())
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        self._save_skills_registry(updated_registry)
        manifest = self._remove_source_from_saved_manifest(normalized_source_id)
        audit_event_id = self._append_skills_audit_event("remove", source_id=normalized_source_id, payload={})
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        refreshed_skills_snapshot = self._skills_state().get("last_overview", {})
        return {
            "ok": True,
            "removed_source_id": normalized_source_id,
            "registry": refreshed_skills_snapshot.get("registry", updated_registry),
            "manifest": manifest,
            "skills": refreshed_skills_snapshot,
            "inventory": inventory_snapshot,
            "audit_event_id": audit_event_id,
        }

    def webui_update_deploy_target(self, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            return {"ok": False, "message": "target_id is required"}
        if not isinstance(payload, dict):
            payload = {}

        skills_snapshot = self.webui_get_skills_payload()
        deploy_rows = skills_snapshot.get("deploy_rows", [])
        target = next(
            (
                item for item in deploy_rows
                if isinstance(item, dict) and str(item.get("target_id", "")) == normalized_target_id
            ),
            None,
        )
        if not target:
            return {"ok": False, "message": f"target_id not found: {normalized_target_id}"}

        available_source_ids = set(_to_str_list(target.get("available_source_ids", [])))
        requested_source_ids = _dedupe_keep_order([
            _normalize_inventory_id(item, default="")
            for item in _to_str_list(payload.get("selected_source_ids", []))
            if _normalize_inventory_id(item, default="")
        ])
        incompatible = [item for item in requested_source_ids if item not in available_source_ids]
        if incompatible:
            return {
                "ok": False,
                "message": (
                    "some selected_source_ids are incompatible with target "
                    f"{normalized_target_id}: {', '.join(incompatible)}"
                ),
            }

        manifest = self._update_saved_manifest_target_selection(
            target_id=normalized_target_id,
            selected_source_ids=requested_source_ids,
        )
        refresh_result = self._project_inventory_and_refresh_skills_from_manifest(
            manifest,
            skills_snapshot=skills_snapshot,
        )
        inventory_snapshot = refresh_result.get("inventory", {})
        updated_skills_snapshot = refresh_result.get("skills", {})
        manifest = refresh_result.get("manifest", manifest)
        self._push_debug_log(
            "info",
            (
                "deploy target updated: "
                f"target={normalized_target_id} selected={','.join(requested_source_ids)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "manifest": manifest,
            "inventory": inventory_snapshot,
            "skills": updated_skills_snapshot,
        }

    def _prepare_deploy_target_repair(
        self,
        deploy_target: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(deploy_target, dict):
            return {"ok": False, "message": "deploy_target is required"}
        if payload is not None and not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}
        payload = payload or {}

        normalized_target_id = str(deploy_target.get("target_id", "")).strip()
        if not normalized_target_id:
            return {"ok": False, "message": "target_id is required"}

        available_actions = _dedupe_keep_order(_to_str_list(deploy_target.get("repair_actions", [])))
        requested_actions = _dedupe_keep_order(_to_str_list(payload.get("actions", []))) or available_actions
        invalid_actions = [action for action in requested_actions if action not in available_actions]
        if invalid_actions:
            return {
                "ok": False,
                "message": (
                    "unsupported repair actions for target "
                    f"{normalized_target_id}: {', '.join(invalid_actions)}"
                ),
            }

        selected_source_ids = _dedupe_keep_order(_to_str_list(deploy_target.get("selected_source_ids", [])))
        changes: list[str] = []

        if "create_target_path" in requested_actions:
            target_path = str(deploy_target.get("target_path", "") or "").strip()
            if not target_path:
                return {"ok": False, "message": f"target {normalized_target_id} does not declare a target_path"}
            try:
                Path(target_path).mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return {"ok": False, "message": f"failed to create target path for {normalized_target_id}: {exc}"}
            changes.append("create_target_path")

        if "drop_missing_sources" in requested_actions:
            missing_sources = set(_to_str_list(deploy_target.get("missing_source_ids", [])))
            next_source_ids = [source_id for source_id in selected_source_ids if source_id not in missing_sources]
            if next_source_ids != selected_source_ids:
                selected_source_ids = next_source_ids
                changes.append("drop_missing_sources")

        if "drop_incompatible_sources" in requested_actions:
            incompatible_sources = set(_to_str_list(deploy_target.get("incompatible_source_ids", [])))
            next_source_ids = [source_id for source_id in selected_source_ids if source_id not in incompatible_sources]
            if next_source_ids != selected_source_ids:
                selected_source_ids = next_source_ids
                changes.append("drop_incompatible_sources")

        return {
            "ok": True,
            "target_id": normalized_target_id,
            "requested_actions": requested_actions,
            "changes": changes,
            "selected_source_ids": selected_source_ids,
        }

    def webui_repair_deploy_target(self, target_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            return {"ok": False, "message": "target_id is required"}
        if payload is not None and not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}
        payload = payload or {}

        target_payload = self.webui_get_deploy_target_payload(normalized_target_id)
        if not target_payload.get("ok"):
            return target_payload

        deploy_target = target_payload.get("deploy_target", {})
        if not isinstance(deploy_target, dict):
            return {"ok": False, "message": f"target_id not found: {normalized_target_id}"}

        repair_result = self._prepare_deploy_target_repair(deploy_target, payload)
        if not repair_result.get("ok"):
            return repair_result

        manifest = self._update_saved_manifest_target_selection(
            target_id=normalized_target_id,
            selected_source_ids=_to_str_list(repair_result.get("selected_source_ids", [])),
        )
        refresh_result = self._project_inventory_and_refresh_skills_from_manifest(
            manifest,
            skills_snapshot=target_payload.get("skills", {}) if isinstance(target_payload.get("skills", {}), dict) else None,
        )
        inventory_snapshot = refresh_result.get("inventory", {})
        updated_skills_snapshot = refresh_result.get("skills", {})
        manifest = refresh_result.get("manifest", manifest)
        refreshed_target = next(
            (
                item for item in updated_skills_snapshot.get("deploy_rows", [])
                if isinstance(item, dict) and str(item.get("target_id", "")) == normalized_target_id
            ),
            None,
        )
        self._push_debug_log(
            "info",
            (
                "deploy target repaired: "
                "target="
                f"{normalized_target_id} actions="
                f"{','.join(_to_str_list(repair_result.get('changes', [])) or _to_str_list(repair_result.get('requested_actions', [])) or ['noop'])}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "changes": _to_str_list(repair_result.get("changes", [])),
            "requested_actions": _to_str_list(repair_result.get("requested_actions", [])),
            "manifest": manifest,
            "inventory": inventory_snapshot,
            "skills": updated_skills_snapshot,
            "deploy_target": refreshed_target or deploy_target,
        }

    def webui_repair_all_deploy_targets(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload is not None and not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}
        payload = payload or {}

        requested_target_ids = {
            str(item or "").strip()
            for item in _to_str_list(payload.get("target_ids", []))
            if str(item or "").strip()
        }
        skills_snapshot = self.webui_get_skills_payload()
        deploy_rows = [
            item
            for item in skills_snapshot.get("deploy_rows", [])
            if isinstance(item, dict)
            and _to_str_list(item.get("repair_actions", []))
            and (
                not requested_target_ids
                or str(item.get("target_id", "")).strip() in requested_target_ids
            )
        ]

        repair_results: list[dict[str, Any]] = []
        failed_targets: list[dict[str, Any]] = []
        repaired_target_ids: list[str] = []

        for deploy_target in deploy_rows:
            repair_result = self._prepare_deploy_target_repair(deploy_target, payload)
            normalized_target_id = str(deploy_target.get("target_id", "")).strip()
            if not repair_result.get("ok"):
                failed_targets.append(
                    {
                        "target_id": normalized_target_id,
                        "message": str(repair_result.get("message") or "repair failed"),
                    },
                )
                continue

            self._update_saved_manifest_target_selection(
                target_id=normalized_target_id,
                selected_source_ids=_to_str_list(repair_result.get("selected_source_ids", [])),
            )
            if _to_str_list(repair_result.get("changes", [])):
                repaired_target_ids.append(normalized_target_id)
            repair_results.append(
                {
                    "target_id": normalized_target_id,
                    "changes": _to_str_list(repair_result.get("changes", [])),
                    "requested_actions": _to_str_list(repair_result.get("requested_actions", [])),
                },
            )

        refresh_result = self._project_inventory_and_refresh_skills_from_manifest(
            self._load_saved_skills_manifest(),
            skills_snapshot=skills_snapshot,
        )
        inventory_snapshot = refresh_result.get("inventory", {})
        updated_skills_snapshot = refresh_result.get("skills", {})
        deploy_target_index = {
            str(item.get("target_id", "")).strip(): item
            for item in updated_skills_snapshot.get("deploy_rows", [])
            if isinstance(item, dict) and str(item.get("target_id", "")).strip()
        }
        self._push_debug_log(
            "info" if not failed_targets else "warn",
            (
                "deploy targets repair-all: "
                f"candidates={len(deploy_rows)} repaired={len(repaired_target_ids)} failed={len(failed_targets)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "inventory": inventory_snapshot,
            "skills": updated_skills_snapshot,
            "repairable_target_ids": [str(item.get("target_id", "")).strip() for item in deploy_rows if str(item.get("target_id", "")).strip()],
            "repaired_target_ids": repaired_target_ids,
            "results": repair_results,
            "failed_targets": failed_targets,
            "remaining_repairable_total": updated_skills_snapshot.get("counts", {}).get("deploy_repairable_total", 0),
            "deploy_targets": [
                deploy_target_index[target_id]
                for target_id in repaired_target_ids
                if target_id in deploy_target_index
            ],
        }

    def webui_reproject_deploy_target(self, target_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            return {"ok": False, "message": "target_id is required"}
        if payload is not None and not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}

        target_payload = self.webui_get_deploy_target_payload(normalized_target_id)
        if not target_payload.get("ok"):
            return target_payload

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        updated_skills_snapshot = self._skills_state().get("last_overview", {})
        refreshed_target_payload = self.webui_get_deploy_target_payload(normalized_target_id)
        self._push_debug_log(
            "info",
            f"deploy target reprojected: target={normalized_target_id}",
            source="webui",
        )
        return {
            "ok": True,
            "inventory": inventory_snapshot,
            "skills": updated_skills_snapshot,
            "deploy_target": refreshed_target_payload.get("deploy_target"),
            "generated_projection": refreshed_target_payload.get("generated_projection", {}),
            "warnings": refreshed_target_payload.get("warnings", []),
        }

    def webui_deploy_skill_source(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
        deploy_result = self._deploy_source_ids_to_targets([normalized_source_id], payload)
        if not deploy_result.get("ok"):
            return deploy_result
        audit_event_id = self._append_skills_audit_event(
            "source_deploy",
            source_id=normalized_source_id,
            payload={
                "scope": str(deploy_result.get("scope") or ""),
                "target_ids": _to_str_list(deploy_result.get("target_ids", [])),
            },
        )
        self._push_debug_log(
            "info",
            (
                "skill source deployed: "
                f"source={normalized_source_id} scope={deploy_result.get('scope', 'global')} "
                f"targets={','.join(_to_str_list(deploy_result.get('target_ids', [])))}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "manifest": deploy_result.get("manifest", {}),
            "inventory": deploy_result.get("inventory", {}),
            "skills": deploy_result.get("skills", {}),
            "target_ids": deploy_result.get("target_ids", []),
            "source": self.webui_get_skill_source_payload(normalized_source_id).get("source"),
            "audit_event_id": audit_event_id,
        }

    def webui_deploy_install_unit(self, install_unit_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._resolve_install_unit_action_context(install_unit_id)
        if not context.get("ok"):
            return context

        deploy_result = self._deploy_source_ids_to_targets(
            _to_str_list(context.get("source_ids", [])),
            payload,
        )
        if not deploy_result.get("ok"):
            return deploy_result

        normalized_install_unit_id = str(context.get("install_unit_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "install_unit_deploy",
            source_id=normalized_install_unit_id,
            payload={
                "scope": str(deploy_result.get("scope") or ""),
                "target_ids": _to_str_list(deploy_result.get("target_ids", [])),
                "source_ids": _to_str_list(context.get("source_ids", [])),
            },
        )
        self._push_debug_log(
            "info",
            (
                "install unit deployed: "
                f"install_unit={normalized_install_unit_id} scope={deploy_result.get('scope', 'global')} "
                f"targets={','.join(_to_str_list(deploy_result.get('target_ids', [])))}"
            ),
            source="webui",
        )
        return self._build_install_unit_mutation_response(
            normalized_install_unit_id,
            inventory_snapshot=deploy_result.get("inventory", {}),
            skills_snapshot=deploy_result.get("skills", {}),
            extra={
                "manifest": deploy_result.get("manifest", {}),
                "target_ids": deploy_result.get("target_ids", []),
                "audit_event_id": audit_event_id,
            },
        )

    def webui_deploy_collection_group(self, collection_group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._resolve_collection_group_action_context(collection_group_id)
        if not context.get("ok"):
            return context

        deploy_result = self._deploy_source_ids_to_targets(
            _to_str_list(context.get("source_ids", [])),
            payload,
        )
        if not deploy_result.get("ok"):
            return deploy_result

        normalized_collection_group_id = str(context.get("collection_group_id", "")).strip()
        audit_event_id = self._append_skills_audit_event(
            "collection_group_deploy",
            source_id=normalized_collection_group_id,
            payload={
                "scope": str(deploy_result.get("scope") or ""),
                "target_ids": _to_str_list(deploy_result.get("target_ids", [])),
                "source_ids": _to_str_list(context.get("source_ids", [])),
            },
        )
        self._push_debug_log(
            "info",
            (
                "collection group deployed: "
                f"collection_group={normalized_collection_group_id} scope={deploy_result.get('scope', 'global')} "
                f"targets={','.join(_to_str_list(deploy_result.get('target_ids', [])))}"
            ),
            source="webui",
        )
        return self._build_collection_group_mutation_response(
            normalized_collection_group_id,
            inventory_snapshot=deploy_result.get("inventory", {}),
            skills_snapshot=deploy_result.get("skills", {}),
            extra={
                "manifest": deploy_result.get("manifest", {}),
                "target_ids": deploy_result.get("target_ids", []),
                "audit_event_id": audit_event_id,
            },
        )

    def webui_doctor_skills(self) -> dict[str, Any]:
        snapshot = self.webui_get_skills_payload()
        return {
            "ok": bool(snapshot.get("ok", True)),
            "generated_at": snapshot.get("generated_at"),
            "doctor": snapshot.get("doctor", {}),
            "warnings": snapshot.get("warnings", []),
            "counts": snapshot.get("counts", {}),
        }

    def webui_update_inventory_bindings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}

        current_bindings = normalize_skill_bindings_payload(self.config.get("skill_bindings", []))
        incoming_bindings = payload.get("bindings")
        skills_snapshot = self.webui_get_skills_payload()
        manifest = (
            skills_snapshot.get("manifest", {})
            if isinstance(skills_snapshot.get("manifest", {}), dict)
            else self._load_saved_skills_manifest()
        )

        if incoming_bindings is not None:
            try:
                next_bindings = normalize_skill_bindings_payload(incoming_bindings)
            except Exception as exc:
                return {"ok": False, "message": f"invalid bindings payload: {exc}"}
            known_software_ids = set(self._skills_snapshot_known_software_ids(skills_snapshot))
            for item in next_bindings:
                if not isinstance(item, dict) or not _to_bool(item.get("enabled", True), True):
                    continue
                software_id = _normalize_inventory_id(item.get("software_id"), default="")
                skill_id = _normalize_inventory_id(item.get("skill_id"), default="")
                if not software_id or not skill_id:
                    continue
                if known_software_ids and software_id not in known_software_ids:
                    return {"ok": False, "message": f"software_id not found: {software_id}"}
                compatible_ids = set(self._skills_snapshot_compatible_source_ids(skills_snapshot, software_id))
                if compatible_ids and skill_id not in compatible_ids:
                    return {
                        "ok": False,
                        "message": (
                            "some skill_ids are incompatible with software "
                            f"{software_id}: {skill_id}"
                        ),
                    }
            manifest = self._replace_saved_manifest_target_selections_from_bindings(manifest, next_bindings)
        else:
            software_id = _normalize_inventory_id(payload.get("software_id", ""))
            if not software_id:
                return {"ok": False, "message": "software_id is required"}
            scope = _normalize_inventory_id(payload.get("scope", "global"), default="global")
            if scope not in {"global", "workspace"}:
                scope = "global"

            requested_skill_ids = [
                _normalize_inventory_id(item)
                for item in _to_str_list(payload.get("skill_ids", []))
            ]
            requested_skill_ids = _dedupe_keep_order([sid for sid in requested_skill_ids if sid])

            software_exists = software_id in set(self._skills_snapshot_known_software_ids(skills_snapshot))
            if not software_exists:
                return {"ok": False, "message": f"software_id not found: {software_id}"}

            compatible_ids = set(self._skills_snapshot_compatible_source_ids(skills_snapshot, software_id))
            incompatible = [sid for sid in requested_skill_ids if compatible_ids and sid not in compatible_ids]
            if incompatible:
                return {
                    "ok": False,
                    "message": (
                        "some skill_ids are incompatible with software "
                        f"{software_id}: {', '.join(incompatible)}"
                    ),
                }

            next_bindings = replace_bindings_for_scope(
                current_bindings,
                software_id=software_id,
                skill_ids=requested_skill_ids,
                scope=scope,
            )

        self.config["skill_bindings"] = next_bindings
        target_key = f"{software_id}:{scope}" if incoming_bindings is None else ""
        if incoming_bindings is None and target_key:
            manifest = self._update_saved_manifest_target_selection(
                target_id=target_key,
                selected_source_ids=requested_skill_ids,
            )
        self._persist_plugin_config()
        refresh_result = self._project_inventory_and_refresh_skills_from_manifest(
            manifest,
            skills_snapshot=skills_snapshot,
        )
        snapshot = refresh_result.get("inventory", {})
        skills_snapshot = refresh_result.get("skills", {})
        manifest = refresh_result.get("manifest", manifest)
        self._push_debug_log(
            "info",
            (
                "inventory bindings updated: "
                f"bindings={len(next_bindings)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "skill_bindings": next_bindings,
            "inventory": snapshot,
            "skills": skills_snapshot,
            "manifest": manifest,
        }

    @staticmethod
    def _normalize_targets_payload(raw: Any) -> dict[str, dict[str, Any]]:
        if isinstance(raw, dict):
            parsed = raw
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except Exception as exc:
                raise ValueError(f"targets_json is not valid JSON: {exc}") from exc
        elif raw is None:
            return {}
        else:
            raise ValueError("targets_json must be a JSON object or JSON string")

        if not isinstance(parsed, dict):
            raise ValueError("targets_json root must be an object")

        normalized: dict[str, dict[str, Any]] = {}
        for name, cfg in parsed.items():
            target_name = str(name or "").strip()
            if not target_name:
                continue
            if not isinstance(cfg, dict):
                raise ValueError(f"target[{target_name}] must be an object")
            normalized[target_name] = dict(cfg)
        return normalized

    def webui_get_config_payload(self) -> dict[str, Any]:
        mode = str(self.config.get("target_config_mode", "human")).strip().lower()
        if mode not in {"human", "developer"}:
            mode = "human"
        try:
            software_catalog = normalize_software_catalog_payload(
                self.config.get("software_catalog", []),
                fallback_defaults=False,
            )
        except Exception:
            software_catalog = []
        try:
            skill_catalog = normalize_skill_catalog_payload(self.config.get("skill_catalog", []))
        except Exception:
            skill_catalog = []
        try:
            skill_bindings = normalize_skill_bindings_payload(self.config.get("skill_bindings", []))
        except Exception:
            skill_bindings = []

        raw_targets_json = self.config.get("targets_json", "")
        if isinstance(raw_targets_json, dict):
            targets_json_text = json.dumps(raw_targets_json, ensure_ascii=False, indent=2)
        else:
            targets_json_text = str(raw_targets_json or "")

        human_entries: list[dict[str, Any]] = []
        raw_human_entries = self.config.get("human_targets", [])
        if isinstance(raw_human_entries, list):
            for item in raw_human_entries:
                parsed = self._normalize_human_target_config(item)
                if not parsed:
                    continue
                name, cfg = parsed
                human_entries.append(self._target_cfg_to_human_template_entry(name, cfg))

        if not human_entries:
            fallback_targets = self._load_targets_from_json()
            if not fallback_targets:
                fallback_targets = DEFAULT_TARGETS
            for name, cfg in sorted(fallback_targets.items(), key=lambda item: str(item[0])):
                if not isinstance(cfg, dict):
                    continue
                human_entries.append(self._target_cfg_to_human_template_entry(name, cfg))

        web_cfg = self.config.get("web_admin", {})
        if not isinstance(web_cfg, dict):
            web_cfg = {}
        inventory_opts = self._inventory_runtime_options()

        web_password = str(web_cfg.get("password", "") or "")
        web_password_configured = bool(web_password.strip())

        config_payload = {
            "enabled": _to_bool(self.config.get("enabled", True), True),
            "poll_interval_minutes": _to_int(self.config.get("poll_interval_minutes", 30), 30, 1),
            "default_check_interval_hours": _to_float(
                self.config.get("default_check_interval_hours", 24),
                24.0,
                0.0,
            ),
            "auto_update_on_schedule": _to_bool(self.config.get("auto_update_on_schedule", True), True),
            "notify_admin_on_schedule": _to_bool(self.config.get("notify_admin_on_schedule", True), True),
            "notify_on_schedule_noop": _to_bool(self.config.get("notify_on_schedule_noop", False), False),
            "dry_run": _to_bool(self.config.get("dry_run", False), False),
            "env_check_timeout_s": _to_int(self.config.get("env_check_timeout_s", 8), 8, 1),
            "admin_sid_list": _to_str_list(self.config.get("admin_sid_list", [])),
            "target_config_mode": mode,
            "human_targets": human_entries,
            "targets_json": targets_json_text,
            "web_admin": {
                "enabled": _to_bool(web_cfg.get("enabled", False), False),
                "host": str(web_cfg.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1",
                "port": _to_int(web_cfg.get("port", 8099), 8099, 1),
                "password": "",
                "password_configured": web_password_configured,
            },
            "web_admin_url": str(self.config.get("web_admin_url", "") or ""),
            "software_catalog": software_catalog,
            "skill_catalog": skill_catalog,
            "skill_bindings": skill_bindings,
            "skill_management_mode": str(inventory_opts.get("skill_management_mode", "npx")),
            "npx_skills_command": str(inventory_opts.get("npx_command", "npx")),
            "npx_skills_timeout_s": _to_int(inventory_opts.get("npx_timeout_s", 12), 12, 1),
            "npx_skills_include_project": _to_bool(inventory_opts.get("npx_include_project", True), True),
            "npx_skills_include_global": _to_bool(inventory_opts.get("npx_include_global", True), True),
            "npx_skills_workdir": str(inventory_opts.get("npx_workdir", "")),
            "auto_discover_cli": _to_bool(inventory_opts.get("auto_discover_cli", True), True),
            "auto_discover_cli_max": _to_int(inventory_opts.get("auto_discover_cli_max", 120), 120, 20),
            "auto_cli_only_known": _to_bool(inventory_opts.get("auto_cli_only_known", True), True),
            "auto_cli_include_commands": _to_str_list(inventory_opts.get("auto_cli_include_commands", [])),
            "auto_cli_exclude_commands": _to_str_list(inventory_opts.get("auto_cli_exclude_commands", [])),
        }

        return {
            "ok": True,
            "config": config_payload,
            "meta": {
                "target_config_modes": ["human", "developer"],
                "strategies": ["cargo_path_git", "command", "system_package"],
                "system_package_managers": sorted(SYSTEM_PACKAGE_REQUIRED_COMMANDS.keys()),
                "software_kinds": ["cli", "gui", "claw", "other"],
                "binding_scopes": ["global", "workspace"],
                "skill_management_modes": ["npx", "filesystem", "hybrid"],
                "web_admin_password_configured": web_password_configured,
            },
        }

    def webui_update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"ok": False, "message": "invalid payload, expected object"}
        incoming = payload.get("config", payload)
        if not isinstance(incoming, dict):
            return {"ok": False, "message": "config must be an object"}

        try:
            mode = str(incoming.get("target_config_mode", self.config.get("target_config_mode", "human"))).strip().lower()
            if mode not in {"human", "developer"}:
                mode = "human"

            self.config["enabled"] = _to_bool(incoming.get("enabled", self.config.get("enabled", True)), True)
            self.config["poll_interval_minutes"] = _to_int(
                incoming.get("poll_interval_minutes", self.config.get("poll_interval_minutes", 30)),
                30,
                1,
            )
            self.config["default_check_interval_hours"] = _to_float(
                incoming.get(
                    "default_check_interval_hours",
                    self.config.get("default_check_interval_hours", 24),
                ),
                24.0,
                0.0,
            )
            self.config["auto_update_on_schedule"] = _to_bool(
                incoming.get("auto_update_on_schedule", self.config.get("auto_update_on_schedule", True)),
                True,
            )
            self.config["notify_admin_on_schedule"] = _to_bool(
                incoming.get("notify_admin_on_schedule", self.config.get("notify_admin_on_schedule", True)),
                True,
            )
            self.config["notify_on_schedule_noop"] = _to_bool(
                incoming.get("notify_on_schedule_noop", self.config.get("notify_on_schedule_noop", False)),
                False,
            )
            self.config["dry_run"] = _to_bool(
                incoming.get("dry_run", self.config.get("dry_run", False)),
                False,
            )
            self.config["env_check_timeout_s"] = _to_int(
                incoming.get("env_check_timeout_s", self.config.get("env_check_timeout_s", 8)),
                8,
                1,
            )
            self.config["admin_sid_list"] = _to_str_list(
                incoming.get("admin_sid_list", self.config.get("admin_sid_list", [])),
            )
            self.config["target_config_mode"] = mode

            current_web_cfg = self.config.get("web_admin", {})
            if not isinstance(current_web_cfg, dict):
                current_web_cfg = {}
            current_web_password = str(current_web_cfg.get("password", "") or "")

            web_cfg_raw = incoming.get("web_admin", current_web_cfg)
            if web_cfg_raw is None:
                web_cfg_raw = {}
            if not isinstance(web_cfg_raw, dict):
                return {"ok": False, "message": "web_admin must be an object"}
            web_host = str(web_cfg_raw.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
            web_port = _to_int(web_cfg_raw.get("port", 8099), 8099, 1)
            if web_port > 65535:
                web_port = 65535
            password_mode = str(web_cfg_raw.get("password_mode", "") or "").strip().lower()
            raw_password = str(web_cfg_raw.get("password", "") or "")
            if password_mode == "keep":
                next_web_password = current_web_password
            elif password_mode == "clear":
                next_web_password = ""
            elif password_mode == "set":
                next_web_password = raw_password
            elif "password" in web_cfg_raw:
                next_web_password = raw_password
            else:
                next_web_password = current_web_password
            self.config["web_admin"] = {
                "enabled": _to_bool(web_cfg_raw.get("enabled", False), False),
                "host": web_host,
                "port": web_port,
                "password": next_web_password,
            }

            parsed_targets_from_json: dict[str, dict[str, Any]] | None = None

            if "targets_json" in incoming:
                parsed_targets_from_json = self._normalize_targets_payload(incoming.get("targets_json"))
                self.config["targets_json"] = json.dumps(
                    parsed_targets_from_json,
                    ensure_ascii=False,
                    indent=2,
                )

            if "human_targets" in incoming:
                raw_human_targets = incoming.get("human_targets")
                if not isinstance(raw_human_targets, list):
                    return {"ok": False, "message": "human_targets must be a list"}
                human_entries: list[dict[str, Any]] = []
                seen_names: set[str] = set()
                for idx, item in enumerate(raw_human_targets):
                    parsed = self._normalize_human_target_config(item)
                    if not parsed:
                        continue
                    name, cfg = parsed
                    if name in seen_names:
                        return {
                            "ok": False,
                            "message": f"duplicated target name in human_targets: {name} (index={idx})",
                        }
                    seen_names.add(name)
                    human_entries.append(self._target_cfg_to_human_template_entry(name, cfg))
                self.config["human_targets"] = human_entries

            if "software_catalog" in incoming:
                software_catalog = normalize_software_catalog_payload(
                    incoming.get("software_catalog"),
                    fallback_defaults=False,
                )
                self.config["software_catalog"] = software_catalog
            if "skill_catalog" in incoming:
                skill_catalog = normalize_skill_catalog_payload(incoming.get("skill_catalog"))
                self.config["skill_catalog"] = skill_catalog
            if "skill_bindings" in incoming:
                skill_bindings = normalize_skill_bindings_payload(incoming.get("skill_bindings"))
                self.config["skill_bindings"] = skill_bindings

            if "skill_management_mode" in incoming:
                inventory_mode = str(incoming.get("skill_management_mode", "npx")).strip().lower()
                if inventory_mode not in {"npx", "filesystem", "hybrid"}:
                    return {"ok": False, "message": "skill_management_mode must be one of: npx/filesystem/hybrid"}
                self.config["skill_management_mode"] = inventory_mode

            if "npx_skills_command" in incoming:
                self.config["npx_skills_command"] = str(incoming.get("npx_skills_command", "npx") or "npx").strip() or "npx"
            if "npx_skills_timeout_s" in incoming:
                self.config["npx_skills_timeout_s"] = _to_int(incoming.get("npx_skills_timeout_s", 12), 12, 1)
            if "npx_skills_include_project" in incoming:
                self.config["npx_skills_include_project"] = _to_bool(
                    incoming.get("npx_skills_include_project", True),
                    True,
                )
            if "npx_skills_include_global" in incoming:
                self.config["npx_skills_include_global"] = _to_bool(
                    incoming.get("npx_skills_include_global", True),
                    True,
                )
            if "npx_skills_workdir" in incoming:
                self.config["npx_skills_workdir"] = str(incoming.get("npx_skills_workdir", "") or "").strip()

            if "auto_discover_cli" in incoming:
                self.config["auto_discover_cli"] = _to_bool(incoming.get("auto_discover_cli", True), True)
            if "auto_discover_cli_max" in incoming:
                self.config["auto_discover_cli_max"] = _to_int(incoming.get("auto_discover_cli_max", 120), 120, 20)
            if "auto_cli_only_known" in incoming:
                self.config["auto_cli_only_known"] = _to_bool(incoming.get("auto_cli_only_known", True), True)
            if "auto_cli_include_commands" in incoming:
                self.config["auto_cli_include_commands"] = _to_str_list(incoming.get("auto_cli_include_commands", []))
            if "auto_cli_exclude_commands" in incoming:
                self.config["auto_cli_exclude_commands"] = _to_str_list(incoming.get("auto_cli_exclude_commands", []))

            if mode == "human":
                self._bootstrap_human_targets_if_needed()
                raw_entries = self.config.get("human_targets", [])
                targets_from_human: dict[str, dict[str, Any]] = {}
                if isinstance(raw_entries, list):
                    for item in raw_entries:
                        parsed = self._normalize_human_target_config(item)
                        if not parsed:
                            continue
                        name, cfg = parsed
                        targets_from_human[name] = cfg
                self.config["targets_json"] = json.dumps(
                    targets_from_human,
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                if parsed_targets_from_json is None:
                    parsed_targets_from_json = self._load_targets_from_json()
                human_entries: list[dict[str, Any]] = []
                for name, cfg in sorted(parsed_targets_from_json.items(), key=lambda item: str(item[0])):
                    if not isinstance(cfg, dict):
                        continue
                    human_entries.append(self._target_cfg_to_human_template_entry(name, cfg))
                self.config["human_targets"] = human_entries

            self._refresh_software_overview()
            self._refresh_inventory_snapshot()
            self._persist_plugin_config()
            self._push_debug_log(
                "info",
                (
                    "webui config updated: "
                    f"mode={mode} targets={len(self._load_targets())} "
                    f"web_enabled={_to_bool(self.config.get('web_admin', {}).get('enabled', False), False)}"
                ),
                source="webui",
            )
            return self.webui_get_config_payload()
        except Exception as exc:
            logger.error("[onesync] webui_update_config failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def webui_start_run(self, scope: str, targets: Any) -> dict[str, Any]:
        scope_key = str(scope or "all").strip().lower()
        all_targets = self._load_targets()
        if scope_key == "filtered":
            requested = _dedupe_keep_order(_to_str_list(targets))
            selected = [
                name
                for name in requested
                if name in all_targets and _to_bool(all_targets[name].get("enabled", True), True)
            ]
        else:
            scope_key = "all"
            selected = [
                name
                for name, cfg in all_targets.items()
                if _to_bool(cfg.get("enabled", True), True)
            ]

        if not selected:
            self._push_debug_log(
                "warn",
                f"webui run rejected: no enabled targets matched (scope={scope_key})",
                source="webui-run",
            )
            return {
                "ok": False,
                "status": "invalid",
                "message": "No enabled targets matched.",
            }

        async with self._web_job_lock:
            for job in self._web_jobs.values():
                if str(job.get("status", "")).lower() in {"queued", "running"}:
                    self._push_debug_log(
                        "warn",
                        (
                            "webui run rejected: another job running "
                            f"(job_id={job.get('id', '')})"
                        ),
                        source="webui-run",
                    )
                    return {
                        "ok": False,
                        "status": "busy",
                        "message": "Another OneSync WebUI job is running.",
                        "job": json.loads(json.dumps(job, ensure_ascii=False)),
                    }

            job_id = secrets.token_hex(8)
            now = _now_iso()
            job = {
                "id": job_id,
                "status": "queued",
                "scope": scope_key,
                "created_at": now,
                "started_at": "",
                "finished_at": "",
                "total_targets": len(selected),
                "targets": selected,
                "summary": "queued",
                "results": [],
            }
            self._web_jobs[job_id] = job
            task = asyncio.create_task(
                self._webui_run_job_task(job_id, selected, scope_key),
                name=f"onesync-webui-job-{job_id}",
            )
            self._web_job_tasks[job_id] = task

            def _cleanup(done_task: asyncio.Task, *, jid: str = job_id):
                self._web_job_tasks.pop(jid, None)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error("[onesync] webui job task cleanup error (%s): %s", jid, exc)

            task.add_done_callback(_cleanup)
            self._push_debug_log(
                "info",
                (
                    f"webui run accepted job_id={job_id} scope={scope_key} "
                    f"targets={','.join(selected)}"
                ),
                source="webui-run",
            )
            return {
                "ok": True,
                "status": "accepted",
                "job": json.loads(json.dumps(job, ensure_ascii=False)),
            }

    async def _webui_run_job_task(
        self,
        job_id: str,
        selected_targets: list[str],
        scope: str,
    ) -> None:
        async with self._web_job_lock:
            job = self._web_jobs.get(job_id)
            if not isinstance(job, dict):
                return
            job["status"] = "running"
            job["started_at"] = _now_iso()
            job["summary"] = "running"
        self._push_debug_log(
            "info",
            (
                f"job started id={job_id} scope={scope} "
                f"targets={','.join(selected_targets)}"
            ),
            source="webui-job",
        )

        try:
            summary, results = await self._run_targets(
                selected_targets,
                mode="run",
                trigger=f"webui-{scope}",
                force=False,
                allow_update=True,
            )
            ok_all = all(bool(item.get("ok")) for item in results)
            changed_any = any(bool(item.get("changed")) for item in results)
            final_status = "success" if ok_all else "partial"
            if not results:
                final_status = "success"
            async with self._web_job_lock:
                target = self._web_jobs.get(job_id)
                if isinstance(target, dict):
                    target["status"] = final_status
                    target["finished_at"] = _now_iso()
                    target["summary"] = summary
                    target["changed"] = changed_any
                    target["results"] = results
            self._push_debug_log(
                "info" if final_status == "success" else "warn",
                f"job finished id={job_id} status={final_status}",
                source="webui-job",
            )
        except asyncio.CancelledError:
            async with self._web_job_lock:
                target = self._web_jobs.get(job_id)
                if isinstance(target, dict):
                    target["status"] = "cancelled"
                    target["finished_at"] = _now_iso()
                    target["summary"] = "cancelled"
            self._push_debug_log(
                "warn",
                f"job cancelled id={job_id}",
                source="webui-job",
            )
            raise
        except Exception as exc:
            async with self._web_job_lock:
                target = self._web_jobs.get(job_id)
                if isinstance(target, dict):
                    target["status"] = "error"
                    target["finished_at"] = _now_iso()
                    target["summary"] = f"webui job error: {exc}"
            logger.error("[onesync] webui job failed (%s): %s", job_id, exc)
            self._push_debug_log(
                "error",
                f"job failed id={job_id}: {exc}",
                source="webui-job",
            )
        finally:
            async with self._web_job_lock:
                ordered = sorted(
                    self._web_jobs.items(),
                    key=lambda item: str(item[1].get("created_at", "")),
                    reverse=True,
                )
                if len(ordered) > self._max_web_jobs:
                    for stale_id, _ in ordered[self._max_web_jobs :]:
                        self._web_jobs.pop(stale_id, None)

    async def _init_webui_if_enabled(self) -> None:
        web_cfg = self.config.get("web_admin", {})
        enabled = False
        if isinstance(web_cfg, dict):
            enabled = _to_bool(web_cfg.get("enabled", False), False)

        if not enabled:
            self._set_web_admin_url("")
            self._push_debug_log(
                "warn",
                "webui disabled by config",
                source="webui",
            )
            return

        try:
            self._webui_server = OneSyncWebUIServer(self)
            await self._webui_server.start()
            self._set_web_admin_url(self._webui_server.public_url)
            self._push_debug_log(
                "info",
                f"webui started at {self._webui_server.public_url}",
                source="webui",
            )
        except Exception as exc:
            logger.error("[onesync] failed to start webui: %s", exc)
            self._set_web_admin_url("")
            self._webui_server = None
            self._push_debug_log(
                "error",
                f"failed to start webui: {exc}",
                source="webui",
            )

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self.state = {"targets": {}, "env": {}, "inventory": {}, "skills": {}}
            return
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                parsed = {}
            targets = parsed.get("targets", {})
            if not isinstance(targets, dict):
                targets = {}
            env_state = parsed.get("env", {})
            if not isinstance(env_state, dict):
                env_state = {}
            inventory_state = parsed.get("inventory", {})
            if not isinstance(inventory_state, dict):
                inventory_state = {}
            skills_state = parsed.get("skills", {})
            if not isinstance(skills_state, dict):
                skills_state = {}
            self.state = {"targets": targets, "env": env_state, "inventory": inventory_state, "skills": skills_state}
        except Exception as exc:
            logger.error("[onesync] failed to load state, reset: %s", exc)
            self.state = {"targets": {}, "env": {}, "inventory": {}, "skills": {}}

    async def _save_state(self) -> None:
        async with self._state_lock:
            self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.state_path)

    def _target_state(self, target_name: str) -> dict[str, Any]:
        targets = self.state.setdefault("targets", {})
        if target_name not in targets or not isinstance(targets.get(target_name), dict):
            targets[target_name] = {}
        return targets[target_name]

    def _env_state(self) -> dict[str, Any]:
        env_state = self.state.setdefault("env", {})
        if not isinstance(env_state, dict):
            env_state = {}
            self.state["env"] = env_state
        return env_state

    def _inventory_state(self) -> dict[str, Any]:
        inventory_state = self.state.setdefault("inventory", {})
        if not isinstance(inventory_state, dict):
            inventory_state = {}
            self.state["inventory"] = inventory_state
        return inventory_state

    def _skills_state(self) -> dict[str, Any]:
        skills_state = self.state.setdefault("skills", {})
        if not isinstance(skills_state, dict):
            skills_state = {}
            self.state["skills"] = skills_state
        return skills_state

    @staticmethod
    def _build_skills_update_all_progress_snapshot(
        *,
        run_id: str = "",
        status: str = "idle",
        workflow_kind: str = "aggregate_update_all",
        candidate_install_unit_total: int = 0,
        planned_install_unit_total: int = 0,
        actionable_install_unit_total: int = 0,
        command_install_unit_total: int = 0,
        source_sync_install_unit_total: int = 0,
        completed_command_install_unit_total: int = 0,
        completed_source_sync_install_unit_total: int = 0,
        skipped_install_unit_total: int = 0,
        failure_count: int = 0,
        success_count: int = 0,
        source_sync_cache_hit_total: int = 0,
        atom_candidate_install_unit_total: int = 0,
        atom_improved_count: int = 0,
        atom_unchanged_count: int = 0,
        started_at: str = "",
        updated_at: str = "",
        message: str = "",
    ) -> dict[str, Any]:
        normalized_status = str(status or "idle").strip().lower() or "idle"
        normalized_workflow_kind = str(workflow_kind or "aggregate_update_all").strip().lower() or "aggregate_update_all"
        now_iso = _now_iso()
        normalized_started_at = str(started_at or "").strip()
        if normalized_status != "idle" and not normalized_started_at:
            normalized_started_at = now_iso
        normalized_updated_at = str(updated_at or "").strip() or now_iso
        completed_command_total = max(0, int(completed_command_install_unit_total or 0))
        completed_source_sync_total = max(0, int(completed_source_sync_install_unit_total or 0))
        skipped_total = max(0, int(skipped_install_unit_total or 0))
        return {
            "run_id": str(run_id or "").strip(),
            "status": normalized_status,
            "workflow_kind": normalized_workflow_kind,
            "active": normalized_status in SKILLS_AGGREGATE_UPDATE_ACTIVE_STATUSES,
            "candidate_install_unit_total": max(0, int(candidate_install_unit_total or 0)),
            "planned_install_unit_total": max(0, int(planned_install_unit_total or 0)),
            "actionable_install_unit_total": max(0, int(actionable_install_unit_total or 0)),
            "command_install_unit_total": max(0, int(command_install_unit_total or 0)),
            "source_sync_install_unit_total": max(0, int(source_sync_install_unit_total or 0)),
            "completed_command_install_unit_total": completed_command_total,
            "completed_source_sync_install_unit_total": completed_source_sync_total,
            "completed_install_unit_total": completed_command_total + completed_source_sync_total + skipped_total,
            "skipped_install_unit_total": skipped_total,
            "failure_count": max(0, int(failure_count or 0)),
            "success_count": max(0, int(success_count or 0)),
            "source_sync_cache_hit_total": max(0, int(source_sync_cache_hit_total or 0)),
            "atom_candidate_install_unit_total": max(0, int(atom_candidate_install_unit_total or 0)),
            "atom_improved_count": max(0, int(atom_improved_count or 0)),
            "atom_unchanged_count": max(0, int(atom_unchanged_count or 0)),
            "started_at": normalized_started_at,
            "updated_at": normalized_updated_at,
            "message": str(message or "").strip(),
        }

    def _get_skills_update_all_progress_snapshot(self) -> dict[str, Any]:
        snapshot = self._skills_update_all_progress
        if not isinstance(snapshot, dict):
            snapshot = self._build_skills_update_all_progress_snapshot()
            self._skills_update_all_progress = snapshot
        return dict(snapshot)

    def _replace_skills_update_all_progress_snapshot(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        payload = snapshot if isinstance(snapshot, dict) else {}
        normalized = self._build_skills_update_all_progress_snapshot(
            run_id=payload.get("run_id", ""),
            status=payload.get("status", "idle"),
            workflow_kind=payload.get("workflow_kind", "aggregate_update_all"),
            candidate_install_unit_total=payload.get("candidate_install_unit_total", 0),
            planned_install_unit_total=payload.get("planned_install_unit_total", 0),
            actionable_install_unit_total=payload.get("actionable_install_unit_total", 0),
            command_install_unit_total=payload.get("command_install_unit_total", 0),
            source_sync_install_unit_total=payload.get("source_sync_install_unit_total", 0),
            completed_command_install_unit_total=payload.get("completed_command_install_unit_total", 0),
            completed_source_sync_install_unit_total=payload.get("completed_source_sync_install_unit_total", 0),
            skipped_install_unit_total=payload.get("skipped_install_unit_total", 0),
            failure_count=payload.get("failure_count", 0),
            success_count=payload.get("success_count", 0),
            source_sync_cache_hit_total=payload.get("source_sync_cache_hit_total", 0),
            atom_candidate_install_unit_total=payload.get("atom_candidate_install_unit_total", 0),
            atom_improved_count=payload.get("atom_improved_count", 0),
            atom_unchanged_count=payload.get("atom_unchanged_count", 0),
            started_at=payload.get("started_at", ""),
            updated_at=payload.get("updated_at", ""),
            message=payload.get("message", ""),
        )
        self._skills_update_all_progress = normalized
        return dict(normalized)

    def _update_skills_update_all_progress_snapshot(self, **patch: Any) -> dict[str, Any]:
        current = self._get_skills_update_all_progress_snapshot()
        current.update({key: value for key, value in patch.items()})
        return self._replace_skills_update_all_progress_snapshot(current)

    def webui_get_update_all_aggregate_progress_payload(
        self,
        run_id: str = "",
    ) -> dict[str, Any]:
        snapshot = self._get_skills_update_all_progress_snapshot()
        requested_run_id = str(run_id or "").strip()
        current_run_id = str(snapshot.get("run_id") or "").strip()
        if requested_run_id and requested_run_id != current_run_id:
            return {
                "ok": False,
                "message": f"aggregate update-all progress not found: {requested_run_id}",
                "progress": snapshot,
            }
        return {
            "ok": True,
            "run_id": current_run_id,
            "status": str(snapshot.get("status") or "idle").strip().lower() or "idle",
            "workflow_kind": str(snapshot.get("workflow_kind") or "aggregate_update_all").strip().lower()
            or "aggregate_update_all",
            "progress": snapshot,
        }

    def webui_get_update_all_aggregate_history_payload(
        self,
        *,
        limit: int = 40,
    ) -> dict[str, Any]:
        normalized_limit = _to_int(limit, 40, 1)
        if normalized_limit > 500:
            normalized_limit = 500

        warnings: list[str] = []
        history_by_run_id: dict[str, dict[str, Any]] = {}

        if self.skills_audit_path.exists():
            try:
                with self.skills_audit_path.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = str(raw_line or "").strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(parsed, dict):
                            continue
                        action = str(parsed.get("action") or "").strip().lower()
                        if action not in {"aggregates_update_all", "install_atom_refresh_all"}:
                            continue
                        payload = parsed.get("payload", {})
                        if not isinstance(payload, dict):
                            payload = {}
                        run_id = str(payload.get("run_id") or "").strip()
                        if not run_id:
                            continue
                        timestamp = str(parsed.get("timestamp") or "").strip()
                        current = history_by_run_id.get(run_id)
                        if not isinstance(current, dict):
                            current = {
                                "run_id": run_id,
                                "timestamp": timestamp,
                                "workflow_kind": "aggregate_update_all",
                                "source_id": str(parsed.get("source_id") or "").strip(),
                                "update": {},
                                "atom_refresh": {},
                            }
                            history_by_run_id[run_id] = current

                        current_timestamp = _parse_iso(str(current.get("timestamp") or "").strip())
                        candidate_timestamp = _parse_iso(timestamp)
                        if candidate_timestamp and (
                            not current_timestamp or candidate_timestamp >= current_timestamp
                        ):
                            current["timestamp"] = timestamp

                        if action == "install_atom_refresh_all":
                            current["workflow_kind"] = "improve_all"
                            current["atom_refresh"] = payload
                        elif action == "aggregates_update_all":
                            current["update"] = payload
                            if str(current.get("workflow_kind") or "").strip().lower() != "improve_all":
                                current["workflow_kind"] = "aggregate_update_all"
            except Exception as exc:
                logger.error("[onesync] read update-all aggregate history failed: %s", exc)
                warnings.append(f"failed to read update-all aggregate history: {exc}")

        items = sorted(
            history_by_run_id.values(),
            key=lambda item: (
                _parse_iso(str(item.get("timestamp") or "").strip()) or datetime.min.replace(tzinfo=timezone.utc),
                str(item.get("run_id") or ""),
            ),
            reverse=True,
        )[:normalized_limit]
        return {
            "ok": True,
            "generated_at": _now_iso(),
            "counts": {
                "total": len(items),
            },
            "items": items,
            "warnings": warnings,
        }

    async def _record_event(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            logger.error("[onesync] append events log failed: %s", exc)

    def _render_software_overview(self) -> list[dict[str, Any]]:
        targets = self._load_targets()
        entries: list[dict[str, Any]] = []
        if not targets:
            return entries

        for name, cfg in sorted(targets.items(), key=lambda item: str(item[0])):
            st = self._target_state(name)
            entries.append(
                {
                    "__template_key": "software_item",
                    "software_name": name,
                    "current_version": str(st.get("current_version", "-") or "-"),
                    "latest_version": str(st.get("latest_version", "-") or "-"),
                    "enabled": "是" if _to_bool(cfg.get("enabled", True), True) else "否",
                    "strategy": str(cfg.get("strategy", "command") or "command"),
                    "last_checked_at": str(st.get("last_checked_at", "-") or "-"),
                },
            )
        return entries

    def _refresh_software_overview(self) -> None:
        overview = self._render_software_overview()
        current = self.config.get("software_overview", [])
        if not isinstance(current, list):
            current = []
        if current == overview:
            return
        self.config["software_overview"] = overview
        self._persist_plugin_config()

    def _collect_required_commands_for_target(self, target_cfg: dict[str, Any]) -> list[str]:
        commands: list[str] = []
        strategy = _normalize_strategy_name(target_cfg.get("strategy", "command"), default="command")

        for raw in _to_str_list(target_cfg.get("required_commands", [])):
            executable = _extract_primary_executable(raw) or str(raw).strip()
            if executable:
                commands.append(executable)
        if strategy == "cargo_path_git":
            commands.extend(["git", "cargo"])
            binary_path = str(target_cfg.get("binary_path", "")).strip()
            if binary_path:
                commands.append(binary_path)
        elif strategy == "system_package":
            manager = _normalize_system_package_manager(target_cfg.get("manager", ""))
            commands.extend(SYSTEM_PACKAGE_REQUIRED_COMMANDS.get(manager, []))

        for key in ("current_version_cmd", "latest_version_cmd", "verify_cmd"):
            executable = _extract_primary_executable(target_cfg.get(key, ""))
            if executable and not ("{" in executable and "}" in executable):
                commands.append(executable)

        for key in ("build_commands", "update_commands"):
            for cmd in _to_str_list(target_cfg.get(key, [])):
                executable = _extract_primary_executable(cmd)
                if executable and not ("{" in executable and "}" in executable):
                    commands.append(executable)

        return _dedupe_keep_order(commands)

    async def _probe_command_env(self, command_name: str, timeout_s: int) -> dict[str, Any]:
        name = str(command_name or "").strip()
        if not name:
            return {
                "name": "",
                "ok": False,
                "path": "",
                "version": "",
                "message": "empty command name",
            }

        quoted_name = shlex.quote(name)
        if "/" in name:
            lookup_cmd = f"if [ -x {quoted_name} ]; then printf '%s\\n' {quoted_name}; else exit 127; fi"
        else:
            lookup_cmd = f"command -v {quoted_name}"
        lookup_res = await self.runner.run(lookup_cmd, timeout_s=timeout_s)

        found_path = _first_non_empty_line(lookup_res.stdout)
        if not lookup_res.ok or not found_path:
            message = (
                "command not found"
                if not lookup_res.timed_out
                else f"lookup timed out ({timeout_s}s)"
            )
            return {
                "name": name,
                "ok": False,
                "path": "",
                "version": "",
                "message": message,
            }

        quoted_path = shlex.quote(found_path)
        version_cmd = (
            f"{quoted_path} --version 2>&1 || "
            f"{quoted_path} -V 2>&1 || "
            f"{quoted_path} version 2>&1"
        )
        version_res = await self.runner.run(version_cmd, timeout_s=timeout_s)
        version_line = _first_non_empty_line(version_res.stdout)
        if not version_line:
            version_line = _first_non_empty_line(version_res.stderr)

        return {
            "name": name,
            "ok": True,
            "path": found_path,
            "version": _short_text(version_line, 220),
            "message": "" if version_line else "version output unavailable",
        }

    def _probe_path(
        self,
        path_text: str,
        *,
        expect_dir: bool = False,
        expect_executable: bool = False,
        require_git_metadata: bool = False,
    ) -> dict[str, Any]:
        text = str(path_text or "").strip()
        if not text:
            return {
                "ok": False,
                "path": "",
                "detail": "path is empty",
            }
        path_obj = Path(text)
        try:
            if not path_obj.exists():
                return {
                    "ok": False,
                    "path": text,
                    "detail": "path not found",
                }
            if expect_dir and not path_obj.is_dir():
                return {
                    "ok": False,
                    "path": text,
                    "detail": "path is not a directory",
                }
            if expect_executable and not path_obj.is_file():
                return {
                    "ok": False,
                    "path": text,
                    "detail": "path is not a file",
                }
            if expect_executable and not (path_obj.stat().st_mode & 0o111):
                return {
                    "ok": False,
                    "path": text,
                    "detail": "file is not executable",
                }
            if require_git_metadata and not (path_obj / ".git").exists():
                return {
                    "ok": False,
                    "path": text,
                    "detail": "not a git worktree (missing .git)",
                }
        except Exception as exc:
            return {
                "ok": False,
                "path": text,
                "detail": f"path probe failed: {_short_text(str(exc), 120)}",
            }
        return {
            "ok": True,
            "path": text,
            "detail": "ok",
        }

    async def _run_env_check_for_target(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any]:
        strategy = _normalize_strategy_name(target_cfg.get("strategy", "command"), default="command")
        report: dict[str, Any] = {
            "target": target_name,
            "strategy": strategy,
            "enabled": _to_bool(target_cfg.get("enabled", True), True),
            "ok": True,
            "paths": [],
            "commands": [],
        }

        if strategy == "cargo_path_git":
            repo_probe = self._probe_path(
                target_cfg.get("repo_path", ""),
                expect_dir=True,
                require_git_metadata=True,
            )
            report["paths"].append({"name": "repo_path", **repo_probe})
            if not repo_probe.get("ok"):
                report["ok"] = False

            binary_probe = self._probe_path(
                target_cfg.get("binary_path", ""),
                expect_executable=True,
            )
            report["paths"].append({"name": "binary_path", **binary_probe})
            if not binary_probe.get("ok"):
                report["ok"] = False
        elif strategy in {"command", "cmd"}:
            current_cmd = str(target_cfg.get("current_version_cmd", "")).strip()
            if not current_cmd:
                report["paths"].append(
                    {
                        "name": "current_version_cmd",
                        "ok": False,
                        "path": "",
                        "detail": "current_version_cmd is empty",
                    },
                )
                report["ok"] = False
        elif strategy == "system_package":
            package_name = str(target_cfg.get("package_name", "")).strip()
            if not package_name:
                report["paths"].append(
                    {
                        "name": "package_name",
                        "ok": False,
                        "path": "",
                        "detail": "package_name is empty",
                    },
                )
                report["ok"] = False
            manager = _normalize_system_package_manager(target_cfg.get("manager", ""))
            if manager not in SYSTEM_PACKAGE_REQUIRED_COMMANDS:
                report["paths"].append(
                    {
                        "name": "manager",
                        "ok": False,
                        "path": str(target_cfg.get("manager", "")).strip(),
                        "detail": (
                            "unsupported manager, expected one of: "
                            + ", ".join(sorted(SYSTEM_PACKAGE_REQUIRED_COMMANDS.keys()))
                        ),
                    },
                )
                report["ok"] = False

        required_commands = self._collect_required_commands_for_target(target_cfg)
        for command_name in required_commands:
            probe = await self._probe_command_env(command_name, timeout_s)
            report["commands"].append(probe)
            if not probe.get("ok"):
                report["ok"] = False

        return report

    def _render_env_check_report(self, reports: list[dict[str, Any]], timeout_s: int) -> str:
        ok_count = sum(1 for item in reports if item.get("ok"))
        fail_count = len(reports) - ok_count
        lines = [
            "Environment Check",
            f"timeout_s={timeout_s} targets={len(reports)} ok={ok_count} fail={fail_count}",
        ]
        for report in reports:
            lines.append(
                (
                    f"- {report.get('target')} strategy={report.get('strategy')} "
                    f"enabled={report.get('enabled')} ok={report.get('ok')}"
                ),
            )
            for path_item in report.get("paths", []):
                lines.append(
                    (
                        f"  path[{path_item.get('name')}] ok={path_item.get('ok')} "
                        f"value={path_item.get('path') or '-'} detail={path_item.get('detail') or '-'}"
                    ),
                )
            for cmd_item in report.get("commands", []):
                if cmd_item.get("ok"):
                    lines.append(
                        (
                            f"  cmd[{cmd_item.get('name')}] ok=true "
                            f"path={cmd_item.get('path') or '-'} "
                            f"version={cmd_item.get('version') or '-'}"
                        ),
                    )
                else:
                    lines.append(
                        (
                            f"  cmd[{cmd_item.get('name')}] ok=false "
                            f"detail={cmd_item.get('message') or '-'}"
                        ),
                    )
        return "\n".join(lines)

    async def _run_env_checks(self, selected_targets: list[str]) -> tuple[str, list[dict[str, Any]]]:
        targets = self._load_targets()
        names = [name for name in selected_targets if name in targets]
        if not names:
            return "no matched targets", []

        timeout_s = _to_int(self.config.get("env_check_timeout_s", 8), 8, 1)
        reports: list[dict[str, Any]] = []

        async with self._run_lock:
            for name in names:
                report = await self._run_env_check_for_target(name, targets[name], timeout_s)
                reports.append(report)

            env_state = self._env_state()
            env_state["last_checked_at"] = _now_iso()
            env_state["total_targets"] = len(reports)
            env_state["ok_targets"] = sum(1 for item in reports if item.get("ok"))
            env_state["results"] = [
                {
                    "target": item.get("target", ""),
                    "ok": bool(item.get("ok")),
                    "missing_commands": sum(
                        1 for cmd in item.get("commands", []) if not cmd.get("ok")
                    ),
                    "path_issues": sum(
                        1 for path_item in item.get("paths", []) if not path_item.get("ok")
                    ),
                }
                for item in reports
            ]
            await self._save_state()

        return self._render_env_check_report(reports, timeout_s), reports

    def _render_status(self) -> str:
        targets = self._load_targets()
        web_cfg = self.config.get("web_admin", {})
        if not isinstance(web_cfg, dict):
            web_cfg = {}
        lines = [
            "Software Updater Status",
            f"enabled={_to_bool(self.config.get('enabled', True), True)}",
            f"poll_interval_minutes={_to_int(self.config.get('poll_interval_minutes', 30), 30, 1)}",
            f"auto_update_on_schedule={_to_bool(self.config.get('auto_update_on_schedule', True), True)}",
            f"target_config_mode={str(self.config.get('target_config_mode', 'human')).strip().lower() or 'human'}",
            f"web_admin_enabled={_to_bool(web_cfg.get('enabled', False), False)}",
            f"web_admin_url={str(self.config.get('web_admin_url', '') or '-')}",
            "",
            f"targets={len(targets)}",
        ]
        for name, cfg in targets.items():
            st = self._target_state(name)
            interval = _to_float(cfg.get("check_interval_hours", 24), 24, 0.0)
            lines.append(
                (
                    f"- {name} strategy={cfg.get('strategy', 'command')} "
                    f"enabled={_to_bool(cfg.get('enabled', True), True)} interval_h={interval} "
                    f"last_checked={st.get('last_checked_at', '-')} "
                    f"status={st.get('last_status', '-')} "
                    f"current={st.get('current_version', '-')} "
                    f"latest={st.get('latest_version', '-')} "
                    f"best_remote={st.get('last_best_remote', '-')}"
                ),
            )
        env_state = self._env_state()
        env_total = _to_int(env_state.get("total_targets", 0), 0, 0)
        env_ok = _to_int(env_state.get("ok_targets", 0), 0, 0)
        lines.append("")
        lines.append(
            (
                f"env_last_checked={env_state.get('last_checked_at', '-')} "
                f"env_ok_targets={env_ok}/{env_total}"
            ),
        )
        lines.append("env_hint=run /updater env [target] for detailed diagnostics")
        for item in env_state.get("results", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                (
                    f"- env {item.get('target', '-')} ok={item.get('ok')} "
                    f"missing_cmds={item.get('missing_commands', '-')} "
                    f"path_issues={item.get('path_issues', '-')}"
                ),
            )
        return "\n".join(lines)

    def _is_target_due(self, target_name: str, target_cfg: dict[str, Any], now: datetime) -> bool:
        if not _to_bool(target_cfg.get("enabled", True), True):
            return False
        interval_h = _to_float(
            target_cfg.get("check_interval_hours", self.config.get("default_check_interval_hours", 24)),
            24.0,
            0.0,
        )
        if interval_h <= 0:
            return False

        st = self._target_state(target_name)
        last_checked = _parse_iso(st.get("last_checked_at"))
        if not last_checked:
            return True
        return (now - last_checked).total_seconds() >= interval_h * 3600

    def _build_runtime_context(self, target_name: str, target_cfg: dict[str, Any]) -> dict[str, Any]:
        data = dict(target_cfg)
        data["target_name"] = target_name
        data["plugin_name"] = PLUGIN_NAME
        data["plugin_data_dir"] = str(self.plugin_data_dir)
        data["state_path"] = str(self.state_path)
        data["events_path"] = str(self.events_path)
        return data

    async def _notify_admins(self, text: str) -> None:
        admin_sid_list = self.config.get("admin_sid_list", [])
        if not isinstance(admin_sid_list, list):
            return
        message_chain = MessageChain([Comp.Plain(text=text)])
        for sid in admin_sid_list:
            sid_text = str(sid).strip()
            if not sid_text:
                continue
            try:
                await self.context.send_message(sid_text, message_chain)
            except Exception as exc:
                logger.error("[onesync] notify admin(%s) failed: %s", sid_text, exc)

    async def _run_target(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        *,
        mode: str,
        trigger: str,
        force: bool,
        allow_update: bool,
    ) -> dict[str, Any]:
        now_iso = _now_iso()
        state = self._target_state(target_name)
        runtime_ctx = self._build_runtime_context(target_name, target_cfg)
        strategy_name = str(target_cfg.get("strategy", "command")).strip().lower()

        result_record: dict[str, Any] = {
            "target": target_name,
            "strategy": strategy_name,
            "mode": mode,
            "trigger": trigger,
            "ok": False,
            "changed": False,
            "current_version": state.get("current_version", ""),
            "latest_version": state.get("latest_version", ""),
            "message": "",
            "timestamp": now_iso,
        }

        async def _finalize_result() -> dict[str, Any]:
            level = "info" if _to_bool(result_record.get("ok", False), False) else "error"
            self._push_debug_log(
                level,
                (
                    f"{target_name} mode={mode} trigger={trigger} "
                    f"ok={result_record.get('ok')} changed={result_record.get('changed')} "
                    f"msg={result_record.get('message', '')}"
                ),
                target=target_name,
                source="target-run",
            )
            await self._record_event(result_record)
            return result_record

        try:
            strategy = build_strategy(
                strategy_name,
                self.runner,
                logger=lambda m: logger.info("[onesync][%s] %s", target_name, m),
            )
        except Exception as exc:
            result_record["message"] = f"cannot build strategy: {exc}"
            state["last_checked_at"] = now_iso
            state["last_status"] = "error"
            state["last_message"] = result_record["message"]
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            return await _finalize_result()

        check_result: CheckResult = await strategy.check(target_name, target_cfg, runtime_ctx)
        result_record["current_version"] = check_result.current_version
        result_record["latest_version"] = check_result.latest_version
        if isinstance(check_result.extra, dict):
            best_remote = str(check_result.extra.get("best_remote", "")).strip()
            if best_remote:
                result_record["best_remote"] = best_remote
                state["last_best_remote"] = best_remote

        state["last_checked_at"] = now_iso
        state["current_version"] = check_result.current_version
        state["latest_version"] = check_result.latest_version
        state["last_check_message"] = check_result.message
        state["last_needs_update"] = check_result.needs_update

        if not check_result.ok:
            result_record["ok"] = False
            result_record["message"] = f"check failed: {check_result.message}"
            state["last_status"] = "error"
            state["last_message"] = result_record["message"]
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            return await _finalize_result()

        if mode == "check" or not allow_update:
            result_record["ok"] = True
            result_record["message"] = (
                "check-only completed: "
                f"current={check_result.current_version}, "
                f"latest={check_result.latest_version or 'unknown'}, "
                f"needs_update={check_result.needs_update}"
            )
            state["last_status"] = "ok"
            state["last_message"] = result_record["message"]
            state["consecutive_failures"] = 0
            return await _finalize_result()

        if not force and not check_result.needs_update:
            result_record["ok"] = True
            result_record["message"] = "already up to date"
            state["last_status"] = "ok"
            state["last_message"] = result_record["message"]
            state["consecutive_failures"] = 0
            return await _finalize_result()

        dry_run = _to_bool(self.config.get("dry_run", False), False)
        update_result: UpdateResult = await strategy.update(
            target_name,
            target_cfg,
            runtime_ctx,
            dry_run=dry_run,
            force=force,
        )

        result_record["ok"] = update_result.ok
        result_record["changed"] = update_result.changed
        result_record["message"] = update_result.message
        if update_result.new_version:
            result_record["current_version"] = update_result.new_version
            state["current_version"] = update_result.new_version
        state["last_updated_at"] = now_iso if update_result.ok else state.get("last_updated_at", "")
        state["last_status"] = "ok" if update_result.ok else "error"
        state["last_message"] = update_result.message
        if update_result.ok:
            state["consecutive_failures"] = 0
        else:
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1

        return await _finalize_result()

    async def _run_targets(
        self,
        selected_targets: list[str],
        *,
        mode: str,
        trigger: str,
        force: bool,
        allow_update: bool,
    ) -> tuple[str, list[dict[str, Any]]]:
        targets = self._load_targets()
        names = [name for name in selected_targets if name in targets]
        if not names:
            return "no matched targets", []

        results: list[dict[str, Any]] = []
        async with self._run_lock:
            for name in names:
                cfg = targets[name]
                if not _to_bool(cfg.get("enabled", True), True):
                    results.append(
                        {
                            "target": name,
                            "ok": True,
                            "changed": False,
                            "message": "target disabled",
                            "current_version": self._target_state(name).get("current_version", ""),
                            "latest_version": self._target_state(name).get("latest_version", ""),
                        },
                    )
                    continue
                result = await self._run_target(
                    name,
                    cfg,
                    mode=mode,
                    trigger=trigger,
                    force=force,
                    allow_update=allow_update,
                )
                results.append(result)
            await self._save_state()
            self._refresh_software_overview()

        ok_count = sum(1 for item in results if item.get("ok"))
        changed_count = sum(1 for item in results if item.get("changed"))
        fail_count = len(results) - ok_count

        lines = [
            f"mode={mode} trigger={trigger} total={len(results)} ok={ok_count} fail={fail_count} changed={changed_count}",
        ]
        for item in results:
            lines.append(
                f"- {item.get('target')}: ok={item.get('ok')} changed={item.get('changed')} "
                f"current={item.get('current_version', '') or '-'} "
                f"latest={item.get('latest_version', '') or '-'} "
                f"msg={item.get('message', '')}",
            )
        return "\n".join(lines), results

    async def _run_due_targets(self) -> tuple[str, list[dict[str, Any]]]:
        now = datetime.now(timezone.utc)
        targets = self._load_targets()
        due: list[str] = []
        for name, cfg in targets.items():
            if self._is_target_due(name, cfg, now):
                due.append(name)
        if not due:
            return "no targets due", []

        auto_update = _to_bool(self.config.get("auto_update_on_schedule", True), True)
        mode = "run" if auto_update else "check"
        return await self._run_targets(
            due,
            mode=mode,
            trigger="scheduled",
            force=False,
            allow_update=auto_update,
        )

    async def _scheduled_loop(self, poll_interval_min: int) -> None:
        while not self._stop_event.is_set():
            try:
                summary, results = await self._run_due_targets()
                if results:
                    should_notify = _to_bool(
                        self.config.get("notify_admin_on_schedule", True),
                        True,
                    )
                    notify_on_noop = _to_bool(
                        self.config.get("notify_on_schedule_noop", False),
                        False,
                    )
                    has_change_or_error = any(
                        (item.get("changed") or not item.get("ok")) for item in results
                    )
                    if should_notify and (has_change_or_error or notify_on_noop):
                        await self._notify_admins(summary)
                logger.info("[onesync] scheduled tick: %s", summary)
                self._push_debug_log(
                    "info",
                    f"scheduled tick: {summary}",
                    source="scheduler",
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[onesync] scheduled loop error: %s", exc)
                self._push_debug_log(
                    "error",
                    f"scheduled loop error: {exc}",
                    source="scheduler",
                )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(1, int(poll_interval_min)) * 60,
                )
            except asyncio.TimeoutError:
                continue

    @filter.command_group("updater")
    def updater(self):
        """通用软件更新器。"""
        pass

    @updater.command("status")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def updater_status(self, event: AstrMessageEvent):
        """查看更新器状态。"""
        self._refresh_software_overview()
        yield event.plain_result(self._render_status())

    @updater.command("env")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def updater_env(self, event: AstrMessageEvent, target: str = ""):
        """检测更新依赖环境，输出命令可用性和版本信息。"""
        targets = self._load_targets()
        target_name = str(target or "").strip()
        selected = [target_name] if target_name else list(targets.keys())
        summary, _ = await self._run_env_checks(selected)
        yield event.plain_result(summary)

    @updater.command("check")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def updater_check(self, event: AstrMessageEvent, target: str = ""):
        """立即检查版本，不执行更新。"""
        targets = self._load_targets()
        target_name = str(target or "").strip()
        selected = [target_name] if target_name else list(targets.keys())
        summary, _ = await self._run_targets(
            selected,
            mode="check",
            trigger="manual-check",
            force=True,
            allow_update=False,
        )
        yield event.plain_result(summary)

    @updater.command("run")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def updater_run(self, event: AstrMessageEvent, target: str = ""):
        """立即执行检查并在需要时更新。"""
        targets = self._load_targets()
        target_name = str(target or "").strip()
        selected = [target_name] if target_name else list(targets.keys())
        summary, _ = await self._run_targets(
            selected,
            mode="run",
            trigger="manual-run",
            force=False,
            allow_update=True,
        )
        yield event.plain_result(summary)

    @updater.command("force")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def updater_force(self, event: AstrMessageEvent, target: str = ""):
        """强制执行更新命令（忽略版本比较结果）。"""
        targets = self._load_targets()
        target_name = str(target or "").strip()
        selected = [target_name] if target_name else list(targets.keys())
        summary, _ = await self._run_targets(
            selected,
            mode="run",
            trigger="manual-force",
            force=True,
            allow_update=True,
        )
        yield event.plain_result(summary)
