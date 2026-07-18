import json
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


if __name__ == "__main__":
    unittest.main()
