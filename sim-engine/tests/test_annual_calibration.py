import json
import math
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick


ROOT = Path(__file__).resolve().parents[1]
CITY_RAIN_ORDER = ("makadi_port", "katora", "timo", "pela", "ruwa")
CITY_TEMP_ORDER = ("timo", "ruwa", "katora", "pela", "makadi_port")


class AnnualCalibrationTests(unittest.TestCase):
    def test_full_year_climate_and_economy_invariants(self):
        resources = EngineResources.load(ROOT / "data")
        state = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
        rainfall = defaultdict(float)
        city_temps = defaultdict(list)
        monthly_temps = defaultdict(list)
        monthly_rain = defaultdict(float)
        population_flows = defaultdict(int)
        releases = 0
        for _ in range(365):
            state = tick(state, resources=resources)
            month = int(state["date"][5:7])
            katora = state["weather"]["katora"]
            for city in CITY_RAIN_ORDER:
                rainfall[city] += state["weather"][city]["rainfall_mm"]
                city_temps[city].append(
                    state["weather"][city]["temp_high"]
                )
            monthly_rain[month] += katora["rainfall_mm"]
            monthly_temps[month].append(katora["temp_high"])
            releases += int(state["economy"]["cpi"]["is_release_day"])
            demographics = state["demographics"]
            for key in (
                "births_today",
                "baseline_deaths_today",
                "returning_diaspora_today",
                "foreign_immigrants_today",
                "emigrants_today",
                "excess_deaths_today",
            ):
                population_flows[key] += demographics[key]
            self.assertTrue(1.80 <= state["economy"]["exchange_rate_mvl_per_usd"] <= 2.80)
            json.dumps(state, ensure_ascii=False, allow_nan=False)
        self.assertTrue(2240 <= rainfall["katora"] <= 3360, rainfall)
        for drier, wetter in zip(CITY_RAIN_ORDER, CITY_RAIN_ORDER[1:]):
            self.assertLess(rainfall[drier], rainfall[wetter], rainfall)
        annual_temp_means = {
            city: sum(city_temps[city]) / len(city_temps[city])
            for city in CITY_TEMP_ORDER
        }
        for cooler, warmer in zip(CITY_TEMP_ORDER, CITY_TEMP_ORDER[1:]):
            self.assertLess(
                annual_temp_means[cooler],
                annual_temp_means[warmer],
                annual_temp_means,
            )
        wet = sum(monthly_rain[m] for m in (11, 12, 1, 2, 3, 4))
        dry = sum(monthly_rain[m] for m in (5, 6, 7, 8, 9, 10))
        self.assertGreater(wet, dry)
        means = {m: sum(v) / len(v) for m, v in monthly_temps.items()}
        self.assertIn(max(means, key=means.get), (12, 1, 2))
        self.assertIn(min(means, key=means.get), (6, 7, 8))
        self.assertEqual(releases, 12)
        self.assertEqual(
            dict(population_flows),
            {
                "births_today": 27_500,
                "baseline_deaths_today": 6_600,
                "returning_diaspora_today": 2_500,
                "foreign_immigrants_today": 2_200,
                "emigrants_today": 2_800,
                "excess_deaths_today": 0,
            },
        )
        self.assertEqual(state["population"], 1_222_800)


if __name__ == "__main__":
    unittest.main()
