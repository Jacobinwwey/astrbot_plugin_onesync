from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_HTML = REPO_ROOT / "webui" / "index.html"


class WebUIInventoryRegistryHostsTests(unittest.TestCase):
    def test_inventory_panel_exposes_registry_and_host_metadata_strings(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventory_summary_registry_hosts", html)
        self.assertIn("inventory_summary_provenance", html)
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
        self.assertIn("source_provenance_resolved_total", html)
        self.assertIn("source_provenance_unresolved_total", html)

    def test_inventory_panel_exposes_provenance_labels_and_helpers(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventory_skill_meta_provenance", html)
        self.assertIn("inventory_skill_meta_origin", html)
        self.assertIn("inventory_skill_meta_package", html)
        self.assertIn("inventory_skill_meta_confidence", html)
        self.assertIn("inventory_provenance_resolved", html)
        self.assertIn("inventory_provenance_unresolved", html)
        self.assertIn("inventory_provenance_partial", html)
        self.assertIn("inventory_provenance_legacy_note", html)
        self.assertIn("function inventorySourceProvenanceSummary(", html)
        self.assertIn("function inventorySourceProvenanceStateLabel(", html)

    def test_inventory_panel_exposes_manual_source_boundary_labels(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("inventory_skill_meta_subpaths", html)
        self.assertIn("inventory_aggregate_kind_source_repo", html)
        self.assertIn("inventory_aggregate_kind_source_root", html)
        self.assertIn("function inventorySourceSubpathSummary(", html)
        self.assertIn("inventory_boundary_title", html)
        self.assertIn("inventory_boundary_collection", html)
        self.assertIn("inventory_boundary_install_unit", html)
        self.assertIn("inventory_boundary_fanout", html)
        self.assertIn("inventory_boundary_subpaths", html)
        self.assertIn("function inventoryBoundaryNotes(", html)

    def test_inventory_panel_exposes_collection_group_fanout_action_note(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("fan out", html)
        self.assertIn("扇出", html)
        self.assertIn("subpathCount", html)

    def test_inventory_panel_exposes_install_unit_drilldown_panel(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventorySourceInstallUnitBar"', html)
        self.assertIn('id="inventoryInstallUnitsTitle"', html)
        self.assertIn('id="inventoryInstallUnitsNote"', html)
        self.assertIn('id="inventorySourceInstallUnitRows"', html)
        self.assertIn("inventory_install_units_title", html)
        self.assertIn("inventory_install_units_note", html)
        self.assertIn("inventory_install_units_collection", html)
        self.assertIn("inventory_install_units_empty", html)
        self.assertIn("inventorySelectedDetailInstallUnitId", html)
        self.assertIn("data-inventory-install-unit-id", html)

    def test_inventory_panel_exposes_detail_scope_tabs_and_fanout_preview(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventorySourceDetailScopeTabs"', html)
        self.assertIn('id="inventorySourceDetailScopeCollection"', html)
        self.assertIn('id="inventorySourceDetailScopeInstallUnit"', html)
        self.assertIn('id="inventoryFanoutPreviewBar"', html)
        self.assertIn('id="inventoryFanoutPreviewTitle"', html)
        self.assertIn('id="inventoryFanoutPreviewRows"', html)
        self.assertIn("inventory_detail_scope_title", html)
        self.assertIn("inventory_detail_scope_collection", html)
        self.assertIn("inventory_detail_scope_install_unit", html)
        self.assertIn("inventory_fanout_preview_title", html)
        self.assertIn("inventory_fanout_preview_collection", html)
        self.assertIn("inventory_fanout_preview_direct", html)
        self.assertIn("syncInventorySourceDetailScopeTabs()", html)

    def test_inventory_panel_exposes_operation_plan_preview(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn('id="inventoryOperationPlanBar"', html)
        self.assertIn('id="inventoryOperationPlanTitle"', html)
        self.assertIn('id="inventoryOperationPlanRows"', html)
        self.assertIn("inventory_operation_plan_title", html)
        self.assertIn("inventory_operation_plan_ready", html)
        self.assertIn("inventory_operation_plan_unsupported", html)
        self.assertIn("renderInventoryOperationPlan(", html)

    def test_inventory_panel_doctor_summary_reads_aggregate_health(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("install_ready", html)
        self.assertIn("install_missing", html)
        self.assertIn("provenance_resolved", html)
        self.assertIn("provenance_partial", html)
        self.assertIn("provenance_unresolved", html)
        self.assertIn("group_ready", html)
        self.assertIn("group_missing", html)
        self.assertIn("doctor.install_unit_health", html)
        self.assertIn("doctor.install_unit_sync", html)
        self.assertIn("doctor.provenance_health", html)
        self.assertIn("doctor.collection_group_health", html)
        self.assertIn("doctor.collection_group_sync", html)

    def test_inventory_panel_supports_aggregate_selection_rows(self) -> None:
        html = WEBUI_HTML.read_text(encoding="utf-8")

        self.assertIn("meaningful_collection_group_rows", html)
        self.assertIn("compatible_meaningful_collection_group_rows_by_software", html)
        self.assertIn("collection_group_rows", html)
        self.assertIn("install_unit_rows", html)
        self.assertIn("data-inventory-source-ids", html)
        self.assertIn("inventorySourceHero", html)
        self.assertIn("/api/skills/install-units/", html)
        self.assertIn("/api/skills/collections/", html)
        self.assertIn('id="inventoryRefreshInstallUnitBtn"', html)
        self.assertIn('id="inventorySyncInstallUnitBtn"', html)
        self.assertIn('id="inventoryUpdateInstallUnitBtn"', html)
        self.assertIn('id="inventoryDeployInstallUnitBtn"', html)
        self.assertIn('id="inventoryRepairInstallUnitBtn"', html)
        self.assertIn("refreshSelectedSourceAggregate()", html)
        self.assertIn("syncSelectedSourceAggregate()", html)
        self.assertIn("updateSelectedSourceAggregate()", html)
        self.assertIn("deploySelectedSourceAggregate()", html)
        self.assertIn("repairSelectedSourceAggregate()", html)
        self.assertIn("/api/skills/install-units/", html)
        self.assertIn("/refresh", html)
        self.assertIn("/repair", html)
        self.assertIn("/sync", html)
        self.assertIn("/update", html)
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
