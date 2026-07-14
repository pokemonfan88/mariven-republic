import random
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from exchange_model import FxDataError, FxDataset, exchange_step


DATA = Path(__file__).resolve().parents[1] / "data"


class FixedShock:
    def __init__(self, value):
        self.value = value

    def gauss(self, mean, standard_deviation):
        del mean, standard_deviation
        return self.value


def write_fx_dataset(directory, overrides=None):
    overrides = overrides or {}
    sources = {
        "aud_usd.csv": "EXUSAL",
        "nzd_usd.csv": "EXUSNZ",
        "usd_cny.csv": "EXCHUS",
        "eur_usd.csv": "EXUSEU",
    }
    for filename, column in sources.items():
        value = overrides.get(filename, "1.0")
        (directory / filename).write_text(
            f"observation_date,{column}\n2026-06-01,{value}\n",
            encoding="utf-8",
        )


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = FxDataset.from_directory(DATA)

    def test_source_quotes_are_normalized_to_usd_per_unit(self):
        rates, months = self.dataset.rates_for(date(2026, 7, 14))
        self.assertAlmostEqual(rates["AUD"], 0.7025, places=4)
        self.assertAlmostEqual(rates["CNY"], 1 / 6.7758, places=7)
        self.assertEqual(months["AUD"], "2026-06")

    def test_cross_rates_multiply_canonical_quotes(self):
        public, next_state, _ = exchange_step(
            date(2026, 7, 14), {"mvl_per_usd": 2.2390},
            self.dataset, random.Random(5),
        )
        self.assertAlmostEqual(
            public["mvl_per_aud"],
            public["mvl_per_usd"] * public["usd_per_aud"], places=4,
        )
        self.assertAlmostEqual(
            public["mvl_per_eur"],
            public["mvl_per_usd"] * public["usd_per_eur"], places=4,
        )
        self.assertEqual(next_state["mvl_per_usd"], public["mvl_per_usd"])

    def test_repeated_input_and_rng_are_deterministic(self):
        args = (date(2026, 7, 14), {"mvl_per_usd": 2.18}, self.dataset)
        self.assertEqual(exchange_step(*args, random.Random(7)),
                         exchange_step(*args, random.Random(7)))

    def test_non_finite_previous_rates_fail(self):
        cases = (
            ("nan", float("nan")),
            ("positive infinity", float("inf")),
            ("negative infinity", float("-inf")),
            ("oversized integer", 10**10000),
        )
        for label, value in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(
                    ValueError, "mvl_per_usd must be a finite real number"
                ):
                    exchange_step(
                        date(2026, 7, 14), {"mvl_per_usd": value},
                        self.dataset, random.Random(7),
                    )

    def test_non_finite_rng_shocks_fail(self):
        cases = (
            ("nan", float("nan")),
            ("positive infinity", float("inf")),
            ("negative infinity", float("-inf")),
            ("oversized integer", 10**10000),
        )
        for label, value in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(
                    ValueError, "RNG shock must be a finite real number"
                ):
                    exchange_step(
                        date(2026, 7, 14), {"mvl_per_usd": 2.18},
                        self.dataset, FixedShock(value),
                    )

    def test_non_finite_target_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_fx_dataset(data_dir)
            source_dataset = FxDataset.from_directory(data_dir)
            dataset = FxDataset(
                source_dataset._series,
                {currency: 1e-308 for currency in source_dataset.base_rates},
                source_dataset.calibration_month,
            )
            with self.assertRaisesRegex(
                ValueError, "exchange-rate target must be a finite real number"
            ):
                exchange_step(
                    date(2026, 7, 14), {"mvl_per_usd": 2.18},
                    dataset, FixedShock(0.0),
                )

    def test_non_finite_derived_rate_fails(self):
        with self.assertRaisesRegex(
            ValueError, "derived mvl_per_usd must be a finite real number"
        ):
            exchange_step(
                date(2026, 7, 14), {"mvl_per_usd": sys.float_info.max},
                self.dataset, FixedShock(sys.float_info.max),
            )

    def test_cny_reciprocal_overflow_fails_during_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_fx_dataset(data_dir, {"usd_cny.csv": "5e-324"})
            with self.assertRaisesRegex(
                FxDataError, "canonical CNY rate must be finite"
            ):
                FxDataset.from_directory(data_dir)

    def test_invalid_basket_log_input_has_labeled_error(self):
        dataset = FxDataset(
            self.dataset._series,
            {**self.dataset.base_rates, "AUD": 0.0},
            self.dataset.calibration_month,
        )
        with self.assertRaisesRegex(
            ValueError, "AUD basket base quote must be a finite positive real number"
        ):
            exchange_step(
                date(2026, 7, 14), {"mvl_per_usd": 2.18},
                dataset, FixedShock(0.0),
            )

    def test_public_cross_rate_overflow_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_fx_dataset(data_dir, {"aud_usd.csv": "1e308"})
            dataset = FxDataset.from_directory(data_dir)
            with self.assertRaisesRegex(
                ValueError, "mvl_per_aud must be a finite real number"
            ):
                exchange_step(
                    date(2026, 7, 1), {"mvl_per_usd": 2.18},
                    dataset, FixedShock(0.0),
                )


if __name__ == "__main__":
    unittest.main()
