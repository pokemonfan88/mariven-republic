import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from events_model import events_step


class EventsTests(unittest.TestCase):
    def test_same_named_streams_produce_same_events(self):
        state = {"population": 1_200_000, "government": {}}
        weather = {"condition": "晴"}

        def factory(name):
            return random.Random("2026-08-12:" + name)

        first = events_step(date(2026, 8, 12), state, weather, factory)
        second = events_step(date(2026, 8, 12), state, weather, factory)
        self.assertEqual(first, second)

    def test_unrelated_random_draw_does_not_change_events(self):
        random.Random(123).random()
        state = {"population": 1_200_000, "government": {}}
        weather = {"condition": "晴"}

        def factory(name):
            return random.Random("2026-08-12:" + name)

        expected = events_step(date(2026, 8, 12), state, weather, factory)
        random.Random(999).random()
        self.assertEqual(expected, events_step(
            date(2026, 8, 12), state, weather, factory,
        ))


if __name__ == "__main__":
    unittest.main()
