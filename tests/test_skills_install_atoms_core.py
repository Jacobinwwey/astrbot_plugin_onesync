from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_install_atoms_core import (
    apply_install_atom_registry,
    build_install_atom_registry,
    normalize_install_atom_registry,
)


class SkillsInstallAtomsCoreTests(unittest.TestCase):
    def test_normalize_install_atom_registry_builds_counts(self) -> None:
        normalized = normalize_install_atom_registry(
            {
                "version": 1,
                "generated_at": "2026-04-10T00:00:00+00:00",
                "install_atoms": [
                    {
                        "install_unit_id": "npm:@demo/pack",
                        "display_name": "@demo/pack",
                        "evidence_level": "explicit",
                        "resolution_status": "resolved",
                    },
                    {
                        "install_unit_id": "synthetic_single:demo",
                        "display_name": "demo",
                        "evidence_level": "unresolved",
                        "resolution_status": "unresolved",
                    },
                ],
            },
        )

        self.assertEqual(2, normalized["counts"]["install_atom_total"])
        self.assertEqual(1, normalized["counts"]["resolved_total"])
        self.assertEqual(1, normalized["counts"]["unresolved_total"])
        self.assertEqual(1, normalized["counts"]["explicit_total"])

    def test_build_install_atom_registry_infers_evidence_from_provenance(self) -> None:
        install_unit_rows = [
            {
                "install_unit_id": "npm:@every-env/compound-plugin",
                "display_name": "Compound Engineering",
                "install_unit_kind": "npm_package",
                "collection_group_id": "collection:compound_engineering",
                "source_ids": ["npx_bundle_compound_engineering_global"],
                "source_count": 1,
                "member_count": 24,
                "provenance_state": "resolved",
                "provenance_note_kind": "",
                "provenance_primary_origin_kind": "registry_package",
                "provenance_primary_origin_ref": "@every-env/compound-plugin",
                "provenance_primary_origin_label": "Compound Engineering",
                "provenance_primary_package_name": "@every-env/compound-plugin",
                "provenance_package_strategy": "cache_path_heuristic",
                "aggregation_strategy": "provenance_package",
            },
            {
                "install_unit_id": "synthetic_single:npx_global_find_skills",
                "display_name": "find-skills",
                "install_unit_kind": "synthetic_single",
                "collection_group_id": "collection:find_skills",
                "source_ids": ["npx_global_find_skills"],
                "source_count": 1,
                "member_count": 1,
                "provenance_state": "unresolved",
                "provenance_note_kind": "legacy_root_only",
                "provenance_primary_origin_kind": "skills_root",
                "provenance_primary_origin_ref": "/root/.agents/skills",
                "provenance_primary_origin_label": "Agents Skills Root",
                "provenance_primary_package_name": "",
                "aggregation_strategy": "synthetic_single",
            },
        ]

        registry = build_install_atom_registry(
            install_unit_rows,
            [],
            generated_at="2026-04-10T00:00:00+00:00",
        )
        install_atoms = {
            item["install_unit_id"]: item
            for item in registry["install_atoms"]
        }

        self.assertEqual("explicit", install_atoms["npm:@every-env/compound-plugin"]["evidence_level"])
        self.assertEqual("resolved", install_atoms["npm:@every-env/compound-plugin"]["resolution_status"])
        self.assertEqual("unresolved", install_atoms["synthetic_single:npx_global_find_skills"]["evidence_level"])
        self.assertEqual("unresolved", install_atoms["synthetic_single:npx_global_find_skills"]["resolution_status"])

    def test_apply_install_atom_registry_adds_aggregation_fields(self) -> None:
        install_unit_rows = [
            {
                "install_unit_id": "npm:@every-env/compound-plugin",
                "display_name": "Compound Engineering",
            },
        ]
        install_atom_registry = {
            "version": 1,
            "generated_at": "2026-04-10T00:00:00+00:00",
            "install_atoms": [
                {
                    "install_unit_id": "npm:@every-env/compound-plugin",
                    "display_name": "Compound Engineering",
                    "evidence_level": "explicit",
                    "resolution_status": "resolved",
                    "evidence_score": 100,
                    "resolver_path": "provenance:cache_path_heuristic",
                    "first_seen_at": "2026-04-09T00:00:00+00:00",
                    "last_changed_at": "2026-04-10T00:00:00+00:00",
                },
            ],
        }

        rows = apply_install_atom_registry(install_unit_rows, install_atom_registry)
        row = rows[0]
        self.assertEqual("explicit", row["aggregation_evidence_level"])
        self.assertEqual("resolved", row["aggregation_resolution_status"])
        self.assertEqual("provenance:cache_path_heuristic", row["aggregation_resolver_path"])
        self.assertEqual(100, row["aggregation_evidence_score"])


if __name__ == "__main__":
    unittest.main()
