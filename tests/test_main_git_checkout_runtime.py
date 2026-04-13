from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import types as pytypes
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_astrbot_modules() -> None:
    required_modules = [
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.star",
        "astrbot.api.message_components",
        "astrbot.core",
        "astrbot.core.utils",
        "astrbot.core.utils.astrbot_path",
        "astrbot.core.utils.version_comparator",
    ]
    if all(module_name in sys.modules for module_name in required_modules):
        return

    astrbot_pkg = types.ModuleType("astrbot")
    api_pkg = types.ModuleType("astrbot.api")
    event_pkg = types.ModuleType("astrbot.api.event")
    star_pkg = types.ModuleType("astrbot.api.star")
    message_components_pkg = types.ModuleType("astrbot.api.message_components")
    core_pkg = types.ModuleType("astrbot.core")
    utils_pkg = types.ModuleType("astrbot.core.utils")
    astrbot_path_pkg = types.ModuleType("astrbot.core.utils.astrbot_path")
    version_comparator_pkg = types.ModuleType("astrbot.core.utils.version_comparator")

    class _FakeLogger:
        def info(self, *_args, **_kwargs) -> None:
            return None

        def warning(self, *_args, **_kwargs) -> None:
            return None

        def error(self, *_args, **_kwargs) -> None:
            return None

    class _FakeCommandGroup:
        def __init__(self, func):
            self.func = func

        def __call__(self, *args, **kwargs):
            return self.func(*args, **kwargs)

        def command(self, *_args, **_kwargs):
            def _decorator(func):
                return func

            return _decorator

    class _FakeFilter:
        class PermissionType:
            ADMIN = "admin"

        @staticmethod
        def command_group(*_args, **_kwargs):
            def _decorator(func):
                return _FakeCommandGroup(func)

            return _decorator

        @staticmethod
        def permission_type(*_args, **_kwargs):
            def _decorator(func):
                return func

            return _decorator

    class _FakeStar:
        def __init__(self, context=None):
            self.context = context

    class _FakeContext:
        pass

    class _FakeMessageChain(list):
        pass

    class _FakeAstrMessageEvent:
        def plain_result(self, text: str) -> str:
            return text

    class _FakePlain:
        def __init__(self, text: str = "") -> None:
            self.text = text

    class _FakeVersionComparator:
        @staticmethod
        def compare_version(a: str, b: str) -> int:
            if a == b:
                return 0
            return -1 if str(a) < str(b) else 1

    api_pkg.AstrBotConfig = dict
    api_pkg.logger = _FakeLogger()
    event_pkg.AstrMessageEvent = _FakeAstrMessageEvent
    event_pkg.MessageChain = _FakeMessageChain
    event_pkg.filter = _FakeFilter
    star_pkg.Context = _FakeContext
    star_pkg.Star = _FakeStar
    message_components_pkg.Plain = _FakePlain
    astrbot_path_pkg.get_astrbot_data_path = lambda: "/tmp/astrbot"
    version_comparator_pkg.VersionComparator = _FakeVersionComparator

    sys.modules["astrbot"] = astrbot_pkg
    sys.modules["astrbot.api"] = api_pkg
    sys.modules["astrbot.api.event"] = event_pkg
    sys.modules["astrbot.api.star"] = star_pkg
    sys.modules["astrbot.api.message_components"] = message_components_pkg
    sys.modules["astrbot.core"] = core_pkg
    sys.modules["astrbot.core.utils"] = utils_pkg
    sys.modules["astrbot.core.utils.astrbot_path"] = astrbot_path_pkg
    sys.modules["astrbot.core.utils.version_comparator"] = version_comparator_pkg

    astrbot_pkg.api = api_pkg
    astrbot_pkg.core = core_pkg
    api_pkg.event = event_pkg
    api_pkg.star = star_pkg
    api_pkg.message_components = message_components_pkg
    core_pkg.utils = utils_pkg
    utils_pkg.astrbot_path = astrbot_path_pkg
    utils_pkg.version_comparator = version_comparator_pkg


def _load_main_module():
    _install_fake_astrbot_modules()

    package_name = "onesync_testpkg"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(REPO_ROOT)]
        sys.modules[package_name] = package

    module_name = f"{package_name}.main"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / "main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load main.py test module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


MAIN_MODULE = _load_main_module()
OneSyncPlugin = MAIN_MODULE.OneSyncPlugin


