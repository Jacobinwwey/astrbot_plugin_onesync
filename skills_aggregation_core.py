from __future__ import annotations

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CURATED_NPX_AGGREGATION_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "compound_engineering",
        "registry_packages": ["@every-env/compound-plugin"],
        "prefixes": ["ce:"],
        "tag_prefixes": ["bundle:compound_engineering"],
        "install_unit_id": "npm:@every-env/compound-plugin",
        "install_unit_kind": "npm_package",
        "install_ref": "@every-env/compound-plugin",
        "install_manager": "bunx",
        "install_unit_display_name": "Compound Engineering",
        "collection_group_id": "collection:compound_engineering",
        "collection_group_name": "Compound Engineering",
        "collection_group_kind": "package",
    },
    {
        "rule_id": "design_review_pack",
        "names": [
            "design-implementation-reviewer",
            "design-iterator",
            "design-lens-reviewer",
        ],
        "install_unit_id": "curated:design_review_pack",
        "install_unit_kind": "curated_npx_pack",
        "install_ref": "design-review-pack",
        "install_manager": "npx",
        "install_unit_display_name": "Design Review Pack",
        "collection_group_id": "collection:design_review",
        "collection_group_name": "Design Review",
        "collection_group_kind": "curated",
    },
    {
        "rule_id": "dhh_rails_pack",
        "prefixes": ["dhh-rails-"],
        "install_unit_id": "curated:dhh_rails_pack",
        "install_unit_kind": "curated_npx_pack",
        "install_ref": "dhh-rails-pack",
        "install_manager": "npx",
        "install_unit_display_name": "DHH Rails Pack",
        "collection_group_id": "collection:dhh_rails",
        "collection_group_name": "DHH Rails",
        "collection_group_kind": "curated",
    },
]

_SOURCE_STATUS_RANK = {
    "missing": 4,
    "unavailable": 3,
    "stale": 2,
    "ready": 1,
    "idle": 0,
}
_FRESHNESS_RANK = {
    "missing": 4,
    "stale": 3,
    "aging": 2,
    "fresh": 1,
}
_SYNC_STATUS_RANK = {
    "error": 3,
    "pending": 2,
    "ok": 1,
    "": 0,
}
_PROVENANCE_CONFIDENCE_RANK = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

PROVENANCE_FIELD_KEYS = (
    "provenance_origin_kind",
    "provenance_origin_ref",
    "provenance_origin_label",
    "provenance_root_kind",
    "provenance_root_path",
    "provenance_package_name",
    "provenance_package_manager",
    "provenance_package_strategy",
    "provenance_confidence",
)

SKILLS_ROOT_PROVENANCE_RULES: list[dict[str, str]] = [
    {
        "marker": "/.codex/skills",
        "root_kind": "codex_home_skills",
        "label": "Codex Skills Root",
    },
    {
        "marker": "/.agents/skills",
        "root_kind": "agents_home_skills",
        "label": "Agents Skills Root",
    },
    {
        "marker": "/.claude/skills",
        "root_kind": "claude_home_skills",
        "label": "Claude Skills Root",
    },
    {
        "marker": "/zeroclaw/.claude/skills",
        "root_kind": "zeroclaw_claude_skills",
        "label": "ZeroClaw Skills Root",
    },
    {
        "marker": "/antigravity/skills",
        "root_kind": "antigravity_skills",
        "label": "Antigravity Skills Root",
    },
]

LEGACY_FAMILY_LABEL_OVERRIDES = {
    "api": "API",
    "cli": "CLI",
    "dhh": "DHH",
    "git": "Git",
    "javascript": "JavaScript",
    "kieran": "Kieran",
    "todo": "Todo",
    "ui": "UI",
    "ux": "UX",
}

_CACHE_SIMILARITY_MATCH_THRESHOLD = 0.97
# Keep this just below observed host-adapted skill variants while relying on
# same-name, same-description, and unique-candidate guards to avoid over-merging.
_CACHE_STRUCTURED_SIMILARITY_MATCH_THRESHOLD = 0.83
_CONTEXT_SECTION_HEADINGS = {
    "## Context",
    "### Context fallback",
}
_EMBEDDED_SOURCE_DOC_FILENAMES = (
    "README.md",
    "WARP.md",
    "NOTICE.txt",
)
_CURATED_REFERENCE_SKILL_REPO_HINTS: dict[str, str] = {
    # Cross-checked against local reference managers (`skill-flow` and
    # `ai-toolbox`) and the upstream repository layout.
    "ui-ux-pro-max": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git#.claude/skills/ui-ux-pro-max",
}


def _slug(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text or default


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
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return _to_str_list(parsed)
        return [seg.strip() for seg in re.split(r"[\n,]+", text) if seg.strip()]
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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_path_text(path_text: Any) -> str:
    return str(path_text or "").strip().replace("\\", "/")


def _safe_expand_path(path_text: Any) -> Path | None:
    text = str(path_text or "").strip()
    if not text:
        return None
    try:
        return Path(os.path.expanduser(text))
    except Exception:
        return None


def _infer_manager_from_hint(management_hint: str, default: str = "") -> str:
    hint = str(management_hint or "").strip().lower()
    if not hint:
        return default
    if hint.startswith("bunx "):
        return "bunx"
    if hint.startswith("pnpm dlx "):
        return "pnpm"
    if hint.startswith("npx "):
        return "npx"
    return default


def _detect_skills_root(path_text: Any) -> tuple[str, str, str]:
    normalized = _normalize_path_text(path_text)
    lowered = normalized.lower()
    if not lowered:
        return "", "", ""
    for rule in SKILLS_ROOT_PROVENANCE_RULES:
        marker = _normalize_path_text(rule.get("marker")).lower().rstrip("/")
        if not marker:
            continue
        idx = lowered.find(marker)
        if idx < 0:
            continue
        root_path = normalized[: idx + len(marker)].rstrip("/")
        return (
            str(rule.get("root_kind") or "").strip(),
            root_path,
            str(rule.get("label") or "").strip(),
        )
    return "", "", ""


def _looks_like_remote_locator(locator: str) -> bool:
    normalized = str(locator or "").strip().lower()
    return normalized.startswith(("http://", "https://", "git@", "ssh://"))


def _normalize_subpath_text(path_text: Any) -> str:
    return str(path_text or "").strip().replace("\\", "/").strip("/")


def _legacy_family_token(name_text: Any) -> str:
    text = str(name_text or "").strip().lower()
    if not text:
        return ""
    if ":" in text:
        head, _, _ = text.partition(":")
        return _slug(head, default="")
    if "-" in text:
        head, _, _ = text.partition("-")
        return _slug(head, default="")
    return ""


def _legacy_family_label(token: str) -> str:
    normalized = _slug(token, default="")
    if not normalized:
        return ""
    override = LEGACY_FAMILY_LABEL_OVERRIDES.get(normalized)
    if override:
        return override
    return " ".join(segment.capitalize() for segment in normalized.split("_") if segment) or normalized


def _repo_label_from_locator(locator: Any) -> str:
    text = str(locator or "").strip()
    if not text:
        return ""
    if text.startswith("git@"):
        _, _, repo_path = text.partition(":")
        repo_path = repo_path.strip().strip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        return repo_path or text
    try:
        parsed = urlparse(text)
    except Exception:
        parsed = None
    if parsed:
        repo_path = str(parsed.path or "").strip().strip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        if repo_path:
            return repo_path
    return text


def _local_root_label(locator: Any) -> str:
    normalized = _normalize_path_text(locator).rstrip("/")
    if not normalized:
        return ""
    basename = normalized.rsplit("/", 1)[-1].strip()
    return basename or normalized


def _join_locator_with_subpath(locator: Any, source_subpath: Any) -> str:
    locator_text = str(locator or "").strip()
    subpath_text = _normalize_subpath_text(source_subpath)
    if locator_text and subpath_text:
        return f"{locator_text}#{subpath_text}"
    return locator_text or subpath_text


def _split_locator_with_subpath(ref_text: Any) -> tuple[str, str]:
    text = str(ref_text or "").strip()
    if not text:
        return "", ""
    locator, fragment = text, ""
    if "#" in text:
        locator, _, fragment = text.partition("#")
    return locator.strip(), _normalize_subpath_text(fragment)


def _manual_source_collection_group(locator: Any, source_kind: str) -> tuple[str, str, str]:
    locator_text = str(locator or "").strip()
    if str(source_kind or "").strip().lower() == "manual_git":
        label = _repo_label_from_locator(locator_text) or locator_text
        return (
            f"collection:source_repo_{_slug(label, default='source_repo')}",
            label,
            "source_repo",
        )
    label = _local_root_label(locator_text) or locator_text
    return (
        f"collection:source_root_{_slug(locator_text, default='source_root')}",
        label,
        "source_root",
    )


def _match_curated_rule(source: dict[str, Any]) -> dict[str, Any] | None:
    registry_package_name = _first_non_empty(
        source.get("registry_package_name"),
        source.get("provenance_package_name"),
    ).strip().lower()
    names = {
        str(source.get("display_name") or "").strip().lower(),
        *[str(item or "").strip().lower() for item in _to_str_list(source.get("member_skill_preview", []))],
    }
    names = {item for item in names if item}
    tags = {
        str(item or "").strip().lower()
        for item in _to_str_list(source.get("tags", []))
    }
    for rule in CURATED_NPX_AGGREGATION_RULES:
        registry_packages = {
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("registry_packages", []))
        }
        if registry_package_name and registry_package_name in registry_packages:
            return dict(rule)

        rule_names = {
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("names", []))
        }
        if rule_names and names.intersection(rule_names):
            return dict(rule)

        prefixes = [
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("prefixes", []))
            if str(item or "").strip()
        ]
        if prefixes and any(any(name.startswith(prefix) for prefix in prefixes) for name in names):
            return dict(rule)

        tag_prefixes = [
            str(item or "").strip().lower()
            for item in _to_str_list(rule.get("tag_prefixes", []))
            if str(item or "").strip()
        ]
        if tag_prefixes and any(any(tag.startswith(prefix) for prefix in tag_prefixes) for tag in tags):
            return dict(rule)
    return None


