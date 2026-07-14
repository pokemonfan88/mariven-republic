import copy
import math
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from state import (
    SCHEMA_VERSION,
    StateValidationError,
    migrate_state,
    prepare_state,
    validate_state,
)


V1 = {
    "_meta": {"random_seed": 42, "ticks_run": 30},
    "date": "2026-08-11",
    "weather": {"condition": "澶氫簯", "temp_high": 27, "temp_low": 18,
                "humidity": 67, "rainfall_mm": 0.0, "wind_kmh": 14,
                "cyclone_risk": "none", "notes": "鍏煎澶╂皵"},
    "economy": {"inflation_pct": 2.4, "unemployment_pct": 5.8,
                "interest_rate_pct": 2.5,
                "exchange_rate_mvl_per_usd": 2.18,
                "fuel_95_price_mvl": 2.85,
                "fuel_diesel_price_mvl": 2.03},
    "government": {"pm": "鎵橀┈鏂烽┈鍗￠噷"},
    "population": 1_200_000,
    "deaths_today": {"total": 0},
    "events_today": [],
}


class StateTests(unittest.TestCase):
    def test_prepare_migrates_without_mutating_input(self):
        original = copy.deepcopy(V1)
        migrated = prepare_state(V1)
        self.assertEqual(V1, original)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(migrated["base_seed"], 42)
        self.assertEqual(migrated["weather"]["condition"], "澶氫簯")
        self.assertEqual(set(migrated["model_state"]),
                         {"weather", "exchange", "commodities", "inflation"})

    def test_prepare_copies_v2_state(self):
        v2 = prepare_state(V1)
        copied = prepare_state(v2)
        self.assertEqual(copied, v2)
        self.assertIsNot(copied, v2)

    def test_invalid_date_reports_field_path(self):
        broken = copy.deepcopy(V1)
        broken["date"] = "14/07/2026"
        with self.assertRaisesRegex(StateValidationError, r"^state\.date"):
            prepare_state(broken)

    def test_migrate_accepts_base_seed_override(self):
        migrated = migrate_state(V1, base_seed=991)
        self.assertEqual(migrated["base_seed"], 991)

    def test_migrate_defaults_missing_random_seed_to_42(self):
        v1 = copy.deepcopy(V1)
        v1["_meta"].pop("random_seed")
        self.assertEqual(migrate_state(v1)["base_seed"], 42)

    def test_migration_builds_constant_growth_cpi_baseline(self):
        history = migrate_state(V1)["model_state"]["inflation"]["monthly_history"]
        self.assertEqual(len(history), 13)
        self.assertEqual(history[-1]["index"], 100.0)
        self.assertEqual(history[-1]["date"], "2026-08-31")
        factor = (1 + V1["economy"]["inflation_pct"] / 100) ** (1 / 12)
        for previous, current in zip(history, history[1:]):
            self.assertTrue(math.isclose(
                current["index"] / previous["index"], factor,
                rel_tol=1e-12,
            ))
            self.assertEqual(current["source"], "migration_baseline")

    def test_validate_state_returns_none_for_prepared_state(self):
        self.assertIsNone(validate_state(migrate_state(V1)))

    def test_validate_rejects_unsupported_schema_version(self):
        broken = migrate_state(V1)
        broken["schema_version"] = 1
        with self.assertRaisesRegex(
                StateValidationError, r"^state\.schema_version"):
            validate_state(broken)

    def test_validate_rejects_missing_core_dictionary(self):
        for field in ("weather", "economy", "government", "deaths_today",
                      "model_state"):
            with self.subTest(field=field):
                broken = migrate_state(V1)
                broken.pop(field)
                with self.assertRaisesRegex(
                        StateValidationError, rf"^state\.{field}"):
                    validate_state(broken)

    def test_validate_rejects_non_positive_population(self):
        for population in (0, -1):
            with self.subTest(population=population):
                broken = migrate_state(V1)
                broken["population"] = population
                with self.assertRaisesRegex(
                        StateValidationError, r"^state\.population"):
                    validate_state(broken)

    def test_validate_rejects_non_finite_core_economic_value(self):
        for field in (
            "inflation_pct",
            "unemployment_pct",
            "interest_rate_pct",
            "exchange_rate_mvl_per_usd",
            "fuel_95_price_mvl",
            "fuel_diesel_price_mvl",
        ):
            with self.subTest(field=field):
                broken = migrate_state(V1)
                broken["economy"][field] = float("nan")
                with self.assertRaisesRegex(
                        StateValidationError, rf"^state\.economy\.{field}"):
                    validate_state(broken)

    def test_validate_rejects_non_finite_nested_model_value(self):
        broken = migrate_state(V1)
        broken["model_state"]["inflation"]["monthly_history"][0][
            "index"
        ] = float("nan")

        with self.assertRaisesRegex(
            StateValidationError,
            r"^state\.model_state\.inflation\.monthly_history\[0\]\.index",
        ):
            validate_state(broken)

    def test_validate_wraps_json_serialization_errors(self):
        broken = migrate_state(V1)
        broken["model_state"]["gdp"] = {"unsupported": object()}

        with self.assertRaisesRegex(
            StateValidationError, r"^state: not JSON serializable"
        ):
            validate_state(broken)

    def test_migration_preserves_current_date(self):
        migrated = migrate_state(V1)
        self.assertEqual(date.fromisoformat(migrated["date"]), date(2026, 8, 11))


if __name__ == "__main__":
    unittest.main()
