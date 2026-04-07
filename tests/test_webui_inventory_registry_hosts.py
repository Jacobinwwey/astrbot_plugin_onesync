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

    def test_inventory_panel_doctor_summary_reads_aggregate_health(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("install_ready", html)
        self.assertIn("install_missing", html)
        self.assertIn("group_ready", html)
        self.assertIn("group_missing", html)
        self.assertIn("doctor.install_unit_health", html)
        self.assertIn("doctor.install_unit_sync", html)
        self.assertIn("doctor.collection_group_health", html)
        self.assertIn("doctor.collection_group_sync", html)

    def test_inventory_panel_supports_aggregate_selection_rows(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("collection_group_rows", html)
        self.assertIn("install_unit_rows", html)
        self.assertIn("data-inventory-source-ids", html)
        self.assertIn("inventorySourceHero", html)
        self.assertIn("/api/skills/install-units/", html)
        self.assertIn("/api/skills/collections/", html)
        self.assertIn('id="inventoryRefreshInstallUnitBtn"', html)
        self.assertIn('id="inventorySyncInstallUnitBtn"', html)
        self.assertIn('id="inventoryDeployInstallUnitBtn"', html)
        self.assertIn('id="inventoryRepairInstallUnitBtn"', html)
        self.assertIn("refreshSelectedSourceAggregate()", html)
        self.assertIn("syncSelectedSourceAggregate()", html)
        self.assertIn("deploySelectedSourceAggregate()", html)
        self.assertIn("repairSelectedSourceAggregate()", html)
        self.assertIn("/api/skills/install-units/", html)
        self.assertIn("/refresh", html)
        self.assertIn("/repair", html)
        self.assertIn("/sync", html)
        self.assertIn("/deploy", html)

    def test_inventory_panel_exposes_source_import_wizard_strings_and_hooks(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventoryImportSourceBtn"', html)
        self.assertIn('id="inventoryImportModal"', html)
        self.assertIn('id="inventoryImportSourceKind"', html)
        self.assertIn('id="inventoryImportLocatorInput"', html)
        self.assertIn('id="inventoryImportSubpathInput"', html)
        self.assertIn("openInventoryImportModal()", html)
        self.assertIn("submitInventoryImport()", html)
        self.assertIn("inventory_import_open", html)
        self.assertIn("inventory_import_subpath", html)


if __name__ == "__main__":
    unittest.main()
