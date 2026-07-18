import copy
import json
import math
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE_PATH = ROOT / "data" / "dengue_baseline_2026.json"
SOURCE_PATH = (
    ROOT / "data" / "sources" / "dengue_external_anchors_2026.json"
)

try:
    from build_dengue_baseline import build_baseline
except ImportError:
    build_baseline = None

try:
    import dengue_model
except ImportError:
    dengue_model = None

DengueBaseline = getattr(dengue_model, "DengueBaseline", None)
DengueDataError = getattr(dengue_model, "DengueDataError", None)
initialize_dengue_state = getattr(
    dengue_model, "initialize_dengue_state", None
)
dengue_step = getattr(dengue_model, "dengue_step", None)
reconcile_dengue_population = getattr(
    dengue_model, "reconcile_dengue_population", None
)
dengue_snapshot = getattr(dengue_model, "dengue_snapshot", None)
validate_dengue_state = getattr(
    dengue_model, "validate_dengue_state", None
)


class DengueBaselineBuilderTests(unittest.TestCase):
    def test_builder_is_available(self):
        self.assertIsNotNone(build_baseline)

    def test_committed_baseline_is_reproducible(self):
        self.assertTrue(BASELINE_PATH.exists())
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(build_baseline(), expected)

    def test_anchor_totals_and_provenance(self):
        self.assertTrue(SOURCE_PATH.exists())
        baseline = build_baseline()

        self.assertEqual(sum(baseline["provinces"].values()), 1_200_000)
        self.assertEqual(
            sum(
                baseline["historical_2026"][
                    "reported_by_province"
                ].values()
            ),
            1_240,
        )
        self.assertEqual(
            baseline["wmar1"]["other_provinces_coverage"], 0.0
        )
        self.assertEqual(
            baseline["metadata"]["source_classes"]["wmar1"],
            "fictional_intervention",
        )


