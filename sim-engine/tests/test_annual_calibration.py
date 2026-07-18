import copy
import json
import math
import random
import sys
import unittest
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from dengue_dynamics import total_humans
from dengue_model import (
    DengueBaseline,
    dengue_step,
    initialize_dengue_state,
    validate_dengue_state,
)
from engine import EngineResources, tick
from random_streams import make_rng
from state import prepare_state
from weather_model import weather_step


ROOT = Path(__file__).resolve().parents[1]
CITY_RAIN_ORDER = ("makadi_port", "katora", "timo", "pela", "ruwa")
CITY_TEMP_ORDER = ("timo", "ruwa", "katora", "pela", "makadi_port")


class AnnualCalibrationTests(unittest.TestCase):
    _paired_cache = None

    @classmethod
    def setUpClass(cls):
        cls.resources = EngineResources.load(ROOT / "data")
        cls.base_state = json.loads(
            (ROOT / "data" / "state.json").read_text(encoding="utf-8")
        )

    def test_full_year_climate_and_economy_invariants(self):
        resources = self.resources
        state = copy.deepcopy(self.base_state)
        rainfall = defaultdict(float)
        city_temps = defaultdict(list)
        monthly_temps = defaultdict(list)
        monthly_rain = defaultdict(float)
        population_flows = defaultdict(int)
        releases = 0
        reported_2026 = None
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
            if state["date"] == "2026-12-31":
                reported_2026 = state["model_state"]["dengue"][
                    "cumulative_annual"
                ]["reported"]
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
        self.assertIsNotNone(reported_2026)
        self.assertGreaterEqual(reported_2026, 1_500)
        self.assertLessEqual(reported_2026, 2_000)
        dengue = state["model_state"]["dengue"]
        humans = {
            province: value["human"]
            for province, value in dengue["provinces"].items()
        }
        self.assertEqual(total_humans(humans), state["population"])
        self.assertLess(
            len(json.dumps(dengue, ensure_ascii=False).encode("utf-8")),
            8_000_000,
        )
        self.assertLessEqual(
            len(dengue["surveillance"]["weekly_ledger"]), 110
        )
        self.assertLessEqual(
            len(dengue["surveillance"]["release_vintages"]), 330
        )

    def test_twelve_seed_median_finishes_in_target_band(self):
        treated, _ = self._paired_runs()
        reported = sorted(item["reported"] for item in treated)
        median = (reported[5] + reported[6]) / 2

        self.assertGreaterEqual(median, 1_500, reported)
        self.assertLessEqual(median, 2_000, reported)

    def test_wmar_pair_reduces_mean_pilot_transmission(self):
        treated, untreated = self._paired_runs()
        treated_mean = sum(
            item["pilot_infections"] for item in treated
        ) / len(treated)
        untreated_mean = sum(
            item["pilot_infections"] for item in untreated
        ) / len(untreated)

        self.assertLess(treated_mean, untreated_mean)

    def test_ten_year_dengue_soak_is_finite_and_bounded(self):
        prepared = prepare_state(
            self.base_state,
            population_baseline=self.resources.population_baseline,
            gdp_baseline=self.resources.gdp_baseline,
            dengue_baseline=self.resources.dengue_baseline,
        )
        dengue = prepared["model_state"]["dengue"]
        population = prepared["model_state"]["population"]
        current = date.fromisoformat(prepared["date"])
        weather = self._constant_weather()
        for _ in range(3_652):
            current += timedelta(days=1)
            _, dengue, _, _ = dengue_step(
                current,
                dengue,
                population,
                weather,
                self.resources.nation_profile,
                self.resources.dengue_baseline,
                lambda name, d=current: random.Random(
                    f"soak:{d}:{name}"
                ),
            )

        ages = {
            age: sum(
                province["human"]["population_by_age"][age]
                for province in dengue["provinces"].values()
            )
            for age in self.resources.dengue_baseline.age_groups
        }
        validate_dengue_state(
            dengue, current, ages, self.resources.dengue_baseline
        )
        self.assertLessEqual(
            len(dengue["surveillance"]["weekly_ledger"]), 110
        )
        self.assertLessEqual(
            len(dengue["surveillance"]["release_vintages"]), 330
        )
        json.dumps(dengue, ensure_ascii=False, allow_nan=False)

    @classmethod
    def _paired_runs(cls):
        if cls._paired_cache is not None:
            return cls._paired_cache
        untreated_raw = copy.deepcopy(cls.resources.dengue_baseline.raw)
        for province in ("katora", "western"):
            untreated_raw["wmar1"][province]["field_effectiveness"] = 0.0
        untreated = DengueBaseline.from_mapping(untreated_raw)
        treated_results = []
        untreated_results = []
        for seed in range(12):
            weather_days, population = cls._weather_path(seed)
            treated_results.append(
                cls._dengue_run(
                    seed,
                    cls.resources.dengue_baseline,
                    weather_days,
                    population,
                )
            )
            untreated_results.append(
                cls._dengue_run(
                    seed, untreated, weather_days, population
                )
            )
        cls._paired_cache = (treated_results, untreated_results)
        return cls._paired_cache

    @classmethod
    def _weather_path(cls, seed):
        raw = copy.deepcopy(cls.base_state)
        raw.setdefault("_meta", {})["random_seed"] = seed
        prepared = prepare_state(
            raw,
            population_baseline=cls.resources.population_baseline,
            gdp_baseline=cls.resources.gdp_baseline,
            dengue_baseline=cls.resources.dengue_baseline,
        )
        weather_state = prepared["model_state"]["weather"]
        current = date.fromisoformat(prepared["date"])
        days = []
        while current < date(2026, 12, 31):
            current += timedelta(days=1)
            public, weather_state, _ = weather_step(
                current,
                weather_state,
                cls.resources.soi_series,
                lambda name, d=current: make_rng(
                    seed, 2, d, "weather", name
                ),
            )
            days.append((current, public))
        return days, prepared["model_state"]["population"]

    @classmethod
    def _dengue_run(cls, seed, baseline, weather_days, population):
        dengue = initialize_dengue_state(
            date(2026, 8, 11),
            population,
            baseline,
            lambda name: make_rng(
                seed,
                4,
                date(2026, 8, 11),
                "dengue-calibration",
                name,
            ),
            "anchor_snapshot",
        )
        pilot_infections = 0
        for current, weather in weather_days:
            flow, dengue, _, _ = dengue_step(
                current,
                dengue,
                population,
                weather,
                cls.resources.nation_profile,
                baseline,
                lambda name, d=current: make_rng(
                    seed, 4, d, "dengue", name
                ),
            )
            pilot_infections += sum(
                flow["new_infections_by_province"][province]
                for province in ("katora", "western")
            )
        return {
            "reported": dengue["cumulative_annual"]["reported"],
            "pilot_infections": pilot_infections,
        }

    @staticmethod
    def _constant_weather():
        city = {
            "temp_high": 30.0,
            "temp_low": 22.0,
            "humidity": 70.0,
            "rainfall_mm": 4.0,
        }
        return {
            **{
                key: dict(city)
                for key in (
                    "katora",
                    "makadi_port",
                    "timo",
                    "pela",
                    "ruwa",
                )
            },
            **city,
            "rainfall_14d_mm": 56.0,
            "soil_moisture_index": 0.5,
        }


if __name__ == "__main__":
    unittest.main()
