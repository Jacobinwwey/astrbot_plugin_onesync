from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_HTML = REPO_ROOT / "webui" / "index.html"


class WebUIInventoryRegistryHostsTests(unittest.TestCase):
    def test_inventory_panel_exposes_registry_and_host_metadata_strings(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventory_summary_registry_hosts", html)
        self.assertIn("inventory_skill_meta_locator", html)
        self.assertIn("inventory_skill_meta_policy", html)
        self.assertIn("inventory_skill_meta_managed_by", html)
        self.assertIn("inventory_meta_host_paths", html)
        self.assertIn("inventory_meta_source_supports", html)

    def test_inventory_panel_scripts_render_registry_kind_and_host_supports(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("function inventorySourceKindLabel(item)", html)
        self.assertIn("supports_source_kinds", html)
        self.assertIn("target_paths", html)
        self.assertIn("inventory_summary_registry_hosts", html)


if __name__ == "__main__":
    unittest.main()
