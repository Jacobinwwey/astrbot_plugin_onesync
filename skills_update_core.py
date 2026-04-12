from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any


_REGISTRY_HINT_PREFIXES = (
    "bunx ",
    "npx ",
    "pnpm dlx ",
    "npm ",
)

_REGISTRY_RUNNERS = ("bunx", "npx", "pnpm", "npm")
_COMPOUND_PLUGIN_PACKAGE = "@every-env/compound-plugin"
_COMPOUND_PLUGIN_NAME = "compound-engineering"


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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _shell_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", text):
        return text
    return shlex.quote(text)


def _normalize_manager(value: Any) -> str:
    manager = str(value or "").strip().lower()
    if manager in {"github"}:
        return "git"
    if manager in {"pnpm dlx"}:
        return "pnpm"
    return manager


def _normalize_source_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _manager_from_hint(management_hint: str) -> str:
    hint = str(management_hint or "").strip().lower()
    if hint.startswith("pnpm dlx "):
        return "pnpm"
    if hint.startswith("bunx "):
        return "bunx"
    if hint.startswith("npx "):
        return "npx"
    if hint.startswith("npm "):
        return "npm"
    return ""


def _resolve_registry_hint_command(management_hint: str, update_policy: str) -> str:
    hint = str(management_hint or "").strip()
    if str(update_policy or "").strip().lower() != "registry":
        return ""
    lowered = hint.lower()
    if any(lowered.startswith(prefix) for prefix in _REGISTRY_HINT_PREFIXES):
        return hint
    return ""


def _derive_codex_home_from_source_paths(source_paths: list[str] | None) -> str:
    for raw_path in source_paths or []:
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        parts = [part.strip() for part in path.parts if str(part).strip()]
        try:
            skills_index = parts.index("skills")
        except ValueError:
            continue
        if skills_index <= 0:
            continue
        codex_home = Path(*parts[:skills_index])
        codex_home_text = str(codex_home).strip()
        if codex_home_text:
            return codex_home_text
    return ""


def _build_compound_plugin_registry_command(manager: str, install_ref: str, source_paths: list[str] | None) -> str:
    install_ref_text = str(install_ref or "").strip()
    if install_ref_text != _COMPOUND_PLUGIN_PACKAGE:
        return ""
    codex_home = _derive_codex_home_from_source_paths(source_paths)
    if not codex_home:
        return ""
    codex_home_token = _shell_token(codex_home)
    if manager == "bunx":
        return (
            f"bunx {_shell_token(_COMPOUND_PLUGIN_PACKAGE)} install {_COMPOUND_PLUGIN_NAME} "
            f"--to codex --codexHome {codex_home_token}"
        )
    if manager == "npx":
        return (
            f"npx {_shell_token(_COMPOUND_PLUGIN_PACKAGE)} install {_COMPOUND_PLUGIN_NAME} "
            f"--to codex --codexHome {codex_home_token}"
        )
    if manager == "pnpm":
        return (
            f"pnpm dlx {_shell_token(_COMPOUND_PLUGIN_PACKAGE)} install {_COMPOUND_PLUGIN_NAME} "
            f"--to codex --codexHome {codex_home_token}"
        )
    if manager == "npm":
        return (
            f"npm exec --yes {_shell_token(_COMPOUND_PLUGIN_PACKAGE)} install {_COMPOUND_PLUGIN_NAME} "
            f"-- --to codex --codexHome {codex_home_token}"
        )
    return ""


def _build_registry_command(manager: str, install_ref: str, *, source_paths: list[str] | None = None) -> str:
    specialized = _build_compound_plugin_registry_command(manager, install_ref, source_paths)
    if specialized:
        return specialized
    token = _shell_token(install_ref)
    if not token:
        return ""
    if manager == "bunx":
        return f"bunx {token}"
    if manager == "npx":
        return f"npx {token}"
    if manager == "pnpm":
        return f"pnpm dlx {token}"
    if manager == "npm":
        return f"npm install -g {_shell_token(f'{install_ref}@latest')}"
    return ""