def _package_name_from_path_heuristic(path_text: str) -> str:
    normalized = str(path_text or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    match = re.search(r"/node_modules/((?:@[^/]+/)?[^/]+)", normalized)
    if match:
        return str(match.group(1) or "").strip()
    return ""


def _package_name_from_nearest_package_json(path_text: str) -> str:
    path = _safe_expand_path(path_text)
    if not path or not path.exists():
        return ""

    current = path if path.is_dir() else path.parent
    max_hops = 4
    for _ in range(max_hops + 1):
        package_json = current / "package.json"
        if package_json.exists() and package_json.is_file():
            try:
                payload = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            package_name = str(payload.get("name") or "").strip()
            if package_name:
                return package_name
        if current.parent == current:
            break
        current = current.parent
    return ""


def _split_path_env(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    result: list[str] = []
    for segment in text.split(os.pathsep):
        normalized = str(segment or "").strip()
        if normalized:
            result.append(normalized)
    return tuple(_dedupe_keep_order(result))


def _configured_package_cache_roots() -> tuple[str, ...]:
    configured = _split_path_env(os.environ.get("ONESYNC_SKILL_PACKAGE_CACHE_ROOTS", ""))
    if configured:
        return configured
    return tuple(
        _dedupe_keep_order(
            [
                str(Path(os.path.expanduser("~/.bun/install/cache"))),
                str(Path(os.path.expanduser("~/.npm/_npx"))),
            ],
        ),
    )


def _configured_local_mirror_roots() -> tuple[str, ...]:
    configured = _split_path_env(os.environ.get("ONESYNC_SKILL_LOCAL_MIRROR_ROOTS", ""))
    if configured:
        return configured
    return tuple(
        _dedupe_keep_order(
            [
                str(Path(os.path.expanduser("~/.codex/.tmp/plugins"))),
            ],
        ),
    )


def _skill_markdown_path(path_text: Any) -> Path | None:
    path = _safe_expand_path(path_text)
    if not path:
        return None
    candidate = path if path.is_file() else path / "SKILL.md"
    try:
        if candidate.exists() and candidate.is_file():
            return candidate
    except Exception:
        return None
    return None


@lru_cache(maxsize=1024)
def _skill_support_file_text(path_text: str, filename: str) -> str:
    base = _safe_expand_path(path_text)
    if not base:
        return ""
    target = (base if base.is_dir() else base.parent) / filename
    try:
        if target.exists() and target.is_file():
            return target.read_text(encoding="utf-8")
    except Exception:
        return ""
    return ""


@lru_cache(maxsize=1024)
def _skill_markdown_signature(path_text: str) -> str:
    skill_markdown = _skill_markdown_path(path_text)
    if not skill_markdown:
        return ""
    try:
        payload = skill_markdown.read_bytes()
    except Exception:
        return ""
    return hashlib.sha1(payload).hexdigest()


@lru_cache(maxsize=1024)
def _skill_markdown_text(path_text: str) -> str:
    skill_markdown = _skill_markdown_path(path_text)
    if not skill_markdown:
        return ""
    try:
        return skill_markdown.read_text(encoding="utf-8")
    except Exception:
        return ""


def _canonical_skill_markdown_text(text: Any) -> str:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    if not normalized.startswith("---\n"):
        return normalized

    frontmatter_end = normalized.find("\n---\n", 4)
    if frontmatter_end < 0:
        return normalized

    frontmatter = normalized[4:frontmatter_end].splitlines()
    body = normalized[frontmatter_end + len("\n---\n") :].strip()
    preserved_frontmatter = [
        line.strip()
        for line in frontmatter
        if str(line or "").strip().lower().startswith(("name:", "description:"))
    ]
    parts = [segment for segment in ("\n".join(preserved_frontmatter).strip(), body) if segment]
    return "\n\n".join(parts).strip()


@lru_cache(maxsize=1024)
def _canonical_skill_markdown_text_for_path(path_text: str) -> str:
    return _canonical_skill_markdown_text(_skill_markdown_text(path_text))


def _skill_markdown_identity_fields(text: Any) -> tuple[str, str]:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized.startswith("---\n"):
        return "", ""
    frontmatter_end = normalized.find("\n---\n", 4)
    if frontmatter_end < 0:
        return "", ""

    name = ""
    description = ""
    for line in normalized[4:frontmatter_end].splitlines():
        stripped = str(line or "").strip()
        lowered = stripped.lower()
        if lowered.startswith("name:"):
            name = stripped[5:].strip().strip("\"'")
        elif lowered.startswith("description:") and not description:
            description = stripped[12:].strip().strip("\"'")
    return name, description


def _normalize_markdown_section_body(text: Any) -> str:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    lines: list[str] = []
    for line in normalized.splitlines():
        stripped = str(line or "").strip()
        if not stripped:
            continue
        lines.append(re.sub(r"\s+", " ", stripped))
    return "\n".join(lines).strip()


def _markdown_section_map(text: Any) -> dict[str, str]:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return {}

    if normalized.startswith("---\n"):
        frontmatter_end = normalized.find("\n---\n", 4)
        if frontmatter_end >= 0:
            normalized = normalized[frontmatter_end + len("\n---\n") :].strip()

    sections: dict[str, list[str]] = {"<root>": []}
    current_heading = "<root>"
    for raw_line in normalized.splitlines():
        line = str(raw_line or "")
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+", stripped):
            current_heading = stripped
            sections.setdefault(current_heading, [])
            continue
        sections.setdefault(current_heading, []).append(line)

    return {
        heading: _normalize_markdown_section_body("\n".join(lines))
        for heading, lines in sections.items()
        if heading not in _CONTEXT_SECTION_HEADINGS and _normalize_markdown_section_body("\n".join(lines))
    }


def _structured_skill_markdown_similarity(left_text: Any, right_text: Any) -> float:
    left_name, left_description = _skill_markdown_identity_fields(left_text)
    right_name, right_description = _skill_markdown_identity_fields(right_text)
    if not left_name or not right_name or left_name != right_name:
        return 0.0
    if left_description and right_description and left_description != right_description:
        return 0.0

    left_sections = _markdown_section_map(left_text)
    right_sections = _markdown_section_map(right_text)
    left_headings = {heading for heading in left_sections if heading != "<root>"}
    right_headings = {heading for heading in right_sections if heading != "<root>"}
    common_headings = left_headings.intersection(right_headings)
    if not common_headings:
        return 0.0

    heading_ratio = len(common_headings) / max(len(left_headings), len(right_headings), 1)
    exact_matches = 0
    strong_matches = 0
    section_scores: list[float] = []
    for heading in common_headings:
        ratio = SequenceMatcher(None, left_sections.get(heading, ""), right_sections.get(heading, "")).ratio()
        section_scores.append(ratio)
        if ratio >= 0.999:
            exact_matches += 1
        if ratio >= 0.72:
            strong_matches += 1

    root_ratio = SequenceMatcher(
        None,
        left_sections.get("<root>", ""),
        right_sections.get("<root>", ""),
    ).ratio()
    section_ratio = sum(section_scores) / len(section_scores)
    exact_ratio = exact_matches / len(common_headings)
    strong_ratio = strong_matches / len(common_headings)
    return (
        (heading_ratio * 0.30)
        + (section_ratio * 0.30)
        + (strong_ratio * 0.20)
        + (root_ratio * 0.10)
        + (exact_ratio * 0.10)
    )


def _ignore_cache_candidate_for_provenance(path_text: Any) -> bool:
    normalized = _normalize_path_text(path_text).lower()
    return any(
        marker in normalized
        for marker in (
            "/tests/",
            "/fixtures/",
            "/__tests__/",
        )
    )


def _repo_url_from_slug(repo_slug: str) -> str:
    slug = str(repo_slug or "").strip().strip("/")
    if not slug or "/" not in slug:
        return ""
    if slug.endswith(".git"):
        slug = slug[:-4]
    return f"https://github.com/{slug}.git"


def _normalize_notice_source_subpath(path_text: Any) -> str:
    normalized = _normalize_subpath_text(path_text)
    if normalized.lower().endswith("/skill.md"):
        normalized = normalized[:-len("/skill.md")]
    elif normalized.lower() == "skill.md":
        normalized = ""
    return normalized


def _embedded_source_repo_candidates(skill_path: str) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    for filename in _EMBEDDED_SOURCE_DOC_FILENAMES:
        text = _skill_support_file_text(skill_path, filename)
        if not text:
            continue

        for match in re.finditer(r"git clone\s+(https://github\.com/[^\s]+)", text, re.IGNORECASE):
            repo_ref = _join_locator_with_subpath(str(match.group(1) or "").strip(), "")
            if repo_ref:
                candidates.append((repo_ref, "embedded_git_clone_url"))

        for match in re.finditer(r"npx\s+skills\s+add\s+(https://github\.com/[^\s]+)", text, re.IGNORECASE):
            repo_ref = _join_locator_with_subpath(str(match.group(1) or "").strip(), "")
            if repo_ref:
                candidates.append((repo_ref, "embedded_skills_add_url"))

        repo_match = re.search(r"Repository:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        if repo_match:
            repo_locator = _repo_url_from_slug(str(repo_match.group(1) or "").strip())
            source_subpath = ""
            path_match = re.search(r"Path:\s*([^\n]+)", text, re.IGNORECASE)
            if path_match:
                source_subpath = _normalize_notice_source_subpath(str(path_match.group(1) or "").strip())
            repo_ref = _join_locator_with_subpath(repo_locator, source_subpath)
            if repo_ref:
                candidates.append((repo_ref, "embedded_notice_repository"))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return tuple(deduped)


def _infer_documented_source_repo(source: dict[str, Any]) -> tuple[str, str, str]:
    source_path = str(source.get("source_path") or "").strip()
    if not source_path:
        return "", "", ""

    candidates = _embedded_source_repo_candidates(source_path)
    if not candidates:
        return "", "", ""

    unique_refs = {ref for ref, _ in candidates if ref}
    if len(unique_refs) != 1:
        return "", "", ""

    origin_ref = next(iter(unique_refs))
    strategies = {strategy for ref, strategy in candidates if ref == origin_ref}
    locator, _ = _split_locator_with_subpath(origin_ref)
    origin_label = _repo_label_from_locator(locator or origin_ref)
    if "embedded_git_clone_url" in strategies:
        return origin_ref, origin_label, "embedded_git_clone_url"
    if "embedded_skills_add_url" in strategies:
        return origin_ref, origin_label, "embedded_skills_add_url"
    if "embedded_notice_repository" in strategies:
        return origin_ref, origin_label, "embedded_notice_repository"
    return "", "", ""


def _infer_curated_reference_repo_hint(source: dict[str, Any]) -> tuple[str, str, str]:
    candidate_names = [
        str(source.get("display_name") or "").strip().lower(),
        *[
            str(item or "").strip().lower()
            for item in _to_str_list(source.get("member_skill_preview", []))
        ],
    ]
    for name in candidate_names:
        if not name:
            continue
        origin_ref = str(_CURATED_REFERENCE_SKILL_REPO_HINTS.get(name) or "").strip()
        if not origin_ref:
            continue
        locator, _ = _split_locator_with_subpath(origin_ref)
        origin_label = _repo_label_from_locator(locator or origin_ref)
        if origin_label:
            return origin_ref, origin_label, "catalog_reference_hint"
    return "", "", ""


def _embedded_local_skill_derivative_base_names(skill_path: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for filename in _EMBEDDED_SOURCE_DOC_FILENAMES:
        text = _skill_support_file_text(skill_path, filename)
        if not text:
            continue
        for match in re.finditer(r"The local `([A-Za-z0-9_.-]+)` skill", text, re.IGNORECASE):
            candidates.append(str(match.group(1) or "").strip())
        for match in re.finditer(r"\.codex/skills/([A-Za-z0-9_.-]+)/assets/", text, re.IGNORECASE):
            candidates.append(str(match.group(1) or "").strip())
    return tuple(_dedupe_keep_order(candidates))


def _related_local_skill_source(source: dict[str, Any], related_name: str) -> dict[str, Any] | None:
    source_path = str(source.get("source_path") or "").strip()
    if not source_path:
        return None
    source_dir = _safe_expand_path(source_path)
    if not source_dir:
        return None
    current_dir = source_dir if source_dir.is_dir() else source_dir.parent
    related_dir = current_dir.parent / str(related_name or "").strip()
    try:
        if not related_dir.exists() or not related_dir.is_dir() or related_dir == current_dir:
            return None
    except Exception:
        return None

    return {
        "source_id": f"related_local_{_slug(related_name, default='skill')}",
        "display_name": related_name,
        "source_kind": "npx_single",
        "source_scope": str(source.get("source_scope") or "global"),
        "source_path": str(related_dir),
        "member_count": 1,
        "member_skill_preview": [related_name],
        "compatible_software_ids": _to_str_list(source.get("compatible_software_ids", [])),
        "status": str(source.get("status") or "ready"),
        "freshness_status": str(source.get("freshness_status") or "fresh"),
    }


def _infer_local_skill_derivative(source: dict[str, Any]) -> tuple[str, str]:
    display_name = str(source.get("display_name") or "").strip().lower()
    for base_name in _embedded_local_skill_derivative_base_names(str(source.get("source_path") or "").strip()):
        normalized_base_name = str(base_name or "").strip()
        if not normalized_base_name or normalized_base_name.lower() == display_name:
            continue
        related_source = _related_local_skill_source(source, normalized_base_name)
        if not related_source:
            continue
        related_provenance = derive_source_provenance_fields(related_source)
        if str(related_provenance.get("provenance_confidence") or "").strip().lower() not in {"high", "medium"}:
            continue
        if str(related_provenance.get("provenance_origin_kind") or "").strip().lower() in {
            "documented_source_repo",
            "catalog_source_repo",
            "local_plugin_bundle",
        }:
            return normalized_base_name, "embedded_local_derivative_notice"
    return "", ""


def _resolve_local_skill_derivative_collection(source: dict[str, Any], base_name: str) -> tuple[str, str, str]:
    related_source = _related_local_skill_source(source, base_name)
    if not related_source:
        return "", "", ""
    related_aggregation = derive_source_aggregation_fields(related_source)
    collection_group_id = str(related_aggregation.get("collection_group_id") or "").strip()
    collection_group_name = str(related_aggregation.get("collection_group_name") or "").strip()
    collection_group_kind = str(related_aggregation.get("collection_group_kind") or "").strip()
    if not collection_group_id:
        return "", "", ""
    return collection_group_id, collection_group_name, collection_group_kind


@lru_cache(maxsize=512)
def _candidate_local_skill_mirror_documents(skill_dir_name: str, local_roots: tuple[str, ...]) -> tuple[str, ...]:
    normalized_name = str(skill_dir_name or "").strip()
    if not normalized_name:
        return ()

    candidates: list[str] = []
    for root_text in local_roots:
        root = _safe_expand_path(root_text)
        if not root:
            continue
        try:
            if not root.exists():
                continue
        except Exception:
            continue
        try:
            for candidate in root.glob(f"**/skills/{normalized_name}/SKILL.md"):
                if candidate.is_file() and not _ignore_cache_candidate_for_provenance(candidate):
                    candidates.append(str(candidate))
        except Exception:
            continue
    return tuple(_dedupe_keep_order(candidates))


@lru_cache(maxsize=256)
def _local_plugin_bundle_metadata(candidate_path: str) -> tuple[str, str]:
    path = _safe_expand_path(candidate_path)
    if not path:
        return "", ""

    current = path.parent if path.is_file() else path
    max_hops = 6
    for _ in range(max_hops + 1):
        plugin_json = current / ".codex-plugin" / "plugin.json"
        if plugin_json.exists() and plugin_json.is_file():
            try:
                payload = json.loads(plugin_json.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            plugin_name = str(payload.get("name") or "").strip()
            repository = str(payload.get("repository") or "").strip()
            interface = payload.get("interface") if isinstance(payload.get("interface"), dict) else {}
            display_name = str(interface.get("displayName") or plugin_name or "").strip()
            origin_ref = ""
            if repository and plugin_name:
                origin_ref = f"{repository}#{plugin_name}"
            elif plugin_name:
                origin_ref = plugin_name
            if origin_ref:
                return origin_ref, display_name or plugin_name
        if current.parent == current:
            break
        current = current.parent
    return "", ""


def _infer_local_plugin_bundle(source: dict[str, Any]) -> tuple[str, str, str]:
    source_path = str(source.get("source_path") or "").strip()
    if not source_path:
        return "", "", ""

    signature = _skill_markdown_signature(source_path)
    if not signature:
        return "", "", ""

    skill_dir_name = ""
    source_dir = _safe_expand_path(source_path)
    if source_dir:
        skill_dir_name = str(source_dir.name or "").strip()
    if not skill_dir_name:
        member_names = _to_str_list(source.get("member_skill_preview", []))
        skill_dir_name = str(member_names[0] if member_names else source.get("display_name") or "").strip()
    if not skill_dir_name:
        return "", "", ""

    local_roots = _configured_local_mirror_roots()
    if not local_roots:
        return "", "", ""

    normalized_source_path = _normalize_path_text(source_path)
    candidates_by_ref: dict[str, tuple[str, str]] = {}
    for candidate in _candidate_local_skill_mirror_documents(skill_dir_name, local_roots):
        if _normalize_path_text(candidate) == normalized_source_path:
            continue
        if _skill_markdown_signature(candidate) != signature:
            continue
        origin_ref, origin_label = _local_plugin_bundle_metadata(candidate)
        if not origin_ref:
            continue
        candidates_by_ref.setdefault(origin_ref, (origin_ref, origin_label))

    if len(candidates_by_ref) != 1:
        return "", "", ""
    origin_ref, origin_label = next(iter(candidates_by_ref.values()))
    return origin_ref, origin_label, "local_plugin_exact_mirror"


@lru_cache(maxsize=512)
def _candidate_package_cache_skill_dirs(skill_dir_name: str, cache_roots: tuple[str, ...]) -> tuple[str, ...]:
    normalized_name = str(skill_dir_name or "").strip()
    if not normalized_name:
        return ()

    candidates: list[str] = []
    for root_text in cache_roots:
        root = _safe_expand_path(root_text)
        if not root:
            continue
        try:
            if not root.exists():
                continue
        except Exception:
            continue
        try:
            for candidate in root.glob(f"**/skills/{normalized_name}"):
                if candidate.is_dir():
                    candidates.append(str(candidate))
        except Exception:
            continue
    return tuple(_dedupe_keep_order(candidates))


@lru_cache(maxsize=512)
def _candidate_package_cache_skill_documents(skill_dir_name: str, cache_roots: tuple[str, ...]) -> tuple[str, ...]:
    normalized_name = str(skill_dir_name or "").strip()
    if not normalized_name:
        return ()

    candidates: list[str] = []
    for root_text in cache_roots:
        root = _safe_expand_path(root_text)
        if not root:
            continue
        try:
            if not root.exists():
                continue
        except Exception:
            continue
        try:
            for candidate in root.glob(f"**/skills/{normalized_name}"):
                if candidate.is_dir() and not _ignore_cache_candidate_for_provenance(candidate):
                    candidates.append(str(candidate))
            for candidate in root.glob(f"**/agents/**/{normalized_name}.md"):
                if candidate.is_file() and not _ignore_cache_candidate_for_provenance(candidate):
                    candidates.append(str(candidate))
        except Exception:
            continue
    return tuple(_dedupe_keep_order(candidates))


def _mirror_package_details(candidate_path: str) -> tuple[str, str]:
    package_name = _package_name_from_path_heuristic(candidate_path)
    if package_name:
        return package_name, "cache_path_heuristic"
    package_name = _package_name_from_nearest_package_json(candidate_path)
    if package_name:
        return package_name, "cache_package_json"
    return "", ""


def _infer_npx_package_from_cache_similarity(source: dict[str, Any]) -> tuple[str, str]:
    source_path = str(source.get("source_path") or "").strip()
    if not source_path:
        return "", ""

    local_text = _canonical_skill_markdown_text_for_path(source_path)
    if not local_text:
        return "", ""

    skill_dir_name = ""
    source_dir = _safe_expand_path(source_path)
    if source_dir:
        skill_dir_name = str(source_dir.name or "").strip()
    if not skill_dir_name:
        member_names = _to_str_list(source.get("member_skill_preview", []))
        skill_dir_name = str(member_names[0] if member_names else source.get("display_name") or "").strip()
    if not skill_dir_name:
        return "", ""

    cache_roots = _configured_package_cache_roots()
    if not cache_roots:
        return "", ""

    normalized_source_path = _normalize_path_text(source_path)
    package_scores: dict[str, float] = {}
    package_strategies: dict[str, set[str]] = {}
    source_raw_text = _skill_markdown_text(source_path)
    for candidate in _candidate_package_cache_skill_documents(skill_dir_name, cache_roots):
        if _normalize_path_text(candidate) == normalized_source_path:
            continue
        package_name, _ = _mirror_package_details(candidate)
        if not package_name:
            continue
        candidate_text = _canonical_skill_markdown_text_for_path(candidate)
        if not candidate_text:
            continue
        ratio = SequenceMatcher(None, local_text, candidate_text).ratio()
        accepted_ratio = 0.0
        accepted_strategy = ""
        candidate_kind = "agent" if "/agents/" in _normalize_path_text(candidate).lower() else "skill"
        if ratio >= _CACHE_SIMILARITY_MATCH_THRESHOLD:
            accepted_ratio = ratio
            accepted_strategy = "cache_agent_similarity_match" if candidate_kind == "agent" else "cache_similarity_match"
        else:
            structured_ratio = _structured_skill_markdown_similarity(
                source_raw_text,
                _skill_markdown_text(candidate),
            )
            if structured_ratio >= _CACHE_STRUCTURED_SIMILARITY_MATCH_THRESHOLD:
                accepted_ratio = structured_ratio
                accepted_strategy = (
                    "cache_agent_structured_similarity_match"
                    if candidate_kind == "agent"
                    else "cache_structured_similarity_match"
                )
        if not accepted_strategy:
            continue
        previous = package_scores.get(package_name, 0.0)
        if accepted_ratio > previous:
            package_scores[package_name] = accepted_ratio
        package_strategies.setdefault(package_name, set()).add(accepted_strategy)

    if len(package_scores) != 1:
        return "", ""
    package_name = next(iter(package_scores.keys()))
    strategies = package_strategies.get(package_name, set())
    if "cache_similarity_match" in strategies:
        return package_name, "cache_similarity_match"
    if "cache_agent_similarity_match" in strategies:
        return package_name, "cache_agent_similarity_match"
    if "cache_structured_similarity_match" in strategies:
        return package_name, "cache_structured_similarity_match"
    if "cache_agent_structured_similarity_match" in strategies:
        return package_name, "cache_agent_structured_similarity_match"
    return package_name, "cache_similarity_match"


def _infer_npx_package_from_cache_mirror(source: dict[str, Any]) -> tuple[str, str]:
    source_path = str(source.get("source_path") or "").strip()
    if not source_path:
        return "", ""

    signature = _skill_markdown_signature(source_path)
    if not signature:
        return "", ""

    skill_dir_name = ""
    source_dir = _safe_expand_path(source_path)
    if source_dir:
        skill_dir_name = str(source_dir.name or "").strip()
    if not skill_dir_name:
        member_names = _to_str_list(source.get("member_skill_preview", []))
        skill_dir_name = str(member_names[0] if member_names else source.get("display_name") or "").strip()
    if not skill_dir_name:
        return "", ""

    cache_roots = _configured_package_cache_roots()
    if not cache_roots:
        return "", ""

    normalized_source_path = _normalize_path_text(source_path)
    package_matches: dict[str, set[str]] = {}
    for candidate in _candidate_package_cache_skill_dirs(skill_dir_name, cache_roots):
        if _normalize_path_text(candidate) == normalized_source_path:
            continue
        if _skill_markdown_signature(candidate) != signature:
            continue
        package_name, strategy = _mirror_package_details(candidate)
        if not package_name:
            continue
        package_matches.setdefault(package_name, set()).add(strategy)

    if len(package_matches) != 1:
        return _infer_npx_package_from_cache_similarity(source)

    package_name, strategies = next(iter(package_matches.items()))
    if "cache_path_heuristic" in strategies:
        return package_name, "cache_path_heuristic"
    if "cache_package_json" in strategies:
        return package_name, "cache_package_json"
    return _infer_npx_package_from_cache_similarity(source)


def _infer_npx_package(source: dict[str, Any]) -> tuple[str, str]:
    for candidate in (
        str(source.get("source_path") or "").strip(),
        str(source.get("locator") or "").strip(),
    ):
        package_name = _package_name_from_path_heuristic(candidate)
        if package_name:
            return package_name, "path_heuristic"
        package_name = _package_name_from_nearest_package_json(candidate)
        if package_name:
            return package_name, "package_json"
    package_name, strategy = _infer_npx_package_from_cache_mirror(source)
    if package_name:
        return package_name, strategy
    return "", ""


def derive_source_provenance_fields(source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("source_id") or source.get("id") or "").strip()
    display_name = str(source.get("display_name") or source_id).strip() or source_id
    source_kind = str(source.get("source_kind") or source.get("skill_kind") or "").strip().lower()
    locator = _first_non_empty(source.get("locator"), source.get("source_path"), source_id)
    source_path = str(source.get("source_path") or "").strip()
    source_subpath = _normalize_subpath_text(source.get("source_subpath"))
    management_hint = str(source.get("management_hint") or "").strip()
    registry_package_name = str(source.get("registry_package_name") or "").strip()
    registry_package_manager = str(source.get("registry_package_manager") or "").strip()
    aggregation_strategy = str(source.get("aggregation_strategy") or "").strip()
    collection_group_name = str(source.get("collection_group_name") or "").strip()
    install_manager = str(source.get("install_manager") or "").strip()
    managed_by = str(source.get("managed_by") or "").strip()

    origin_kind = str(source.get("provenance_origin_kind") or "").strip()
    origin_ref = str(source.get("provenance_origin_ref") or "").strip()
    origin_label = str(source.get("provenance_origin_label") or "").strip()
    root_kind = str(source.get("provenance_root_kind") or "").strip()
    root_path = str(source.get("provenance_root_path") or "").strip()
    package_name = str(source.get("provenance_package_name") or "").strip()
    package_manager = str(source.get("provenance_package_manager") or "").strip()
    package_strategy = str(source.get("provenance_package_strategy") or "").strip()
    confidence = str(source.get("provenance_confidence") or "").strip().lower()

    detected_root_kind, detected_root_path, detected_root_label = _detect_skills_root(source_path)
    if not root_kind:
        root_kind = detected_root_kind
    if not root_path:
        root_path = detected_root_path

    rule = _match_curated_rule(source)
    rule_registry_packages = _to_str_list(rule.get("registry_packages", [])) if rule else []
    rule_registry_package = str(rule_registry_packages[0] or "").strip() if rule_registry_packages else ""

    if aggregation_strategy in {"skill_lock_path", "skill_lock_source"} or (
        _looks_like_remote_locator(locator) and source_subpath and str(source.get("update_policy") or "").strip() == "source_sync"
    ):
        if not origin_kind:
            origin_kind = "skill_lock_source"
        if not origin_ref:
            origin_ref = locator
        if not origin_label:
            origin_label = collection_group_name or display_name
        if not package_manager:
            package_manager = install_manager or managed_by
        if not package_strategy:
            package_strategy = aggregation_strategy or ("skill_lock_path" if source_subpath else "skill_lock_source")
        if not confidence:
            confidence = "high"

    if not package_name:
        if registry_package_name:
            package_name = registry_package_name
            package_manager = package_manager or registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
            package_strategy = package_strategy or ("explicit_rule" if rule else "registry_package")
            origin_kind = origin_kind or "registry_package"
            origin_ref = origin_ref or registry_package_name
            if not origin_label:
                origin_label = str(rule.get("collection_group_name") or display_name) if rule else display_name
            confidence = confidence or "high"
        elif rule_registry_package:
            package_name = rule_registry_package
            package_manager = package_manager or str(rule.get("install_manager") or "") or _infer_manager_from_hint(management_hint, "npm")
            package_strategy = package_strategy or "explicit_rule"
            origin_kind = origin_kind or "registry_package"
            origin_ref = origin_ref or rule_registry_package
            origin_label = origin_label or str(rule.get("collection_group_name") or rule.get("install_unit_display_name") or display_name)
            confidence = confidence or "high"
        elif source_kind == "npx_single":
            inferred_package_name, inferred_strategy = _infer_npx_package(source)
            if inferred_package_name:
                package_name = inferred_package_name
                package_manager = package_manager or registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
                package_strategy = package_strategy or inferred_strategy
                origin_kind = origin_kind or "registry_package"
                origin_ref = origin_ref or inferred_package_name
                origin_label = origin_label or display_name
                confidence = confidence or (
                    "high"
                    if inferred_strategy in {
                        "package_json",
                        "cache_package_json",
                        "cache_path_heuristic",
                        "cache_similarity_match",
                        "cache_agent_similarity_match",
                        "cache_structured_similarity_match",
                        "cache_agent_structured_similarity_match",
                    }
                    else "medium"
                )
            else:
                plugin_origin_ref, plugin_origin_label, plugin_strategy = _infer_local_plugin_bundle(source)
                if plugin_origin_ref:
                    origin_kind = origin_kind or "local_plugin_bundle"
                    origin_ref = origin_ref or plugin_origin_ref
                    origin_label = origin_label or plugin_origin_label or display_name
                    package_strategy = package_strategy or plugin_strategy
                    confidence = confidence or "high"
                else:
                    documented_origin_ref, documented_origin_label, documented_strategy = _infer_documented_source_repo(source)
                    if documented_origin_ref:
                        origin_kind = origin_kind or "documented_source_repo"
                        origin_ref = origin_ref or documented_origin_ref
                        origin_label = origin_label or documented_origin_label or display_name
                        package_strategy = package_strategy or documented_strategy
                        confidence = confidence or "high"
                    else:
                        hinted_origin_ref, hinted_origin_label, hinted_strategy = _infer_curated_reference_repo_hint(source)
                        if hinted_origin_ref:
                            origin_kind = origin_kind or "catalog_source_repo"
                            origin_ref = origin_ref or hinted_origin_ref
                            origin_label = origin_label or hinted_origin_label or display_name
                            package_strategy = package_strategy or hinted_strategy
                            confidence = confidence or "medium"
                        else:
                            derivative_base_name, derivative_strategy = _infer_local_skill_derivative(source)
                            if derivative_base_name:
                                origin_kind = origin_kind or "local_skill_derivative"
                                origin_ref = origin_ref or derivative_base_name
                                origin_label = origin_label or derivative_base_name
                                package_strategy = package_strategy or derivative_strategy
                                confidence = confidence or "medium"

    if not rule and package_name:
        rule = _match_curated_rule(
            {
                **source,
                "registry_package_name": registry_package_name or package_name,
                "provenance_package_name": package_name,
            },
        )
        rule_registry_packages = _to_str_list(rule.get("registry_packages", [])) if rule else []
        rule_registry_package = str(rule_registry_packages[0] or "").strip() if rule_registry_packages else ""
    if rule and package_name and origin_kind == "registry_package":
        origin_label = str(
            rule.get("collection_group_name")
            or rule.get("install_unit_display_name")
            or package_name
            or origin_label
            or display_name
        )
        if not confidence:
            confidence = "high"

    if rule and not origin_kind:
        if package_name:
            origin_kind = "registry_package"
            origin_ref = origin_ref or package_name
        elif source_kind == "npx_bundle":
            origin_kind = "curated_bundle"
            origin_ref = origin_ref or str(rule.get("install_ref") or source_id or display_name)
        elif source_kind == "npx_single":
            origin_kind = "curated_bundle"
            origin_ref = origin_ref or str(rule.get("install_ref") or display_name)
        origin_label = origin_label or str(rule.get("collection_group_name") or rule.get("install_unit_display_name") or display_name)
        package_manager = package_manager or str(rule.get("install_manager") or "")
        package_strategy = package_strategy or ("explicit_rule" if package_name else "curated_override")
        confidence = confidence or "high"

    if source_kind == "manual_git":
        repo_label = _repo_label_from_locator(locator or source_path or source_id)
        origin_kind = origin_kind or "git_source"
        origin_ref = origin_ref or locator
        origin_label = origin_label or repo_label or collection_group_name or display_name
        package_strategy = package_strategy or ("source_locator_subpath" if source_subpath else "source_locator")
        confidence = confidence or "high"
    elif source_kind == "manual_local":
        root_label = _local_root_label(locator or source_path or source_id)
        origin_kind = origin_kind or "local_source"
        origin_ref = origin_ref or locator
        origin_label = origin_label or root_label or collection_group_name or display_name
        package_strategy = package_strategy or ("source_locator_subpath" if source_subpath else "source_locator")
        confidence = confidence or "medium"
    elif source_kind == "npx_bundle":
        origin_kind = origin_kind or ("registry_package" if package_name else "source_bundle")
        origin_ref = origin_ref or package_name or locator or source_id
        if not origin_label:
            origin_label = str(rule.get("collection_group_name") or display_name) if rule else display_name
        package_manager = package_manager or _infer_manager_from_hint(management_hint, install_manager or "npx")
        package_strategy = package_strategy or aggregation_strategy or ("explicit_rule" if rule else "source_bundle")
        confidence = confidence or ("high" if rule or package_name else "medium")
    elif source_kind == "npx_single":
        if not origin_kind and root_path:
            origin_kind = "skills_root"
            origin_ref = root_path
            origin_label = detected_root_label or origin_label or display_name
            package_strategy = package_strategy or "fallback_root"
            confidence = confidence or "low"
        else:
            origin_kind = origin_kind or "npx_single"
            origin_ref = origin_ref or locator or source_path or source_id
            origin_label = origin_label or display_name
            package_strategy = package_strategy or aggregation_strategy or "fallback_single"
            confidence = confidence or "low"
    else:
        origin_kind = origin_kind or (source_kind or "source")
        origin_ref = origin_ref or locator or source_id
        origin_label = origin_label or display_name
        confidence = confidence or "medium"

    if package_name and not package_manager:
        package_manager = registry_package_manager or _infer_manager_from_hint(management_hint, "npm")

    return {
        "provenance_origin_kind": origin_kind,
        "provenance_origin_ref": origin_ref,
        "provenance_origin_label": origin_label,
        "provenance_root_kind": root_kind,
        "provenance_root_path": root_path,
        "provenance_package_name": package_name,
        "provenance_package_manager": package_manager,
        "provenance_package_strategy": package_strategy,
        "provenance_confidence": confidence or "low",
    }


def build_provenance_summary(rows: list[dict[str, Any]] | dict[str, Any] | None) -> dict[str, Any]:
    normalized_rows = rows if isinstance(rows, list) else ([rows] if isinstance(rows, dict) else [])
    items = [item for item in normalized_rows if isinstance(item, dict)]

    resolved = 0
    partial = 0
    unresolved = 0
    origin_labels: list[str] = []
    origin_kinds: list[str] = []
    package_names: list[str] = []
    package_strategies: list[str] = []
    note_kind = ""

    for item in items:
        provenance = derive_source_provenance_fields(item)
        confidence = str(
            item.get("provenance_confidence")
            or provenance.get("provenance_confidence")
            or "low"
        ).strip().lower()
        if confidence == "high":
            resolved += 1
        elif confidence == "medium":
            partial += 1
        else:
            unresolved += 1

        origin_label = str(
            item.get("provenance_origin_label")
            or provenance.get("provenance_origin_label")
            or ""
        ).strip()
        origin_kind = str(
            item.get("provenance_origin_kind")
            or provenance.get("provenance_origin_kind")
            or ""
        ).strip()
        package_name = str(
            item.get("provenance_package_name")
            or provenance.get("provenance_package_name")
            or ""
        ).strip()
        package_strategy = str(
            item.get("provenance_package_strategy")
            or provenance.get("provenance_package_strategy")
            or ""
        ).strip()
        if origin_label and origin_label not in origin_labels:
            origin_labels.append(origin_label)
        if origin_kind and origin_kind not in origin_kinds:
            origin_kinds.append(origin_kind)
        if package_name and package_name not in package_names:
            package_names.append(package_name)
        if package_strategy and package_strategy not in package_strategies:
            package_strategies.append(package_strategy)

    if items and resolved == len(items):
        state = "resolved"
        aggregate_confidence = "high"
    elif resolved > 0 or partial > 0:
        state = "partial"
        aggregate_confidence = "medium"
    else:
        state = "unresolved"
        aggregate_confidence = "low"

    if unresolved == len(items) and origin_kinds and set(origin_kinds) == {"skills_root"}:
        note_kind = "legacy_root_only"
    elif state == "partial":
        note_kind = "mixed_resolution"
    elif state == "resolved" and package_names:
        note_kind = "package_resolved"

    return {
        "provenance_state": state,
        "provenance_resolved_count": resolved,
        "provenance_partial_count": partial,
        "provenance_unresolved_count": unresolved,
        "provenance_primary_origin_label": origin_labels[0] if origin_labels else "",
        "provenance_primary_origin_kind": origin_kinds[0] if origin_kinds else "",
        "provenance_primary_package_name": package_names[0] if package_names else "",
        "provenance_primary_package_strategy": package_strategies[0] if package_strategies else "",
        "provenance_confidence": aggregate_confidence,
        "provenance_note_kind": note_kind,
    }


def _legacy_family_collection_candidate(install_unit: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(install_unit, dict):
        return None
    if str(install_unit.get("install_unit_kind") or "").strip().lower() != "synthetic_single":
        return None
    if str(install_unit.get("collection_group_kind") or "").strip().lower() != "install_unit":
        return None
    if str(install_unit.get("registry_package_name") or "").strip():
        return None
    if str(install_unit.get("provenance_primary_origin_kind") or "").strip().lower() != "skills_root":
        return None
    if str(install_unit.get("provenance_note_kind") or "").strip().lower() != "legacy_root_only":
        return None

    member_names = _to_str_list(install_unit.get("member_skill_preview", []))
    token = _legacy_family_token(member_names[0] if member_names else install_unit.get("display_name"))
    if not token:
        return None

    scope = str(install_unit.get("scope") or "").strip().lower() or "mixed"
    origin_label = str(install_unit.get("provenance_primary_origin_label") or "").strip() or "skills_root"
    root_slug = _slug(origin_label, default="skills_root")
    collection_group_id = f"collection:legacy_family_{root_slug}_{token}_{_slug(scope, default='mixed')}"
    collection_group_name = _legacy_family_label(token)
    if not collection_group_name:
        return None
    return {
        "collection_group_id": collection_group_id,
        "collection_group_name": collection_group_name,
        "collection_group_kind": "legacy_family",
    }


def _apply_legacy_family_collection_groups(install_unit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_candidates: dict[str, dict[str, Any]] = {}
    for index, install_unit in enumerate(install_unit_rows):
        candidate = _legacy_family_collection_candidate(install_unit)
        if not candidate:
            continue
        group = grouped_candidates.setdefault(
            candidate["collection_group_id"],
            {
                "candidate": candidate,
                "indexes": [],
            },
        )
        group["indexes"].append(index)

    for group in grouped_candidates.values():
        indexes = group["indexes"]
        if len(indexes) < 2:
            continue
        candidate = group["candidate"]
        for index in indexes:
            install_unit_rows[index]["collection_group_id"] = candidate["collection_group_id"]
            install_unit_rows[index]["collection_group_name"] = candidate["collection_group_name"]
            install_unit_rows[index]["collection_group_kind"] = candidate["collection_group_kind"]
    return install_unit_rows


def derive_source_aggregation_fields(source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("source_id") or source.get("id") or "").strip()
    display_name = str(source.get("display_name") or source_id).strip() or source_id
    source_kind = str(source.get("source_kind") or source.get("skill_kind") or "").strip().lower()
    locator = _first_non_empty(source.get("locator"), source.get("source_path"), source_id)
    source_subpath = _normalize_subpath_text(source.get("source_subpath"))
    management_hint = str(source.get("management_hint") or "").strip()
    registry_package_name = str(source.get("registry_package_name") or "").strip()
    registry_package_manager = str(source.get("registry_package_manager") or "").strip()
    provenance = derive_source_provenance_fields(source)
    provenance_package_name = str(source.get("provenance_package_name") or provenance.get("provenance_package_name") or "").strip()
    provenance_package_manager = str(
        source.get("provenance_package_manager")
        or provenance.get("provenance_package_manager")
        or ""
    ).strip()
    provenance_origin_kind = str(
        source.get("provenance_origin_kind")
        or provenance.get("provenance_origin_kind")
        or ""
    ).strip()
    provenance_origin_ref = str(
        source.get("provenance_origin_ref")
        or provenance.get("provenance_origin_ref")
        or ""
    ).strip()
    provenance_origin_label = str(
        source.get("provenance_origin_label")
        or provenance.get("provenance_origin_label")
        or ""
    ).strip()
    provenance_package_strategy = str(
        source.get("provenance_package_strategy")
        or provenance.get("provenance_package_strategy")
        or ""
    ).strip()

    existing_install_unit_id = str(source.get("install_unit_id") or "").strip()
    existing_install_unit_kind = str(source.get("install_unit_kind") or "").strip()
    existing_install_ref = str(source.get("install_ref") or "").strip()
    existing_install_manager = str(source.get("install_manager") or "").strip()
    existing_install_display_name = str(source.get("install_unit_display_name") or "").strip()
    existing_strategy = str(source.get("aggregation_strategy") or "").strip()

    rule = _match_curated_rule(
        {
            **source,
            "registry_package_name": registry_package_name or provenance_package_name,
            "provenance_package_name": provenance_package_name,
        },
    )
    install_unit_id = existing_install_unit_id
    install_unit_kind = existing_install_unit_kind
    install_ref = existing_install_ref
    install_manager = existing_install_manager
    install_unit_display_name = existing_install_display_name
    aggregation_strategy = existing_strategy

    if not install_unit_id:
        if provenance_package_name:
            install_unit_id = f"npm:{provenance_package_name}"
            install_unit_kind = "npm_package"
            install_ref = provenance_package_name
            install_manager = provenance_package_manager or registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
            install_unit_display_name = (
                str(rule.get("install_unit_display_name") or provenance_package_name or display_name)
                if rule
                else provenance_package_name or display_name
            )
            aggregation_strategy = provenance_package_strategy or ("explicit_rule" if rule else "registry_package")
        elif source_kind == "manual_git":
            repo_label = _repo_label_from_locator(locator or source_id) or display_name
            install_ref = _join_locator_with_subpath(locator or source_id, source_subpath)
            install_unit_id = f"git:{install_ref}"
            install_unit_kind = "git_source"
            install_ref = install_ref
            install_manager = "git"
            install_unit_display_name = (
                f"{repo_label} :: {source_subpath}" if source_subpath else repo_label
            )
            aggregation_strategy = "source_locator_subpath" if source_subpath else "source_locator"
        elif source_kind == "manual_local":
            root_label = _local_root_label(locator or source_id) or display_name
            install_ref = _join_locator_with_subpath(locator or source_id, source_subpath)
            install_unit_id = f"local:{install_ref}"
            install_unit_kind = "local_source"
            install_ref = install_ref
            install_manager = "filesystem"
            install_unit_display_name = (
                f"{root_label} :: {source_subpath}" if source_subpath else root_label
            )
            aggregation_strategy = "source_locator_subpath" if source_subpath else "source_locator"
        elif source_kind == "npx_bundle":
            if rule:
                install_unit_id = str(rule.get("install_unit_id") or f"bundle:{source_id}")
                install_unit_kind = str(rule.get("install_unit_kind") or "curated_npx_pack")
                install_ref = str(rule.get("install_ref") or locator or source_id)
                install_manager = str(rule.get("install_manager") or _infer_manager_from_hint(management_hint, "npx"))
                install_unit_display_name = str(rule.get("install_unit_display_name") or display_name)
                aggregation_strategy = "explicit_rule"
            else:
                install_unit_id = f"bundle:{source_id}"
                install_unit_kind = "npx_bundle"
                install_ref = locator or source_id
                install_manager = _infer_manager_from_hint(management_hint, "npx")
                install_unit_display_name = display_name
                aggregation_strategy = "source_bundle"
        elif source_kind == "npx_single":
            inferred_package_name, inferred_strategy = _infer_npx_package(source)
            if inferred_package_name:
                install_unit_id = f"npm:{inferred_package_name}"
                install_unit_kind = "npm_package"
                install_ref = inferred_package_name
                install_manager = registry_package_manager or _infer_manager_from_hint(management_hint, "npm")
                install_unit_display_name = display_name
                aggregation_strategy = inferred_strategy
            elif provenance_origin_kind == "local_plugin_bundle" and provenance_origin_ref:
                install_unit_id = f"plugin:{provenance_origin_ref}"
                install_unit_kind = "local_plugin_bundle"
                install_ref = provenance_origin_ref
                install_manager = "plugin"
                install_unit_display_name = provenance_origin_label or display_name
                aggregation_strategy = provenance_package_strategy or "local_plugin_exact_mirror"
            elif provenance_origin_kind == "documented_source_repo" and provenance_origin_ref:
                repo_locator, repo_subpath = _split_locator_with_subpath(provenance_origin_ref)
                repo_label = _repo_label_from_locator(repo_locator or provenance_origin_ref) or display_name
                install_unit_id = f"repo:{provenance_origin_ref}"
                install_unit_kind = "documented_source_repo"
                install_ref = provenance_origin_ref
                install_manager = "manual"
                install_unit_display_name = (
                    f"{repo_label} :: {repo_subpath}" if repo_subpath else repo_label
                )
                aggregation_strategy = provenance_package_strategy or "documented_source_repo"
            elif provenance_origin_kind == "catalog_source_repo" and provenance_origin_ref:
                repo_locator, repo_subpath = _split_locator_with_subpath(provenance_origin_ref)
                repo_label = _repo_label_from_locator(repo_locator or provenance_origin_ref) or display_name
                install_unit_id = f"repo:{provenance_origin_ref}"
                install_unit_kind = "catalog_source_repo"
                install_ref = provenance_origin_ref
                install_manager = "manual"
                install_unit_display_name = (
                    f"{repo_label} :: {repo_subpath}" if repo_subpath else repo_label
                )
                aggregation_strategy = provenance_package_strategy or "catalog_reference_hint"
            elif provenance_origin_kind == "local_skill_derivative" and provenance_origin_ref:
                install_unit_id = f"derived:{source_id}"
                install_unit_kind = "local_skill_derivative"
                install_ref = display_name or source_id
                install_manager = "manual"
                install_unit_display_name = display_name
                aggregation_strategy = provenance_package_strategy or "embedded_local_derivative_notice"
            elif rule:
                install_unit_id = str(rule.get("install_unit_id") or f"curated:{_slug(display_name, default='pack')}")
                install_unit_kind = str(rule.get("install_unit_kind") or "curated_npx_pack")
                install_ref = str(rule.get("install_ref") or display_name)
                install_manager = str(rule.get("install_manager") or _infer_manager_from_hint(management_hint, "npx"))
                install_unit_display_name = str(rule.get("install_unit_display_name") or display_name)
                aggregation_strategy = "curated_override"
            else:
                install_unit_id = f"synthetic_single:{source_id}"
                install_unit_kind = "synthetic_single"
                install_ref = source_id or display_name
                install_manager = _infer_manager_from_hint(management_hint, "npx")
                install_unit_display_name = display_name
                aggregation_strategy = "fallback_single"
        else:
            install_unit_id = f"source:{source_id}"
            install_unit_kind = source_kind or "source"
            install_ref = locator or source_id
            install_manager = _infer_manager_from_hint(management_hint, "")
            install_unit_display_name = display_name
            aggregation_strategy = "source_identity"

    collection_group_id = str(source.get("collection_group_id") or "").strip()
    collection_group_name = str(source.get("collection_group_name") or "").strip()
    collection_group_kind = str(source.get("collection_group_kind") or "").strip()
    if not collection_group_id:
        if rule:
            collection_group_id = str(rule.get("collection_group_id") or f"collection:{_slug(install_unit_display_name, default='group')}")
            collection_group_name = str(rule.get("collection_group_name") or install_unit_display_name or display_name)
            collection_group_kind = str(rule.get("collection_group_kind") or "curated")
        elif provenance_package_name:
            collection_group_id = f"collection:package_{_slug(provenance_package_name, default='package')}"
            collection_group_name = install_unit_display_name or provenance_package_name or display_name
            collection_group_kind = "package"
        elif provenance_origin_kind == "local_plugin_bundle" and provenance_origin_ref:
            collection_group_id = f"collection:plugin_{_slug(provenance_origin_ref, default='plugin')}"
            collection_group_name = install_unit_display_name or provenance_origin_label or display_name
            collection_group_kind = "plugin_bundle"
        elif provenance_origin_kind == "documented_source_repo" and provenance_origin_ref:
            repo_locator, _ = _split_locator_with_subpath(provenance_origin_ref)
            collection_group_id, collection_group_name, collection_group_kind = _manual_source_collection_group(
                repo_locator or provenance_origin_ref,
                "manual_git",
            )
        elif provenance_origin_kind == "catalog_source_repo" and provenance_origin_ref:
            repo_locator, _ = _split_locator_with_subpath(provenance_origin_ref)
            collection_group_id, collection_group_name, collection_group_kind = _manual_source_collection_group(
                repo_locator or provenance_origin_ref,
                "manual_git",
            )
        elif provenance_origin_kind == "local_skill_derivative" and provenance_origin_ref:
            collection_group_id, collection_group_name, collection_group_kind = _resolve_local_skill_derivative_collection(
                source,
                provenance_origin_ref,
            )
        elif source_kind in {"manual_git", "manual_local"}:
            collection_group_id, collection_group_name, collection_group_kind = _manual_source_collection_group(
                locator or source_id,
                source_kind,
            )
        else:
            group_name = install_unit_display_name or display_name or install_ref or source_id
            collection_group_id = f"collection:{_slug(group_name, default='group')}"
            collection_group_name = group_name
            collection_group_kind = "install_unit"

    return {
        "install_unit_id": install_unit_id,
        "install_unit_kind": install_unit_kind,
        "install_ref": install_ref,
        "install_manager": install_manager,
        "install_unit_display_name": install_unit_display_name or display_name,
        "aggregation_strategy": aggregation_strategy or "fallback_single",
        "collection_group_id": collection_group_id,
        "collection_group_name": collection_group_name or install_unit_display_name or display_name,
        "collection_group_kind": collection_group_kind or "install_unit",
    }


def enrich_source_aggregation(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **source,
        **build_provenance_summary(source),
        **derive_source_aggregation_fields(source),
    }


def _aggregate_status(values: list[str], ranks: dict[str, int], default: str) -> str:
    best_value = default
    best_rank = -1
    for value in values:
        key = str(value or "").strip().lower()
        rank = ranks.get(key, -1)
        if rank > best_rank:
            best_rank = rank
            best_value = key or default
    return best_value


def _build_member_preview(values: list[str], limit: int = 6) -> tuple[list[str], int]:
    preview = _dedupe_keep_order([str(item or "").strip() for item in values if str(item or "").strip()])
    kept = preview[:limit]
    overflow = max(0, len(preview) - len(kept))
    return kept, overflow


def _build_deployed_target_map(deploy_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in deploy_rows:
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "").strip()
        if not target_id:
            continue
        for source_id in _to_str_list(row.get("selected_source_ids", [])):
            result.setdefault(source_id, []).append(target_id)
    return {
        source_id: _dedupe_keep_order(target_ids)
        for source_id, target_ids in result.items()
    }


def build_install_unit_rows(source_rows: list[dict[str, Any]], deploy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deployed_target_map = _build_deployed_target_map(deploy_rows)
    grouped: dict[str, dict[str, Any]] = {}

    for raw_source in source_rows:
        if not isinstance(raw_source, dict):
            continue
        source = enrich_source_aggregation(raw_source)
        install_unit_id = str(source.get("install_unit_id") or "").strip()
        if not install_unit_id:
            continue
        row = grouped.setdefault(
            install_unit_id,
            {
                "install_unit_id": install_unit_id,
                "install_unit_kind": str(source.get("install_unit_kind") or ""),
                "display_name": str(source.get("install_unit_display_name") or source.get("display_name") or install_unit_id),
                "install_ref": str(source.get("install_ref") or ""),
                "locator_values": [],
                "source_path_values": [],
                "source_subpaths": [],
                "install_manager": str(source.get("install_manager") or ""),
                "aggregation_strategy": str(source.get("aggregation_strategy") or ""),
                "collection_group_id": str(source.get("collection_group_id") or ""),
                "collection_group_name": str(source.get("collection_group_name") or ""),
                "collection_group_kind": str(source.get("collection_group_kind") or ""),
                "registry_package_name": str(source.get("registry_package_name") or source.get("provenance_package_name") or ""),
                "registry_package_manager": str(source.get("registry_package_manager") or source.get("provenance_package_manager") or ""),
                "management_hint": str(source.get("management_hint") or ""),
                "managed_by": str(source.get("managed_by") or ""),
                "update_policy": str(source.get("update_policy") or ""),
                "source_ids": [],
                "scopes": [],
                "member_names": [],
                "member_total": 0,
                "compatible_software_ids": [],
                "compatible_software_families": [],
                "status_values": [],
                "freshness_values": [],
                "sync_status_values": [],
                "deployed_target_ids": [],
            },
        )
        source_id = str(source.get("source_id") or source.get("id") or "").strip()
        if source_id:
            row["source_ids"].append(source_id)
            row["deployed_target_ids"].extend(deployed_target_map.get(source_id, []))
        row["scopes"].append(str(source.get("source_scope") or "global"))
        row["member_names"].extend(_to_str_list(source.get("member_skill_preview", [])) or [str(source.get("display_name") or source_id)])
        row["member_total"] += max(1, int(source.get("member_count", 1) or 1))
        row["compatible_software_ids"].extend(_to_str_list(source.get("compatible_software_ids", [])))
        row["compatible_software_families"].extend(_to_str_list(source.get("compatible_software_families", [])))
        row["status_values"].append(str(source.get("status") or ""))
        row["freshness_values"].append(str(source.get("freshness_status") or ""))
        row["sync_status_values"].append(str(source.get("sync_status") or ""))
        row["locator_values"].append(str(source.get("locator") or "").strip())
        row["source_path_values"].append(str(source.get("source_path") or "").strip())
        row["source_subpaths"].append(str(source.get("source_subpath") or "").strip())
        if not row["registry_package_name"]:
            row["registry_package_name"] = str(source.get("registry_package_name") or source.get("provenance_package_name") or "")
        if not row["registry_package_manager"]:
            row["registry_package_manager"] = str(source.get("registry_package_manager") or source.get("provenance_package_manager") or "")
        if not row["management_hint"]:
            row["management_hint"] = str(source.get("management_hint") or "")
        if not row["managed_by"]:
            row["managed_by"] = str(source.get("managed_by") or "")
        if not row["update_policy"]:
            row["update_policy"] = str(source.get("update_policy") or "")

    result: list[dict[str, Any]] = []
    for row in grouped.values():
        source_ids = sorted(_dedupe_keep_order(row.pop("source_ids")))
        member_preview, member_overflow = _build_member_preview(row.pop("member_names"))
        deployed_target_ids = _dedupe_keep_order(row.pop("deployed_target_ids"))
        compatible_software_ids = _dedupe_keep_order(row.pop("compatible_software_ids"))
        compatible_software_families = _dedupe_keep_order(row.pop("compatible_software_families"))
        scopes = _dedupe_keep_order(row.pop("scopes"))
        locators = _dedupe_keep_order(row.pop("locator_values"))
        source_paths = _dedupe_keep_order(row.pop("source_path_values"))
        source_subpaths = _dedupe_keep_order(row.pop("source_subpaths"))
        member_total = int(row.pop("member_total") or 0)
        status = _aggregate_status(row.pop("status_values"), _SOURCE_STATUS_RANK, "ready")
        freshness_status = _aggregate_status(row.pop("freshness_values"), _FRESHNESS_RANK, "missing")
        sync_status = _aggregate_status(row.pop("sync_status_values"), _SYNC_STATUS_RANK, "")

        result.append(
            {
                **row,
                "source_ids": source_ids,
                "source_count": len(source_ids),
                "primary_source_id": source_ids[0] if len(source_ids) == 1 else "",
                "scope": scopes[0] if len(scopes) == 1 else "mixed",
                "scopes": scopes,
                "member_count": member_total or max(1, len(member_preview) + member_overflow),
                "member_skill_preview": member_preview,
                "member_skill_overflow": member_overflow,
                "locator": locators[0] if len(locators) == 1 else "",
                "source_path": source_paths[0] if len(source_paths) == 1 else "",
                "source_subpath": source_subpaths[0] if len(source_subpaths) == 1 else "",
                "source_subpaths": source_subpaths,
                "compatible_software_ids": compatible_software_ids,
                "compatible_software_families": compatible_software_families,
                "status": status,
                "freshness_status": freshness_status,
                "sync_status": sync_status,
                "deployed_target_ids": deployed_target_ids,
                "deployed_target_count": len(deployed_target_ids),
                **build_provenance_summary(
                    [
                        raw_source
                        for raw_source in source_rows
                        if isinstance(raw_source, dict)
                        and str(enrich_source_aggregation(raw_source).get("install_unit_id") or "").strip() == str(row.get("install_unit_id") or "").strip()
                    ],
                ),
            },
        )

    result = _apply_legacy_family_collection_groups(result)
    result.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("install_unit_id", "")).lower()))
    return result


def build_collection_group_rows(install_unit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for install_unit in install_unit_rows:
        if not isinstance(install_unit, dict):
            continue
        collection_group_id = str(install_unit.get("collection_group_id") or "").strip()
        if not collection_group_id:
            continue
        row = grouped.setdefault(
            collection_group_id,
            {
                "collection_group_id": collection_group_id,
                "display_name": str(install_unit.get("collection_group_name") or install_unit.get("display_name") or collection_group_id),
                "collection_group_name": str(install_unit.get("collection_group_name") or install_unit.get("display_name") or collection_group_id),
                "collection_group_kind": str(install_unit.get("collection_group_kind") or ""),
                "install_unit_ids": [],
                "source_ids": [],
                "member_names": [],
                "locator_values": [],
                "source_path_values": [],
                "source_subpaths": [],
                "member_total": 0,
                "compatible_software_ids": [],
                "compatible_software_families": [],
                "status_values": [],
                "freshness_values": [],
                "sync_status_values": [],
                "deployed_target_ids": [],
                "management_hint": "",
                "managed_by": "",
                "update_policy": "",
                "registry_package_name": str(install_unit.get("registry_package_name") or install_unit.get("provenance_primary_package_name") or ""),
                "registry_package_manager": str(install_unit.get("registry_package_manager") or ""),
            },
        )
        row["install_unit_ids"].append(str(install_unit.get("install_unit_id") or ""))
        row["source_ids"].extend(_to_str_list(install_unit.get("source_ids", [])))
        row["member_names"].extend(_to_str_list(install_unit.get("member_skill_preview", [])))
        row["member_total"] += max(1, int(install_unit.get("member_count", 1) or 1))
        row["compatible_software_ids"].extend(_to_str_list(install_unit.get("compatible_software_ids", [])))
        row["compatible_software_families"].extend(_to_str_list(install_unit.get("compatible_software_families", [])))
        row["status_values"].append(str(install_unit.get("status") or ""))
        row["freshness_values"].append(str(install_unit.get("freshness_status") or ""))
        row["sync_status_values"].append(str(install_unit.get("sync_status") or ""))
        row["locator_values"].append(str(install_unit.get("locator") or "").strip())
        row["source_path_values"].append(str(install_unit.get("source_path") or "").strip())
        row["source_subpaths"].extend(_to_str_list(install_unit.get("source_subpaths", [])) or [str(install_unit.get("source_subpath") or "").strip()])
        row["deployed_target_ids"].extend(_to_str_list(install_unit.get("deployed_target_ids", [])))
        if not row["management_hint"]:
            row["management_hint"] = str(install_unit.get("management_hint") or "")
        if not row["managed_by"]:
            row["managed_by"] = str(install_unit.get("managed_by") or "")
        if not row["update_policy"]:
            row["update_policy"] = str(install_unit.get("update_policy") or "")
        if not row["registry_package_name"]:
            row["registry_package_name"] = str(install_unit.get("registry_package_name") or install_unit.get("provenance_primary_package_name") or "")
        if not row["registry_package_manager"]:
            row["registry_package_manager"] = str(install_unit.get("registry_package_manager") or "")

    result: list[dict[str, Any]] = []
    for row in grouped.values():
        source_ids = sorted(_dedupe_keep_order(row.pop("source_ids")))
        install_unit_ids = _dedupe_keep_order(row.pop("install_unit_ids"))
        member_preview, member_overflow = _build_member_preview(row.pop("member_names"))
        deployed_target_ids = _dedupe_keep_order(row.pop("deployed_target_ids"))
        compatible_software_ids = _dedupe_keep_order(row.pop("compatible_software_ids"))
        compatible_software_families = _dedupe_keep_order(row.pop("compatible_software_families"))
        locators = _dedupe_keep_order(row.pop("locator_values"))
        source_paths = _dedupe_keep_order(row.pop("source_path_values"))
        source_subpaths = _dedupe_keep_order(row.pop("source_subpaths"))
        member_total = int(row.pop("member_total") or 0)
        status = _aggregate_status(row.pop("status_values"), _SOURCE_STATUS_RANK, "ready")
        freshness_status = _aggregate_status(row.pop("freshness_values"), _FRESHNESS_RANK, "missing")
        sync_status = _aggregate_status(row.pop("sync_status_values"), _SYNC_STATUS_RANK, "")

        result.append(
            {
                **row,
                "install_unit_ids": install_unit_ids,
                "install_unit_count": len(install_unit_ids),
                "source_ids": source_ids,
                "source_count": len(source_ids),
                "primary_source_id": source_ids[0] if len(source_ids) == 1 else "",
                "member_count": member_total or max(1, len(member_preview) + member_overflow),
                "member_skill_preview": member_preview,
                "member_skill_overflow": member_overflow,
                "locator": locators[0] if len(locators) == 1 else "",
                "source_path": source_paths[0] if len(source_paths) == 1 else "",
                "source_subpath": source_subpaths[0] if len(source_subpaths) == 1 else "",
                "source_subpaths": source_subpaths,
                "compatible_software_ids": compatible_software_ids,
                "compatible_software_families": compatible_software_families,
                "status": status,
                "freshness_status": freshness_status,
                "sync_status": sync_status,
                "deployed_target_ids": deployed_target_ids,
                "deployed_target_count": len(deployed_target_ids),
                **build_provenance_summary(
                    [
                        install_unit
                        for install_unit in install_unit_rows
                        if isinstance(install_unit, dict)
                        and str(install_unit.get("collection_group_id") or "").strip() == str(row.get("collection_group_id") or "").strip()
                    ],
                ),
            },
        )

    result.sort(key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("collection_group_id", "")).lower()))
    return result


def build_compatible_aggregate_rows_by_software(
    aggregate_rows: list[dict[str, Any]],
    compatible_source_rows_by_software: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for software_id, source_rows in compatible_source_rows_by_software.items():
        compatible_source_ids = {
            str(item.get("source_id") or item.get("id") or "").strip()
            for item in source_rows
            if isinstance(item, dict) and str(item.get("source_id") or item.get("id") or "").strip()
        }
        result[str(software_id)] = [
            dict(item)
            for item in aggregate_rows
            if compatible_source_ids.intersection(
                {
                    str(source_id or "").strip()
                    for source_id in _to_str_list(item.get("source_ids", []))
                    if str(source_id or "").strip()
                },
            )
        ]
    return result
