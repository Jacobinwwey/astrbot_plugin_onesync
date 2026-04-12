from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request

_GIT_MANAGER_ALIASES = {
    "git",
    "github",
}
_GITHUB_PROVIDER_ALIASES = {
    "git",
    "github",
    "github_enterprise",
}
_GITLAB_PROVIDER_ALIASES = {
    "gitlab",
}
_BITBUCKET_PROVIDER_ALIASES = {
    "bitbucket",
    "bitbucket_cloud",
}
_REPO_LOCATOR_PREFIXES = (
    "repo:",
    "documented:",
    "catalog:",
    "community:",
    "source:",
)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_manager(value: Any) -> str:
    manager = _normalize_text(value).lower()
    if manager == "github":
        return "git"
    return manager


def _normalize_repo_provider(value: Any) -> str:
    normalized = _normalize_text(value).lower()
    if normalized in _GITHUB_PROVIDER_ALIASES:
        return "github"
    if normalized in _GITLAB_PROVIDER_ALIASES:
        return "gitlab"
    if normalized in _BITBUCKET_PROVIDER_ALIASES:
        return "bitbucket"
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repository_url(repository: Any) -> str:
    if isinstance(repository, str):
        return repository.strip()
    if isinstance(repository, dict):
        return str(repository.get("url") or "").strip()
    return ""


def _looks_like_git_locator(value: Any) -> bool:
    locator = _normalize_text(value).lower()
    if not locator:
        return False
    if locator.startswith("git@"):
        return True
    if locator.startswith("ssh://"):
        return True
    if locator.endswith(".git"):
        return True
    if "github.com/" in locator or "gitlab.com/" in locator or "bitbucket.org/" in locator:
        return True
    return False


def _strip_repo_locator_prefix(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    for prefix in _REPO_LOCATOR_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _has_repo_locator_prefix(value: Any) -> bool:
    locator = _normalize_text(value).lower()
    if not locator:
        return False
    return any(locator.startswith(prefix) for prefix in _REPO_LOCATOR_PREFIXES)


def _normalize_repo_locator_url(value: Any) -> str:
    locator = _strip_repo_locator_prefix(_normalize_text(value))
    if not locator:
        return ""
    if locator.startswith("git+"):
        locator = locator[4:].strip()
    if "#" in locator:
        locator = locator.split("#", 1)[0].strip()
    if (
        locator.startswith("github.com/")
        or locator.startswith("www.github.com/")
        or locator.startswith("gitlab.com/")
        or locator.startswith("www.gitlab.com/")
        or locator.startswith("bitbucket.org/")
        or locator.startswith("www.bitbucket.org/")
    ):
        locator = f"https://{locator}"
    if locator.startswith("http://") or locator.startswith("https://"):
        return locator
    return ""


def _extract_github_repo_ref(value: Any) -> tuple[str, str, str] | None:
    locator_url = _normalize_repo_locator_url(value)
    if not locator_url:
        return None
    parsed = parse.urlparse(locator_url)
    host = str(parsed.netloc or "").strip().lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0].strip()
    repo = parts[1].strip()
    if repo.endswith(".git"):
        repo = repo[:-4].strip()
    if not owner or not repo:
        return None
    return owner, repo, f"https://github.com/{owner}/{repo}"


def _extract_gitlab_repo_ref(value: Any) -> tuple[str, str] | None:
    locator_url = _normalize_repo_locator_url(value)
    if not locator_url:
        return None
    parsed = parse.urlparse(locator_url)
    host = str(parsed.netloc or "").strip().lower()
    if host not in {"gitlab.com", "www.gitlab.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if "/-/" in parsed.path:
        marker_index = parts.index("-") if "-" in parts else -1
        if marker_index >= 2:
            parts = parts[:marker_index]
    if len(parts) < 2:
        return None
    if parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4].strip()
    parts = [part.strip() for part in parts if str(part).strip()]
    if len(parts) < 2:
        return None
    namespace = "/".join(parts)
    return namespace, f"https://gitlab.com/{namespace}"


