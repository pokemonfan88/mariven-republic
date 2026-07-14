import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from commodities_model import CommoditySeries, DataSourceError, commodities_step


DATA = Path(__file__).resolve().parents[1] / "data" / "commodities_real.csv"


class CommodityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series = CommoditySeries.from_csv(DATA)

    def test_future_date_uses_last_real_observation(self):
        public, state, events = commodities_step(date(2026, 7, 14), {}, self.series)
        self.assertEqual(public["source_month"], "2024-12")
        self.assertAlmostEqual(public["brent_usd_barrel"], 73.833, places=3)
        self.assertTrue(public["is_stale"])
        self.assertGreater(public["staleness_days"], 365)
        self.assertEqual(state["source_month"], "2024-12")
        self.assertEqual(events, [])

    def test_sugar_is_converted_from_kg_to_lb(self):
        obs = self.series.lookup(date(2024, 12, 1))
        self.assertAlmostEqual(obs.sugar_usd_lb, 0.1979, places=4)

    def test_missing_required_column_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("date,gold_usd_oz\n2024-12,2648.01\n", encoding="utf-8")
            with self.assertRaisesRegex(DataSourceError, "sugar_usd_kg"):
                CommoditySeries.from_csv(path)


if __name__ == "__main__":
    unittest.main()