class DengueBaselineTests(unittest.TestCase):
    def test_module_exposes_labeled_loader(self):
        self.assertIsNotNone(DengueBaseline)
        self.assertIsNotNone(DengueDataError)
        self.assertTrue(issubclass(DengueDataError, RuntimeError))
        self.assertTrue(hasattr(DengueBaseline, "from_json"))
        self.assertTrue(hasattr(DengueBaseline, "from_mapping"))

    def test_loader_exposes_complete_dimensions(self):
        self.assertIsNotNone(DengueBaseline)
        baseline = DengueBaseline.from_json(BASELINE_PATH)

        self.assertEqual(
            baseline.age_groups,
            ("0-4", "5-14", "15-29", "30-59", "60+"),
        )
        self.assertEqual(
            baseline.serotypes,
            ("DENV-1", "DENV-2", "DENV-3", "DENV-4"),
        )
        self.assertEqual(sum(baseline.province_populations.values()), 1_200_000)
        self.assertEqual(baseline.anchor_date.isoformat(), "2026-08-11")

    def test_loader_rejects_bad_mobility_row(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["mobility"]["katora"]["katora"] -= 0.1

        with self.assertRaisesRegex(
            DengueDataError, r"^baseline\.mobility\.katora"
        ):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_unknown_version(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["version"] = "unknown"

        with self.assertRaisesRegex(DengueDataError, r"^baseline\.version"):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_non_finite_probability(self):
        self.assertIsNotNone(DengueBaseline)
        raw = build_baseline()
        raw["transmission"]["mosquito_to_human"] = math.nan

        with self.assertRaisesRegex(
            DengueDataError,
            r"^baseline\.transmission\.mosquito_to_human",
        ):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_bad_reporting_delay_distribution(self):
        raw = build_baseline()
        raw["surveillance"]["reporting_delay_days"]["0"] += 0.1

        with self.assertRaisesRegex(
            DengueDataError,
            r"^baseline\.surveillance\.reporting_delay_days",
        ):
            DengueBaseline.from_mapping(raw)

    def test_loader_rejects_bad_importation_weights(self):
        raw = build_baseline()
        raw["importation"]["province_weights"]["katora"] -= 0.1

        with self.assertRaisesRegex(
            DengueDataError,
            r"^baseline\.importation\.province_weights",
        ):
            DengueBaseline.from_mapping(raw)


class DengueStateInitializationTests(unittest.TestCase):
    def test_initializer_creates_dated_conserving_state(self):
        self.assertIsNotNone(initialize_dengue_state)
        from population_model import (
            PopulationBaseline,
            initialize_population_state,
        )

        population_baseline = PopulationBaseline.from_json(
            ROOT / "data" / "population_baseline_2026.json"
        )
        population_state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            population_baseline,
            base_seed=42,
        )
        baseline = DengueBaseline.from_json(BASELINE_PATH)

        state = initialize_dengue_state(
            date(2026, 8, 11),
            population_state,
            baseline,
            lambda name: random.Random(f"init:{name}"),
            "anchor_snapshot",
        )

        self.assertEqual(state["last_processed_date"], "2026-08-11")
        self.assertEqual(state["initialization_source"], "anchor_snapshot")
        self.assertEqual(
            sum(
                sum(province["human"]["population_by_age"].values())
                for province in state["provinces"].values()
            ),
            1_200_000,
        )
        self.assertEqual(
            set(state["provinces"]["katora"]["vector"]),
            {
                "larval_pressure",
                "adult_total",
                "susceptible",
                "exposed",
                "infectious",
                "rainfall_queue",
            },
        )
        self.assertEqual(
            {
                "clinical_queue",
                "reporting_queue",
                "laboratory_queue",
                "daily_records",
                "weekly_ledger",
                "release_vintages",
                "daily_death_requests",
                "alert_state",
                "daily_totals",
            },
            set(state["surveillance"]),
        )


class DengueDailyOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from population_model import (
            PopulationBaseline,
            initialize_population_state,
        )

        cls.baseline = DengueBaseline.from_json(BASELINE_PATH)
        population_baseline = PopulationBaseline.from_json(
            ROOT / "data" / "population_baseline_2026.json"
        )
        cls.population_state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            population_baseline,
            base_seed=42,
        )
        cls.state = initialize_dengue_state(
            date(2026, 8, 11),
            cls.population_state,
            cls.baseline,
            lambda name: random.Random(f"init:{name}"),
            "anchor_snapshot",
        )
        cls.profile = json.loads(
            (ROOT / "data" / "nation_profile.json").read_text(
                encoding="utf-8"
            )
        )

    def test_public_daily_interfaces_exist(self):
        self.assertIsNotNone(dengue_step)
        self.assertIsNotNone(reconcile_dengue_population)
        self.assertIsNotNone(dengue_snapshot)
        self.assertIsNotNone(validate_dengue_state)

    def test_daily_step_is_pure_deterministic_and_conserving(self):
        from dengue_dynamics import national_age_totals, total_humans

        original = copy.deepcopy(self.state)
        arguments = (
            date(2026, 8, 12),
            self.state,
            self.population_state,
            self._weather(),
            self.profile,
            self.baseline,
            self._rng_factory,
        )

        first = dengue_step(*arguments)
        second = dengue_step(*arguments)

        self.assertEqual(first, second)
        self.assertEqual(self.state, original)
        self.assertEqual(len(first), 4)
        self.assertEqual(first[1]["last_processed_date"], "2026-08-12")
        self.assertEqual(
            total_humans({
                province: value["human"]
                for province, value in first[1]["provinces"].items()
            }),
            sum(national_age_totals(self.population_state).values()),
        )

    def test_daily_step_rejects_a_non_contiguous_date(self):
        with self.assertRaisesRegex(
            DengueDataError,
            r"last_processed_date: expected 2026-08-12",
        ):
            dengue_step(
                date(2026, 8, 13),
                self.state,
                self.population_state,
                self._weather(),
                self.profile,
                self.baseline,
                self._rng_factory,
            )

    def test_reconciliation_matches_changed_population_age_margins(self):
        from dengue_dynamics import national_age_totals

        after = copy.deepcopy(self.population_state)
        after["cohorts"]["male"][0] += 5
        after["cohorts"]["female"][30] -= 3

        reconciled = reconcile_dengue_population(
            self.state,
            self.population_state,
            after,
            [],
            self.baseline,
        )
        dengue_ages = {
            age: sum(
                province["human"]["population_by_age"][age]
                for province in reconciled["provinces"].values()
            )
            for age in self.baseline.age_groups
        }

        self.assertEqual(dengue_ages, national_age_totals(after))
        self.assertEqual(self.state["last_processed_date"], "2026-08-11")

    def test_confirmed_dengue_death_is_removed_once_and_booked(self):
        after = copy.deepcopy(self.population_state)
        after["cohorts"]["female"][70] -= 1
        before_katora = self.state["provinces"]["katora"]["human"][
            "population_by_age"
        ]["60+"]

        reconciled = reconcile_dengue_population(
            self.state,
            self.population_state,
            after,
            [{
                "cause": "dengue",
                "province": "katora",
                "age_group": "60+",
                "count": 1,
            }],
            self.baseline,
        )

        self.assertEqual(
            reconciled["provinces"]["katora"]["human"]
            ["population_by_age"]["60+"],
            before_katora - 1,
        )
        self.assertEqual(
            reconciled["cumulative_annual"]["deaths"],
            self.state["cumulative_annual"]["deaths"] + 1,
        )
        self.assertEqual(
            self.state["provinces"]["katora"]["human"]
            ["population_by_age"]["60+"],
            before_katora,
        )

    def test_validation_rejects_population_mismatch(self):
        from dengue_dynamics import national_age_totals

        expected = national_age_totals(self.population_state)
        expected["0-4"] += 1
        with self.assertRaisesRegex(
            DengueDataError, r"human\.population_by_age\.0-4"
        ):
            validate_dengue_state(
                self.state,
                date(2026, 8, 11),
                expected,
                self.baseline,
            )

    def test_snapshot_separates_estimated_and_reported(self):
        state = copy.deepcopy(self.state)
        state["surveillance"]["daily_totals"].update({
            "date": "2026-08-11",
            "estimated_infections": 17,
            "reported": 3,
        })

        public = dengue_snapshot(date(2026, 8, 11), state, self.baseline)

        self.assertEqual(public["national"]["estimated_infections"], 17)
        self.assertEqual(public["national"]["reported_cases"], 3)
        self.assertIn("serotypes", public)
        self.assertIn("healthcare_pressure", public)
        self.assertNotIn("clinical_queue", public)

    @staticmethod
    def _rng_factory(name):
        return random.Random(f"daily:{name}")

    @staticmethod
    def _weather():
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