def _extract_bitbucket_repo_ref(value: Any) -> tuple[str, str, str] | None:
    locator_url = _normalize_repo_locator_url(value)
    if not locator_url:
        return None
    parsed = parse.urlparse(locator_url)
    host = str(parsed.netloc or "").strip().lower()
    if host not in {"bitbucket.org", "www.bitbucket.org"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    workspace = parts[0].strip()
    repo = parts[1].strip()
    if repo.endswith(".git"):
        repo = repo[:-4].strip()
    if not workspace or not repo:
        return None
    return workspace, repo, f"https://bitbucket.org/{workspace}/{repo}"


def _extract_repo_path_parts(value: Any) -> tuple[str, list[str]] | None:
    locator_url = _normalize_repo_locator_url(value)
    if not locator_url:
        return None
    parsed = parse.urlparse(locator_url)
    host = str(parsed.netloc or "").strip().lower()
    if not host:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if "/-/" in parsed.path:
        marker_index = parts.index("-") if "-" in parts else -1
        if marker_index >= 2:
            parts = parts[:marker_index]
    parts = [part.strip() for part in parts if str(part).strip()]
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4].strip()
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return None
    return host, parts


def _resolve_repo_metadata_target_from_locator(
    value: Any,
    *,
    provider_hint: str = "",
) -> dict[str, Any] | None:
    github_ref = _extract_github_repo_ref(value)
    if github_ref:
        owner, repo, homepage = github_ref
        return {
            "provider": "github",
            "owner": owner,
            "repo": repo,
            "homepage": homepage,
        }

    gitlab_ref = _extract_gitlab_repo_ref(value)
    if gitlab_ref:
        namespace, homepage = gitlab_ref
        return {
            "provider": "gitlab",
            "namespace": namespace,
            "homepage": homepage,
        }

    bitbucket_ref = _extract_bitbucket_repo_ref(value)
    if bitbucket_ref:
        workspace, repo, homepage = bitbucket_ref
        return {
            "provider": "bitbucket",
            "workspace": workspace,
            "repo": repo,
            "homepage": homepage,
        }

    normalized_hint = _normalize_repo_provider(provider_hint)
    path_parts = _extract_repo_path_parts(value)
    if normalized_hint and path_parts:
        host, parts = path_parts
        if normalized_hint == "github":
            owner = parts[0]
            repo = parts[1]
            return {
                "provider": "github",
                "owner": owner,
                "repo": repo,
                "homepage": f"https://{host}/{owner}/{repo}",
            }
        if normalized_hint == "gitlab":
            namespace = "/".join(parts)
            return {
                "provider": "gitlab",
                "namespace": namespace,
                "homepage": f"https://{host}/{namespace}",
            }
        if normalized_hint == "bitbucket":
            workspace = parts[0]
            repo = parts[1]
            return {
                "provider": "bitbucket",
                "workspace": workspace,
                "repo": repo,
                "homepage": f"https://{host}/{workspace}/{repo}",
            }
    return None


def _infer_provider_from_api_base(value: Any) -> str:
    api_base = _normalize_text(value).lower()
    if not api_base:
        return ""
    if "gitlab" in api_base:
        return "gitlab"
    if "bitbucket" in api_base:
        return "bitbucket"
    if "github" in api_base:
        return "github"
    if "/api/v4" in api_base:
        return "gitlab"
    if "/api/v3" in api_base:
        return "github"
    return ""


def _resolve_repo_provider_hint(source_row: dict[str, Any]) -> str:
    api_provider = _infer_provider_from_api_base(source_row.get("sync_api_base"))
    if api_provider:
        return api_provider
    for field_name in ("sync_provider", "managed_by", "install_manager", "registry_package_manager"):
        normalized = _normalize_repo_provider(source_row.get(field_name))
        if normalized:
            return normalized
    normalized_manager = _normalize_repo_provider(_resolve_source_manager(source_row))
    if normalized_manager:
        return normalized_manager
    return ""


