import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from random_streams import derive_seed, make_rng


class RandomStreamsTests(unittest.TestCase):
    def test_seed_is_stable(self):
        args = (42, 2, date(2026, 7, 14), "weather", "condition")
        self.assertEqual(derive_seed(*args), derive_seed(*args))

    def test_stream_names_are_isolated(self):
        a = make_rng(42, 2, date(2026, 7, 14), "weather", "condition")
        b = make_rng(42, 2, date(2026, 7, 14), "weather", "rain")
        self.assertNotEqual([a.random() for _ in range(4)], [b.random() for _ in range(4)])

    def test_global_random_state_is_untouched(self):
        random.seed(991)
        expected = random.random()
        random.seed(991)
        make_rng(42, 2, date(2026, 7, 14), "exchange").random()
        self.assertEqual(random.random(), expected)


if __name__ == "__main__":
    unittest.main()
