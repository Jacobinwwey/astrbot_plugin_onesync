from __future__ import annotations

import asyncio
import json
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

DEFAULT_TARGETS: dict[str, dict[str, Any]] = {
    "zeroclaw": {
        "enabled": True,
        "strategy": "cargo_path_git",
        "check_interval_hours": 12,
        "repo_path": "/home/jacob/zeroclaw",
        "binary_path": "/root/.cargo/bin/zeroclaw",
        "branch": "",
        "upstream_repo": "https://github.com/zeroclaw-labs/zeroclaw.git",
        "mirror_prefixes": ["", "https://gh-proxy.com/", "https://ghfast.top/"],
        "remote_candidates": [],
        "build_commands": ["cargo install --path {repo_path}"],
        "verify_cmd": "{binary_path} --version",
        "check_timeout_s": 120,
        "update_timeout_s": 1800,
        "verify_timeout_s": 120,
        "current_version_pattern": "(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.\\-]+)?)",
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


class OneSyncPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.runner = CommandRunner()

        self.plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.state_path = self.plugin_data_dir / "state.json"
        self.events_path = self.plugin_data_dir / "events.jsonl"

        self.state: dict[str, Any] = {"targets": {}}
        self._run_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

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

    def _load_targets(self) -> dict[str, dict[str, Any]]:
        raw = self.config.get("targets_json", "")
        if isinstance(raw, dict):
            parsed = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                logger.error(
                    "[onesync] invalid targets_json, fallback to default: %s",
                    exc,
                )
                parsed = {}
        else:
            parsed = {}

        if not isinstance(parsed, dict) or not parsed:
            parsed = DEFAULT_TARGETS

        normalized: dict[str, dict[str, Any]] = {}
        for name, cfg in parsed.items():
            if not isinstance(cfg, dict):
                continue
            target_name = str(name).strip()
            if not target_name:
                continue
            normalized[target_name] = dict(cfg)
        return normalized

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self.state = {"targets": {}}
            return
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                parsed = {}
            targets = parsed.get("targets", {})
            if not isinstance(targets, dict):
                targets = {}
            self.state = {"targets": targets}
        except Exception as exc:
            logger.error("[onesync] failed to load state, reset: %s", exc)
            self.state = {"targets": {}}

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

    async def _record_event(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            logger.error("[onesync] append events log failed: %s", exc)

    def _render_status(self) -> str:
        targets = self._load_targets()
        lines = [
            "Software Updater Status",
            f"enabled={_to_bool(self.config.get('enabled', True), True)}",
            f"poll_interval_minutes={_to_int(self.config.get('poll_interval_minutes', 30), 30, 1)}",
            f"auto_update_on_schedule={_to_bool(self.config.get('auto_update_on_schedule', True), True)}",
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
                    f"latest={st.get('latest_version', '-')}"
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
        yield event.plain_result(self._render_status())

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
