import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick
from weather_model import weather_step as real_weather_step


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

    def test_tick_weather_alert_texts_are_unique(self):
        cases = (
            ("阵雨", "午后阵雨——预计持续1-2小时"),
            ("暴雨", "暴雨预警——卡托拉市低洼区注意积水"),
        )
        rain_alerts = {text for _, text in cases}

        for condition, expected_alert in cases:
            with self.subTest(condition=condition):
                def forced_weather(*args, **kwargs):
                    public, state, events = real_weather_step(*args, **kwargs)
                    public["condition"] = condition
                    public["katora"]["condition"] = condition
                    events = [
                        event for event in events
                        if event.get("text") not in rain_alerts
                    ]
                    events.append({
                        "type": "weather",
                        "severity": (
                            "warning" if condition == "暴雨" else "info"
                        ),
                        "text": expected_alert,
                    })
                    return public, state, events

                with patch("engine.weather_step", side_effect=forced_weather):
                    result = tick(self.v1, resources=self.resources)

                texts = [event["text"] for event in result["events_today"]]
                self.assertEqual(texts.count(expected_alert), 1, texts)
                self.assertEqual(len(texts), len(set(texts)), texts)


if __name__ == "__main__":
    unittest.main()