class OneSyncPluginGitCheckoutTests(unittest.TestCase):
    def test_resolve_preferred_git_remote_locator_prefers_faster_candidate(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        plugin._candidate_git_clone_locators = lambda _locator: [
            "https://github.com/vercel-labs/skills.git",
            "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git",
        ]
        plugin._probe_git_remote_candidate = lambda locator, timeout_s=20: {
            "locator": locator,
            "ok": True,
            "message": "",
            "duration_ms": 420 if locator.startswith("https://github.com/") else 120,
        }

        selected = OneSyncPlugin._resolve_preferred_git_remote_locator(
            plugin,
            "https://github.com/vercel-labs/skills.git",
            current_origin="https://github.com/vercel-labs/skills.git",
        )

        self.assertEqual(
            "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git",
            selected,
        )

    def test_resolve_preferred_git_remote_locator_keeps_current_when_latency_gap_is_small(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        plugin._candidate_git_clone_locators = lambda _locator: [
            "https://github.com/vercel-labs/skills.git",
            "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git",
        ]
        plugin._probe_git_remote_candidate = lambda locator, timeout_s=20: {
            "locator": locator,
            "ok": True,
            "message": "",
            "duration_ms": 190 if locator.startswith("https://github.com/") else 120,
        }

        selected = OneSyncPlugin._resolve_preferred_git_remote_locator(
            plugin,
            "https://github.com/vercel-labs/skills.git",
            current_origin="https://github.com/vercel-labs/skills.git",
        )

        self.assertEqual("https://github.com/vercel-labs/skills.git", selected)

    def test_align_managed_git_checkout_remote_uses_reachable_candidate(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        commands: list[tuple[tuple[str, ...], str | None]] = []

        def _fake_run_git_probe(
            args: list[str],
            *,
            cwd: str | Path | None = None,
            timeout_s: int = 30,
        ) -> tuple[bool, str]:
            commands.append((tuple(args), str(cwd) if cwd else None))
            if args == ["ls-remote", "https://github.com/vercel-labs/skills.git", "HEAD"]:
                return False, "github timeout"
            if args == ["ls-remote", "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git", "HEAD"]:
                return True, "ok"
            if args == ["remote", "set-url", "origin", "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git"]:
                return True, ""
            return False, f"unexpected command: {args}"

        plugin._run_git_probe = _fake_run_git_probe
        plugin._path_is_git_worktree = lambda _path: True
        plugin._git_remote_origin_url = lambda _path: "https://github.com/vercel-labs/skills.git"

        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_path = str(Path(tmpdir) / "managed-checkout")
            Path(checkout_path).mkdir(parents=True, exist_ok=True)
            result = OneSyncPlugin._align_managed_git_checkout_remote(
                plugin,
                checkout_path,
                "https://github.com/vercel-labs/skills.git",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git",
            result["remote_locator"],
        )
        self.assertIn(
            (
                (
                    "remote",
                    "set-url",
                    "origin",
                    "https://edgeone.gh-proxy.com/https://github.com/vercel-labs/skills.git",
                ),
                checkout_path,
            ),
            commands,
        )

    def test_augment_source_row_aligns_existing_managed_checkout(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        align_calls: list[tuple[str, str]] = []
        plugin._path_is_git_worktree = lambda _path: True

        def _fake_align(checkout_path: str | Path, locator: str, *, preferred_locator: str = "") -> dict:
            _ = preferred_locator
            align_calls.append((str(checkout_path), locator))
            return {
                "ok": True,
                "message": "",
                "error_code": "",
                "remote_locator": locator,
            }

        plugin._align_managed_git_checkout_remote = _fake_align

        row = {
            "source_id": "find_skills",
            "display_name": "find-skills",
            "git_checkout_path": "/tmp/managed-checkout",
            "git_checkout_managed": True,
            "install_manager": "github",
            "locator": "https://github.com/vercel-labs/skills.git",
        }

        result = OneSyncPlugin._augment_source_row_with_git_checkout(plugin, row)

        self.assertEqual("/tmp/managed-checkout", result["git_checkout_path"])
        self.assertEqual("", result["git_checkout_error"])
        self.assertEqual(
            [("/tmp/managed-checkout", "https://github.com/vercel-labs/skills.git")],
            align_calls,
        )

    def test_update_saved_registry_source_metadata_preserves_sync_fields_without_sync_payload(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-11T00:00:00+00:00",
            "sources": [
                {
                    "source_id": "find_skills",
                    "display_name": "find-skills",
                    "source_kind": "manual_git",
                    "source_scope": "global",
                    "locator": "https://github.com/vercel-labs/skills.git",
                    "source_path": "/root/.agents/skills/find-skills",
                    "managed_by": "github",
                    "update_policy": "source_sync",
                    "sync_status": "ok",
                    "sync_checked_at": "2026-04-11T00:00:01+00:00",
                    "sync_kind": "git_checkout",
                    "sync_message": "sync ok",
                    "sync_local_revision": "abc",
                    "sync_remote_revision": "def",
                    "sync_resolved_revision": "def",
                    "sync_branch": "main",
                    "sync_dirty": False,
                    "sync_error_code": "",
                    "registry_latest_version": "def",
                    "registry_published_at": "",
                    "registry_homepage": "https://github.com/vercel-labs/skills",
                    "registry_description": "skills repo",
                    "git_checkout_path": "/old/checkout",
                    "git_checkout_managed": True,
                    "git_checkout_error": "",
                }
            ],
        }

        plugin._load_saved_skills_registry = lambda: saved_registry
        plugin._save_skills_registry = lambda registry: registry

        updated = OneSyncPlugin._update_saved_registry_source_metadata(
            plugin,
            source_id="find_skills",
            source_payload={
                "source_id": "find_skills",
                "display_name": "find-skills",
                "source_kind": "manual_git",
                "source_scope": "global",
                "locator": "https://github.com/vercel-labs/skills.git",
                "source_path": "/root/.agents/skills/find-skills",
                "managed_by": "github",
                "update_policy": "source_sync",
                "git_checkout_path": "/new/checkout",
                "git_checkout_managed": True,
                "git_checkout_error": "",
            },
            sync_payload=None,
        )

        updated_row = next(item for item in updated["sources"] if item["source_id"] == "find_skills")
        self.assertEqual("ok", updated_row["sync_status"])
        self.assertEqual("git_checkout", updated_row["sync_kind"])
        self.assertEqual("def", updated_row["registry_latest_version"])
        self.assertEqual("/new/checkout", updated_row["git_checkout_path"])

    def test_summarize_update_all_failure_taxonomy_groups_failed_and_blocked_units(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        taxonomy = OneSyncPlugin._summarize_update_all_failure_taxonomy(
            plugin,
            failed_install_units=[
                {
                    "install_unit_id": "git:one",
                    "display_name": "Git One",
                    "manager": "git",
                    "policy": "source_sync",
                    "reason_code": "precheck_failed",
                },
                {
                    "install_unit_id": "git:two",
                    "display_name": "Git Two",
                    "manager": "git",
                    "policy": "source_sync",
                    "reason_code": "precheck_failed",
                },
                {
                    "install_unit_id": "npm:three",
                    "display_name": "Npm Three",
                    "manager": "bunx",
                    "policy": "registry",
                    "reason_code": "update_failed",
                },
            ],
            install_unit_results=[
                {
                    "install_unit_id": "git:one",
                    "display_name": "Git One",
                    "manager": "git",
                    "policy": "source_sync",
                    "ok": False,
                    "failure_reason": "precheck_failed",
                },
                {
                    "install_unit_id": "git:two",
                    "display_name": "Git Two",
                    "manager": "git",
                    "policy": "source_sync",
                    "ok": False,
                    "failure_reason": "precheck_failed",
                },
                {
                    "install_unit_id": "npm:three",
                    "display_name": "Npm Three",
                    "manager": "bunx",
                    "policy": "registry",
                    "ok": False,
                    "failure_reason": "update_failed",
                },
            ],
            blocked_unit_plans=[
                {
                    "install_unit_id": "manual:one",
                    "display_name": "Manual One",
                    "reason_code": "manual_managed",
                },
                {
                    "install_unit_id": "manual:two",
                    "display_name": "Manual Two",
                    "reason_code": "manual_managed",
                },
            ],
            failed_sources=[
                {
                    "install_unit_id": "git:one",
                    "display_name": "Git One",
                    "source_id": "src:one",
                    "sync_status": "error",
                    "sync_error_code": "git_remote_align_failed",
                }
            ],
        )

        self.assertEqual(3, taxonomy["failed_install_unit_total"])
        self.assertEqual("precheck_failed", taxonomy["failed_install_unit_reason_groups"][0]["failure_reason"])
        self.assertEqual(2, taxonomy["failed_install_unit_reason_groups"][0]["count"])
        self.assertEqual("git", taxonomy["failed_install_unit_manager_groups"][0]["manager"])
        self.assertEqual(2, taxonomy["failed_install_unit_manager_groups"][0]["count"])
        self.assertEqual("manual_managed", taxonomy["blocked_reason_groups"][0]["reason_code"])
        self.assertEqual(2, taxonomy["blocked_reason_groups"][0]["count"])
        self.assertEqual("git_remote_align_failed", taxonomy["failed_source_sync_error_groups"][0]["sync_error_code"])
        self.assertEqual(1, taxonomy["failed_source_sync_error_groups"][0]["count"])


class OneSyncPluginGitCheckoutPrewarmTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_git_checkout_prewarm_dedupes_by_locator(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin._git_checkout_prewarm_tasks = {}

        gate = asyncio.Event()

        async def _fake_run_git_checkout_prewarm(_row: dict[str, object]) -> None:
            await gate.wait()

        plugin._run_git_checkout_prewarm = _fake_run_git_checkout_prewarm

        source_rows = [
            {
                "source_id": "find_skills",
                "install_manager": "github",
                "locator": "https://github.com/vercel-labs/skills.git#skills/find-skills",
            },
            {
                "source_id": "frontend_design",
                "install_manager": "github",
                "locator": "https://github.com/vercel-labs/skills.git#skills/frontend-design",
            },
            {
                "source_id": "compound",
                "install_manager": "github",
                "locator": "https://github.com/every-env/compound-plugin.git#skills/ce-brainstorm",
            },
        ]

        OneSyncPlugin._schedule_git_checkout_prewarm(plugin, source_rows)

        self.assertEqual(2, len(plugin._git_checkout_prewarm_tasks))

        gate.set()
        await asyncio.gather(*list(plugin._git_checkout_prewarm_tasks.values()), return_exceptions=True)

    async def test_execute_install_unit_source_sync_plans_reuses_repo_metadata_sync_records(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin._augment_source_row_with_git_checkout = lambda source: dict(source)
        plugin._update_saved_registry_source_metadata = lambda **kwargs: {}

        source_rows = [
            {
                "source_id": "npx_global_javascript_pro",
                "install_unit_id": "repo:https://github.com/AndyAnh174/wellness.git#skills/javascript-pro",
                "source_path": "/root/.codex/skills/javascript-pro",
                "locator": "/root/.codex/skills/javascript-pro",
                "install_ref": "https://github.com/AndyAnh174/wellness.git#.agent/skills/javascript-pro",
                "install_manager": "manual",
                "update_policy": "registry",
            },
            {
                "source_id": "npx_global_javascript_mastery",
                "install_unit_id": "repo:https://github.com/AndyAnh174/wellness.git#skills/javascript-mastery",
                "source_path": "/root/.codex/skills/javascript-mastery",
                "locator": "/root/.codex/skills/javascript-mastery",
                "install_ref": "https://github.com/AndyAnh174/wellness.git#.agent/skills/javascript-mastery",
                "install_manager": "manual",
                "update_policy": "registry",
            },
        ]
        plans = [
            {
                "install_unit_id": "repo:https://github.com/AndyAnh174/wellness.git#skills/javascript-pro",
                "display_name": "AndyAnh174/wellness :: javascript-pro",
                "manager": "manual",
                "policy": "source_sync",
                "source_ids": ["npx_global_javascript_pro"],
            },
            {
                "install_unit_id": "repo:https://github.com/AndyAnh174/wellness.git#skills/javascript-mastery",
                "display_name": "AndyAnh174/wellness :: javascript-mastery",
                "manager": "manual",
                "policy": "source_sync",
                "source_ids": ["npx_global_javascript_mastery"],
            },
        ]

        original_builder = MAIN_MODULE.build_source_sync_record
        call_count = {"value": 0}

        def _fake_build_source_sync_record(source_row, *, checked_at=None, urlopen=None, git_runner=None, timeout_s=8):
            _ = checked_at, urlopen, git_runner, timeout_s
            call_count["value"] += 1
            return {
                "ok": True,
                "sync_status": "ok",
                "sync_kind": "repo_metadata_github",
                "sync_message": f"fetched github repository metadata for {source_row.get('source_id')}",
                "sync_local_revision": "",
                "sync_remote_revision": "rev-demo",
                "sync_resolved_revision": "rev-demo",
                "sync_branch": "",
                "sync_dirty": False,
                "sync_error_code": "",
                "registry_latest_version": "rev-demo",
                "registry_published_at": "",
                "registry_homepage": "https://github.com/AndyAnh174/wellness",
                "registry_description": "demo",
            }

        MAIN_MODULE.build_source_sync_record = _fake_build_source_sync_record
        try:
            result = OneSyncPlugin._execute_install_unit_source_sync_plans(
                plugin,
                plans,
                source_rows,
            )
        finally:
            MAIN_MODULE.build_source_sync_record = original_builder

        self.assertEqual(1, call_count["value"])
        self.assertEqual(2, result["source_sync_success_count"])
        self.assertEqual(0, result["source_sync_failure_count"])
        self.assertEqual(1, result["source_sync_cache_hit_total"])

    async def test_execute_install_unit_source_sync_plans_reuses_gitea_repo_metadata_sync_records(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin._augment_source_row_with_git_checkout = lambda source: dict(source)
        plugin._update_saved_registry_source_metadata = lambda **kwargs: {}

        source_rows = [
            {
                "source_id": "codeberg_find_skills",
                "install_unit_id": "repo:codeberg.org/astral/skills#skills/find-skills",
                "source_path": "/root/.codex/skills/find-skills",
                "locator": "/root/.codex/skills/find-skills",
                "install_ref": "repo:codeberg.org/astral/skills#skills/find-skills",
                "install_manager": "manual",
                "managed_by": "manual",
                "update_policy": "manual",
            },
            {
                "source_id": "codeberg_frontend_design",
                "install_unit_id": "repo:codeberg.org/astral/skills#skills/frontend-design",
                "source_path": "/root/.codex/skills/frontend-design",
                "locator": "/root/.codex/skills/frontend-design",
                "install_ref": "repo:codeberg.org/astral/skills#skills/frontend-design",
                "install_manager": "manual",
                "managed_by": "manual",
                "update_policy": "manual",
            },
        ]
        plans = [
            {
                "install_unit_id": "repo:codeberg.org/astral/skills#skills/find-skills",
                "display_name": "astral/skills :: find-skills",
                "manager": "manual",
                "policy": "source_sync",
                "source_ids": ["codeberg_find_skills"],
            },
            {
                "install_unit_id": "repo:codeberg.org/astral/skills#skills/frontend-design",
                "display_name": "astral/skills :: frontend-design",
                "manager": "manual",
                "policy": "source_sync",
                "source_ids": ["codeberg_frontend_design"],
            },
        ]

        original_builder = MAIN_MODULE.build_source_sync_record
        call_count = {"value": 0}

        def _fake_build_source_sync_record(source_row, *, checked_at=None, urlopen=None, git_runner=None, timeout_s=8):
            _ = checked_at, urlopen, git_runner, timeout_s
            call_count["value"] += 1
            return {
                "ok": True,
                "sync_status": "ok",
                "sync_kind": "repo_metadata_gitea",
                "sync_message": f"fetched gitea repository metadata for {source_row.get('source_id')}",
                "sync_local_revision": "",
                "sync_remote_revision": "rev-gitea-demo",
                "sync_resolved_revision": "rev-gitea-demo",
                "sync_branch": "main",
                "sync_dirty": False,
                "sync_error_code": "",
                "registry_latest_version": "rev-gitea-demo",
                "registry_published_at": "",
                "registry_homepage": "https://codeberg.org/astral/skills",
                "registry_description": "codeberg demo",
            }

        MAIN_MODULE.build_source_sync_record = _fake_build_source_sync_record
        try:
            result = OneSyncPlugin._execute_install_unit_source_sync_plans(
                plugin,
                plans,
                source_rows,
            )
        finally:
            MAIN_MODULE.build_source_sync_record = original_builder

        self.assertEqual(1, call_count["value"])
        self.assertEqual(2, result["source_sync_success_count"])
        self.assertEqual(0, result["source_sync_failure_count"])
        self.assertEqual(1, result["source_sync_cache_hit_total"])

    async def test_execute_install_unit_update_plans_treats_successful_fallback_chain_as_success(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin.webui_get_skills_payload = lambda: {"source_rows": []}

        class _FakeRunner:
            def __init__(self) -> None:
                self._results = [
                    pytypes.SimpleNamespace(
                        command="command -v bunx >/dev/null 2>&1 || command -v npx >/dev/null 2>&1 || command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        duration_s=0.01,
                        timed_out=False,
                    ),
                    pytypes.SimpleNamespace(
                        command="bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
                        exit_code=127,
                        stdout="",
                        stderr="/bin/bash: line 1: bunx: command not found\n",
                        duration_s=0.01,
                        timed_out=False,
                    ),
                    pytypes.SimpleNamespace(
                        command="npx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
                        exit_code=127,
                        stdout="",
                        stderr="/usr/bin/env: 'bun': No such file or directory\n",
                        duration_s=0.2,
                        timed_out=False,
                    ),
                    pytypes.SimpleNamespace(
                        command="pnpm dlx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex",
                        exit_code=127,
                        stdout="",
                        stderr="exec: bun: not found\n",
                        duration_s=0.2,
                        timed_out=False,
                    ),
                    pytypes.SimpleNamespace(
                        command="npm exec --yes @every-env/compound-plugin install compound-engineering -- --to codex --codexHome /root/.codex",
                        exit_code=0,
                        stdout="changed 5 packages in 3s\n",
                        stderr="",
                        duration_s=0.3,
                        timed_out=False,
                    ),
                ]

            async def run(self, command: str, *, timeout_s: int = 600, cwd: str | None = None, env_update=None):
                _ = timeout_s, cwd, env_update
                result = self._results.pop(0)
                assert result.command == command
                return result

        plugin.runner = _FakeRunner()

        result = await OneSyncPlugin._execute_install_unit_update_plans(
            plugin,
            [
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
                    "manager": "bunx",
                    "policy": "registry",
                    "install_ref": "@every-env/compound-plugin",
                    "supported": True,
                    "precheck_commands": [
                        "command -v bunx >/dev/null 2>&1 || command -v npx >/dev/null 2>&1 || command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1"
                    ],
                    "commands": [
                        "bunx @every-env/compound-plugin install compound-engineering --to codex --codexHome /root/.codex"
                    ],
                }
            ],
        )

        self.assertEqual(2, result["success_count"])
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(1, result["update_success_count"])
        self.assertEqual(0, result["update_failure_count"])
        self.assertEqual([], result["failed_install_units"])
        self.assertEqual(True, result["install_unit_results"][0]["ok"])
        ignored = [
            item for item in result["install_unit_results"][0]["results"]
            if isinstance(item, dict) and item.get("ignored")
        ]
        self.assertGreaterEqual(len(ignored), 3)

    async def test_execute_install_unit_update_plans_stamps_registry_refresh_anchor_after_successful_command_update(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin.state = {"skills": {"saved_registry": {}}, "inventory": {}}

        source_row = {
            "source_id": "npx_global_ui_ux_pro_max",
            "display_name": "ui-ux-pro-max",
            "source_kind": "npx_single",
            "provider_key": "npx_skills",
            "source_scope": "global",
            "source_path": "/root/.codex/skills/ui-ux-pro-max",
            "locator": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git#.claude/skills/ui-ux-pro-max",
            "managed_by": "npx",
            "update_policy": "registry",
            "source_exists": True,
            "last_seen_at": "2026-03-25T02:15:37.179549+00:00",
            "last_refresh_at": "2026-04-01T09:12:34.003161+00:00",
            "freshness_status": "aging",
            "sync_status": "ok",
            "sync_kind": "repo_metadata_github",
            "sync_checked_at": "2026-04-01T09:12:24.739012+00:00",
            "registry_latest_version": "2026-04-03T05:08:19Z",
            "registry_package_name": "@nextlevelbuilder/ui-ux-pro-max-skill",
            "registry_package_manager": "npm",
            "install_unit_id": "npm:@nextlevelbuilder/ui-ux-pro-max-skill",
            "install_manager": "bunx",
        }
        saved_registry = {
            "version": 1,
            "generated_at": "2026-04-01T09:12:34.003161+00:00",
            "sources": [dict(source_row)],
        }
        saved_registry_box = {"value": saved_registry}

        plugin.webui_get_skills_payload = lambda: {"source_rows": [dict(source_row)]}
        plugin._load_saved_skills_registry = lambda: saved_registry_box["value"]
        plugin._save_skills_registry = lambda registry: saved_registry_box.__setitem__("value", registry) or registry

        class _FakeRunner:
            async def run(self, command: str, *, timeout_s: int = 600, cwd: str | None = None, env_update=None):
                _ = timeout_s, cwd, env_update
                return pytypes.SimpleNamespace(
                    command=command,
                    exit_code=0,
                    stdout="updated 1 package\n",
                    stderr="",
                    duration_s=0.1,
                    timed_out=False,
                )

        plugin.runner = _FakeRunner()

        original_now_iso = MAIN_MODULE._now_iso
        MAIN_MODULE._now_iso = lambda: "2026-04-12T12:34:56+00:00"
        try:
            result = await OneSyncPlugin._execute_install_unit_update_plans(
                plugin,
                [
                    {
                        "install_unit_id": "npm:@nextlevelbuilder/ui-ux-pro-max-skill",
                        "display_name": "ui-ux-pro-max",
                        "manager": "bunx",
                        "policy": "registry",
                        "supported": True,
                        "source_ids": ["npx_global_ui_ux_pro_max"],
                        "commands": [
                            "bunx @nextlevelbuilder/ui-ux-pro-max-skill update --target codex",
                        ],
                    }
                ],
            )
        finally:
            MAIN_MODULE._now_iso = original_now_iso

        self.assertTrue(result["install_unit_results"][0]["ok"])
        updated_row = next(
            item for item in saved_registry_box["value"]["sources"]
            if item["source_id"] == "npx_global_ui_ux_pro_max"
        )
        self.assertEqual("2026-04-12T12:34:56+00:00", updated_row["last_refresh_at"])
        self.assertEqual("2026-04-12T12:34:56+00:00", updated_row["last_seen_at"])
        self.assertEqual("ok", updated_row["sync_status"])


class OneSyncPluginAuthorityBoundaryTests(unittest.TestCase):
    def test_inventory_bindings_update_uses_skills_snapshot_as_primary_compatibility_source(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin.config = {
            "skill_bindings": [
                {"software_id": "codex", "skill_id": "legacy_source", "scope": "global"},
            ],
        }
        plugin.state = {
            "inventory": {
                "last_snapshot": {
                    "ok": True,
                    "generated_at": "2026-04-12T10:00:00+00:00",
                    "software_rows": [
                        {
                            "id": "codex",
                            "display_name": "Codex",
                            "binding_count": 1,
                        },
                    ],
                    "skill_rows": [
                        {"id": "legacy_source", "display_name": "Legacy Source"},
                        {"id": "source_b", "display_name": "Source B"},
                    ],
                    "binding_rows": [
                        {
                            "software_id": "codex",
                            "skill_id": "legacy_source",
                            "scope": "global",
                            "enabled": True,
                            "valid": True,
                            "reason": "",
                        },
                    ],
                    "binding_map": {"codex": ["legacy_source"]},
                    "binding_map_by_scope": {
                        "global": {"codex": ["legacy_source"]},
                        "workspace": {"codex": []},
                    },
                    "compatibility": {"codex": ["legacy_source", "source_b"]},
                    "counts": {
                        "bindings_total": 1,
                        "bindings_valid": 1,
                        "bindings_invalid": 0,
                    },
                    "warnings": [],
                },
            },
            "skills": {
                "last_overview": {
                    "ok": True,
                    "generated_at": "2026-04-12T10:00:00+00:00",
                    "host_rows": [
                        {"host_id": "codex", "display_name": "Codex"},
                    ],
                    "compatible_source_rows_by_software": {
                        "codex": [
                            {"source_id": "legacy_source"},
                            {"source_id": "source_b"},
                        ],
                    },
                    "manifest": {"deploy_targets": []},
                    "registry": {},
                    "lock": {},
                    "install_atom_registry": {},
                },
            },
        }

        manifest_calls: list[tuple[str, list[str]]] = []
        persisted: list[bool] = []
        debug_logs: list[str] = []

        def _update_saved_manifest_target_selection(*, target_id: str, selected_source_ids: list[str]):
            manifest_calls.append((target_id, list(selected_source_ids)))
            return {
                "version": 1,
                "generated_at": "2026-04-12T10:00:00+00:00",
                "sources": [],
                "deploy_targets": [
                    {
                        "target_id": target_id,
                        "software_id": "codex",
                        "scope": "global",
                        "selected_source_ids": list(selected_source_ids),
                    },
                ],
            }

        def _refresh_skills_snapshot(
            inventory_snapshot=None,
            *,
            saved_manifest=None,
            saved_registry=None,
            saved_lock=None,
            saved_install_atom_registry=None,
        ):
            plugin.state.setdefault("skills", {})["last_overview"] = {
                "ok": True,
                "generated_at": "2026-04-12T10:00:00+00:00",
                "manifest": saved_manifest or {},
                "registry": saved_registry or {},
                "lock": saved_lock or {},
                "install_atom_registry": saved_install_atom_registry or {},
            }
            return plugin.state["skills"]["last_overview"]

        plugin.webui_get_skills_payload = lambda: plugin.state["skills"]["last_overview"]
        plugin._update_saved_manifest_target_selection = _update_saved_manifest_target_selection
        plugin._persist_plugin_config = lambda: persisted.append(True)
        plugin._push_debug_log = lambda _level, message, **_kwargs: debug_logs.append(str(message))
        plugin._load_saved_skills_registry = lambda: {}
        plugin._load_saved_skills_lock = lambda: {}
        plugin._load_saved_install_atom_registry = lambda: {}
        plugin._refresh_skills_snapshot = _refresh_skills_snapshot
        plugin._build_inventory_snapshot = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("inventory rescan should not be required for binding projection"),
        )

        result = OneSyncPlugin.webui_update_inventory_bindings(
            plugin,
            {"software_id": "codex", "skill_ids": ["source_b"], "scope": "global"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual([("codex:global", ["source_b"])], manifest_calls)
        self.assertEqual(
            [{"software_id": "codex", "skill_id": "source_b", "scope": "global", "enabled": True, "settings": {}}],
            plugin.config["skill_bindings"],
        )
        self.assertEqual(["source_b"], result["inventory"]["binding_map"]["codex"])
        self.assertEqual(["source_b"], result["inventory"]["binding_map_by_scope"]["global"]["codex"])
        self.assertEqual(1, result["inventory"]["counts"]["bindings_total"])
        self.assertTrue(persisted)
        self.assertTrue(any("bindings=1" in item for item in debug_logs))

    def test_inventory_bindings_full_replace_clears_omitted_manifest_targets_without_rescan(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        plugin.config = {
            "skill_bindings": [
                {"software_id": "codex", "skill_id": "legacy_source", "scope": "global"},
                {"software_id": "claude_code", "skill_id": "source_x", "scope": "global"},
            ],
        }
        plugin.state = {
            "inventory": {
                "last_snapshot": {
                    "ok": True,
                    "generated_at": "2026-04-12T10:00:00+00:00",
                    "software_rows": [
                        {"id": "codex", "display_name": "Codex", "binding_count": 1},
                        {"id": "claude_code", "display_name": "Claude Code", "binding_count": 1},
                    ],
                    "skill_rows": [
                        {"id": "legacy_source", "display_name": "Legacy Source"},
                        {"id": "source_b", "display_name": "Source B"},
                        {"id": "source_x", "display_name": "Source X"},
                    ],
                    "binding_rows": [
                        {
                            "software_id": "codex",
                            "skill_id": "legacy_source",
                            "scope": "global",
                            "enabled": True,
                            "valid": True,
                            "reason": "",
                        },
                        {
                            "software_id": "claude_code",
                            "skill_id": "source_x",
                            "scope": "global",
                            "enabled": True,
                            "valid": True,
                            "reason": "",
                        },
                    ],
                    "binding_map": {
                        "codex": ["legacy_source"],
                        "claude_code": ["source_x"],
                    },
                    "binding_map_by_scope": {
                        "global": {
                            "codex": ["legacy_source"],
                            "claude_code": ["source_x"],
                        },
                        "workspace": {
                            "codex": [],
                            "claude_code": [],
                        },
                    },
                    "compatibility": {
                        "codex": ["legacy_source", "source_b"],
                        "claude_code": ["source_x"],
                    },
                    "counts": {
                        "bindings_total": 2,
                        "bindings_valid": 2,
                        "bindings_invalid": 0,
                    },
                    "warnings": [],
                },
            },
            "skills": {
                "last_overview": {
                    "ok": True,
                    "generated_at": "2026-04-12T10:00:00+00:00",
                    "host_rows": [
                        {"host_id": "codex", "display_name": "Codex"},
                        {"host_id": "claude_code", "display_name": "Claude Code"},
                    ],
                    "compatible_source_rows_by_software": {
                        "codex": [
                            {"source_id": "legacy_source"},
                            {"source_id": "source_b"},
                        ],
                        "claude_code": [
                            {"source_id": "source_x"},
                        ],
                    },
                    "manifest": {
                        "version": 1,
                        "generated_at": "2026-04-12T10:00:00+00:00",
                        "sources": [],
                        "deploy_targets": [
                            {
                                "target_id": "codex:global",
                                "software_id": "codex",
                                "scope": "global",
                                "selected_source_ids": ["legacy_source"],
                            },
                            {
                                "target_id": "claude_code:global",
                                "software_id": "claude_code",
                                "scope": "global",
                                "selected_source_ids": ["source_x"],
                            },
                        ],
                    },
                    "registry": {},
                    "lock": {},
                    "install_atom_registry": {},
                },
            },
        }

        persisted: list[bool] = []
        debug_logs: list[str] = []

        def _refresh_skills_snapshot(
            inventory_snapshot=None,
            *,
            saved_manifest=None,
            saved_registry=None,
            saved_lock=None,
            saved_install_atom_registry=None,
        ):
            plugin.state.setdefault("skills", {})["last_overview"] = {
                "ok": True,
                "generated_at": "2026-04-12T10:00:00+00:00",
                "manifest": saved_manifest or {},
                "registry": saved_registry or {},
                "lock": saved_lock or {},
                "install_atom_registry": saved_install_atom_registry or {},
            }
            return plugin.state["skills"]["last_overview"]

        plugin.webui_get_skills_payload = lambda: plugin.state["skills"]["last_overview"]
        plugin._persist_plugin_config = lambda: persisted.append(True)
        plugin._push_debug_log = lambda _level, message, **_kwargs: debug_logs.append(str(message))
        plugin._load_saved_skills_registry = lambda: {}
        plugin._load_saved_skills_lock = lambda: {}
        plugin._load_saved_install_atom_registry = lambda: {}
        plugin._refresh_skills_snapshot = _refresh_skills_snapshot
        plugin._build_inventory_snapshot = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("inventory rescan should not be required for binding projection"),
        )

        result = OneSyncPlugin.webui_update_inventory_bindings(
            plugin,
            {"bindings": [{"software_id": "codex", "skill_id": "source_b", "scope": "global"}]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [{"software_id": "codex", "skill_id": "source_b", "scope": "global", "enabled": True, "settings": {}}],
            plugin.config["skill_bindings"],
        )
        manifest_targets = {
            item["target_id"]: item
            for item in result["manifest"]["deploy_targets"]
        }
        self.assertEqual(["source_b"], manifest_targets["codex:global"]["selected_source_ids"])
        self.assertEqual([], manifest_targets["claude_code:global"]["selected_source_ids"])
        self.assertEqual(["source_b"], result["inventory"]["binding_map"]["codex"])
        self.assertEqual([], result["inventory"]["binding_map"]["claude_code"])
        self.assertEqual(["source_b"], result["inventory"]["binding_map_by_scope"]["global"]["codex"])
        self.assertEqual([], result["inventory"]["binding_map_by_scope"]["global"]["claude_code"])
        self.assertEqual(1, result["inventory"]["counts"]["bindings_total"])
        self.assertTrue(persisted)
        self.assertTrue(any("bindings=1" in item for item in debug_logs))


class OneSyncPluginAstrbotNeoDetailTests(unittest.TestCase):
    def test_get_astrbot_neo_source_payload_enriches_remote_state_and_activity(self) -> None:
        plugin = object.__new__(OneSyncPlugin)

        plugin.config = {
            "provider_settings": {
                "sandbox": {
                    "shipyard_neo_endpoint": "https://neo.example.com",
                    "shipyard_neo_access_token": "secret-token",
                }
            }
        }
        plugin.webui_get_skills_payload = lambda: {
            "generated_at": "2026-04-13T10:00:00+00:00",
            "astrbot_neo_source_rows": [
                {
                    "source_id": "astrneo:astrbot:demo.skill",
                    "display_name": "neo-demo",
                    "source_kind": "astrneo_release",
                    "astrneo_host_id": "astrbot",
                    "astrneo_skill_key": "demo.skill",
                    "astrneo_skill_name": "neo_demo",
                    "astrneo_release_id": "rel-local",
                    "astrneo_candidate_id": "cand-local",
                    "astrneo_payload_ref": "payload-local",
                    "astrneo_updated_at": "2026-04-13T09:58:00+00:00",
                    "status": "ready",
                }
            ],
            "warnings": [],
        }

        class _FakeSkillsApi:
            def __init__(self) -> None:
                self.last_release_kwargs = None
                self.last_candidate_kwargs = None

            async def list_releases(self, **kwargs):
                self.last_release_kwargs = kwargs
                return {
                    "total": 2,
                    "items": [
                        {
                            "id": "rel-stable",
                            "skill_key": "demo.skill",
                            "candidate_id": "cand-stable",
                            "stage": "stable",
                            "is_active": True,
                            "created_at": "2026-04-13T09:00:00+00:00",
                        },
                        {
                            "id": "rel-canary",
                            "skill_key": "demo.skill",
                            "candidate_id": "cand-canary",
                            "stage": "canary",
                            "is_active": True,
                            "created_at": "2026-04-13T09:30:00+00:00",
                        },
                    ],
                }

            async def list_candidates(self, **kwargs):
                self.last_candidate_kwargs = kwargs
                return {
                    "total": 2,
                    "items": [
                        {
                            "id": "cand-stable",
                            "skill_key": "demo.skill",
                            "status": "approved",
                            "payload_ref": "payload-stable",
                            "updated_at": "2026-04-13T08:55:00+00:00",
                        },
                        {
                            "id": "cand-canary",
                            "skill_key": "demo.skill",
                            "status": "draft",
                            "payload_ref": "payload-canary",
                            "updated_at": "2026-04-13T09:25:00+00:00",
                        },
                    ],
                }

        fake_skills_api = _FakeSkillsApi()

        class _FakeBayClient:
            def __init__(self, *, endpoint_url: str, access_token: str) -> None:
                self.endpoint_url = endpoint_url
                self.access_token = access_token
                self.skills = fake_skills_api

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        shipyard_module = types.ModuleType("shipyard_neo")
        shipyard_module.BayClient = _FakeBayClient
        previous_shipyard_module = sys.modules.get("shipyard_neo")
        sys.modules["shipyard_neo"] = shipyard_module

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.skills_state_dir = Path(tmpdir)
            plugin.skills_audit_path = Path(tmpdir) / "audit.log.jsonl"
            plugin.skills_audit_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-04-13T09:59:00+00:00",
                                "action": "astrbot_neo_source_sync",
                                "source_id": "astrneo:astrbot:demo.skill",
                                "payload": {"release_id": "rel-local"},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-13T10:01:00+00:00",
                                "action": "astrbot_neo_source_promote",
                                "source_id": "astrneo:astrbot:demo.skill",
                                "payload": {"release_id": "rel-stable", "stage": "stable"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            try:
                detail = OneSyncPlugin.webui_get_astrbot_neo_source_payload(
                    plugin,
                    "astrneo:astrbot:demo.skill",
                )
            finally:
                if previous_shipyard_module is None:
                    sys.modules.pop("shipyard_neo", None)
                else:
                    sys.modules["shipyard_neo"] = previous_shipyard_module

        self.assertTrue(detail["ok"])
        self.assertEqual("demo.skill", detail["neo_state"]["skill_key"])
        self.assertTrue(detail["neo_remote_state"]["configured"])
        self.assertEqual("rel-stable", detail["neo_remote_state"]["current"]["active_stable_release_id"])
        self.assertEqual("cand-canary", detail["neo_remote_state"]["current"]["latest_candidate_id"])
        self.assertEqual(2, detail["neo_remote_state"]["releases"]["total"])
        self.assertEqual(2, detail["neo_remote_state"]["candidates"]["total"])
        self.assertEqual(2, detail["neo_activity"]["counts"]["total"])
        self.assertEqual(
            "astrbot_neo_source_promote",
            detail["neo_activity"]["items"][0]["action"],
        )
        self.assertEqual(
            {"skill_key": "demo.skill", "limit": 5, "offset": 0},
            fake_skills_api.last_release_kwargs,
        )
        self.assertEqual(
            {"skill_key": "demo.skill", "limit": 5, "offset": 0},
            fake_skills_api.last_candidate_kwargs,
        )


class OneSyncPluginSkillsAuditTests(unittest.TestCase):
    def test_append_skills_audit_event_generates_event_id(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plugin.skills_state_dir = tmp_path / "state"
            plugin.skills_audit_path = plugin.skills_state_dir / "audit.log.jsonl"

            event_id = OneSyncPlugin._append_skills_audit_event(
                plugin,
                "install_unit_rollback",
                source_id="install:skill_cli",
                payload={
                    "request_source": "audit_retry",
                    "retry_of_event_id": "audit_prev",
                },
            )

            self.assertTrue(event_id.startswith("audit_"))
            payload = OneSyncPlugin.webui_get_skills_audit_payload(
                plugin,
                limit=20,
                action="rollback",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(1, payload["counts"]["total"])
            self.assertEqual(event_id, payload["items"][0]["event_id"])
            self.assertEqual("install_unit_rollback", payload["items"][0]["action"])
            self.assertEqual("install:skill_cli", payload["items"][0]["source_id"])
            self.assertEqual(
                "audit_retry",
                payload["items"][0]["payload"]["request_source"],
            )

    def test_webui_get_skills_audit_payload_backfills_legacy_event_id(self) -> None:
        plugin = object.__new__(OneSyncPlugin)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plugin.skills_state_dir = tmp_path / "state"
            plugin.skills_state_dir.mkdir(parents=True, exist_ok=True)
            plugin.skills_audit_path = plugin.skills_state_dir / "audit.log.jsonl"
            plugin.skills_audit_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-13T12:00:00+00:00",
                        "action": "install_unit_rollback",
                        "source_id": "install:skill_cli",
                        "payload": {"candidate_total": 1},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = OneSyncPlugin.webui_get_skills_audit_payload(
                plugin,
                limit=20,
                action="rollback",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(1, payload["counts"]["total"])
            self.assertEqual("legacy_1", payload["items"][0]["event_id"])
