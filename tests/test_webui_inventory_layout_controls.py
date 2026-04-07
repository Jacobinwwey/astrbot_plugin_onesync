from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_HTML = REPO_ROOT / "webui" / "index.html"


class WebUIInventoryLayoutControlsTests(unittest.TestCase):
    def test_inventory_panel_exposes_layout_and_card_controls(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventoryScopeTabs"', html)
        self.assertIn('id="inventoryPanelViewTabs"', html)
        self.assertIn('id="inventoryCardFontSizeSelect"', html)
        self.assertIn('id="inventoryCardWidthSelect"', html)
        self.assertIn('id="inventoryCardHeightSelect"', html)

    def test_inventory_panel_scripts_persist_layout_preferences(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventoryCardView", html)
        self.assertIn("inventoryCardFontSize", html)
        self.assertIn("inventoryCardWidth", html)
        self.assertIn("inventoryCardHeight", html)
        self.assertIn("--inventory-card-font-size", html)


if __name__ == "__main__":
    unittest.main()
