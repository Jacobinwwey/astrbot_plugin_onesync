from __future__ import annotations

import re
import shlex
from typing import Any


_REGISTRY_HINT_PREFIXES = (
    "bunx ",
    "npx ",
    "pnpm dlx ",
    "npm ",
)


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


def _build_registry_command(manager: str, install_ref: str) -> str:
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
    if not manager:
        manager = _manager_from_hint(management_hint)
    update_policy = _first_non_empty(
        unit.get("update_policy"),
        *[item.get("update_policy") for item in rows],
    )
    if not update_policy:
        update_policy = "registry" if install_ref and manager in {"bunx", "npx", "pnpm", "npm"} else "manual"

    source_paths = _dedupe_keep_order(
        [
            str(item.get("source_path") or "").strip()
            for item in rows
            if str(item.get("source_path") or "").strip()
        ],
    )

    hint_command = _resolve_registry_hint_command(management_hint, update_policy)
    commands: list[str] = []
    supported = False
    message = ""

    if hint_command:
        supported = True
        commands = [hint_command]
        message = f"registry update will use management_hint for {display_name}"
    else:
        registry_command = _build_registry_command(manager, install_ref)
        if registry_command and update_policy == "registry":
            supported = True
            commands = [registry_command]
            message = f"registry update is available for {display_name}"
        elif manager == "git" and source_paths:
            supported = True
            commands = [f"git -C {_shell_token(source_paths[0])} pull --ff-only"]
            message = f"git update is available for {display_name}"
        elif manager in {"filesystem", "manual", ""} or update_policy == "manual":
            message = f"update unsupported for manually managed aggregate: {display_name}"
        else:
            message = f"update unsupported for manager '{manager or 'unknown'}': {display_name}"

    return {
        "install_unit_id": install_unit_id,
        "display_name": display_name,
        "manager": manager,
        "policy": str(update_policy or "").strip().lower(),
        "install_ref": install_ref,
        "management_hint": management_hint,
        "source_paths": source_paths,
        "commands": commands,
        "command_count": len(commands),
        "supported": supported,
        "message": message,
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
    commands = [
        command
        for item in supported_plans
        for command in _to_str_list(item.get("commands", []))
    ]
    managers = _dedupe_keep_order([str(item.get("manager") or "").strip() for item in supported_plans])
    policies = _dedupe_keep_order([str(item.get("policy") or "").strip() for item in supported_plans])
    if supported_plans:
        message = f"collection group update prepared for {len(supported_plans)} install units"
    else:
        message = f"update unsupported for collection group: {display_name}"

    return {
        "collection_group_id": collection_group_id,
        "display_name": display_name,
        "supported": bool(supported_plans),
        "manager": managers[0] if len(managers) == 1 else ("mixed" if managers else ""),
        "policy": policies[0] if len(policies) == 1 else ("mixed" if policies else ""),
        "commands": commands,
        "command_count": len(commands),
        "install_unit_plans": plans,
        "supported_install_unit_total": len(supported_plans),
        "unsupported_install_unit_total": len(unsupported_plans),
        "unsupported_install_units": [
            {
                "install_unit_id": str(item.get("install_unit_id") or "").strip(),
                "message": str(item.get("message") or "").strip(),
            }
            for item in unsupported_plans
        ],
        "message": message,
    }