def _build_registry_precheck_commands(manager: str) -> list[str]:
    normalized = _normalize_manager(manager)
    candidates = [normalized, *_REGISTRY_RUNNERS]
    ordered = _dedupe_keep_order([item for item in candidates if item in _REGISTRY_RUNNERS])
    if not ordered:
        ordered = list(_REGISTRY_RUNNERS)
    checks = [f"command -v {item} >/dev/null 2>&1" for item in ordered]
    if not checks:
        return []
    return [" || ".join(checks)]


def _build_git_precheck_commands(source_path: str) -> list[str]:
    token = _shell_token(source_path)
    if not token:
        return []
    return [
        f"git -C {token} rev-parse --is-inside-work-tree",
        f'test -z "$(git -C {token} status --porcelain)"',
    ]


def summarize_revision_capture_delta(
    before_rows: list[dict[str, Any]] | None,
    after_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    before_list = [item for item in (before_rows or []) if isinstance(item, dict)]
    after_list = [item for item in (after_rows or []) if isinstance(item, dict)]

    before_index: dict[str, dict[str, Any]] = {}
    for item in before_list:
        source_id = _normalize_source_id(item.get("source_id"))
        if source_id:
            before_index[source_id] = item

    after_index: dict[str, dict[str, Any]] = {}
    for item in after_list:
        source_id = _normalize_source_id(item.get("source_id"))
        if source_id:
            after_index[source_id] = item

    source_ids = _dedupe_keep_order(list(before_index.keys()) + list(after_index.keys()))
    changed_source_ids: list[str] = []
    unchanged_source_ids: list[str] = []
    unknown_source_ids: list[str] = []

    for source_id in source_ids:
        before_row = before_index.get(source_id, {})
        after_row = after_index.get(source_id, {})
        before_revision = str(before_row.get("sync_resolved_revision") or "").strip()
        after_revision = str(after_row.get("sync_resolved_revision") or "").strip()
        if before_revision and after_revision:
            if before_revision == after_revision:
                unchanged_source_ids.append(source_id)
            else:
                changed_source_ids.append(source_id)
            continue
        unknown_source_ids.append(source_id)

    return {
        "source_ids": source_ids,
        "source_total": len(source_ids),
        "changed_source_ids": changed_source_ids,
        "changed_total": len(changed_source_ids),
        "unchanged_source_ids": unchanged_source_ids,
        "unchanged_total": len(unchanged_source_ids),
        "unknown_source_ids": unknown_source_ids,
        "unknown_total": len(unknown_source_ids),
        "changed": bool(changed_source_ids),
    }


def build_git_rollback_preview(
    source_rows: list[dict[str, Any]] | None,
    before_rows: list[dict[str, Any]] | None,
    changed_source_ids: list[str] | None,
) -> dict[str, Any]:
    sources = [item for item in (source_rows or []) if isinstance(item, dict)]
    before = [item for item in (before_rows or []) if isinstance(item, dict)]
    normalized_changed_ids = _dedupe_keep_order(
        [
            _normalize_source_id(item)
            for item in (changed_source_ids or [])
            if _normalize_source_id(item)
        ],
    )
    source_index: dict[str, dict[str, Any]] = {}
    for item in sources:
        source_id = _normalize_source_id(item.get("source_id"))
        if source_id:
            source_index[source_id] = item

    before_index: dict[str, dict[str, Any]] = {}
    for item in before:
        source_id = _normalize_source_id(item.get("source_id"))
        if source_id:
            before_index[source_id] = item

    candidates: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    for source_id in normalized_changed_ids:
        source_row = source_index.get(source_id, {})
        before_row = before_index.get(source_id, {})
        source_path = str(source_row.get("source_path") or "").strip()
        before_revision = str(before_row.get("sync_resolved_revision") or "").strip()
        if not source_path or not before_revision:
            skipped_sources.append(
                {
                    "source_id": source_id,
                    "reason": "missing_source_path_or_before_revision",
                },
            )
            continue
        path_token = _shell_token(source_path)
        revision_token = _shell_token(before_revision)
        candidates.append(
            {
                "source_id": source_id,
                "source_path": source_path,
                "before_revision": before_revision,
                "precheck_commands": _build_git_precheck_commands(source_path),
                "command": f"git -C {path_token} reset --hard {revision_token}",
                "warning": "destructive_reset_hard",
            },
        )

    return {
        "supported": bool(candidates),
        "candidate_total": len(candidates),
        "candidates": candidates,
        "skipped_sources": skipped_sources,
        "warning": "preview_only_not_executed",
    }


def build_install_unit_update_plan(
    install_unit: dict[str, Any] | None,
    source_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unit = install_unit if isinstance(install_unit, dict) else {}
    rows = [item for item in (source_rows or []) if isinstance(item, dict)]
    install_unit_id = str(unit.get("install_unit_id") or "").strip()
    display_name = str(unit.get("display_name") or install_unit_id or "install unit").strip()
    management_hint = _first_non_empty(
        unit.get("management_hint"),
        *[item.get("management_hint") for item in rows],
    )
    hint_manager = _manager_from_hint(management_hint)
    install_ref = _first_non_empty(
        unit.get("install_ref"),
        *[item.get("install_ref") for item in rows],
        *[item.get("registry_package_name") for item in rows],
        unit.get("locator"),
    )
    manager = _normalize_manager(
        _first_non_empty(
            unit.get("install_manager"),
            unit.get("managed_by"),
            *[item.get("install_manager") for item in rows],
            *[item.get("managed_by") for item in rows],
            *[item.get("registry_package_manager") for item in rows],
        ),
    )
    if hint_manager:
        manager = hint_manager
    update_policy = _first_non_empty(
        unit.get("update_policy"),
        *[item.get("update_policy") for item in rows],
    )
    if not update_policy:
        update_policy = "registry" if install_ref and manager in {"bunx", "npx", "pnpm", "npm"} else "manual"

    source_paths = _dedupe_keep_order(
        [
            str(item.get("git_checkout_path") or item.get("source_path") or "").strip()
            for item in rows
            if str(item.get("git_checkout_path") or item.get("source_path") or "").strip()
        ],
    )
    source_ids = _dedupe_keep_order(
        [
            _normalize_source_id(item.get("source_id"))
            for item in rows
            if _normalize_source_id(item.get("source_id"))
        ],
    )

    specialized_command = _build_registry_command(manager, install_ref, source_paths=source_paths)
    hint_command = _resolve_registry_hint_command(management_hint, update_policy)
    commands: list[str] = []
    precheck_commands: list[str] = []
    supported = False
    message = ""
    reason_code = ""

    if specialized_command:
        supported = True
        precheck_commands = _build_registry_precheck_commands(manager)
        commands = [specialized_command]
        message = f"registry update will use specialized command for {display_name}"
    elif hint_command:
        supported = True
        precheck_commands = _build_registry_precheck_commands(manager)
        commands = [hint_command]
        message = f"registry update will use management_hint for {display_name}"
    else:
        registry_command = _build_registry_command(manager, install_ref, source_paths=source_paths)
        if registry_command and update_policy == "registry":
            supported = True
            precheck_commands = _build_registry_precheck_commands(manager)
            commands = [registry_command]
            message = f"registry update is available for {display_name}"
        elif manager == "git" and source_paths:
            supported = True
            precheck_commands = _build_git_precheck_commands(source_paths[0])
            commands = [f"git -C {_shell_token(source_paths[0])} pull --ff-only"]
            message = f"git update is available for {display_name}"
        elif manager in {"filesystem", "manual", ""} or update_policy == "manual":
            message = f"update unsupported for manually managed aggregate: {display_name}"
            reason_code = "manual_managed"
        else:
            message = f"update unsupported for manager '{manager or 'unknown'}': {display_name}"
            reason_code = "unsupported_manager"

    return {
        "install_unit_id": install_unit_id,
        "display_name": display_name,
        "manager": manager,
        "policy": str(update_policy or "").strip().lower(),
        "install_ref": install_ref,
        "management_hint": management_hint,
        "source_ids": source_ids,
        "source_paths": source_paths,
        "precheck_commands": precheck_commands,
        "precheck_command_count": len(precheck_commands),
        "commands": commands,
        "command_count": len(commands),
        "supported": supported,
        "message": message,
        "reason_code": reason_code,
    }


def build_collection_group_update_plan(
    collection_group: dict[str, Any] | None,
    install_unit_rows: list[dict[str, Any]] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    group = collection_group if isinstance(collection_group, dict) else {}
    unit_rows = [item for item in (install_unit_rows or []) if isinstance(item, dict)]
    rows = [item for item in (source_rows or []) if isinstance(item, dict)]
    collection_group_id = str(group.get("collection_group_id") or "").strip()
    display_name = str(group.get("display_name") or collection_group_id or "collection group").strip()

    if not unit_rows and rows:
        grouped_units: dict[str, dict[str, Any]] = {}
        for item in rows:
            install_unit_id = str(item.get("install_unit_id") or "").strip()
            if not install_unit_id or install_unit_id in grouped_units:
                continue
            grouped_units[install_unit_id] = {
                "install_unit_id": install_unit_id,
                "display_name": str(item.get("install_unit_display_name") or item.get("display_name") or install_unit_id),
                "install_ref": str(item.get("install_ref") or ""),
                "install_manager": str(item.get("install_manager") or ""),
                "management_hint": str(item.get("management_hint") or ""),
                "managed_by": str(item.get("managed_by") or ""),
                "update_policy": str(item.get("update_policy") or ""),
            }
        unit_rows = list(grouped_units.values())

    plans: list[dict[str, Any]] = []
    for unit in unit_rows:
        install_unit_id = str(unit.get("install_unit_id") or "").strip()
        unit_source_rows = [
            item
            for item in rows
            if str(item.get("install_unit_id") or "").strip() == install_unit_id
        ]
        plans.append(build_install_unit_update_plan(unit, unit_source_rows))

    supported_plans = [item for item in plans if item.get("supported")]
    unsupported_plans = [item for item in plans if not item.get("supported")]
    precheck_commands = [
        command
        for item in supported_plans
        for command in _to_str_list(item.get("precheck_commands", []))
    ]
    commands = [
        command
        for item in supported_plans
        for command in _to_str_list(item.get("commands", []))
    ]
    managers = _dedupe_keep_order([str(item.get("manager") or "").strip() for item in supported_plans])
    policies = _dedupe_keep_order([str(item.get("policy") or "").strip() for item in supported_plans])
    blocked_reason_codes = _dedupe_keep_order(
        [
            str(item.get("reason_code") or "").strip().lower()
            for item in unsupported_plans
            if str(item.get("reason_code") or "").strip()
        ],
    )
    if supported_plans:
        message = f"collection group update prepared for {len(supported_plans)} install units"
        reason_code = ""
    else:
        message = f"update unsupported for collection group: {display_name}"
        if len(blocked_reason_codes) == 1:
            reason_code = blocked_reason_codes[0]
        elif blocked_reason_codes:
            reason_code = "mixed_blocked_reasons"
        else:
            reason_code = "manual_only"

    return {
        "collection_group_id": collection_group_id,
        "display_name": display_name,
        "supported": bool(supported_plans),
        "manager": managers[0] if len(managers) == 1 else ("mixed" if managers else ""),
        "policy": policies[0] if len(policies) == 1 else ("mixed" if policies else ""),
        "precheck_commands": precheck_commands,
        "precheck_command_count": len(precheck_commands),
        "commands": commands,
        "command_count": len(commands),
        "install_unit_plans": plans,
        "supported_install_unit_total": len(supported_plans),
        "unsupported_install_unit_total": len(unsupported_plans),
        "unsupported_install_units": [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "message": str(item.get("message") or "").strip(),
                "reason_code": str(item.get("reason_code") or "").strip().lower(),
            }
            for item in unsupported_plans
        ],
        "blocked_reasons": [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "reason": str(item.get("message") or "").strip(),
                "reason_code": str(item.get("reason_code") or "").strip().lower(),
            }
            for item in unsupported_plans
        ],
        "reason_code": reason_code,
        "message": message,
    }
