import random
import statistics
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from weather_model import (
    SoiSeries, coral_bleaching_risk, temperature_baseline, weather_step,
)


DATA = Path(__file__).resolve().parents[1] / "data" / "soi_monthly.csv"


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.soi = SoiSeries.from_csv(DATA)

    def test_southern_temperature_phase(self):
        self.assertGreater(temperature_baseline(date(2026, 1, 30)),
                           temperature_baseline(date(2026, 5, 1)))
        self.assertLess(temperature_baseline(date(2026, 7, 30)),
                        temperature_baseline(date(2026, 10, 30)))

    def test_soi_does_not_read_future(self):
        value, month = self.soi.value_for(date(1990, 12, 1))
        self.assertIsNone(value)
        self.assertIsNone(month)

    def test_standard_gamma_sampler_has_expected_mean(self):
        rng = random.Random(123)
        values = [rng.gammavariate(0.8, 1.2) for _ in range(20_000)]
        self.assertAlmostEqual(statistics.fmean(values), 0.96, delta=0.04)

    def test_critical_coral_risk_is_reachable(self):
        self.assertEqual(coral_bleaching_risk(date(2026, 3, 1), 30.0), "critical")

    def test_step_emits_critical_coral_event_during_strong_el_nino_peak(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "strong_el_nino.csv"
            source.write_text(
                "Year,Month,SOI\n2026,3,-20.0\n",
                encoding="utf-8",
            )
            strong_el_nino = SoiSeries.from_csv(source)

        def factory(name):
            return random.Random("2026-03-01:" + name)

        public, _, events = weather_step(
            date(2026, 3, 1),
            {"previous_conditions": {}, "rainfall_history": []},
            strong_el_nino,
            factory,
        )
        critical_event = any(
            event["type"] == "weather" and event["severity"] == "critical"
            for event in events
        )
        self.assertEqual(
            ("critical", True),
            (public["coral_bleaching_risk"], critical_event),
        )

    def test_step_is_deterministic_and_outputs_five_cities(self):
        previous = {"previous_conditions": {}, "rainfall_history": []}

        def factory(name):
            return random.Random("2026-07-14:" + name)

        first = weather_step(date(2026, 7, 14), previous, self.soi, factory)
        second = weather_step(date(2026, 7, 14), previous, self.soi, factory)
        self.assertEqual(first, second)
        public = first[0]
        self.assertEqual(
            {"katora", "makadi_port", "timo", "pela", "ruwa"},
            {key for key in public if key in {
                "katora", "makadi_port", "timo", "pela", "ruwa"
            }},
        )
        self.assertEqual(public["condition"], public["katora"]["condition"])


if __name__ == "__main__":
    unittest.main()
