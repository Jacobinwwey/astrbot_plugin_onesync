from __future__ import annotations

import asyncio
import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .updater_core import (
    CheckResult,
    CommandRunner,
    UpdateResult,
    build_strategy,
)

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

        self.state: dict[str, Any] = {"targets": {}, "env": {}}
        self._run_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
        self._bootstrap_human_targets_if_needed()
        self._refresh_software_overview()

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

    async def terminate(self) -> None:
        self._stop_event.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("[onesync] scheduled loop exit error: %s", exc)
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
        strategy = str(raw_cfg.get("strategy", template_key or "command")).strip().lower()
        if strategy not in {"command", "cmd", "cargo_path_git", "git_cargo"}:
            strategy = "command"

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

        if strategy in {"cargo_path_git", "git_cargo"}:
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
        strategy = str(target_cfg.get("strategy", "command")).strip().lower()
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

        if strategy in {"cargo_path_git", "git_cargo"}:
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

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self.state = {"targets": {}, "env": {}}
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
            self.state = {"targets": targets, "env": env_state}
        except Exception as exc:
            logger.error("[onesync] failed to load state, reset: %s", exc)
            self.state = {"targets": {}, "env": {}}

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
        strategy = str(target_cfg.get("strategy", "command")).strip().lower()

        for raw in _to_str_list(target_cfg.get("required_commands", [])):
            executable = _extract_primary_executable(raw) or str(raw).strip()
            if executable:
                commands.append(executable)
        if strategy in {"cargo_path_git", "git_cargo"}:
            commands.extend(["git", "cargo"])
            binary_path = str(target_cfg.get("binary_path", "")).strip()
            if binary_path:
                commands.append(binary_path)

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
        strategy = str(target_cfg.get("strategy", "command")).strip().lower()
        report: dict[str, Any] = {
            "target": target_name,
            "strategy": strategy,
            "enabled": _to_bool(target_cfg.get("enabled", True), True),
            "ok": True,
            "paths": [],
            "commands": [],
        }

        if strategy in {"cargo_path_git", "git_cargo"}:
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
        lines = [
            "Software Updater Status",
            f"enabled={_to_bool(self.config.get('enabled', True), True)}",
            f"poll_interval_minutes={_to_int(self.config.get('poll_interval_minutes', 30), 30, 1)}",
            f"auto_update_on_schedule={_to_bool(self.config.get('auto_update_on_schedule', True), True)}",
            f"target_config_mode={str(self.config.get('target_config_mode', 'human')).strip().lower() or 'human'}",
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
            await self._record_event(result_record)
            return result_record

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
            await self._record_event(result_record)
            return result_record

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
            await self._record_event(result_record)
            return result_record

        if not force and not check_result.needs_update:
            result_record["ok"] = True
            result_record["message"] = "already up to date"
            state["last_status"] = "ok"
            state["last_message"] = result_record["message"]
            state["consecutive_failures"] = 0
            await self._record_event(result_record)
            return result_record

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

        await self._record_event(result_record)
        return result_record

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
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[onesync] scheduled loop error: %s", exc)

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
