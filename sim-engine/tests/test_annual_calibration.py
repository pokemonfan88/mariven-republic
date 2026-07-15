import json
import math
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick


ROOT = Path(__file__).resolve().parents[1]


class AnnualCalibrationTests(unittest.TestCase):
    def test_full_year_climate_and_economy_invariants(self):
        resources = EngineResources.load(ROOT / "data")
        state = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
        rainfall = 0.0
        monthly_temps = defaultdict(list)
        monthly_rain = defaultdict(float)
        releases = 0
        for _ in range(365):
            state = tick(state, resources=resources)
            month = int(state["date"][5:7])
            katora = state["weather"]["katora"]
            rainfall += katora["rainfall_mm"]
            monthly_rain[month] += katora["rainfall_mm"]
            monthly_temps[month].append(katora["temp_high"])
            releases += int(state["economy"]["cpi"]["is_release_day"])
            self.assertTrue(1.80 <= state["economy"]["exchange_rate_mvl_per_usd"] <= 2.80)
            json.dumps(state, ensure_ascii=False, allow_nan=False)
        self.assertTrue(2240 <= rainfall <= 3360, rainfall)
        wet = sum(monthly_rain[m] for m in (11, 12, 1, 2, 3, 4))
        dry = sum(monthly_rain[m] for m in (5, 6, 7, 8, 9, 10))
        self.assertGreater(wet, dry)
        means = {m: sum(v) / len(v) for m, v in monthly_temps.items()}
        self.assertIn(max(means, key=means.get), (12, 1, 2))
        self.assertIn(min(means, key=means.get), (6, 7, 8))
        self.assertEqual(releases, 12)


if __name__ == "__main__":
    unittest.main()
