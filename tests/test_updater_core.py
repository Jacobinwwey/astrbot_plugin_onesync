from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_fake_astrbot_version_comparator() -> None:
    if "astrbot.core.utils.version_comparator" in sys.modules and "astrbot.api" in sys.modules:
        return

    astrbot_pkg = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
    api_pkg = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
    event_pkg = sys.modules.setdefault("astrbot.api.event", types.ModuleType("astrbot.api.event"))
    star_pkg = sys.modules.setdefault("astrbot.api.star", types.ModuleType("astrbot.api.star"))
    message_components_pkg = sys.modules.setdefault(
        "astrbot.api.message_components",
        types.ModuleType("astrbot.api.message_components"),
    )
    core_pkg = sys.modules.setdefault("astrbot.core", types.ModuleType("astrbot.core"))
    utils_pkg = sys.modules.setdefault("astrbot.core.utils", types.ModuleType("astrbot.core.utils"))
    astrbot_path_pkg = sys.modules.setdefault(
        "astrbot.core.utils.astrbot_path",
        types.ModuleType("astrbot.core.utils.astrbot_path"),
    )
    version_comparator_pkg = types.ModuleType("astrbot.core.utils.version_comparator")

    class _FakeLogger:
        def info(self, *_args, **_kwargs) -> None:
            return None

        def warning(self, *_args, **_kwargs) -> None:
            return None

        def error(self, *_args, **_kwargs) -> None:
            return None

    class _FakeFilter:
        class PermissionType:
            ADMIN = "admin"

        @staticmethod
        def command_group(*_args, **_kwargs):
            def _decorator(func):
                return func

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
    sys.modules["astrbot.core.utils.version_comparator"] = version_comparator_pkg

    astrbot_pkg.api = api_pkg
    astrbot_pkg.core = core_pkg
    api_pkg.event = event_pkg
    api_pkg.star = star_pkg
    api_pkg.message_components = message_components_pkg
    core_pkg.utils = utils_pkg
    utils_pkg.astrbot_path = astrbot_path_pkg
    utils_pkg.version_comparator = version_comparator_pkg


_install_fake_astrbot_version_comparator()

from updater_core import CommandRunner


class CommandRunnerPathTests(unittest.TestCase):
    def test_ensure_runtime_path_includes_bun_bin_on_unix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            bun_bin = home / ".bun" / "bin"
            bun_bin.mkdir(parents=True, exist_ok=True)
            env = {
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
            }

            CommandRunner._ensure_runtime_path(env)

            path_entries = env["PATH"].split(":")
            self.assertIn(str(bun_bin), path_entries)
            self.assertLess(path_entries.index(str(bun_bin)), path_entries.index("/usr/bin"))
