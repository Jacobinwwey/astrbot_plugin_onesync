from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def read_generated_target_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_generated_target_diff(
    current_target: dict[str, Any] | None,
    persisted_target: dict[str, Any] | None,
) -> dict[str, Any]:
    current = current_target if isinstance(current_target, dict) else {}
    persisted = persisted_target if isinstance(persisted_target, dict) else None

    if persisted is None:
        return {
            "ok": False,
            "missing_file": True,
            "field_diff_total": 1,
            "changed_fields": ["generated_projection"],
            "fields": {
                "generated_projection": {
                    "current": "present" if current else "missing",
                    "persisted": "missing",
                },
            },
        }

    compare_fields = (
        "software_id",
        "scope",
        "target_path",
        "selected_source_ids",
        "missing_source_ids",
        "incompatible_source_ids",
        "repair_actions",
        "status",
        "drift_status",
    )
    changed_fields: list[str] = []
    field_details: dict[str, dict[str, Any]] = {}

    for field in compare_fields:
        current_value: Any
        persisted_value: Any
        if field.endswith("_ids") or field == "repair_actions":
            current_value = _normalize_str_list(current.get(field, []))
            persisted_value = _normalize_str_list(persisted.get(field, []))
        else:
            current_value = str(current.get(field, "") or "").strip()
            persisted_value = str(persisted.get(field, "") or "").strip()
        if current_value == persisted_value:
            continue
        changed_fields.append(field)
        field_details[field] = {
            "current": current_value,
            "persisted": persisted_value,
        }

    return {
        "ok": not changed_fields,
        "missing_file": False,
        "field_diff_total": len(changed_fields),
        "changed_fields": changed_fields,
        "fields": field_details,
    }