def _resolve_repo_metadata_target(source_row: dict[str, Any]) -> dict[str, Any] | None:
    provider_hint = _resolve_repo_provider_hint(source_row)
    candidates: list[Any] = [
        source_row.get("locator"),
        source_row.get("repository"),
        source_row.get("registry_homepage"),
        source_row.get("source_url"),
    ]
    install_ref = source_row.get("install_ref")
    if isinstance(install_ref, str) and (
        install_ref.startswith("repo:")
        or install_ref.startswith("http://")
        or install_ref.startswith("https://")
        or install_ref.startswith("github.com/")
        or install_ref.startswith("www.github.com/")
        or install_ref.startswith("gitlab.com/")
        or install_ref.startswith("www.gitlab.com/")
        or install_ref.startswith("bitbucket.org/")
        or install_ref.startswith("www.bitbucket.org/")
    ):
        candidates.append(install_ref)

    for candidate in candidates:
        candidate_url = _repository_url(candidate) if isinstance(candidate, dict) else candidate
        resolved = _resolve_repo_metadata_target_from_locator(
            candidate_url,
            provider_hint=provider_hint,
        )
        if resolved:
            return resolved
    return None


def _resolve_source_manager(source_row: dict[str, Any]) -> str:
    for field in ("install_manager", "managed_by", "registry_package_manager"):
        manager = _normalize_manager(source_row.get(field))
        if manager:
            return manager
    return ""


def _is_git_syncable(source_row: dict[str, Any]) -> bool:
    manager = _resolve_source_manager(source_row)
    update_policy = _normalize_text(source_row.get("update_policy")).lower()
    source_kind = _normalize_text(source_row.get("source_kind")).lower()
    source_path = _normalize_text(source_row.get("source_path"))
    locator = _normalize_text(source_row.get("locator"))
    locator_is_repo_ref = _has_repo_locator_prefix(locator)
    locator_is_git = _looks_like_git_locator(locator)
    if manager in _GIT_MANAGER_ALIASES and (source_path or (locator_is_git and not locator_is_repo_ref)):
        return True
    if source_kind == "manual_git" and (source_path or (locator_is_git and not locator_is_repo_ref)):
        return True
    if update_policy == "source_sync" and (source_path or (locator_is_git and not locator_is_repo_ref)):
        return True
    return False


def is_source_syncable(source: dict[str, Any] | None) -> bool:
    source_row = source if isinstance(source, dict) else {}
    package_name = _normalize_text(source_row.get("registry_package_name"))
    package_manager = _normalize_manager(source_row.get("registry_package_manager"))
    if package_name and package_manager == "npm":
        return True

    if _is_git_syncable(source_row):
        return True
    if _resolve_repo_metadata_target(source_row):
        return True
    return False


