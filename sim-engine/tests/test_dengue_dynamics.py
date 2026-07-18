import copy
import random
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from dengue_model import DengueBaseline
from population_model import PopulationBaseline, initialize_population_state

try:
    import dengue_dynamics
except ImportError:
    dengue_dynamics = None

allocate_province_ages = getattr(
    dengue_dynamics, "allocate_province_ages", None
)
advance_human_state = getattr(dengue_dynamics, "advance_human_state", None)
initialize_human_state = getattr(
    dengue_dynamics, "initialize_human_state", None
)
is_susceptible = getattr(dengue_dynamics, "is_susceptible", None)
national_age_totals = getattr(dengue_dynamics, "national_age_totals", None)
total_humans = getattr(dengue_dynamics, "total_humans", None)


class DengueHumanStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = DengueBaseline.from_json(
            ROOT / "data" / "dengue_baseline_2026.json"
        )
        population_baseline = PopulationBaseline.from_json(
            ROOT / "data" / "population_baseline_2026.json"
        )
        cls.population_state = initialize_population_state(
            date(2026, 8, 11),
            1_200_000,
            population_baseline,
            base_seed=42,
        )

    @staticmethod
    def rng_factory(name):
        return random.Random(f"dengue-test:{name}")

    def test_module_exposes_human_state_functions(self):
        self.assertIsNotNone(dengue_dynamics)
        self.assertIsNotNone(national_age_totals)
        self.assertIsNotNone(allocate_province_ages)
        self.assertIsNotNone(initialize_human_state)
        self.assertIsNotNone(advance_human_state)
        self.assertIsNotNone(total_humans)

    def test_national_age_totals_cover_population(self):
        self.assertIsNotNone(national_age_totals)
        totals = national_age_totals(self.population_state)

        self.assertEqual(tuple(totals), self.baseline.age_groups)
        self.assertEqual(sum(totals.values()), 1_200_000)

    def test_province_age_allocation_reconciles_both_margins(self):
        self.assertIsNotNone(allocate_province_ages)
        totals = national_age_totals(self.population_state)
        allocated = allocate_province_ages(totals, self.baseline)

        for age in self.baseline.age_groups:
            self.assertEqual(
                sum(province[age] for province in allocated.values()),
                totals[age],
            )
        for province, expected in self.baseline.province_populations.items():
            self.assertEqual(sum(allocated[province].values()), expected)

    def test_same_serotype_cannot_reinfect_immune_mask(self):
        self.assertIsNotNone(is_susceptible)
        self.assertFalse(is_susceptible(mask=0b0010, serotype_index=1))
        self.assertTrue(is_susceptible(mask=0b0010, serotype_index=0))

    def test_initialized_human_state_is_integer_and_conserving(self):
        self.assertIsNotNone(initialize_human_state)
        totals = national_age_totals(self.population_state)
        allocated = allocate_province_ages(totals, self.baseline)
        state = initialize_human_state(
            allocated, self.baseline, self.rng_factory
        )

        self.assertEqual(total_humans(state), 1_200_000)
        self.assertTrue(
            all(
                isinstance(count, int) and count >= 0
                for province in state.values()
                for masks in province["susceptible"].values()
                for count in masks.values()
            )
        )
        self.assertGreater(
            state["katora"]["susceptible"]["30-59"].get("0010", 0),
            0,
        )

    def test_cross_immunity_expires_on_scheduled_ring_day(self):
        self.assertIsNotNone(advance_human_state)
        state = self._minimal_state(mask="0001", count=7)
        state["katora"]["susceptible"]["0-4"]["0001"] = 0
        state["katora"]["cross_protected"][0] = [
            {"age_group": "0-4", "new_mask": 1, "count": 7}
        ]
        next_state, flows = advance_human_state(
            state, self._zero_force(), self.baseline, self.rng_factory
        )

        self.assertEqual(flows["cross_protection_expired"], 7)
        self.assertEqual(
            next_state["katora"]["susceptible"]["0-4"]["0001"], 7
        )
        self.assertEqual(next_state["katora"]["cross_immunity_cursor"], 1)

    def test_immune_stock_ignores_force_from_seen_serotype(self):
        self.assertIsNotNone(advance_human_state)
        state = self._minimal_state(mask="0001", count=7)
        force = self._zero_force()
        force["katora"]["DENV-1"] = 1.0

        next_state, flows = advance_human_state(
            state, force, self.baseline, self.rng_factory
        )

        self.assertEqual(flows["new_infections"], 0)
        self.assertEqual(
            next_state["katora"]["susceptible"]["0-4"]["0001"], 7
        )

    def test_unseen_serotype_creates_exposed_flow_by_serotype(self):
        state = self._minimal_state(mask="0000", count=20)
        force = self._zero_force()
        force["katora"]["DENV-2"] = 100.0

        next_state, flows = advance_human_state(
            state, force, self.baseline, self.rng_factory
        )

        self.assertIn("new_infections_by_serotype", flows)
        self.assertEqual(flows["new_infections_by_serotype"]["DENV-2"], 20)
        self.assertEqual(sum(c["count"] for c in next_state["katora"]["exposed"]), 20)
        self.assertEqual(total_humans(next_state), 20)

    def test_exposed_progression_reports_serotype_flow(self):
        state = self._minimal_state(mask="0000", count=5)
        state["katora"]["susceptible"]["0-4"]["0000"] = 0
        state["katora"]["exposed"] = [{
            "age_group": "0-4",
            "prior_mask": 0,
            "serotype": "DENV-3",
            "days_remaining": 1,
            "count": 5,
        }]

        next_state, flows = advance_human_state(
            state, self._zero_force(), self.baseline, self.rng_factory
        )

        self.assertIn("exposed_to_infectious_by_serotype", flows)
        self.assertEqual(
            flows["exposed_to_infectious_by_serotype"]["DENV-3"], 5
        )
        self.assertEqual(
            sum(c["count"] for c in next_state["katora"]["infectious"]),
            5,
        )

    def test_recovery_reports_serotype_and_enters_cross_protection(self):
        state = self._minimal_state(mask="0000", count=4)
        state["katora"]["susceptible"]["0-4"]["0000"] = 0
        state["katora"]["infectious"] = [{
            "age_group": "0-4",
            "prior_mask": 0,
            "serotype": "DENV-4",
            "days_remaining": 1,
            "count": 4,
        }]

        next_state, flows = advance_human_state(
            state, self._zero_force(), self.baseline, self.rng_factory
        )

        self.assertIn("recoveries_by_serotype", flows)
        self.assertEqual(flows["recoveries_by_serotype"]["DENV-4"], 4)
        self.assertEqual(
            next_state["katora"]["cross_protected"][0],
            [{"age_group": "0-4", "new_mask": 8, "count": 4}],
        )
        self.assertEqual(total_humans(next_state), 4)

    def _minimal_state(self, *, mask, count):
        susceptible = {
            age: ({mask: count} if age == "0-4" else {})
            for age in self.baseline.age_groups
        }
        return {
            "katora": {
                "population_by_age": {
                    age: count if age == "0-4" else 0
                    for age in self.baseline.age_groups
                },
                "susceptible": susceptible,
                "exposed": [],
                "infectious": [],
                "cross_protected": [[] for _ in range(180)],
                "cross_immunity_cursor": 0,
            }
        }

    @staticmethod
    def _zero_force():
        return {
            "katora": {
                serotype: 0.0
                for serotype in ("DENV-1", "DENV-2", "DENV-3", "DENV-4")
            }
        }


if __name__ == "__main__":
    unittest.main()
