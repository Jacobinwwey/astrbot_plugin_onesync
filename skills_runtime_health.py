from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from .inventory_core import normalize_skill_bindings_payload
    from .skills_core import manifest_to_binding_rows
except ImportError:  # pragma: no cover
    from inventory_core import normalize_skill_bindings_payload
    from skills_core import manifest_to_binding_rows


def _normalize_file_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return text.strip("_")


def _list_json_stems(directory: Path) -> set[str]:
    if not directory.exists() or not directory.is_dir():
        return set()
    stems: set[str] = set()
    for item in directory.glob("*.json"):
        stem = str(item.stem or "").strip().lower()
        if stem:
            stems.add(stem)
    return stems


def _binding_signature_rows(value: Any) -> set[str]:
    rows = normalize_skill_bindings_payload(value if isinstance(value, list) else [])
    signatures: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        software_id = str(item.get("software_id", "")).strip()
        skill_id = str(item.get("skill_id", "")).strip()
        scope = str(item.get("scope", "")).strip()
        enabled = "1" if bool(item.get("enabled", True)) else "0"
        if not software_id or not skill_id or not scope:
            continue
        signatures.add(f"{software_id}|{skill_id}|{scope}|{enabled}")
    return signatures


def _summarize_ids(values: list[str], *, limit: int = 5) -> str:
    clean = [str(item or "").strip() for item in values if str(item or "").strip()]
    if not clean:
        return ""
    if len(clean) <= limit:
        return ", ".join(clean)
    return ", ".join(clean[:limit]) + f" (+{len(clean) - limit} more)"


def build_skills_runtime_health(
    skills_snapshot: dict[str, Any],
    *,
    current_bindings: list[dict[str, Any]] | None,
    manifest_path: Path,
    lock_path: Path,
    sources_dir: Path,
    generated_dir: Path,
) -> dict[str, Any]:
    snapshot = skills_snapshot if isinstance(skills_snapshot, dict) else {}
    expected_source_files = {
        _normalize_file_id(item.get("source_id", ""))
        for item in snapshot.get("source_rows", [])
        if isinstance(item, dict) and _normalize_file_id(item.get("source_id", ""))
    }
    expected_generated_files = {
        _normalize_file_id(item.get("target_id", ""))
        for item in snapshot.get("deploy_rows", [])
        if isinstance(item, dict) and _normalize_file_id(item.get("target_id", ""))
    }
    actual_source_files = _list_json_stems(sources_dir)
    actual_generated_files = _list_json_stems(generated_dir)

    missing_source_files = sorted(expected_source_files - actual_source_files)
    extra_source_files = sorted(actual_source_files - expected_source_files)
    missing_generated_files = sorted(expected_generated_files - actual_generated_files)
    extra_generated_files = sorted(actual_generated_files - expected_generated_files)

    expected_binding_signatures = _binding_signature_rows(
        manifest_to_binding_rows(snapshot.get("manifest", {})),
    )
    current_binding_signatures = _binding_signature_rows(current_bindings or [])
    missing_projection_bindings = sorted(expected_binding_signatures - current_binding_signatures)
    extra_projection_bindings = sorted(current_binding_signatures - expected_binding_signatures)

    manifest_present = manifest_path.exists() and manifest_path.is_file()
    lock_present = lock_path.exists() and lock_path.is_file()
    state_ok = (
        manifest_present
        and lock_present
        and not missing_source_files
        and not extra_source_files
        and not missing_generated_files
        and not extra_generated_files
    )
    projection_ok = not missing_projection_bindings and not extra_projection_bindings

    warnings: list[str] = []
    if not manifest_present:
        warnings.append("skills state file missing: manifest.json")
    if not lock_present:
        warnings.append("skills state file missing: lock.json")
    if missing_source_files:
        warnings.append(
            "skills source state files missing: "
            + _summarize_ids(missing_source_files),
        )
    if extra_source_files:
        warnings.append(
            "skills source state files unexpected: "
            + _summarize_ids(extra_source_files),
        )
    if missing_generated_files:
        warnings.append(
            "skills deploy state files missing: "
            + _summarize_ids(missing_generated_files),
        )
    if extra_generated_files:
        warnings.append(
            "skills deploy state files unexpected: "
            + _summarize_ids(extra_generated_files),
        )
    if missing_projection_bindings:
        warnings.append(
            "skills binding projection missing rows: "
            + _summarize_ids(missing_projection_bindings),
        )
    if extra_projection_bindings:
        warnings.append(
            "skills binding projection has unexpected rows: "
            + _summarize_ids(extra_projection_bindings),
        )

    return {
        "state_health": {
            "ok": state_ok,
            "manifest_present": manifest_present,
            "lock_present": lock_present,
            "source_files_expected_total": len(expected_source_files),
            "source_files_actual_total": len(actual_source_files),
            "source_files_missing_total": len(missing_source_files),
            "source_files_extra_total": len(extra_source_files),
            "generated_files_expected_total": len(expected_generated_files),
            "generated_files_actual_total": len(actual_generated_files),
            "generated_files_missing_total": len(missing_generated_files),
            "generated_files_extra_total": len(extra_generated_files),
            "source_files_missing_ids": missing_source_files,
            "source_files_extra_ids": extra_source_files,
            "generated_files_missing_ids": missing_generated_files,
            "generated_files_extra_ids": extra_generated_files,
        },
        "projection_health": {
            "ok": projection_ok,
            "binding_rows_expected_total": len(expected_binding_signatures),
            "binding_rows_current_total": len(current_binding_signatures),
            "binding_rows_missing_total": len(missing_projection_bindings),
            "binding_rows_extra_total": len(extra_projection_bindings),
            "binding_rows_missing_ids": missing_projection_bindings,
            "binding_rows_extra_ids": extra_projection_bindings,
        },
        "counts": {
            "state_manifest_present": 1 if manifest_present else 0,
            "state_lock_present": 1 if lock_present else 0,
            "state_source_files_missing_total": len(missing_source_files),
            "state_source_files_extra_total": len(extra_source_files),
            "state_generated_files_missing_total": len(missing_generated_files),
            "state_generated_files_extra_total": len(extra_generated_files),
            "projection_binding_missing_total": len(missing_projection_bindings),
            "projection_binding_extra_total": len(extra_projection_bindings),
        },
        "warnings": warnings,
    }