def _run_git_command(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout_s: int = 8,
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
        message = (completed.stderr or completed.stdout or "").strip()
        return False, message or f"git command failed with exit code {completed.returncode}"
    return True, (completed.stdout or "").strip()


def fetch_git_source_summary(
    source_row: dict[str, Any],
    *,
    git_runner: Callable[..., tuple[bool, str]] = _run_git_command,
    timeout_s: int = 8,
) -> dict[str, Any]:
    source_path = _normalize_text(source_row.get("source_path"))
    git_checkout_path = _normalize_text(source_row.get("git_checkout_path"))
    checkout_path = git_checkout_path or source_path
    locator = _normalize_text(source_row.get("locator"))
    local_branch = ""
    local_commit = ""
    local_dirty = False

    if checkout_path:
        source_path_obj = Path(checkout_path)
        if source_path_obj.exists():
            ok_worktree, _ = git_runner(
                ["rev-parse", "--is-inside-work-tree"],
                cwd=checkout_path,
                timeout_s=timeout_s,
            )
            if ok_worktree:
                ok_branch, branch_output = git_runner(
                    ["rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=checkout_path,
                    timeout_s=timeout_s,
                )
                ok_commit, commit_output = git_runner(
                    ["rev-parse", "HEAD"],
                    cwd=checkout_path,
                    timeout_s=timeout_s,
                )
                ok_status, status_output = git_runner(
                    ["status", "--porcelain"],
                    cwd=checkout_path,
                    timeout_s=timeout_s,
                )
                if ok_branch:
                    local_branch = branch_output.strip()
                if ok_commit:
                    local_commit = commit_output.strip()
                if ok_status:
                    local_dirty = bool(status_output.strip())

    remote_head = ""
    if _looks_like_git_locator(locator):
        ok_remote, remote_output = git_runner(
            ["ls-remote", locator, "HEAD"],
            timeout_s=timeout_s,
        )
        if ok_remote and remote_output:
            remote_head = remote_output.split()[0].strip()
        elif not local_commit:
            return {
                "ok": False,
                "sync_kind": "git_remote",
                "sync_message": f"git remote metadata request failed for {locator}: {remote_output}",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": "",
                "registry_description": "",
                "sync_local_revision": local_commit,
                "sync_remote_revision": "",
                "sync_resolved_revision": local_commit,
                "sync_branch": local_branch,
                "sync_dirty": local_dirty,
                "sync_error_code": "git_remote_failed",
            }

    if local_commit:
        revision = remote_head or local_commit
        summary_bits: list[str] = []
        if local_branch:
            summary_bits.append(f"branch={local_branch}")
        summary_bits.append(f"local={local_commit[:12]}")
        if remote_head:
            summary_bits.append(f"remote={remote_head[:12]}")
        if local_dirty:
            summary_bits.append("dirty=true")
        return {
            "ok": True,
            "sync_kind": "git_checkout",
            "sync_message": f"checked git checkout metadata for {checkout_path}: {' '.join(summary_bits)}",
            "registry_latest_version": revision,
            "registry_published_at": "",
            "registry_homepage": locator if locator.startswith(("http://", "https://", "ssh://")) else "",
            "registry_description": f"git checkout ({local_branch or 'detached'})",
            "sync_local_revision": local_commit,
            "sync_remote_revision": remote_head,
            "sync_resolved_revision": revision,
            "sync_branch": local_branch,
            "sync_dirty": local_dirty,
            "sync_error_code": "",
        }

    if remote_head:
        return {
            "ok": True,
            "sync_kind": "git_remote",
            "sync_message": f"fetched git remote metadata for {locator}",
            "registry_latest_version": remote_head,
            "registry_published_at": "",
            "registry_homepage": locator if locator.startswith(("http://", "https://", "ssh://")) else "",
            "registry_description": "git remote HEAD",
            "sync_local_revision": "",
            "sync_remote_revision": remote_head,
            "sync_resolved_revision": remote_head,
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": "",
        }

    return {
        "ok": False,
        "sync_kind": "git_checkout",
        "sync_message": f"git sync requires a valid git source path or git locator: {checkout_path or locator or 'unknown'}",
        "registry_latest_version": "",
        "registry_published_at": "",
        "registry_homepage": "",
        "registry_description": "",
        "sync_local_revision": "",
        "sync_remote_revision": "",
        "sync_resolved_revision": "",
        "sync_branch": "",
        "sync_dirty": False,
        "sync_error_code": "git_source_unresolved",
    }


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
            "sync_error_code": "npm_registry_package_required",
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
            "sync_error_code": "npm_registry_http_error",
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
            "sync_error_code": "npm_registry_request_failed",
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
            "sync_error_code": "npm_registry_parse_failed",
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
            "sync_error_code": "npm_registry_response_invalid",
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
        "sync_local_revision": "",
        "sync_remote_revision": latest_version,
        "sync_resolved_revision": latest_version,
        "sync_branch": "",
        "sync_dirty": False,
        "sync_error_code": "",
    }


def fetch_repo_metadata_summary(
    source_row: dict[str, Any],
    *,
    urlopen: Callable[..., Any] = request.urlopen,
    timeout_s: int = 8,
) -> dict[str, Any]:
    def _normalize_api_base(value: Any, default: str) -> str:
        text = _normalize_text(value)
        if not text:
            return default
        if not text.startswith(("http://", "https://")):
            text = f"https://{text.lstrip('/')}"
        parsed = parse.urlparse(text)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return text.rstrip("/")

    def _http_header_value(headers: Any, name: str) -> str:
        if headers is None:
            return ""
        if hasattr(headers, "get"):
            value = headers.get(name)
            if value is not None:
                return str(value).strip()
        items = []
        if hasattr(headers, "items"):
            try:
                items = list(headers.items())
            except Exception:
                items = []
        for key, value in items:
            if str(key).strip().lower() == name.lower():
                return str(value).strip()
        return ""

    def _build_auth_header(provider: str) -> tuple[tuple[str, str] | None, dict[str, str] | None]:
        auth_token = _normalize_text(source_row.get("sync_auth_token"))
        auth_header = _normalize_text(source_row.get("sync_auth_header"))
        if not auth_header and not auth_token:
            return None, None

        if auth_header and ":" in auth_header:
            header_name, header_value = auth_header.split(":", 1)
            normalized_name = header_name.strip()
            normalized_value = header_value.strip()
            if not normalized_name:
                return None, {
                    "sync_error_code": "repo_metadata_auth_config_invalid",
                    "sync_message": "sync_auth_header is invalid: missing header name",
                }
            if "{token}" in normalized_value:
                if not auth_token:
                    return None, {
                        "sync_error_code": "repo_metadata_auth_config_invalid",
                        "sync_message": "sync_auth_token is required for sync_auth_header template",
                    }
                normalized_value = normalized_value.replace("{token}", auth_token)
            if not normalized_value and auth_token:
                normalized_value = auth_token
            if not normalized_value:
                return None, {
                    "sync_error_code": "repo_metadata_auth_config_invalid",
                    "sync_message": "sync_auth_header is invalid: missing header value",
                }
            return (normalized_name, normalized_value), None

        if auth_header:
            key = auth_header.lower()
            if key in {"bearer", "authorization", "authorization_bearer"}:
                if not auth_token:
                    return None, {
                        "sync_error_code": "repo_metadata_auth_config_invalid",
                        "sync_message": "sync_auth_token is required for bearer authorization",
                    }
                return ("Authorization", f"Bearer {auth_token}"), None
            if key in {"token", "authorization_token"}:
                if not auth_token:
                    return None, {
                        "sync_error_code": "repo_metadata_auth_config_invalid",
                        "sync_message": "sync_auth_token is required for token authorization",
                    }
                return ("Authorization", f"token {auth_token}"), None
            if key in {"private-token", "private_token"}:
                if not auth_token:
                    return None, {
                        "sync_error_code": "repo_metadata_auth_config_invalid",
                        "sync_message": "sync_auth_token is required for PRIVATE-TOKEN header",
                    }
                return ("PRIVATE-TOKEN", auth_token), None
            if key in {"x-auth-token", "x_auth_token"}:
                if not auth_token:
                    return None, {
                        "sync_error_code": "repo_metadata_auth_config_invalid",
                        "sync_message": "sync_auth_token is required for X-Auth-Token header",
                    }
                return ("X-Auth-Token", auth_token), None
            if auth_token:
                return (auth_header, auth_token), None
            return None, {
                "sync_error_code": "repo_metadata_auth_config_invalid",
                "sync_message": "sync_auth_token is required when sync_auth_header has no explicit value",
            }

        if provider == "gitlab":
            return ("PRIVATE-TOKEN", auth_token), None
        return ("Authorization", f"Bearer {auth_token}"), None

    def _classify_http_error(provider: str, exc: error.HTTPError) -> tuple[str, str]:
        status_code = int(getattr(exc, "code", 0) or 0)
        headers = getattr(exc, "headers", None)
        retry_after = _http_header_value(headers, "Retry-After")
        rate_limit_remaining = (
            _http_header_value(headers, "X-RateLimit-Remaining")
            or _http_header_value(headers, "RateLimit-Remaining")
        )
        if status_code == 429 or (status_code == 403 and rate_limit_remaining == "0"):
            suffix = f"http {status_code}"
            if retry_after:
                suffix += f" retry_after={retry_after}"
            return "repo_metadata_rate_limited", suffix
        if status_code in {401, 403}:
            return "repo_metadata_auth_failed", f"http {status_code}"
        if status_code in {500, 502, 503, 504}:
            suffix = f"http {status_code}"
            if retry_after:
                suffix += f" retry_after={retry_after}"
            return "repo_metadata_provider_unreachable", suffix
        return "repo_metadata_http_error", f"http {status_code}"

    def _classify_request_exception(exc: Exception) -> tuple[str, str]:
        reason = _normalize_text(getattr(exc, "reason", ""))
        message = _normalize_text(str(exc))
        lowered = f"{reason} {message}".lower()
        if any(
            token in lowered
            for token in (
                "timed out",
                "temporary failure",
                "name or service not known",
                "connection refused",
                "network is unreachable",
                "no route to host",
                "tls",
                "ssl",
                "certificate",
            )
        ):
            return "repo_metadata_provider_unreachable", message or reason or "provider unreachable"
        return "repo_metadata_request_failed", message or reason or "request failed"

    target = _resolve_repo_metadata_target(source_row)
    if not target:
        return {
            "ok": False,
            "sync_kind": "repo_metadata",
            "sync_message": "repo metadata locator is required",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": "repo_metadata_locator_required",
        }

    provider = str(target.get("provider") or "").strip().lower()
    homepage = str(target.get("homepage") or "").strip()
    sync_kind = f"repo_metadata_{provider}" if provider else "repo_metadata"

    if provider == "github":
        owner = str(target.get("owner") or "").strip()
        repo = str(target.get("repo") or "").strip()
        if not owner or not repo:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "github repo metadata target is invalid",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_target_invalid",
            }
        target_label = f"{owner}/{repo}"
        api_base = _normalize_api_base(source_row.get("sync_api_base"), "https://api.github.com")
        if not api_base:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "sync_api_base is invalid for github repo metadata",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_api_base_invalid",
            }
        api_url = f"{api_base}/repos/{parse.quote(owner, safe='')}/{parse.quote(repo, safe='')}"
        request_headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "onesync-source-sync",
        }
        req = request.Request(
            api_url,
            headers=request_headers,
        )
        homepage_field = "html_url"
        description_field = "description"
        branch_field = "default_branch"
        revision_fields = ("pushed_at", "updated_at")
    elif provider == "gitlab":
        namespace = str(target.get("namespace") or "").strip()
        if not namespace:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "gitlab repo metadata target is invalid",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_target_invalid",
            }
        target_label = namespace
        api_base = _normalize_api_base(source_row.get("sync_api_base"), "https://gitlab.com/api/v4")
        if not api_base:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "sync_api_base is invalid for gitlab repo metadata",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_api_base_invalid",
            }
        api_url = f"{api_base}/projects/{parse.quote(namespace, safe='')}"
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "onesync-source-sync",
        }
        req = request.Request(
            api_url,
            headers=request_headers,
        )
        homepage_field = "web_url"
        description_field = "description"
        branch_field = "default_branch"
        revision_fields = ("last_activity_at", "updated_at")
    elif provider == "bitbucket":
        workspace = str(target.get("workspace") or "").strip()
        repo = str(target.get("repo") or "").strip()
        if not workspace or not repo:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "bitbucket repo metadata target is invalid",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_target_invalid",
            }
        target_label = f"{workspace}/{repo}"
        api_base = _normalize_api_base(source_row.get("sync_api_base"), "https://api.bitbucket.org/2.0")
        if not api_base:
            return {
                "ok": False,
                "sync_kind": sync_kind,
                "sync_message": "sync_api_base is invalid for bitbucket repo metadata",
                "registry_latest_version": "",
                "registry_published_at": "",
                "registry_homepage": homepage,
                "registry_description": "",
                "sync_local_revision": "",
                "sync_remote_revision": "",
                "sync_resolved_revision": "",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "repo_metadata_api_base_invalid",
            }
        api_url = (
            f"{api_base}/repositories/"
            f"{parse.quote(workspace, safe='')}/{parse.quote(repo, safe='')}"
        )
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "onesync-source-sync",
        }
        req = request.Request(
            api_url,
            headers=request_headers,
        )
        homepage_field = ""
        description_field = "description"
        branch_field = ""
        revision_fields = ("updated_on", "created_on")
    else:
        return {
            "ok": False,
            "sync_kind": "repo_metadata",
            "sync_message": f"repo metadata provider is unsupported: {provider or 'unknown'}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": "",
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": "repo_metadata_provider_unsupported",
        }

    auth_header, auth_error = _build_auth_header(provider)
    if auth_error:
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": f"{provider} repo metadata auth config is invalid for {target_label}: {auth_error['sync_message']}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": auth_error["sync_error_code"],
        }
    if auth_header:
        req.add_header(auth_header[0], auth_header[1])

    try:
        with urlopen(req, timeout=timeout_s) as response:
            raw = response.read()
    except error.HTTPError as exc:
        error_code, error_suffix = _classify_http_error(provider, exc)
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": f"{provider} repo metadata request failed for {target_label}: {error_suffix}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": error_code,
        }
    except Exception as exc:
        error_code, error_message = _classify_request_exception(exc)
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": f"{provider} repo metadata request failed for {target_label}: {error_message}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": error_code,
        }

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": f"{provider} repo metadata parse failed for {target_label}: {exc}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": "repo_metadata_parse_failed",
        }

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": f"{provider} repo metadata response is invalid for {target_label}",
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": "",
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": "",
            "sync_dirty": False,
            "sync_error_code": "repo_metadata_response_invalid",
        }

    resolved_revision = ""
    for field in revision_fields:
        resolved_revision = _normalize_text(payload.get(field))
        if resolved_revision:
            break
    if not resolved_revision:
        return {
            "ok": False,
            "sync_kind": sync_kind,
            "sync_message": (
                f"{provider} repo metadata does not include revision fields for {target_label}: "
                + "/".join(revision_fields)
            ),
            "registry_latest_version": "",
            "registry_published_at": "",
            "registry_homepage": homepage,
            "registry_description": _normalize_text(payload.get(description_field)),
            "sync_local_revision": "",
            "sync_remote_revision": "",
            "sync_resolved_revision": "",
            "sync_branch": _normalize_text(payload.get(branch_field)) if branch_field else "",
            "sync_dirty": False,
            "sync_error_code": "repo_metadata_response_invalid",
        }

    payload_homepage = ""
    if provider == "bitbucket":
        links = payload.get("links", {})
        links = links if isinstance(links, dict) else {}
        html_link = links.get("html", {})
        html_link = html_link if isinstance(html_link, dict) else {}
        payload_homepage = _normalize_text(html_link.get("href")) or _normalize_text(payload.get("website"))
    else:
        payload_homepage = _normalize_text(payload.get(homepage_field)) if homepage_field else ""

    branch = ""
    if provider == "bitbucket":
        mainbranch = payload.get("mainbranch", {})
        mainbranch = mainbranch if isinstance(mainbranch, dict) else {}
        branch = _normalize_text(mainbranch.get("name"))
    else:
        branch = _normalize_text(payload.get(branch_field)) if branch_field else ""

    return {
        "ok": True,
        "sync_kind": sync_kind,
        "sync_message": f"fetched {provider} repository metadata for {target_label}",
        "registry_latest_version": resolved_revision,
        "registry_published_at": resolved_revision,
        "registry_homepage": payload_homepage or homepage,
        "registry_description": _normalize_text(payload.get(description_field)),
        "sync_local_revision": "",
        "sync_remote_revision": resolved_revision,
        "sync_resolved_revision": resolved_revision,
        "sync_branch": branch,
        "sync_dirty": False,
        "sync_error_code": "",
    }


