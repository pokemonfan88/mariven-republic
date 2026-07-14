import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from exchange_model import FxDataset, exchange_step


DATA = Path(__file__).resolve().parents[1] / "data"


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


if __name__ == "__main__":
    unittest.main()
