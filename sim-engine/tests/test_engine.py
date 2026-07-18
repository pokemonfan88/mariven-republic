import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, render_brief, tick
from dengue_model import dengue_step as real_dengue_step
from state import StateValidationError, prepare_state, validate_state
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
        self.assertEqual(result["schema_version"], 5)
        self.assertIn("katora", result["weather"])
        self.assertIn("exchange_rates", result["economy"])
        self.assertIn("commodities", result["economy"])
        self.assertIn("cpi", result["economy"])
        self.assertEqual(
            result["economy"]["inflation_pct"],
            result["economy"]["cpi"]["yoy_pct"],
        )
        self.assertIn("population", result["model_state"])
        self.assertIn("gdp", result["model_state"])
        self.assertIn("dengue", result["model_state"])
        self.assertIn("dengue", result["public_health"])
        self.assertIn("gdp", result["economy"])
        self.assertEqual(
            result["economy"]["gdp"]["as_of_date"], result["date"]
        )
        self.assertEqual(
            result["model_state"]["gdp"]["last_processed_date"], result["date"]
        )
        self.assertEqual(result["population"], result["demographics"]["population"])
        self.assertEqual(
            result["population"],
            sum(result["model_state"]["population"]["cohorts"]["male"])
            + sum(result["model_state"]["population"]["cohorts"]["female"]),
        )

    def test_tick_advances_dengue_and_publishes_public_health(self):
        result = tick(self.v1, resources=self.resources)

        self.assertEqual(
            result["model_state"]["dengue"]["last_processed_date"],
            result["date"],
        )
        self.assertIn(
            "reported_cases",
            result["public_health"]["dengue"]["national"],
        )
        self.assertEqual(
            result["public_health"]["dengue"]["national"]["population"],
            result["population"],
        )

    def test_dengue_death_is_confirmed_by_population_and_reconciled(self):
        def forced_dengue(*args, **kwargs):
            flow, state, _, events = real_dengue_step(*args, **kwargs)
            return flow, state, [{
                "cause": "dengue",
                "province": "western",
                "age_group": "60+",
                "count": 1,
            }], events

        with patch("engine.dengue_step", side_effect=forced_dengue):
            result = tick(self.v1, resources=self.resources)

        self.assertEqual(result["deaths_today"]["dengue"], 1)
        self.assertEqual(
            result["demographics"]["cause_specific_deaths_today"][0]
            ["count"],
            1,
        )
        self.assertEqual(
            result["model_state"]["dengue"]["cumulative_annual"][
                "deaths"
            ],
            1,
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
        previous["model_state"]["future_model"] = copy.deepcopy(future_state)

        result = tick(previous, resources=self.resources)

        self.assertEqual(result["model_state"]["future_model"], future_state)

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
        self.assertEqual(
            captured["state"]["public_health"]["dengue"]["as_of_date"],
            result["date"],
        )
        captured_economy = copy.deepcopy(captured["state"]["economy"])
        result_economy = copy.deepcopy(result["economy"])
        captured_gdp = captured_economy.pop("gdp")
        result_gdp = result_economy.pop("gdp")
        self.assertEqual(captured_economy, result_economy)
        self.assertEqual(
            captured_gdp["current_quarter_nowcast"],
            result_gdp["current_quarter_nowcast"],
        )
        self.assertEqual(
            captured_gdp["annual_nowcast"], result_gdp["annual_nowcast"]
        )
        self.assertEqual(result_gdp["population"], result["population"])
        for model in ("weather", "exchange", "commodities", "inflation"):
            self.assertEqual(
                captured["state"]["model_state"][model],
                result["model_state"][model],
            )

    def test_population_reconciles_notable_deaths_once(self):
        notable = {
            "traffic": 2,
            "drowning": 0,
            "suicide": 0,
            "murder": 0,
            "workplace": 0,
            "lightning": 0,
            "other": 0,
            "total": 2,
        }

        with patch("engine.events_step", return_value=(notable, [])):
            result = tick(self.v1, resources=self.resources)

        demographics = result["demographics"]
        self.assertEqual(result["deaths_today"]["traffic"], 2)
        self.assertEqual(result["deaths_today"]["notable_total"], 2)
        self.assertEqual(
            result["deaths_today"]["total"],
            demographics["deaths_all_causes_today"],
        )
        self.assertEqual(
            result["population"],
            1_200_000 + demographics["population_change_today"],
        )

    def test_validation_rejects_mismatched_daily_death_ledger(self):
        result = tick(self.v1, resources=self.resources)
        result["deaths_today"]["total"] += 1

        with self.assertRaisesRegex(
            StateValidationError,
            r"^state\.deaths_today\.total",
        ):
            validate_state(
                result,
                population_baseline=self.resources.population_baseline,
            )

    def test_population_integration_does_not_perturb_existing_model_streams(self):
        result = tick(self.v1, resources=self.resources)

        self.assertEqual(result["weather"]["katora"]["condition"], "多云")
        self.assertEqual(result["weather"]["katora"]["rainfall_mm"], 0.9)
        self.assertAlmostEqual(
            result["economy"]["exchange_rate_mvl_per_usd"],
            2.1923411312677206,
        )
        self.assertEqual(result["economy"]["inflation_pct"], 2.379)
        self.assertEqual(result["deaths_today"]["traffic"], 1)

    def test_render_brief_includes_population_flows(self):
        result = tick(self.v1, resources=self.resources)
        demographics = result["demographics"]

        brief = render_brief(result)

        self.assertIn(
            (
                f"**人口** {result['population']:,} | "
                f"出生 {demographics['births_today']} | "
                f"全因死亡 {demographics['deaths_all_causes_today']} | "
                f"净迁移 {demographics['net_migration_today']:+d} | "
                f"净变动 {demographics['population_change_today']:+d}"
            ),
            brief,
        )

    def test_render_brief_includes_gdp_nowcast_and_latest_release(self):
        result = tick(self.v1, resources=self.resources)
        gdp = result["economy"]["gdp"]

        brief = render_brief(result)

        self.assertIn("**GDP**", brief)
        self.assertIn(gdp["current_quarter_nowcast"]["period"], brief)
        self.assertIn(gdp["latest_release"]["period"], brief)
        self.assertIn("年度预测", brief)

    def test_render_brief_includes_dengue_status(self):
        result = tick(self.v1, resources=self.resources)

        brief = render_brief(result)

        self.assertIn("**登革热**", brief)
        self.assertIn(
            result["public_health"]["dengue"]["epidemiological_week"],
            brief,
        )

    def test_render_brief_handles_benchmark_release_without_yoy_growth(self):
        early = copy.deepcopy(self.v1)
        early["date"] = "2026-04-01"
        state = prepare_state(
            early,
            population_baseline=self.resources.population_baseline,
            gdp_baseline=self.resources.gdp_baseline,
        )

        brief = render_brief(state)

        self.assertIn("基准期同比不适用", brief)

    def test_render_brief_separates_notable_and_non_notable_deaths(self):
        notable = {
            "traffic": 2,
            "drowning": 0,
            "suicide": 0,
            "murder": 0,
            "workplace": 0,
            "lightning": 0,
            "other": 0,
            "total": 2,
        }
        with patch("engine.events_step", return_value=(notable, [])):
            result = tick(self.v1, resources=self.resources)

        brief = render_brief(result)
        deaths = result["deaths_today"]

        self.assertIn(
            (
                f"**死亡** 全因 {deaths['total']} 人 | "
                f"显著 {deaths['notable_total']} 人（traffic=2） | "
                f"其他疾病/自然 {deaths['non_notable']} 人"
            ),
            brief,
        )
        self.assertNotIn("notable_total=", brief)
        self.assertNotIn("non_notable=", brief)

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
