from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_HTML = REPO_ROOT / "webui" / "index.html"


class WebUIInventoryLayoutControlsTests(unittest.TestCase):
    def test_inventory_panel_exposes_independent_source_and_deploy_layout_controls(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventoryScopeTabs"', html)
        self.assertIn('id="inventorySourcePanelViewTabs"', html)
        self.assertIn('id="inventoryDeployPanelViewTabs"', html)
        self.assertIn('id="inventoryDeployScopeTabs"', html)
        self.assertIn('id="inventoryDeployInstallTabs"', html)
        self.assertIn('id="inventorySourceCardFontSizeSelect"', html)
        self.assertIn('id="inventorySourceCardWidthSelect"', html)
        self.assertIn('id="inventorySourceCardHeightSelect"', html)
        self.assertIn('id="inventoryDeployCardFontSizeSelect"', html)
        self.assertIn('id="inventoryDeployCardWidthSelect"', html)
        self.assertIn('id="inventoryDeployCardHeightSelect"', html)

    def test_inventory_inspector_is_not_sticky(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        block_start = html.index("    .inventory-inspector {\n")
        block_end = html.index("    .inventory-inspector-head {\n", block_start)
        block = html[block_start:block_end]

        self.assertNotIn("position: sticky;", block)
        self.assertNotIn("top: 12px;", block)

    def test_inventory_inspector_panel_expands_without_stretching_primary_workspace(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        shell_start = html.index("    .inventory-shell {\n")
        shell_end = html.index("    .inventory-grid {\n", shell_start)
        shell_block = html[shell_start:shell_end]
        self.assertIn("align-items: start;", shell_block)
        self.assertNotIn("align-items: stretch;", shell_block)

        inspector_start = html.index("    .inventory-inspector {\n")
        inspector_end = html.index("    .inventory-inspector-head {\n", inspector_start)
        inspector_block = html[inspector_start:inspector_end]
        self.assertNotIn("align-self: stretch;", inspector_block)

        panel_start = html.index("    .inventory-inspector-panel {\n")
        panel_end = html.index("    .inventory-inspector-card {\n", panel_start)
        panel_block = html[panel_start:panel_end]
        self.assertNotIn("max-height:", panel_block)
        self.assertNotIn("overflow: auto;", panel_block)

    def test_inventory_panel_declares_compatible_sources_before_status_cards(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        compatible_index = html.index("const compatibleSources = inventoryCompatibleSelectionRows(overview, selectedSoftwareId);")
        status_cards_index = html.index("const statusCards = [")

        self.assertLess(compatible_index, status_cards_index)

    def test_inventory_panel_scripts_persist_independent_layout_preferences(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventorySourceCardView", html)
        self.assertIn("inventorySourceCardFontSize", html)
        self.assertIn("inventorySourceCardWidth", html)
        self.assertIn("inventorySourceCardHeight", html)
        self.assertIn("inventoryDeployCardView", html)
        self.assertIn("inventoryDeployCardFontSize", html)
        self.assertIn("inventoryDeployCardWidth", html)
        self.assertIn("inventoryDeployCardHeight", html)
        self.assertIn("inventoryDeployScopeFilter", html)
        self.assertIn("inventoryDeployInstallFilter", html)
        self.assertIn("syncInventoryDeployFilterTabs", html)
        self.assertIn('$("inventoryDeployScopeTabs").addEventListener("click"', html)
        self.assertIn('$("inventoryDeployInstallTabs").addEventListener("click"', html)
        self.assertIn("--inventory-source-card-font-size", html)
        self.assertIn("--inventory-deploy-card-font-size", html)


if __name__ == "__main__":
    unittest.main()