def build_source_sync_record(
    source: dict[str, Any],
    *,
    checked_at: str | None = None,
    urlopen: Callable[..., Any] = request.urlopen,
    git_runner: Callable[..., tuple[bool, str]] = _run_git_command,
    timeout_s: int = 8,
) -> dict[str, Any]:
    source_row = source if isinstance(source, dict) else {}
    ts = str(checked_at or _now_iso())
    package_name = _normalize_text(source_row.get("registry_package_name"))
    package_manager = _normalize_manager(source_row.get("registry_package_manager"))

    base = {
        "sync_status": "unsupported",
        "sync_checked_at": ts,
        "sync_kind": "",
        "sync_message": "source does not declare a supported sync adapter",
        "registry_latest_version": "",
        "registry_published_at": "",
        "registry_homepage": "",
        "registry_description": "",
        "sync_local_revision": "",
        "sync_remote_revision": "",
        "sync_resolved_revision": "",
        "sync_branch": "",
        "sync_dirty": False,
        "sync_error_code": "",
    }

    if not is_source_syncable(source_row):
        return {
            **base,
            "sync_error_code": "unsupported_sync_adapter",
        }

    if package_name and package_manager == "npm":
        summary = fetch_npm_registry_package_summary(
            package_name,
            urlopen=urlopen,
            timeout_s=timeout_s,
        )
    elif _is_git_syncable(source_row):
        summary = fetch_git_source_summary(
            source_row,
            git_runner=git_runner,
            timeout_s=timeout_s,
        )
    else:
        summary = fetch_repo_metadata_summary(
            source_row,
            urlopen=urlopen,
            timeout_s=timeout_s,
        )
    return {
        **base,
        **summary,
        "sync_status": "ok" if summary.get("ok") else "error",
        "sync_checked_at": ts,
    }
