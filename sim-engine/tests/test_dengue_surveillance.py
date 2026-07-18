import copy
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from dengue_model import DengueBaseline

try:
    import dengue_surveillance
except ImportError:
    dengue_surveillance = None

advance_surveillance = getattr(
    dengue_surveillance, "advance_surveillance", None
)
advance_alert_state = getattr(
    dengue_surveillance, "advance_alert_state", None
)
classify_clinical_outcomes = getattr(
    dengue_surveillance, "classify_clinical_outcomes", None
)
epidemiological_week = getattr(
    dengue_surveillance, "epidemiological_week", None
)
province_alert = getattr(dengue_surveillance, "province_alert", None)
release_dates = getattr(dengue_surveillance, "release_dates", None)
severe_probability = getattr(
    dengue_surveillance, "severe_probability", None
)
treated_fatality_probability = getattr(
    dengue_surveillance, "treated_fatality_probability", None
)
surveillance_snapshot = getattr(
    dengue_surveillance, "surveillance_snapshot", None
)


class DengueSurveillanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = DengueBaseline.from_json(
            ROOT / "data" / "dengue_baseline_2026.json"
        )

    @staticmethod
    def rng_factory(name):
        return random.Random(f"surveillance-test:{name}")

    def test_module_exposes_surveillance_functions(self):
        self.assertIsNotNone(dengue_surveillance)
        self.assertIsNotNone(classify_clinical_outcomes)
        self.assertIsNotNone(advance_surveillance)
        self.assertIsNotNone(release_dates)
        self.assertIsNotNone(epidemiological_week)
        self.assertIsNotNone(province_alert)
        self.assertIsNotNone(advance_alert_state)
        self.assertIsNotNone(surveillance_snapshot)

    def test_secondary_infection_has_higher_severe_probability(self):
        self.assertIsNotNone(severe_probability)
        primary = severe_probability("15-29", 0, self.baseline)
        secondary = severe_probability("15-29", 0b0001, self.baseline)

        self.assertGreater(secondary, primary)

    def test_overload_increases_treated_fatality_smoothly(self):
        self.assertIsNotNone(treated_fatality_probability)
        low = treated_fatality_probability(0.20, self.baseline)
        middle = treated_fatality_probability(0.85, self.baseline)
        high = treated_fatality_probability(1.00, self.baseline)

        self.assertLess(low, middle)
        self.assertLess(middle, high)
        self.assertLess(low, 0.01)

    def test_clinical_tree_preserves_parent_bounds(self):
        self.assertIsNotNone(classify_clinical_outcomes)
        infection_flows = {
            "new_infections": 100,
            "infections_by_cohort": [{
                "province": "katora",
                "age_group": "15-29",
                "prior_mask": 1,
                "serotype": "DENV-2",
                "count": 100,
            }],
        }

        outcomes = classify_clinical_outcomes(
            infection_flows, 0.20, self.baseline, self.rng_factory
        )

        self.assertEqual(outcomes["infections"], 100)
        self.assertLessEqual(outcomes["symptomatic"], 100)
        self.assertLessEqual(outcomes["severe"], outcomes["symptomatic"])
        self.assertLessEqual(outcomes["hospitalized"], outcomes["severe"])
        self.assertLessEqual(outcomes["deaths"], outcomes["severe"])
        self.assertLessEqual(outcomes["reported"], outcomes["symptomatic"])
        self.assertLessEqual(outcomes["sampled"], outcomes["reported"])

    def test_release_dates_are_plus_4_14_28(self):
        self.assertIsNotNone(release_dates)
        self.assertEqual(
            release_dates(date(2026, 8, 16)),
            {
                "provisional": date(2026, 8, 20),
                "revised": date(2026, 8, 30),
                "final": date(2026, 9, 13),
            },
        )

    def test_epi_week_is_monday_through_sunday(self):
        self.assertIsNotNone(epidemiological_week)
        self.assertEqual(
            epidemiological_week(date(2026, 8, 12)),
            (date(2026, 8, 10), date(2026, 8, 16)),
        )

    def test_lab_capacity_leaves_backlog(self):
        self.assertIsNotNone(advance_surveillance)
        state = self._empty_state()
        state["laboratory_queue"] = [{
            "due_date": "2026-08-12",
            "province": "katora",
            "age_group": "15-29",
            "serotype": "DENV-2",
            "count": 50,
        }]

        next_state, _ = advance_surveillance(
            date(2026, 8, 12),
            state,
            self._empty_clinical(),
            self.baseline,
            self.rng_factory,
        )

        self.assertEqual(next_state["daily_totals"]["lab_processed"], 40)
        self.assertEqual(
            sum(item["count"] for item in next_state["laboratory_queue"]),
            10,
        )

    def test_provisional_release_is_not_duplicated(self):
        self.assertIsNotNone(advance_surveillance)
        state = self._empty_state()
        state["weekly_ledger"] = [{
            "week_start": "2026-08-10",
            "week_end": "2026-08-16",
            "reported_by_province": {
                province: 1 if province == "katora" else 0
                for province in self.baseline.province_populations
            },
            "reported_national": 1,
            "confirmed_national": 0,
            "severe_national": 0,
            "hospitalized_national": 0,
            "deaths_national": 0,
            "source": "dynamic",
        }]

        first, events = advance_surveillance(
            date(2026, 8, 20), state, self._empty_clinical(),
            self.baseline, self.rng_factory,
        )
        second, second_events = advance_surveillance(
            date(2026, 8, 20), first, self._empty_clinical(),
            self.baseline, self.rng_factory,
        )

        self.assertEqual(len(first["release_vintages"]), 1)
        self.assertEqual(first["release_vintages"][0]["vintage"], "provisional")
        self.assertEqual(len(events), 1)
        self.assertEqual(second["release_vintages"], first["release_vintages"])
        self.assertEqual(second_events, [])

    def test_outbreak_threshold_requires_confirmed_cluster(self):
        self.assertIsNotNone(province_alert)
        level = province_alert(
            cases=20,
            p75=5,
            p90=10,
            p95=15,
            rt=1.2,
            confirmed=3,
            pressure=0.20,
            previous="alert",
        )
        without_confirmation = province_alert(
            cases=20,
            p75=5,
            p90=10,
            p95=15,
            rt=1.2,
            confirmed=2,
            pressure=0.20,
            previous="alert",
        )

        self.assertEqual(level, "outbreak")
        self.assertEqual(without_confirmation, "alert")

    def test_clinical_reports_are_delayed_then_enter_lab_queue(self):
        self.assertIsNotNone(advance_surveillance)
        state = self._empty_state()
        clinical = {
            **self._empty_clinical(),
            "infections": 20,
            "symptomatic": 12,
            "reported": 10,
            "sampled": 4,
            "severe": 1,
            "hospitalized": 1,
            "cohort_outcomes": [{
                "province": "katora",
                "age_group": "15-29",
                "prior_mask": 0,
                "serotype": "DENV-2",
                "infections": 20,
                "symptomatic": 12,
                "warning": 2,
                "severe": 1,
                "hospitalized": 1,
                "deaths": 0,
                "reported": 10,
                "sampled": 4,
            }],
        }

        state, _ = advance_surveillance(
            date(2026, 8, 12), state, clinical,
            self.baseline, self.rng_factory,
        )

        self.assertEqual(state["daily_totals"]["reported"], 0)
        self.assertEqual(
            sum(item["count"] for item in state["reporting_queue"]), 10
        )
        self.assertGreaterEqual(
            min(date.fromisoformat(item["due_date"]) for item in state["reporting_queue"]),
            date(2026, 8, 16),
        )

        for day in range(13, 27):
            state, _ = advance_surveillance(
                date(2026, 8, day), state, self._empty_clinical(),
                self.baseline, self.rng_factory,
            )
        self.assertEqual(
            sum(record["reported"] for record in state["daily_records"]),
            10,
        )
        self.assertEqual(
            sum(record["sampled"] for record in state["daily_records"]),
            4,
        )

    def test_due_deaths_keep_structured_province_and_age_requests(self):
        state = self._empty_state()
        clinical = {
            **self._empty_clinical(),
            "infections": 1,
            "symptomatic": 1,
            "severe": 1,
            "hospitalized": 1,
            "deaths": 1,
            "cohort_outcomes": [{
                "province": "katora",
                "age_group": "60+",
                "prior_mask": 1,
                "serotype": "DENV-2",
                "infections": 1,
                "symptomatic": 1,
                "warning": 0,
                "severe": 1,
                "hospitalized": 1,
                "deaths": 1,
                "reported": 0,
                "sampled": 0,
            }],
        }

        requests = []
        for offset in range(10):
            state, _ = advance_surveillance(
                date(2026, 8, 12) + timedelta(days=offset),
                state,
                clinical if offset == 0 else self._empty_clinical(),
                self.baseline,
                self.rng_factory,
            )
            requests.extend(state.get("daily_death_requests", []))

        self.assertEqual(requests, [{
            "cause": "dengue",
            "province": "katora",
            "age_group": "60+",
            "count": 1,
        }])

    def test_revision_vintages_form_explicit_chain(self):
        state = self._empty_state()
        state["weekly_ledger"] = [{
            "week_start": "2026-08-10",
            "week_end": "2026-08-16",
            "reported_by_province": {
                province: 1 if province == "katora" else 0
                for province in self.baseline.province_populations
            },
            "reported_national": 1,
            "confirmed_national": 0,
            "severe_national": 0,
            "hospitalized_national": 0,
            "deaths_national": 0,
            "source": "dynamic",
        }]
        for release_day in (
            date(2026, 8, 20),
            date(2026, 8, 30),
            date(2026, 9, 13),
        ):
            state, _ = advance_surveillance(
                release_day, state, self._empty_clinical(),
                self.baseline, self.rng_factory,
            )

        self.assertEqual(
            [item["vintage"] for item in state["release_vintages"]],
            ["provisional", "revised", "final"],
        )
        self.assertIsNone(
            state["release_vintages"][0].get("revision_of", "missing")
        )
        self.assertEqual(
            state["release_vintages"][1]["revision_of"], "provisional"
        )
        self.assertEqual(state["release_vintages"][2]["revision_of"], "revised")

    def test_alert_state_requires_two_outbreak_weeks(self):
        self.assertIsNotNone(advance_alert_state)
        initial = {
            "level": "alert",
            "outbreak_weeks": 0,
            "recovery_weeks": 0,
        }
        first = advance_alert_state(initial, "outbreak")
        second = advance_alert_state(first, "outbreak")

        self.assertEqual(first["level"], "alert")
        self.assertEqual(second["level"], "outbreak")

    def test_snapshot_keeps_estimated_and_reported_separate(self):
        self.assertIsNotNone(surveillance_snapshot)
        state = self._empty_state()
        state["daily_totals"] = {
            "date": "2026-08-12",
            "estimated_infections": 12,
            "symptomatic": 5,
            "reported": 2,
            "lab_processed": 1,
            "confirmed": 1,
            "severe": 0,
            "hospitalized": 0,
            "deaths": 0,
        }
        public = surveillance_snapshot(
            date(2026, 8, 12),
            state,
            self.baseline.province_populations,
            self.baseline,
        )

        self.assertEqual(public["national"]["estimated_infections"], 12)
        self.assertEqual(public["national"]["reported_cases"], 2)
        self.assertEqual(public["national"]["lab_confirmed"], 1)

    def _empty_state(self):
        return {
            "reporting_queue": [],
            "laboratory_queue": [],
            "daily_records": [],
            "weekly_ledger": [],
            "release_vintages": [],
            "alert_state": {
                province: "baseline"
                for province in self.baseline.province_populations
            },
            "daily_totals": {},
        }

    @staticmethod
    def _empty_clinical():
        return {
            "infections": 0,
            "symptomatic": 0,
            "warning": 0,
            "severe": 0,
            "hospitalized": 0,
            "deaths": 0,
            "reported": 0,
            "sampled": 0,
            "cohort_outcomes": [],
        }


if __name__ == "__main__":
    unittest.main()
