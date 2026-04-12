from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_astrbot_modules() -> None:
    if "astrbot" in sys.modules:
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
