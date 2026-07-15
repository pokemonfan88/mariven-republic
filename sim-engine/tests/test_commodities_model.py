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
        self.assertEqual(public["staleness_days"], 560)
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

    def test_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.csv"
            with self.assertRaisesRegex(
                DataSourceError, "cannot read commodity data"
            ):
                CommoditySeries.from_csv(path)

    def test_conflicting_duplicate_month_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.csv"
            path.write_text(
                "date,sugar_usd_kg,gold_usd_oz,brent_usd_bbl\n"
                "2024-12,0.4364,2648.01,73.833\n"
                "2024-12,0.4364,2648.01,74.000\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DataSourceError, "conflicting observations for month 2024-12"
            ):
                CommoditySeries.from_csv(path)

    def test_invalid_month_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-month.csv"
            path.write_text(
                "date,sugar_usd_kg,gold_usd_oz,brent_usd_bbl\n"
                "2024-13,0.4364,2648.01,73.833\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DataSourceError, "invalid commodity month '2024-13'"
            ):
                CommoditySeries.from_csv(path)

    def test_empty_dataset_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.csv"
            path.write_text(
                "date,sugar_usd_kg,gold_usd_oz,brent_usd_bbl\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DataSourceError, "contains no observations"
            ):
                CommoditySeries.from_csv(path)

    def test_lookup_before_first_observation_fails(self):
        with self.assertRaisesRegex(
            DataSourceError,
            "no commodity observation exists on or before 1959-12-31",
        ):
            self.series.lookup(date(1959, 12, 31))

    def test_non_finite_prices_fail(self):
        cases = (
            ("sugar_usd_kg", "nan"),
            ("gold_usd_oz", "inf"),
            ("brent_usd_bbl", "-inf"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            for column, invalid_value in cases:
                with self.subTest(column=column, value=invalid_value):
                    values = {
                        "sugar_usd_kg": "0.4364",
                        "gold_usd_oz": "2648.01",
                        "brent_usd_bbl": "73.833",
                    }
                    values[column] = invalid_value
                    path.write_text(
                        "date,sugar_usd_kg,gold_usd_oz,brent_usd_bbl\n"
                        f"2024-12,{values['sugar_usd_kg']},{values['gold_usd_oz']},"
                        f"{values['brent_usd_bbl']}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(DataSourceError, column):
                        CommoditySeries.from_csv(path)


if __name__ == "__main__":
    unittest.main()
