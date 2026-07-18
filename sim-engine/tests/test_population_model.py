import sys
import unittest
import json
import copy
import random
import tempfile
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_population_baseline import build_baseline
from population_model import (
    PopulationBaseline,
    PopulationDataError,
    _largest_remainder,
    _remove_people,
    age_population,
    build_balanced_plan,
    initialize_population_state,
    median_age,
    population_step,
    validate_population_state,
)


DATA = ROOT / "data" / "population_baseline_2026.json"
WPP_FIJI_2026 = (
    ROOT / "data" / "sources" / "wpp2024_fiji_2026_single_age_sex.json"
)


class PopulationBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = PopulationBaseline.from_json(DATA)

    def test_baseline_has_single_age_sex_cohorts(self):
        cohorts = self.baseline.cohorts

        self.assertEqual(len(cohorts["male"]), 101)
        self.assertEqual(len(cohorts["female"]), 101)
        self.assertEqual(
            sum(cohorts["male"]) + sum(cohorts["female"]),
            1_200_000,
        )
        self.assertEqual(round(median_age(cohorts), 1), 27.8)

    def test_birthday_buckets_reconcile_to_every_cohort(self):
        for sex in ("male", "female"):
            buckets = self.baseline.birthday_buckets[sex]
            self.assertEqual(len(buckets), 101)
            self.assertTrue(all(len(age) == 12 for age in buckets))
            self.assertEqual(
                [sum(age) for age in buckets],
                self.baseline.cohorts[sex],
            )

    def test_baseline_calibration_and_first_cycle_targets(self):
        calibration = self.baseline.calibration
        targets = self.baseline.first_cycle_targets

        self.assertEqual(self.baseline.anchor_date.isoformat(), "2026-08-11")
        self.assertEqual(calibration["total_population"], 1_200_000)
        self.assertAlmostEqual(calibration["median_age"], 27.8, delta=0.05)
        self.assertEqual(calibration["tfr"], 2.3)
        self.assertEqual(calibration["life_expectancy_male"], 67.0)
        self.assertEqual(calibration["life_expectancy_female"], 71.5)
        self.assertEqual(calibration["infant_mortality_per_1000"], 16.2)
        self.assertEqual(calibration["under_five_mortality_per_1000"], 21.3)
        self.assertEqual(
            targets,
            {
                "births": 27_500,
                "baseline_deaths": 6_600,
                "returning_diaspora": 2_500,
                "foreign_immigrants": 2_200,
                "emigrants": 2_800,
            },
        )

    def test_mortality_table_integrates_to_annual_death_anchor(self):
        implied_deaths = sum(
            self.baseline.cohorts[sex][age]
            * self.baseline.mortality_rates[sex][age]
            for sex in ("male", "female")
            for age in range(101)
        )

        self.assertAlmostEqual(implied_deaths, 6_600, delta=1.0)

    def test_rate_and_migration_shapes_are_complete(self):
        self.assertEqual(len(self.baseline.fertility_weights), 35)
        self.assertAlmostEqual(sum(self.baseline.fertility_weights), 1.0)
        for sex in ("male", "female"):
            self.assertEqual(len(self.baseline.mortality_rates[sex]), 101)
        for migration_type in (
            "returning_diaspora",
            "foreign_immigrants",
            "emigrants",
        ):
            weights = self.baseline.migration_weights[migration_type]
            self.assertEqual(len(weights["male"]), 101)
            self.assertEqual(len(weights["female"]), 101)
            self.assertAlmostEqual(
                sum(weights["male"]) + sum(weights["female"]),
                1.0,
            )
        returning = self.baseline.migration_weights["returning_diaspora"]
        foreign = self.baseline.migration_weights["foreign_immigrants"]
        emigrants = self.baseline.migration_weights["emigrants"]

        def share(weights, start, end):
            return sum(
                sum(weights[sex][start:end])
                for sex in ("male", "female")
            )

        self.assertAlmostEqual(sum(returning["male"]), 0.50)
        self.assertAlmostEqual(sum(foreign["male"]), 0.55)
        self.assertAlmostEqual(sum(emigrants["male"]), 0.50)
        self.assertGreater(share(returning, 25, 50), 0.64)
        self.assertGreater(share(foreign, 20, 45), 0.80)
        self.assertGreater(share(emigrants, 18, 40), 0.80)

    def test_committed_baseline_is_reproducible_from_generator(self):
        committed = json.loads(DATA.read_text(encoding="utf-8"))

        self.assertEqual(build_baseline(), committed)

    def test_baseline_uses_checked_wpp_fiji_2026_single_age_prior(self):
        source = json.loads(WPP_FIJI_2026.read_text(encoding="utf-8"))

        self.assertEqual(len(source["male"]), 101)
        self.assertEqual(len(source["female"]), 101)
        self.assertEqual(
            self.baseline.metadata["single_age_prior"][
                "source_file_sha256"
            ],
            source["_meta"]["source_file_sha256"],
        )
        self.assertEqual(
            self.baseline.metadata["single_age_prior"]["reference_date"],
            "2026-01-01",
        )
        self.assertEqual(
            self.baseline.metadata["single_age_prior"][
                "extract_data_sha256"
            ],
            "1162453270449aa7bdb2518e402d970807fbda6806502d7229a2fd01adc291bb",
        )

    def test_baseline_rejects_mortality_probability_above_one(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["mortality_rates"]["male"][40] = 1.01

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-population.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                r"baseline\.mortality_rates\.male\[40\]",
            ):
                PopulationBaseline.from_json(path)

    def test_baseline_requires_every_notable_death_category(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        del invalid["notable_death_weights"]["lightning"]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-population.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                r"baseline\.notable_death_weights",
            ):
                PopulationBaseline.from_json(path)


class PopulationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = PopulationBaseline.from_json(DATA)

    def test_balanced_plan_is_exact_variable_and_deterministic(self):
        first = build_balanced_plan(
            27_500,
            date(2026, 8, 12),
            base_seed=42,
            stream_name="births",
        )
        second = build_balanced_plan(
            27_500,
            date(2026, 8, 12),
            base_seed=42,
            stream_name="births",
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 365)
        self.assertEqual(sum(first), 27_500)
        self.assertGreater(len(set(first)), 1)
        self.assertTrue(all(isinstance(value, int) and value >= 0 for value in first))
        isolated = build_balanced_plan(
            27_500,
            date(2026, 8, 12),
            base_seed=42,
            stream_name="unrelated",
        )
        self.assertNotEqual(first, isolated)

    def test_largest_remainder_uses_supplied_random_tie_breakers(self):
        allocated = _largest_remainder(
            [1.0, 1.0, 1.0],
            1,
            tie_breakers=[0.1, 0.9, 0.2],
        )

        self.assertEqual(allocated, [0, 1, 0])

    def test_initial_state_contains_exact_first_cycle_plans(self):
        state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )

        self.assertEqual(state["current_population"], 1_200_000)
        self.assertEqual(state["cycle"]["start_date"], "2026-08-12")
        self.assertEqual(state["cycle"]["end_date"], "2027-08-11")
        self.assertEqual(state["cycle"]["offset"], 0)
        for key, target in self.baseline.first_cycle_targets.items():
            self.assertEqual(sum(state["cycle"]["plans"][key]), target)
            daily_average = target / 365
            self.assertLessEqual(
                max(state["cycle"]["plans"][key]),
                daily_average * 2.1 + 1,
            )
        self.assertEqual(sum(state["cycle"]["plans"]["births_male"]), 14_085)
        self.assertEqual(sum(state["cycle"]["plans"]["births_female"]), 13_415)
        self.assertEqual(
            [
                male + female
                for male, female in zip(
                    state["cycle"]["plans"]["births_male"],
                    state["cycle"]["plans"]["births_female"],
                )
            ],
            state["cycle"]["plans"]["births"],
        )
        validate_population_state(state, 1_200_000, self.baseline)
        self.assertEqual(
            json.loads(json.dumps(state, ensure_ascii=False)),
            state,
        )

    def test_initial_state_scales_integer_cohorts_to_other_population(self):
        state = initialize_population_state(
            date(2028, 4, 3),
            1_350_017,
            self.baseline,
            base_seed=91,
        )

        self.assertEqual(
            sum(state["cohorts"]["male"]) + sum(state["cohorts"]["female"]),
            1_350_017,
        )
        for sex in ("male", "female"):
            self.assertEqual(
                [sum(buckets) for buckets in state["birthday_buckets"][sex]],
                state["cohorts"][sex],
            )
        validate_population_state(state, 1_350_017, self.baseline)

    def test_state_rejects_cycle_cumulative_that_disagrees_with_offset(self):
        state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        state["cycle"]["offset"] = 1

        with self.assertRaisesRegex(
            ValueError,
            r"cycle\.cumulative\.births",
        ):
            validate_population_state(state, 1_200_000, self.baseline)

    def test_state_rejects_broken_cycle_population_accounting(self):
        state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        state["cycle"]["starting_population"] += 1

        with self.assertRaisesRegex(
            ValueError,
            r"cycle\.starting_population",
        ):
            validate_population_state(state, 1_200_000, self.baseline)


class PopulationStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = PopulationBaseline.from_json(DATA)

    def setUp(self):
        self.state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )

    @staticmethod
    def rng_factory(name):
        return random.Random(f"2026-08-12:{name}")

    def test_daily_step_reconciles_flows_without_mutating_input(self):
        original = copy.deepcopy(self.state)
        offset = self.state["cycle"]["offset"]
        plans = self.state["cycle"]["plans"]
        notable = {
            "traffic": 1,
            "drowning": 0,
            "suicide": 0,
            "murder": 0,
            "workplace": 0,
            "lightning": 0,
            "other": 0,
            "total": 1,
        }

        public, next_state, deaths, events = population_step(
            date(2026, 8, 12),
            self.state,
            notable,
            self.baseline,
            self.rng_factory,
        )

        baseline_deaths = plans["baseline_deaths"][offset]
        expected_change = (
            plans["births"][offset]
            - baseline_deaths
            + plans["returning_diaspora"][offset]
            + plans["foreign_immigrants"][offset]
            - plans["emigrants"][offset]
        )
        self.assertEqual(self.state, original)
        self.assertEqual(public["births_today"], plans["births"][offset])
        self.assertEqual(public["deaths_all_causes_today"], baseline_deaths)
        self.assertEqual(public["notable_deaths_today"], 1)
        self.assertEqual(public["excess_deaths_today"], 0)
        self.assertEqual(public["population_change_today"], expected_change)
        self.assertEqual(public["population"], 1_200_000 + expected_change)
        self.assertEqual(deaths["total"], baseline_deaths)
        self.assertEqual(deaths["notable_total"], 1)
        self.assertEqual(deaths["non_notable"], baseline_deaths - 1)
        self.assertEqual(deaths["traffic"], 1)
        self.assertEqual(events, [])
        self.assertEqual(next_state["cycle"]["offset"], 1)
        self.assertEqual(
            sum(next_state["cohorts"]["male"])
            + sum(next_state["cohorts"]["female"]),
            public["population"],
        )
        validate_population_state(next_state, public["population"], self.baseline)

    def test_cause_specific_death_stays_in_requested_age_group(self):
        request = {
            "cause": "dengue",
            "province": "western",
            "age_group": "5-14",
            "count": 1,
        }

        public, _, deaths, _ = population_step(
            date(2026, 8, 12),
            self.state,
            {"total": 0},
            self.baseline,
            self.rng_factory,
            cause_specific_deaths=[request],
        )

        self.assertEqual(deaths["dengue"], 1)
        baseline_deaths = self.state["cycle"]["plans"][
            "baseline_deaths"
        ][0]
        self.assertEqual(deaths["total"], baseline_deaths)
        self.assertEqual(deaths["notable_total"], 1)
        self.assertEqual(deaths["non_notable"], baseline_deaths - 1)
        self.assertEqual(public["cause_specific_deaths_today"][0]["count"], 1)
        removed = public["cause_specific_deaths_today"][0]["removed"]
        self.assertEqual(sum(item["count"] for item in removed), 1)
        self.assertTrue(all(5 <= item["age"] <= 14 for item in removed))

    def test_empty_cause_specific_input_preserves_legacy_result(self):
        arguments = (
            date(2026, 8, 12),
            self.state,
            {"total": 0},
            self.baseline,
            self.rng_factory,
        )

        legacy = population_step(*arguments)
        explicit_empty = population_step(
            *arguments, cause_specific_deaths=[]
        )

        self.assertEqual(explicit_empty, legacy)

    def test_cause_specific_deaths_above_baseline_are_excess(self):
        baseline_deaths = self.state["cycle"]["plans"][
            "baseline_deaths"
        ][0]

        public, _, deaths, _ = population_step(
            date(2026, 8, 12),
            self.state,
            {"total": 0},
            self.baseline,
            self.rng_factory,
            cause_specific_deaths=[{
                "cause": "dengue",
                "province": "katora",
                "age_group": "60+",
                "count": baseline_deaths + 2,
            }],
        )

        self.assertEqual(deaths["total"], baseline_deaths + 2)
        self.assertEqual(deaths["non_notable"], 0)
        self.assertEqual(deaths["excess"], 2)
        self.assertEqual(public["excess_deaths_today"], 2)

    def test_cause_specific_death_rejects_unknown_cause(self):
        with self.assertRaisesRegex(
            PopulationDataError,
            r"cause_specific_deaths\[0\]\.cause",
        ):
            population_step(
                date(2026, 8, 12),
                self.state,
                {"total": 0},
                self.baseline,
                self.rng_factory,
                cause_specific_deaths=[{
                    "cause": "unknown",
                    "province": "western",
                    "age_group": "5-14",
                    "count": 1,
                }],
            )

    def test_notable_deaths_above_baseline_become_excess(self):
        baseline_deaths = self.state["cycle"]["plans"]["baseline_deaths"][0]
        notable = {
            "traffic": baseline_deaths + 5,
            "drowning": 0,
            "suicide": 0,
            "murder": 0,
            "workplace": 0,
            "lightning": 0,
            "other": 0,
            "total": baseline_deaths + 5,
        }

        public, next_state, deaths, _ = population_step(
            date(2026, 8, 12),
            self.state,
            notable,
            self.baseline,
            self.rng_factory,
        )

        self.assertEqual(deaths["total"], baseline_deaths + 5)
        self.assertEqual(deaths["non_notable"], 0)
        self.assertEqual(deaths["excess"], 5)
        self.assertEqual(public["excess_deaths_today"], 5)
        self.assertEqual(next_state["cycle"]["excess_deaths"], 5)
        self.assertEqual(next_state["excess_deaths_total"], 5)

    def test_monthly_aging_moves_only_current_birthday_bucket(self):
        state = initialize_population_state(
            date(2026, 8, 31),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        original = copy.deepcopy(state)
        month_index = 8
        before_age_9 = state["cohorts"]["male"][9]
        before_age_10 = state["cohorts"]["male"][10]
        ninth_birthdays = state["birthday_buckets"]["male"][9][month_index]
        tenth_birthdays = state["birthday_buckets"]["male"][10][month_index]

        aged = age_population(state, date(2026, 9, 1))

        self.assertEqual(state, original)
        self.assertEqual(
            aged["cohorts"]["male"][9],
            before_age_9 - ninth_birthdays
            + state["birthday_buckets"]["male"][8][month_index],
        )
        self.assertEqual(
            aged["cohorts"]["male"][10],
            before_age_10 - tenth_birthdays + ninth_birthdays,
        )
        self.assertEqual(aged["last_aging_month"], "2026-09")
        self.assertEqual(
            sum(aged["cohorts"]["male"]) + sum(aged["cohorts"]["female"]),
            1_200_000,
        )

    def test_100_plus_group_is_open_and_same_month_is_idempotent(self):
        state = initialize_population_state(
            date(2026, 8, 31),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        month_index = 8
        before_100 = state["cohorts"]["female"][100]
        birthdays_99 = state["birthday_buckets"]["female"][99][month_index]

        aged = age_population(state, date(2026, 9, 1))
        aged_again = age_population(aged, date(2026, 9, 20))

        self.assertEqual(
            aged["cohorts"]["female"][100],
            before_100 + birthdays_99,
        )
        self.assertEqual(aged_again, aged)

    def test_public_age_groups_reconcile_to_population(self):
        public, _, _, _ = population_step(
            date(2026, 8, 12),
            self.state,
            {"total": 0},
            self.baseline,
            self.rng_factory,
        )

        self.assertEqual(
            sum(group["total"] for group in public["five_year_age_groups"]),
            public["population"],
        )
        self.assertEqual(
            public["male_population"] + public["female_population"],
            public["population"],
        )
        self.assertEqual(
            public["children_0_14"]
            + public["working_age_15_64"]
            + public["elderly_65_plus"],
            public["population"],
        )

    def test_removal_falls_back_to_adjacent_available_age(self):
        sparse = {
            "cohorts": {
                "male": [0] * 20 + [1] + [0] * 80,
                "female": [0] * 101,
            },
            "birthday_buckets": {
                "male": [[0] * 12 for _ in range(101)],
                "female": [[0] * 12 for _ in range(101)],
            },
        }
        sparse["birthday_buckets"]["male"][20][0] = 1
        weights = {
            "male": [0.0] * 30 + [1.0] + [0.0] * 70,
            "female": [0.0] * 101,
        }

        _remove_people(
            sparse,
            1,
            weights,
            random.Random(42),
            path="test.removal",
        )

        self.assertEqual(sparse["cohorts"]["male"][20], 0)

    def test_removal_capacity_error_has_state_path(self):
        empty = {
            "cohorts": {sex: [0] * 101 for sex in ("male", "female")},
            "birthday_buckets": {
                sex: [[0] * 12 for _ in range(101)]
                for sex in ("male", "female")
            },
        }
        weights = {
            "male": [1.0] + [0.0] * 100,
            "female": [0.0] * 101,
        }

        with self.assertRaisesRegex(PopulationDataError, r"^test\.capacity"):
            _remove_people(
                empty,
                1,
                weights,
                random.Random(42),
                path="test.capacity",
            )

    def test_removal_uses_other_sex_after_preferred_sex_is_exhausted(self):
        sparse = {
            "cohorts": {
                "male": [0] * 101,
                "female": [0] * 22 + [1] + [0] * 78,
            },
            "birthday_buckets": {
                sex: [[0] * 12 for _ in range(101)]
                for sex in ("male", "female")
            },
        }
        sparse["birthday_buckets"]["female"][22][0] = 1
        weights = {
            "male": [0.0] * 30 + [1.0] + [0.0] * 70,
            "female": [0.0] * 101,
        }

        _remove_people(
            sparse,
            1,
            weights,
            random.Random(42),
            path="test.other_sex",
        )

        self.assertEqual(sparse["cohorts"]["female"][22], 0)


class PopulationCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = PopulationBaseline.from_json(DATA)

    @staticmethod
    def rng_factory(d):
        return lambda name: random.Random(f"{d.isoformat()}:{name}")

    def run_days(self, days, state=None):
        state = state or initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        daily = []
        first_date = date.fromisoformat(state["cycle"]["start_date"]) + timedelta(
            days=state["cycle"]["offset"]
        )
        for offset in range(days):
            d = first_date + timedelta(days=offset)
            public, state, _, _ = population_step(
                d,
                state,
                {"total": 0},
                self.baseline,
                self.rng_factory(d),
            )
            daily.append(public)
        return state, daily

    def test_first_365_days_hit_exact_population_accounts(self):
        state, daily = self.run_days(365)

        self.assertEqual(sum(day["births_today"] for day in daily), 27_500)
        self.assertEqual(
            sum(day["baseline_deaths_today"] for day in daily), 6_600
        )
        self.assertEqual(
            sum(day["returning_diaspora_today"] for day in daily), 2_500
        )
        self.assertEqual(
            sum(day["foreign_immigrants_today"] for day in daily), 2_200
        )
        self.assertEqual(sum(day["emigrants_today"] for day in daily), 2_800)
        self.assertEqual(daily[-1]["population"], 1_222_800)
        self.assertEqual(state["cycle"]["offset"], 365)
        self.assertEqual(state["cycle"]["cumulative"], state["cycle"]["targets"])
        self.assertGreater(len({day["births_today"] for day in daily}), 1)
        self.assertGreater(
            len({day["population_change_today"] for day in daily}), 1
        )

    def test_full_cycle_excess_deaths_reduce_only_the_final_population(self):
        state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        baseline_deaths = state["cycle"]["plans"]["baseline_deaths"][0]
        d = date(2026, 8, 12)
        _, state, _, _ = population_step(
            d,
            state,
            {"traffic": baseline_deaths + 10, "total": baseline_deaths + 10},
            self.baseline,
            self.rng_factory(d),
        )

        state, daily = self.run_days(364, state)

        self.assertEqual(daily[-1]["population"], 1_222_790)
        self.assertEqual(state["cycle"]["excess_deaths"], 10)

    def test_day_366_starts_a_long_term_cycle(self):
        state, _ = self.run_days(365)
        d = date(2027, 8, 12)

        public, next_state, _, _ = population_step(
            d,
            state,
            {"total": 0},
            self.baseline,
            self.rng_factory(d),
        )

        self.assertEqual(next_state["cycle"]["index"], 1)
        self.assertEqual(next_state["cycle"]["start_date"], "2027-08-12")
        self.assertEqual(next_state["cycle"]["offset"], 1)
        self.assertLess(next_state["cycle"]["tfr"], 2.3)
        self.assertLess(
            next_state["cycle"]["targets"]["returning_diaspora"],
            2_500,
        )
        parameters = next_state["cycle"]["parameters"]
        self.assertEqual(parameters["version"], "mariven-demographic-path-v1")
        self.assertGreater(parameters["elapsed_years"], 0)
        self.assertLess(parameters["mortality_improvement_factor"], 1.0)
        self.assertLess(parameters["returning_diaspora_decay_factor"], 1.0)
        self.assertGreater(parameters["migration_population_scale"], 1.0)
        self.assertEqual(public["baseline_period_end"], "2028-08-10")

    def test_long_term_birth_target_uses_age_specific_fertility(self):
        state, _ = self.run_days(365)
        older_mothers = copy.deepcopy(state)
        moved = 1_000
        source_age = 27
        target_age = 49
        remaining = moved
        for month in range(12):
            available = older_mothers["birthday_buckets"]["female"][
                source_age
            ][month]
            transfer = min(remaining, available)
            older_mothers["birthday_buckets"]["female"][source_age][
                month
            ] -= transfer
            older_mothers["birthday_buckets"]["female"][target_age][
                month
            ] += transfer
            remaining -= transfer
        self.assertEqual(remaining, 0)
        older_mothers["cohorts"]["female"][source_age] -= moved
        older_mothers["cohorts"]["female"][target_age] += moved

        d = date(2027, 8, 12)
        _, reference, _, _ = population_step(
            d,
            state,
            {"total": 0},
            self.baseline,
            self.rng_factory(d),
        )
        _, shifted, _, _ = population_step(
            d,
            older_mothers,
            {"total": 0},
            self.baseline,
            self.rng_factory(d),
        )

        self.assertGreater(
            reference["cycle"]["targets"]["births"],
            shifted["cycle"]["targets"]["births"],
        )

    def test_serialized_resume_matches_continuous_population_run(self):
        initial = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            self.baseline,
            base_seed=42,
        )
        continuous, _ = self.run_days(80, copy.deepcopy(initial))
        checkpoint, _ = self.run_days(35, copy.deepcopy(initial))
        reloaded = json.loads(json.dumps(checkpoint, ensure_ascii=False))
        resumed, _ = self.run_days(45, reloaded)

        self.assertEqual(continuous, resumed)

    def test_long_term_population_structure_moves_toward_2035_anchors(self):
        days = (date(2035, 8, 11) - date(2026, 8, 11)).days

        state, daily = self.run_days(days)

        final = daily[-1]
        previous_year_population = daily[-366]["population"]
        recent_growth_pct = (
            (final["population"] - previous_year_population)
            / previous_year_population
            * 100
        )
        initial_elderly_share = (
            self.baseline.calibration["elderly_65_plus"] / 1_200_000
        )
        final_elderly_share = (
            final["elderly_65_plus"] / final["population"]
        )

        self.assertAlmostEqual(state["cycle"]["tfr"], 2.0, delta=0.05)
        self.assertLess(
            state["cycle"]["targets"]["returning_diaspora"],
            1_500,
        )
        self.assertGreater(final["median_age"], 27.8)
        self.assertLess(final["median_age"], 35.0)
        self.assertGreater(final_elderly_share, initial_elderly_share)
        self.assertGreater(recent_growth_pct, 0.7)
        self.assertLess(recent_growth_pct, 1.6)
        validate_population_state(
            state,
            final["population"],
            self.baseline,
        )
        self.assertLess(
            len(json.dumps(state, ensure_ascii=False).encode("utf-8")),
            250_000,
        )


if __name__ == "__main__":
    unittest.main()
