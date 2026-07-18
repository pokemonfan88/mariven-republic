import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE_PATH = ROOT / "data" / "dengue_baseline_2026.json"
SOURCE_PATH = (
    ROOT / "data" / "sources" / "dengue_external_anchors_2026.json"
)

try:
    from build_dengue_baseline import build_baseline
except ImportError:
    build_baseline = None

try:
    import dengue_model
except ImportError:
    dengue_model = None

DengueBaseline = getattr(dengue_model, "DengueBaseline", None)
DengueDataError = getattr(dengue_model, "DengueDataError", None)


class DengueBaselineBuilderTests(unittest.TestCase):
    def test_builder_is_available(self):
        self.assertIsNotNone(build_baseline)

    def test_committed_baseline_is_reproducible(self):
        self.assertTrue(BASELINE_PATH.exists())
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(build_baseline(), expected)

    def test_anchor_totals_and_provenance(self):
        self.assertTrue(SOURCE_PATH.exists())
        baseline = build_baseline()

        self.assertEqual(sum(baseline["provinces"].values()), 1_200_000)
        self.assertEqual(
            sum(
                baseline["historical_2026"][
                    "reported_by_province"
                ].values()
            ),
            1_240,
        )
        self.assertEqual(
            baseline["wmar1"]["other_provinces_coverage"], 0.0
        )
        self.assertEqual(
            baseline["metadata"]["source_classes"]["wmar1"],
            "fictional_intervention",
        )


class DengueBaselineTests(unittest.TestCase):
    def test_module_exposes_labeled_loader(self):
        self.assertIsNotNone(DengueBaseline)
        self.assertIsNotNone(DengueDataError)
        self.assertTrue(issubclass(DengueDataError, RuntimeError))
        self.assertTrue(hasattr(DengueBaseline, "from_json"))
        self.assertTrue(hasattr(DengueBaseline, "from_mapping"))

    def test_loader_exposes_complete_dimensions(self):
        self.assertIsNotNone(DengueBaseline)
        baseline = DengueBaseline.from_json(BASELINE_PATH)

        self.assertEqual(
            baseline.age_groups,
            ("0-4", "5-14", "15-29", "30-59", "60+"),
        )
        self.assertEqual(
            baseline.serotypes,
            ("DENV-1", "DENV-2", "DENV-3", "DENV-4"),
        )
        self.assertEqual(sum(baseline.province_populations.values()), 1_200_000)
        self.assertEqual(baseline.anchor_date.isoformat(), "2026-08-11")

    def test_loader_rejects_bad_mobility_row(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["mobility"]["katora"]["katora"] -= 0.1

        with self.assertRaisesRegex(
            DengueDataError, r"^baseline\.mobility\.katora"
        ):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_unknown_version(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["version"] = "unknown"

        with self.assertRaisesRegex(DengueDataError, r"^baseline\.version"):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_non_finite_probability(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["transmission"]["mosquito_to_human"] = math.nan

        with self.assertRaisesRegex(
            DengueDataError,
            r"^baseline\.transmission\.mosquito_to_human",
        ):
            DengueBaseline.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
