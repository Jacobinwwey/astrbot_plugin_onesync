from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from source_sync_core import build_source_sync_record, fetch_npm_registry_package_summary


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SourceSyncCoreTests(unittest.TestCase):
    def test_fetch_npm_registry_package_summary(self) -> None:
        def _fake_urlopen(url: str, timeout: int = 0):
            self.assertIn("%40every-env%2Fcompound-plugin", url)
            self.assertEqual(6, timeout)
            return _FakeResponse(
                {
                    "dist-tags": {"latest": "2.62.1"},
                    "versions": {
                        "2.62.1": {
                            "homepage": "https://github.com/every-env/compound-plugin",
                            "description": "Compound plugin bundle",
                        },
                    },
                    "time": {
                        "modified": "2026-04-01T12:00:00.000Z",
                        "2.62.1": "2026-04-01T11:58:00.000Z",
                    },
                },
            )

        summary = fetch_npm_registry_package_summary(
            "@every-env/compound-plugin",
            urlopen=_fake_urlopen,
            timeout_s=6,
        )

        self.assertTrue(summary["ok"])
        self.assertEqual("2.62.1", summary["registry_latest_version"])
        self.assertEqual("2026-04-01T11:58:00.000Z", summary["registry_published_at"])
        self.assertEqual("https://github.com/every-env/compound-plugin", summary["registry_homepage"])
        self.assertEqual("Compound plugin bundle", summary["registry_description"])
        self.assertEqual("npm_registry", summary["sync_kind"])

    def test_build_source_sync_record_marks_unsupported_sources(self) -> None:
        record = build_source_sync_record(
            {
                "source_id": "manual_skill",
                "display_name": "Manual Skill",
                "registry_package_name": "",
                "registry_package_manager": "",
            },
            checked_at="2026-04-06T12:00:00+00:00",
        )

        self.assertEqual("unsupported", record["sync_status"])
        self.assertEqual("2026-04-06T12:00:00+00:00", record["sync_checked_at"])
        self.assertEqual("", record["registry_latest_version"])

    def test_build_source_sync_record_fetches_npm_registry(self) -> None:
        def _fake_urlopen(_url: str, timeout: int = 0):
            self.assertEqual(8, timeout)
            return _FakeResponse(
                {
                    "dist-tags": {"latest": "2.62.1"},
                    "versions": {
                        "2.62.1": {
                            "homepage": "https://github.com/every-env/compound-plugin",
                            "description": "Compound plugin bundle",
                        },
                    },
                    "time": {
                        "modified": "2026-04-01T12:00:00.000Z",
                        "2.62.1": "2026-04-01T11:58:00.000Z",
                    },
                },
            )

        record = build_source_sync_record(
            {
                "source_id": "npx_bundle_compound_engineering_global",
                "display_name": "Compound Engineering",
                "registry_package_name": "@every-env/compound-plugin",
                "registry_package_manager": "npm",
            },
            checked_at="2026-04-06T12:00:00+00:00",
            urlopen=_fake_urlopen,
            timeout_s=8,
        )

        self.assertEqual("ok", record["sync_status"])
        self.assertEqual("2026-04-06T12:00:00+00:00", record["sync_checked_at"])
        self.assertEqual("2.62.1", record["registry_latest_version"])
        self.assertIn("@every-env/compound-plugin", record["sync_message"])


if __name__ == "__main__":
    unittest.main()
