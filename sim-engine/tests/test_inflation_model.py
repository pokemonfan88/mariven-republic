import copy
import json
import math
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from inflation_model import inflation_step
from state import prepare_state


class InflationTests(unittest.TestCase):
    def setUp(self):
        self.state = prepare_state({
            "_meta": {"random_seed": 42}, "date": "2026-07-31",
            "weather": {"condition": "晴", "temp_high": 26, "temp_low": 20,
                        "humidity": 70, "rainfall_mm": 2, "wind_kmh": 12,
                        "cyclone_risk": "none", "notes": ""},
            "economy": {"inflation_pct": 2.4, "unemployment_pct": 5.8,
                        "interest_rate_pct": 2.5,
                        "exchange_rate_mvl_per_usd": 2.18,
                        "fuel_95_price_mvl": 2.85,
                        "fuel_diesel_price_mvl": 2.03},
            "government": {}, "population": 1_200_000,
            "deaths_today": {"total": 0}, "events_today": [],
        })["model_state"]["inflation"]
        self.weather = {"katora": {"rainfall_mm": 2.0, "temp_high": 26.0}}
        self.commodities = {"sugar_usd_lb": 0.20, "brent_usd_barrel": 74.0}
        self.exchange = {"mvl_per_usd": 2.18, "basket_index": 1.0}
        self.profile = {"demographics": {"urbanization_pct": 53.6}}

    def step(self, d, state):
        return inflation_step(d, state, self.weather, self.commodities,
                              self.exchange, self.profile,
                              random.Random(d.isoformat()))

    def test_official_value_holds_between_release_days(self):
        public1, state1, _ = self.step(date(2026, 8, 14), self.state)
        public2, _, _ = self.step(date(2026, 8, 16), state1)
        self.assertEqual(public1["index"], public2["index"])
        self.assertEqual(public1["yoy_pct"], public2["yoy_pct"])

    def test_migrated_components_hold_until_first_release(self):
        state = copy.deepcopy(self.state)
        official_components = []
        release_dates = []
        pump_prices = []
        upstream_inputs = (
            (2.0, 26.0, 0.20, 60.0, 2.10),
            (20.0, 31.0, 0.30, 90.0, 2.35),
            (0.0, 22.0, 0.10, 120.0, 2.60),
        )

        for offset, inputs in enumerate(upstream_inputs):
            rainfall, temperature, sugar, brent, exchange_rate = inputs
            d = date(2026, 8, 12 + offset)
            public, state, _ = inflation_step(
                d,
                state,
                {"katora": {
                    "rainfall_mm": rainfall,
                    "temp_high": temperature,
                }},
                {"sugar_usd_lb": sugar, "brent_usd_barrel": brent},
                {"mvl_per_usd": exchange_rate, "basket_index": 1.0},
                self.profile,
                random.Random(d.isoformat()),
            )
            official_components.append(public["components"])
            release_dates.append(public["release_date"])
            pump_prices.append(public["fuel_95_price_mvl"])
            self.assertIn("published_components", state)
            self.assertEqual(
                state["published_components"], public["components"]
            )

        self.assertEqual(
            official_components,
            [official_components[0]] * len(official_components),
        )
        self.assertEqual(release_dates, [None, None, None])
        self.assertEqual(state["last_release_date"], None)
        self.assertNotEqual(pump_prices[0], pump_prices[-1])

    def test_release_day_preserves_previous_month_for_mom(self):
        _, state1, _ = self.step(date(2026, 8, 14), self.state)
        public, state2, events = self.step(date(2026, 8, 15), state1)
        self.assertTrue(public["is_release_day"])
        self.assertEqual(public["release_date"], "2026-08-15")
        self.assertNotEqual(public["mom_pct"], 0.0)
        self.assertEqual(state2["last_release_date"], "2026-08-15")
        self.assertEqual(events[0]["type"], "economy")

    def test_release_uses_exact_index_mom_and_yoy_formulas(self):
        state = copy.deepcopy(self.state)
        state["published_index"] = 110.0
        state["monthly_history"] = [{
            "date": "2025-07-31",
            "index": 100.0,
            "source": "synthetic_history",
        }]
        component_pressures = {
            "food": 0.5,
            "fuel": 1.0,
            "housing": 1.5,
            "transport": 2.0,
            "other": 2.5,
        }
        state["daily_observations"] = [{
            "date": "2026-07-31",
            "component_pressures": component_pressures,
            "component_details": {},
        }]

        public, next_state, _ = self.step(date(2026, 8, 15), state)

        weighted_change = round(math.fsum((
            0.35 * 0.5,
            0.18 * 1.0,
            0.15 * 1.5,
            0.12 * 2.0,
            0.20 * 2.5,
        )), 4)
        expected_index = round(110.0 * (1.0 + weighted_change / 100), 6)
        expected_mom = round((expected_index / 110.0 - 1.0) * 100, 4)
        expected_yoy = round((expected_index / 100.0 - 1.0) * 100, 4)
        self.assertEqual(weighted_change, 1.32)
        self.assertEqual(public["index"], expected_index)
        self.assertEqual(public["mom_pct"], expected_mom)
        self.assertEqual(public["yoy_pct"], expected_yoy)
        release = next_state["monthly_history"][-1]
        self.assertEqual(release["index"], expected_index)
        self.assertEqual(release["mom_pct"], expected_mom)
        self.assertEqual(release["yoy_pct"], expected_yoy)

    def test_release_holds_official_components_and_uses_target_month_details(self):
        _, july30_state, _ = self.step(date(2026, 7, 30), self.state)
        _, july_state, _ = inflation_step(
            date(2026, 7, 31), july30_state,
            {"katora": {"rainfall_mm": 0.0, "temp_high": 30.0}},
            {"sugar_usd_lb": 0.30, "brent_usd_barrel": 90.0},
            {"mvl_per_usd": 2.35, "basket_index": 1.0}, self.profile,
            random.Random("2026-07-31"),
        )
        release_weather = {
            "katora": {"rainfall_mm": 100.0, "temp_high": 40.0}
        }
        release_commodities = {
            "sugar_usd_lb": 0.50, "brent_usd_barrel": 120.0,
        }
        release_exchange = {"mvl_per_usd": 2.70, "basket_index": 1.0}
        released, released_state, _ = inflation_step(
            date(2026, 8, 15), july_state, release_weather,
            release_commodities, release_exchange, self.profile,
            random.Random("2026-08-15"),
        )

        next_day, _, _ = inflation_step(
            date(2026, 8, 16), released_state,
            {"katora": {"rainfall_mm": 0.0, "temp_high": 10.0}},
            {"sugar_usd_lb": 0.05, "brent_usd_barrel": 40.0},
            {"mvl_per_usd": 1.80, "basket_index": 1.0}, self.profile,
            random.Random("2026-08-16"),
        )

        self.assertEqual(
            released["components"]["food"]["weather_pressure"],
            round((
                july30_state["daily_observations"][-1]
                ["component_details"]["food"]["weather_pressure"]
                + july_state["daily_observations"][-1]
                ["component_details"]["food"]["weather_pressure"]
            ) / 2.0, 4),
        )
        self.assertEqual(released_state["published_components"],
                         released["components"])
        self.assertEqual(
            (released["index"], released["mom_pct"], released["yoy_pct"]),
            (next_day["index"], next_day["mom_pct"], next_day["yoy_pct"]),
        )
        self.assertEqual(released["components"], next_day["components"])
        self.assertNotEqual(released["fuel_95_price_mvl"],
                            next_day["fuel_95_price_mvl"])

    def test_release_day_is_idempotent(self):
        _, state1, _ = self.step(date(2026, 8, 14), self.state)
        public1, state2, events1 = self.step(date(2026, 8, 15), state1)
        public2, state3, events2 = self.step(date(2026, 8, 15), state2)
        self.assertEqual(public1, public2)
        self.assertEqual(state2, state3)
        self.assertEqual(len(events1), 1)
        self.assertEqual(events2, [])

    def test_normal_daily_rain_is_not_compared_to_month_total(self):
        public, state, _ = self.step(date(2026, 7, 31), self.state)
        self.assertLess(abs(public["components"]["food"]["weather_pressure"]),
                        0.5)
        self.assertAlmostEqual(
            state["daily_observations"][-1]["rainfall_normal_mm"],
            55.0 / 31.0,
        )

    def test_higher_brent_increases_pump_price(self):
        low, _, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 60.0}, self.exchange,
            self.profile, random.Random(1),
        )
        high, _, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 100.0}, self.exchange,
            self.profile, random.Random(1),
        )
        self.assertGreater(high["fuel_95_price_mvl"],
                           low["fuel_95_price_mvl"])

    def test_transport_uses_one_day_lagged_fuel_pressure(self):
        _, low_state, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 60.0}, self.exchange,
            self.profile, random.Random(1),
        )
        _, high_state, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 100.0}, self.exchange,
            self.profile, random.Random(1),
        )
        low_details = low_state["daily_observations"][-1]["component_details"]
        high_details = high_state["daily_observations"][-1]["component_details"]
        self.assertNotEqual(low_details["fuel"]["rate_pct"],
                            high_details["fuel"]["rate_pct"])
        self.assertEqual(low_details["transport"]["rate_pct"],
                         high_details["transport"]["rate_pct"])

        _, after_low_state, _ = self.step(date(2026, 8, 2), low_state)
        _, after_high_state, _ = self.step(date(2026, 8, 2), high_state)
        after_low = after_low_state["daily_observations"][-1][
            "component_details"
        ]
        after_high = after_high_state["daily_observations"][-1][
            "component_details"
        ]
        self.assertEqual(after_low["fuel"]["rate_pct"],
                         after_high["fuel"]["rate_pct"])
        self.assertNotEqual(after_low["transport"]["rate_pct"],
                            after_high["transport"]["rate_pct"])

    def test_observation_for_same_date_is_replaced(self):
        _, state1, _ = self.step(date(2026, 8, 1), self.state)
        wetter = copy.deepcopy(self.weather)
        wetter["katora"]["rainfall_mm"] = 12.0
        _, state2, _ = inflation_step(
            date(2026, 8, 1), state1, wetter, self.commodities,
            self.exchange, self.profile, random.Random("2026-08-01"),
        )
        self.assertEqual(len(state1["daily_observations"]),
                         len(state2["daily_observations"]))
        self.assertEqual(state2["daily_observations"][-1]["rainfall_mm"],
                         12.0)

    def test_histories_are_bounded_and_json_compatible(self):
        seeded = copy.deepcopy(self.state)
        first_day = date(2026, 5, 1)
        seeded["daily_observations"] = [
            {
                "date": (first_day + timedelta(days=offset)).isoformat(),
                "rainfall_mm": 2.0,
                "rainfall_normal_mm": 2.0,
                "temperature_deviation_c": 0.0,
                "sugar_usd_lb": 0.20,
                "brent_usd_barrel": 74.0,
                "mvl_per_usd": 2.18,
                "component_pressures": {
                    name: 0.2 for name in (
                        "food", "fuel", "housing", "transport", "other"
                    )
                },
            }
            for offset in range(70)
        ]
        seeded["monthly_history"] = [
            {"date": f"{year:04d}-{month + 1:02d}-28",
             "index": 90.0 + offset,
             "source": "migration_baseline"}
            for offset, (year, month) in enumerate(
                (divmod(2023 * 12 + value, 12) for value in range(30))
            )
        ]

        public, state, _ = self.step(date(2026, 8, 15), seeded)

        self.assertLessEqual(len(state["daily_observations"]), 62)
        self.assertEqual(len(state["monthly_history"]), 24)
        json.dumps(state, allow_nan=False)
        json.dumps(public, allow_nan=False)

    def test_release_replaces_target_month_baseline_without_duplicate(self):
        _, july_state, _ = self.step(date(2026, 7, 31), self.state)
        _, released_state, _ = self.step(date(2026, 8, 15), july_state)

        history = released_state["monthly_history"]
        month_keys = [record["date"][:7] for record in history]
        july_records = [
            record for record in history if record["date"] == "2026-07-31"
        ]
        self.assertEqual(len(month_keys), len(set(month_keys)))
        self.assertEqual(len(july_records), 1)
        self.assertEqual(july_records[0]["source"], "monthly_release")
        self.assertEqual(len(history), len(self.state["monthly_history"]))

    def test_input_dictionaries_are_not_mutated(self):
        inputs = (self.state, self.weather, self.commodities,
                  self.exchange, self.profile)
        originals = copy.deepcopy(inputs)

        self.step(date(2026, 8, 15), self.state)

        self.assertEqual(inputs, originals)

    def test_public_components_have_rates_and_contributions(self):
        public, _, _ = self.step(date(2026, 8, 1), self.state)
        self.assertEqual(set(public["components"]),
                         {"food", "fuel", "housing", "transport", "other"})
        for component in public["components"].values():
            self.assertIn("rate_pct", component)
            self.assertIn("contribution_pct", component)


if __name__ == "__main__":
    unittest.main()
