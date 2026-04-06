from __future__ import annotations

import asyncio
import json
import re
import secrets
import shlex
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
from .skills_core import (
    build_skills_overview,
    manifest_to_binding_rows,
    normalize_saved_skills_manifest,
)
from .updater_core import (
    CheckResult,
    CommandRunner,
    UpdateResult,
    build_strategy,
)
from .webui_server import OneSyncWebUIServer

PLUGIN_NAME = "astrbot_plugin_onesync"

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
        self.skills_sources_dir = self.skills_state_dir / "sources"
        self.skills_generated_dir = self.skills_state_dir / "generated"

        self.state: dict[str, Any] = {"targets": {}, "env": {}, "inventory": {}, "skills": {}}
        self._run_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._web_job_lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task | None = None
        self._webui_server: OneSyncWebUIServer | None = None
        self._web_jobs: dict[str, dict[str, Any]] = {}
        self._web_job_tasks: dict[str, asyncio.Task] = {}
        self._max_web_jobs = 40
        self._debug_logs: list[dict[str, Any]] = []
        self._debug_log_seq = 0
        self._max_debug_logs = 1200

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
    ) -> dict[str, Any]:
        snapshot = inventory_snapshot if isinstance(inventory_snapshot, dict) else self._build_inventory_snapshot()
        return build_skills_overview(snapshot, saved_manifest=saved_manifest)

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

    def _save_skills_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_saved_skills_manifest(manifest)
        skills_state = self._skills_state()
        skills_state["saved_manifest"] = normalized
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_file(self.skills_manifest_path, normalized)
        return normalized

    def _sync_skill_bindings_projection(self, manifest: dict[str, Any]) -> bool:
        projected_bindings = normalize_skill_bindings_payload(manifest_to_binding_rows(manifest))
        current_bindings = normalize_skill_bindings_payload(self.config.get("skill_bindings", []))
        if current_bindings == projected_bindings:
            return False
        self.config["skill_bindings"] = projected_bindings
        self._persist_plugin_config()
        return True

    def _write_json_file(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_skills_state_files(self, skills_snapshot: dict[str, Any]) -> None:
        manifest = skills_snapshot.get("manifest", {})
        lock = skills_snapshot.get("lock", {})
        self.skills_state_dir.mkdir(parents=True, exist_ok=True)
        self.skills_sources_dir.mkdir(parents=True, exist_ok=True)
        self.skills_generated_dir.mkdir(parents=True, exist_ok=True)

        self._write_json_file(self.skills_manifest_path, manifest)
        self._write_json_file(self.skills_lock_path, lock)

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

    def _refresh_skills_snapshot(
        self,
        inventory_snapshot: dict[str, Any] | None = None,
        *,
        saved_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            skills_snapshot = self._build_skills_snapshot(inventory_snapshot, saved_manifest=saved_manifest)
        except Exception as exc:
            logger.error("[onesync] skills snapshot build failed: %s", exc)
            skills_snapshot = {
                "ok": False,
                "generated_at": _now_iso(),
                "manifest": {},
                "lock": {},
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
            )
            manifest = skills_snapshot.get("manifest", {})
            if isinstance(manifest, dict) and manifest:
                self._save_skills_manifest(manifest)
                bindings_changed = self._sync_skill_bindings_projection(manifest)
                if bindings_changed:
                    snapshot = self._build_inventory_snapshot(
                        skill_bindings_override=manifest_to_binding_rows(manifest),
                    )
                    inventory_state["last_snapshot"] = snapshot
                    inventory_state["last_scanned_at"] = snapshot.get("generated_at", _now_iso())
                    self._refresh_skills_snapshot(
                        inventory_snapshot=snapshot,
                        saved_manifest=manifest,
                    )
        return snapshot

    def webui_get_inventory_payload(self) -> dict[str, Any]:
        return self._refresh_inventory_snapshot()

    def webui_get_skills_payload(self) -> dict[str, Any]:
        self._refresh_inventory_snapshot(sync_skills=True)
        skills_state = self._skills_state()
        return skills_state.get("last_overview", {})

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

    def webui_sync_skill_source(self, source_id: str) -> dict[str, Any]:
        snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        _ = snapshot
        return self.webui_get_skill_source_payload(source_id)

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
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        updated_skills_snapshot = self._skills_state().get("last_overview", {})
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

        manifest = self._update_saved_manifest_target_selection(
            target_id=normalized_target_id,
            selected_source_ids=selected_source_ids,
        )
        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        updated_skills_snapshot = self._skills_state().get("last_overview", {})
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
                f"target={normalized_target_id} actions={','.join(changes or requested_actions or ['noop'])}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "changes": changes,
            "requested_actions": requested_actions,
            "manifest": manifest,
            "inventory": inventory_snapshot,
            "skills": updated_skills_snapshot,
            "deploy_target": refreshed_target or deploy_target,
        }

    def webui_deploy_skill_source(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_source_id = _normalize_inventory_id(source_id, default="")
        if not normalized_source_id:
            return {"ok": False, "message": "source_id is required"}
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
            if normalized_source_id not in compatible_ids:
                return {
                    "ok": False,
                    "message": f"source {normalized_source_id} is incompatible with software {software_id}",
                }
        manifest = self._load_saved_skills_manifest()
        for software_id in requested_software_ids:
            target_id = f"{software_id}:{scope}"
            current_target = next(
                (
                    item for item in manifest.get("deploy_targets", [])
                    if isinstance(item, dict) and str(item.get("target_id", "")) == target_id
                ),
                None,
            )
            next_source_ids = _dedupe_keep_order(
                _to_str_list(current_target.get("selected_source_ids", [])) + [normalized_source_id],
            ) if isinstance(current_target, dict) else [normalized_source_id]
            manifest = self._update_saved_manifest_target_selection(
                target_id=target_id,
                selected_source_ids=next_source_ids,
            )

        inventory_snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
        self._push_debug_log(
            "info",
            (
                "skill source deployed: "
                f"source={normalized_source_id} scope={scope} targets={','.join(requested_software_ids)}"
            ),
            source="webui",
        )
        return {
            "ok": True,
            "manifest": manifest,
            "inventory": inventory_snapshot,
            "skills": skills_snapshot,
            "source": self.webui_get_skill_source_payload(normalized_source_id).get("source"),
        }

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

        if incoming_bindings is not None:
            try:
                next_bindings = normalize_skill_bindings_payload(incoming_bindings)
            except Exception as exc:
                return {"ok": False, "message": f"invalid bindings payload: {exc}"}
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

            snapshot = self._build_inventory_snapshot()
            compatibility = snapshot.get("compatibility", {})
            software_rows = snapshot.get("software_rows", [])
            software_exists = any(
                str(item.get("id", "")) == software_id
                for item in software_rows
                if isinstance(item, dict)
            )
            if not software_exists:
                return {"ok": False, "message": f"software_id not found: {software_id}"}

            compatible_ids = set(compatibility.get(software_id, []))
            incompatible = [sid for sid in requested_skill_ids if sid not in compatible_ids]
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
        manifest = self._load_saved_skills_manifest()
        target_key = f"{software_id}:{scope}" if incoming_bindings is None else ""
        if incoming_bindings is None and target_key:
            manifest = self._update_saved_manifest_target_selection(
                target_id=target_key,
                selected_source_ids=requested_skill_ids,
            )
        elif incoming_bindings is not None:
            for item in next_bindings:
                if not isinstance(item, dict):
                    continue
                target_key = f"{item.get('software_id', '')}:{item.get('scope', 'global')}"
                selected_for_target = [
                    str(row.get("skill_id", "")).strip()
                    for row in next_bindings
                    if isinstance(row, dict)
                    and str(row.get("software_id", "")).strip() == str(item.get("software_id", "")).strip()
                    and str(row.get("scope", "global")).strip() == str(item.get("scope", "global")).strip()
                ]
                manifest = self._update_saved_manifest_target_selection(
                    target_id=target_key,
                    selected_source_ids=selected_for_target,
                )
        self._persist_plugin_config()
        snapshot = self._refresh_inventory_snapshot(sync_skills=True)
        skills_snapshot = self._skills_state().get("last_overview", {})
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
                "password": str(web_cfg.get("password", "") or ""),
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

            web_cfg_raw = incoming.get("web_admin", self.config.get("web_admin", {}))
            if web_cfg_raw is None:
                web_cfg_raw = {}
            if not isinstance(web_cfg_raw, dict):
                return {"ok": False, "message": "web_admin must be an object"}
            web_host = str(web_cfg_raw.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
            web_port = _to_int(web_cfg_raw.get("port", 8099), 8099, 1)
            if web_port > 65535:
                web_port = 65535
            self.config["web_admin"] = {
                "enabled": _to_bool(web_cfg_raw.get("enabled", False), False),
                "host": web_host,
                "port": web_port,
                "password": str(web_cfg_raw.get("password", "") or ""),
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
