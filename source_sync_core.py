from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, parse, request


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repository_url(repository: Any) -> str:
    if isinstance(repository, str):
        return repository.strip()
    if isinstance(repository, dict):
        return str(repository.get("url") or "").strip()
    return ""


def fetch_npm_registry_package_summary(
    package_name: str,
    *,
    urlopen: Callable[..., Any] = request.urlopen,
    timeout_s: int = 8,
) -> dict[str, Any]:
    normalized_package_name = str(package_name or "").strip()
    if not normalized_package_name:
        return {
            "ok": False,
            "sync_kind": "npm_registry",
            "sync_message": "registry package name is required",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
        }

    url = f"https://registry.npmjs.org/{parse.quote(normalized_package_name, safe='')}"
    try:
        with urlopen(url, timeout=timeout_s) as response:
            raw = response.read()
    except error.HTTPError as exc:
        return {
            "ok": False,
            "sync_kind": "npm_registry",
            "sync_message": f"npm registry request failed for {normalized_package_name}: http {exc.code}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "sync_kind": "npm_registry",
            "sync_message": f"npm registry request failed for {normalized_package_name}: {exc}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
        }

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "sync_kind": "npm_registry",
            "sync_message": f"npm registry response parse failed for {normalized_package_name}: {exc}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
        }

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "sync_kind": "npm_registry",
            "sync_message": f"npm registry response is invalid for {normalized_package_name}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
        }

    dist_tags = payload.get("dist-tags", {})
    dist_tags = dist_tags if isinstance(dist_tags, dict) else {}
    versions = payload.get("versions", {})
    versions = versions if isinstance(versions, dict) else {}
    time_map = payload.get("time", {})
    time_map = time_map if isinstance(time_map, dict) else {}

    latest_version = str(dist_tags.get("latest") or "").strip()
    latest_meta = versions.get(latest_version, {}) if latest_version else {}
    latest_meta = latest_meta if isinstance(latest_meta, dict) else {}
    published_at = str(time_map.get(latest_version) or time_map.get("modified") or "").strip()
    homepage = str(latest_meta.get("homepage") or payload.get("homepage") or "").strip()
    if not homepage:
        homepage = _repository_url(latest_meta.get("repository") or payload.get("repository"))
    description = str(latest_meta.get("description") or payload.get("description") or "").strip()

    return {
        "ok": True,
        "sync_kind": "npm_registry",
        "sync_message": f"fetched npm registry metadata for {normalized_package_name}",
        "registry_latest_version": latest_version,
        "registry_published_at": published_at,
        "registry_homepage": homepage,
        "registry_description": description,
    }


def build_source_sync_record(
    source: dict[str, Any],
    *,
    checked_at: str | None = None,
    urlopen: Callable[..., Any] = request.urlopen,
    timeout_s: int = 8,
) -> dict[str, Any]:
    source_row = source if isinstance(source, dict) else {}
    ts = str(checked_at or _now_iso())
    package_name = str(source_row.get("registry_package_name") or "").strip()
    package_manager = str(source_row.get("registry_package_manager") or "").strip().lower()

    base = {
        "sync_status": "unsupported",
        "sync_checked_at": ts,
        "sync_kind": "",
        "sync_message": "source does not declare a supported registry package",
        "registry_latest_version": "",
        "registry_published_at": "",
        "registry_homepage": "",
        "registry_description": "",
    }

    if not package_name or package_manager != "npm":
        return base

    summary = fetch_npm_registry_package_summary(
        package_name,
        urlopen=urlopen,
        timeout_s=timeout_s,
    )
    return {
        **base,
        **summary,
        "sync_status": "ok" if summary.get("ok") else "error",
        "sync_checked_at": ts,
    }
