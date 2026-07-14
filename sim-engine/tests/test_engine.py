import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick


ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = EngineResources.load(ROOT / "data")
        cls.v1 = json.loads(
            (ROOT / "data" / "state.json").read_text(encoding="utf-8")
        )

    def test_tick_does_not_mutate_input_and_is_deterministic(self):
        original = copy.deepcopy(self.v1)
        first = tick(self.v1, resources=self.resources)
        second = tick(self.v1, resources=self.resources)
        self.assertEqual(self.v1, original)
        self.assertEqual(first, second)

    def test_tick_uses_all_p0_models(self):
        result = tick(self.v1, resources=self.resources)
        self.assertEqual(result["schema_version"], 2)
        self.assertIn("katora", result["weather"])
        self.assertIn("exchange_rates", result["economy"])
        self.assertIn("commodities", result["economy"])
        self.assertIn("cpi", result["economy"])
        self.assertEqual(
            result["economy"]["inflation_pct"],
            result["economy"]["cpi"]["yoy_pct"],
        )

    def test_serialized_resume_matches_continuous_run(self):
        day1 = tick(self.v1, resources=self.resources)
        continuous = tick(day1, resources=self.resources)
        reloaded = json.loads(json.dumps(day1, ensure_ascii=False))
        resumed = tick(reloaded, resources=self.resources)
        self.assertEqual(continuous, resumed)

    def test_tick_preserves_unknown_model_state(self):
        previous = tick(self.v1, resources=self.resources)
        future_state = {"nested": {"trend": [1.0, 2.0, 3.0]}}
        previous["model_state"]["gdp"] = copy.deepcopy(future_state)

        result = tick(previous, resources=self.resources)

        self.assertEqual(result["model_state"]["gdp"], future_state)

    def test_events_receive_fully_integrated_current_day_state(self):
        captured = {}

        def capture_events(d, state, weather, rng_factory):
            del rng_factory
            captured["date"] = d
            captured["state"] = copy.deepcopy(state)
            captured["weather"] = copy.deepcopy(weather)
            return {"total": 0}, []

        with patch("engine.events_step", side_effect=capture_events):
            result = tick(self.v1, resources=self.resources)

        self.assertEqual(captured["date"], date(2026, 8, 12))
        self.assertEqual(captured["state"]["date"], result["date"])
        self.assertEqual(captured["state"]["weather"], result["weather"])
        self.assertEqual(captured["weather"], result["weather"])
        self.assertEqual(captured["state"]["economy"], result["economy"])
        self.assertEqual(
            captured["state"]["model_state"], result["model_state"]
        )

    def test_tick_output_is_strict_json(self):
        result = tick(self.v1, resources=self.resources)

        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)

        self.assertIsInstance(encoded, str)


if __name__ == "__main__":
    unittest.main()
