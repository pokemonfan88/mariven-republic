import copy
import json
import subprocess
import sys
import tempfile
from datetime import date
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data" / "gdp_baseline_2026.json"
SOURCE = ROOT / "data" / "sources" / "gdp_external_anchors_2026.json"
NATION_PROFILE = ROOT / "data" / "nation_profile.json"

try:
    import gdp_model
except ImportError:
    gdp_model = None

GdpBaseline = getattr(gdp_model, "GdpBaseline", None)
GdpDataError = getattr(gdp_model, "GdpDataError", None)
initialize_gdp_state = getattr(gdp_model, "initialize_gdp_state", None)
gdp_step = getattr(gdp_model, "gdp_step", None)
validate_gdp_state = getattr(gdp_model, "validate_gdp_state", None)

try:
    from build_gdp_baseline import build_baseline
except ImportError:
    build_baseline = None


class GdpBaselineTests(unittest.TestCase):
    def test_gdp_module_exposes_baseline_loader(self):
        self.assertIsNotNone(GdpBaseline)
        self.assertTrue(hasattr(GdpBaseline, "from_json"))

    def test_gdp_module_exposes_labeled_data_error(self):
        self.assertIsNotNone(GdpDataError)
        self.assertTrue(issubclass(GdpDataError, ValueError))

    def test_committed_baseline_has_2025_and_2026_anchors(self):
        self.assertTrue(DATA.exists(), "GDP baseline data file is missing")

        baseline = GdpBaseline.from_json(DATA)

        self.assertEqual(baseline.version, "mariven-gdp-2026-v1")
        self.assertEqual(baseline.base_year, 2025)
        self.assertEqual(baseline.base_nominal_gdp_mvl, 16_350_000_000)
        self.assertEqual(baseline.real_growth_2025_pct, 3.1)
        self.assertEqual(baseline.real_growth_2026_pct, 2.4)
        self.assertEqual(baseline.deflator_growth_2026_pct, 2.2)
        self.assertAlmostEqual(
            baseline.nominal_target_2026_mvl,
            17_110_732_800,
            delta=0.01,
        )

    def test_production_accounts_reconcile_to_four_worldbuilding_groups(self):
        baseline = GdpBaseline.from_json(DATA)

        industries = getattr(baseline, "industries", None)
        self.assertIsNotNone(industries)
        self.assertEqual(len(industries), 14)
        self.assertAlmostEqual(
            sum(item.share_pct for item in industries.values()),
            100.0,
        )
        group_shares = {}
        for item in industries.values():
            group_shares[item.group] = (
                group_shares.get(item.group, 0.0) + item.share_pct
            )
        self.assertEqual(
            {key: round(value, 1) for key, value in group_shares.items()},
            {
                "primary_and_mining": 14.2,
                "industry": 17.8,
                "services": 57.4,
                "net_product_taxes": 10.6,
            },
        )
        self.assertAlmostEqual(
            sum(item.nominal_mvl for item in industries.values()),
            baseline.base_nominal_gdp_mvl,
            delta=0.01,
        )

    def test_expenditure_accounts_close_and_separate_tourism_receipts(self):
        baseline = GdpBaseline.from_json(DATA)

        expenditure = getattr(baseline, "expenditure", None)
        tourism = getattr(baseline, "tourism", None)
        self.assertIsNotNone(expenditure)
        self.assertIsNotNone(tourism)
        calculated_gdp = (
            expenditure["household_consumption_mvl"]
            + expenditure["government_consumption_mvl"]
            + expenditure["gross_fixed_capital_formation_mvl"]
            + expenditure["changes_in_inventories_mvl"]
            + expenditure["exports_goods_services_mvl"]
            - expenditure["imports_goods_services_mvl"]
            + expenditure["statistical_discrepancy_mvl"]
        )
        self.assertAlmostEqual(
            calculated_gdp,
            baseline.base_nominal_gdp_mvl,
            delta=0.01,
        )
        self.assertEqual(tourism["visitor_spending_mvl"], 6_208_400_000)
        self.assertEqual(tourism["direct_gva_mvl"], 1_635_000_000)
        self.assertEqual(tourism["direct_gva_share_pct"], 10.0)
        self.assertGreater(
            tourism["visitor_spending_mvl"], tourism["direct_gva_mvl"]
        )

    def test_nation_profile_uses_reconciled_tourism_accounts(self):
        profile = json.loads(NATION_PROFILE.read_text(encoding="utf-8"))
        tourism = profile["economy"]["tourism"]

        self.assertNotIn("revenue_mvl_billions", tourism)
        self.assertEqual(tourism["visitor_spending_mvl_billions"], 6.2084)
        self.assertEqual(tourism["direct_gva_mvl_billions"], 1.635)
        self.assertEqual(tourism["gdp_share_direct_pct"], 10)

    def test_external_anchors_record_only_available_official_data(self):
        self.assertTrue(SOURCE.exists(), "GDP source extract is missing")
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        sources = source.get("sources")
        self.assertIsInstance(sources, dict)
        self.assertEqual(
            sources["imf_fiji_2026_article_iv"]["extracted"],
            {
                "reference_year": 2026,
                "real_gdp_growth_pct": 2.4,
                "gdp_deflator_growth_pct": 2.2,
                "gdp_current_market_prices_fjd_million": 14_419,
                "gdp_current_market_prices_usd_million": 6_352,
            },
        )
        availability = sources["fiji_2026_release_calendar"]["extracted"]
        self.assertEqual(
            availability["gdp_production_2025_release_date"], "2026-08-31"
        )
        self.assertFalse(
            availability["complete_2025_production_data_available_on_access_date"]
        )

    def test_baseline_metadata_carries_external_anchor_provenance(self):
        baseline = GdpBaseline.from_json(DATA)

        metadata = getattr(baseline, "metadata", None)
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata["accessed_on"], "2026-07-18")
        self.assertEqual(
            metadata["external_anchors"]["real_gdp_growth_2026_pct"], 2.4
        )
        self.assertEqual(
            metadata["external_anchors"]["gdp_deflator_growth_2026_pct"], 2.2
        )
        self.assertEqual(
            metadata["availability"]["fiji_2025_production_release_date"],
            "2026-08-31",
        )
        self.assertFalse(
            metadata["availability"]["fiji_2025_production_available"]
        )
        prior = metadata.get("expenditure_structure_prior_pct")
        self.assertIsInstance(prior, dict)
        self.assertAlmostEqual(prior["final_consumption"], 12.1 / 13.5 * 100)
        self.assertAlmostEqual(prior["gross_capital_formation"], 2.8 / 13.5 * 100)
        self.assertAlmostEqual(prior["net_exports"], -1.4 / 13.5 * 100)

    def test_committed_baseline_is_reproducible_from_generator(self):
        self.assertIsNotNone(build_baseline)
        committed = json.loads(DATA.read_text(encoding="utf-8"))

        self.assertEqual(build_baseline(), committed)

    def test_generator_cli_writes_the_reproducible_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "gdp.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_gdp_baseline.py"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output.exists())
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                json.loads(DATA.read_text(encoding="utf-8")),
            )

    def test_industry_paths_have_complete_seasonality_and_hit_growth_target(self):
        baseline = GdpBaseline.from_json(DATA)
        paths = [
            (
                getattr(item, "quarter_weights", None),
                getattr(item, "real_growth_2026_pct", None),
                item.share_pct,
            )
            for item in baseline.industries.values()
        ]
        self.assertTrue(all(weights is not None for weights, _, _ in paths))
        self.assertTrue(all(growth is not None for _, growth, _ in paths))
        for weights, _, _ in paths:
            self.assertEqual(len(weights), 4)
            self.assertAlmostEqual(sum(weights), 1.0)
            self.assertTrue(all(weight > 0 for weight in weights))
        weighted_growth = sum(
            share * growth / 100.0 for _, growth, share in paths
        )
        self.assertAlmostEqual(
            weighted_growth, baseline.real_growth_2026_pct, places=12
        )

    def test_baseline_rejects_industry_shares_that_do_not_sum_to_100(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["production_accounts"]["industries"][
            "manufacturing"
        ]["share_pct"] += 1.0

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.production_accounts\.industries: shares must sum to 100$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_quarter_weights_that_do_not_sum_to_one(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["production_accounts"]["industries"][
            "construction"
        ]["quarter_weights"][0] += 0.1

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.production_accounts\.industries\.construction\.quarter_weights: weights must sum to 1$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_expenditure_accounts_that_do_not_close(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["expenditure_accounts"]["2025"][
            "household_consumption_mvl"
        ] += 1.0

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.expenditure_accounts\.2025: expenditure identity does not match nominal GDP$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_production_values_that_do_not_match_gdp(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["production_accounts"]["industries"]["mining_quarrying"][
            "nominal_mvl"
        ] += 1.0

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.production_accounts\.industries: nominal values do not match nominal GDP$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_unknown_version(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["version"] = "future"

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.version: expected mariven-gdp-2026-v1$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_annual_path_that_differs_from_source_anchor(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["annual_path"]["2026"]["real_growth_pct"] = 2.5

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.annual_path\.2026\.real_growth_pct: does not match the external anchor$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_tourism_direct_gva_mismatch(self):
        invalid = json.loads(DATA.read_text(encoding="utf-8"))
        invalid["tourism_reconciliation"]["direct_gva_mvl"] += 1.0

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid-gdp.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.tourism_reconciliation\.direct_gva_mvl: does not equal the stated GDP share$",
            ):
                GdpBaseline.from_json(path)

    def test_baseline_rejects_source_extract_without_official_url(self):
        baseline_data = json.loads(DATA.read_text(encoding="utf-8"))
        source_data = json.loads(SOURCE.read_text(encoding="utf-8"))
        source_data["sources"]["imf_fiji_2026_article_iv"].pop("url")

        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            path = data_dir / "gdp.json"
            path.write_text(json.dumps(baseline_data), encoding="utf-8")
            (source_dir / "gdp_external_anchors_2026.json").write_text(
                json.dumps(source_data), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                GdpDataError,
                r"^baseline\.metadata\.source_extract\.sources\.imf_fiji_2026_article_iv\.url: expected an official HTTPS URL$",
            ):
                GdpBaseline.from_json(path)

    def test_release_policy_has_provisional_revised_and_final_vintages(self):
        baseline = GdpBaseline.from_json(DATA)

        policy = getattr(baseline, "release_lags_days", None)
        self.assertEqual(
            policy,
            {"provisional": 90, "revised": 180, "final": 365},
        )

    def test_driver_parameters_are_versioned_in_the_baseline(self):
        baseline = GdpBaseline.from_json(DATA)
        drivers = getattr(baseline, "driver_parameters", None)

        self.assertIsInstance(drivers, dict)
        self.assertEqual(drivers["version"], "mariven-gdp-drivers-2026-v1")
        self.assertEqual(
            drivers["reference_values"],
            {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
                "mvl_per_usd": 2.18,
                "cpi_yoy_pct": 2.2,
                "population": 1_200_000,
            },
        )
        self.assertIn("commodity_elasticities", drivers)
        self.assertIn("exchange_elasticities", drivers)
        self.assertIn("population_elasticities", drivers)
        self.assertIn("rainfall_elasticities_per_mm", drivers)
        self.assertIn("cyclone_high_factors", drivers)


class GdpStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = GdpBaseline.from_json(DATA)

    def test_model_exposes_state_initializer(self):
        self.assertIsNotNone(initialize_gdp_state)
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        self.assertIsInstance(state, dict)

    def test_initializer_creates_a_valid_gdp_state(self):
        self.assertIsNotNone(validate_gdp_state)
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)

        self.assertIsNone(
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)
        )

    def test_validation_rejects_closed_quarter_production_mismatch(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        state["quarterly_history"][-1]["production"]["real_gdp_mvl"] += 1.0

        with self.assertRaisesRegex(
            GdpDataError,
            r"^state\.model_state\.gdp\.quarterly_history\[5\]\.production\.real_gdp_mvl",
        ):
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)

    def test_validation_rejects_closed_quarter_expenditure_mismatch(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        state["quarterly_history"][-1]["expenditure"][
            "household_consumption_mvl"
        ] += 1.0

        with self.assertRaisesRegex(
            GdpDataError,
            r"^state\.model_state\.gdp\.quarterly_history\[5\]\.expenditure: expenditure identity does not match nominal GDP$",
        ):
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)

    def test_validation_rejects_current_quarter_period_mismatch(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        state["current_quarter"]["period"] = "2026-Q4"

        with self.assertRaisesRegex(
            GdpDataError,
            r"^state\.model_state\.gdp\.current_quarter\.period: does not match state date$",
        ):
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)

    def test_validation_rejects_out_of_order_quarter_history(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        state["quarterly_history"][0], state["quarterly_history"][1] = (
            state["quarterly_history"][1],
            state["quarterly_history"][0],
        )

        with self.assertRaisesRegex(
            GdpDataError,
            r"^state\.model_state\.gdp\.quarterly_history\[1\]\.period: quarters must be ordered and consecutive$",
        ):
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)

    def test_validation_rejects_release_date_outside_policy(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        q1_2026 = state["quarterly_history"][-2]
        q1_2026["vintages"][0]["release_date"] = "2026-06-28"

        with self.assertRaisesRegex(
            GdpDataError,
            r"^state\.model_state\.gdp\.quarterly_history\[4\]\.vintages\[0\]\.release_date: does not match the release policy$",
        ):
            validate_gdp_state(state, date(2026, 8, 11), self.baseline)

    def test_initializer_seeds_closed_quarters_release_and_current_accumulator(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)

        self.assertEqual(state.get("current_quarter", {}).get("period"), "2026-Q3")
        self.assertEqual(state["current_quarter"]["days_elapsed"], 42)
        periods = [item["period"] for item in state.get("quarterly_history", [])]
        self.assertEqual(
            periods,
            [
                "2025-Q1",
                "2025-Q2",
                "2025-Q3",
                "2025-Q4",
                "2026-Q1",
                "2026-Q2",
            ],
        )
        latest = state.get("latest_release")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["period"], "2026-Q1")
        self.assertEqual(latest["vintage"], "provisional")
        self.assertEqual(latest["release_date"], "2026-06-29")
        q2 = state["quarterly_history"][-1]
        self.assertEqual(q2["period"], "2026-Q2")
        self.assertEqual(q2["vintages"], [])

    def test_latest_release_contains_reconciled_production_and_expenditure(self):
        state = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        latest = state["latest_release"]

        contributions = latest.get("industry_contributions_pct")
        shares = latest.get("industry_shares_pct")
        expenditure = latest.get("expenditure")
        self.assertIsInstance(contributions, dict)
        self.assertIsInstance(shares, dict)
        self.assertIsInstance(expenditure, dict)
        self.assertAlmostEqual(sum(shares.values()), 100.0, places=12)
        self.assertAlmostEqual(
            sum(contributions.values()), latest["real_growth_yoy_pct"], places=12
        )
        calculated = (
            expenditure["household_consumption_mvl"]
            + expenditure["government_consumption_mvl"]
            + expenditure["gross_fixed_capital_formation_mvl"]
            + expenditure["changes_in_inventories_mvl"]
            + expenditure["exports_goods_services_mvl"]
            - expenditure["imports_goods_services_mvl"]
            + expenditure["statistical_discrepancy_mvl"]
        )
        self.assertAlmostEqual(calculated, latest["nominal_gdp_mvl"], delta=0.01)
        self.assertEqual(latest.get("status"), "official_release")
        self.assertFalse(latest.get("is_model_nowcast", True))

    def test_daily_step_is_pure_deterministic_and_advances_accumulator(self):
        self.assertIsNotNone(gdp_step)
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        original = copy.deepcopy(previous)
        inputs = {
            "weather": {
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "commodities": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            "exchange": {"mvl_per_usd": 2.18},
        }

        first = gdp_step(
            date(2026, 8, 12),
            previous,
            population=1_200_000,
            baseline=self.baseline,
            **inputs,
        )
        second = gdp_step(
            date(2026, 8, 12),
            previous,
            population=1_200_000,
            baseline=self.baseline,
            **inputs,
        )

        self.assertEqual(previous, original)
        self.assertEqual(first, second)
        public, state, events = first
        self.assertEqual(events, [])
        self.assertEqual(state["last_processed_date"], "2026-08-12")
        self.assertEqual(state["current_quarter"]["days_elapsed"], 43)
        self.assertEqual(public["as_of_date"], "2026-08-12")
        self.assertEqual(public["current_quarter_nowcast"]["period"], "2026-Q3")
        self.assertIsInstance(
            public["current_quarter_nowcast"].get("real_growth_yoy_pct"),
            float,
        )
        annual = public["annual_nowcast"]
        risk = annual.get("real_growth_risk_pct")
        self.assertIsInstance(risk, dict)
        self.assertEqual(risk["central"], annual["real_growth_pct"])
        self.assertLess(risk["low"], risk["central"])
        self.assertGreater(risk["high"], risk["central"])

    def test_cyclone_risk_reduces_exposed_sectors_without_touching_ict(self):
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        common = {
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "commodities": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        neutral, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            weather={
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            **common,
        )
        cyclone, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            weather={
                "condition": "台风",
                "cyclone_risk": "high",
                "rainfall_mm": 180.0,
            },
            **common,
        )
        neutral_sectors = neutral["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        cyclone_sectors = cyclone["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        for sector in (
            "construction",
            "accommodation_food_tourism",
            "transport_storage",
        ):
            self.assertLess(cyclone_sectors[sector], neutral_sectors[sector])
        self.assertEqual(
            cyclone_sectors["information_communication"],
            neutral_sectors["information_communication"],
        )

    def test_ordinary_rainfall_uses_declared_bounded_sector_drivers(self):
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        common = {
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "commodities": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        dry, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            weather={
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            **common,
        )
        wet, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            weather={
                "condition": "阵雨",
                "cyclone_risk": "none",
                "rainfall_mm": 40.0,
            },
            **common,
        )
        dry_sectors = dry["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        wet_sectors = wet["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]

        self.assertGreater(
            wet_sectors["agriculture_forestry_fishing"],
            dry_sectors["agriculture_forestry_fishing"],
        )
        self.assertLess(
            wet_sectors["construction"], dry_sectors["construction"]
        )
        self.assertEqual(
            wet_sectors["information_communication"],
            dry_sectors["information_communication"],
        )

    def test_gold_price_only_changes_mining_daily_driver(self):
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        common = {
            "weather": {
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        base, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities={
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            **common,
        )
        high_gold, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities={
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 3200.0,
                "brent_usd_barrel": 73.833,
            },
            **common,
        )
        base_sectors = base["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        high_sectors = high_gold["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        self.assertGreater(
            high_sectors["mining_quarrying"], base_sectors["mining_quarrying"]
        )
        for sector in set(base_sectors) - {"mining_quarrying"}:
            self.assertEqual(high_sectors[sector], base_sectors[sector])

    def test_sugar_price_changes_only_agriculture_and_manufacturing(self):
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        common = {
            "weather": {
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        base, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities={
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            **common,
        )
        high_sugar, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities={
                "sugar_usd_lb": 0.30,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            **common,
        )
        base_sectors = base["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        high_sectors = high_sugar["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        exposed = {"agriculture_forestry_fishing", "manufacturing"}
        for sector in exposed:
            self.assertGreater(high_sectors[sector], base_sectors[sector])
        for sector in set(base_sectors) - exposed:
            self.assertEqual(high_sectors[sector], base_sectors[sector])

    def test_brent_and_exchange_change_only_declared_industries(self):
        previous = initialize_gdp_state(date(2026, 8, 11), self.baseline)
        common = {
            "weather": {
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        reference_commodities = {
            "sugar_usd_lb": 0.19789976464730627,
            "gold_usd_oz": 2648.01,
            "brent_usd_barrel": 73.833,
        }
        base, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities=reference_commodities,
            exchange={"mvl_per_usd": 2.18},
            **common,
        )
        high_brent, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities={**reference_commodities, "brent_usd_barrel": 120.0},
            exchange={"mvl_per_usd": 2.18},
            **common,
        )
        weak_mvl, _, _ = gdp_step(
            date(2026, 8, 12),
            previous,
            commodities=reference_commodities,
            exchange={"mvl_per_usd": 2.6},
            **common,
        )
        base_sectors = base["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        brent_sectors = high_brent["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        exchange_sectors = weak_mvl["current_quarter_nowcast"][
            "real_gva_mvl_by_industry"
        ]
        brent_exposed = {
            "manufacturing",
            "electricity_water",
            "accommodation_food_tourism",
            "transport_storage",
        }
        exchange_exposed = set(
            self.baseline.driver_parameters["exchange_elasticities"]
        )
        for sector in brent_exposed:
            self.assertLess(brent_sectors[sector], base_sectors[sector])
        for sector in set(base_sectors) - brent_exposed:
            self.assertEqual(brent_sectors[sector], base_sectors[sector])
        for sector in exchange_exposed:
            self.assertNotEqual(exchange_sectors[sector], base_sectors[sector])
        for sector in set(base_sectors) - exchange_exposed:
            self.assertEqual(exchange_sectors[sector], base_sectors[sector])

    def test_benchmark_quarter_final_release_has_safe_event_text(self):
        previous = initialize_gdp_state(date(2026, 9, 29), self.baseline)

        _, state, events = gdp_step(
            date(2026, 9, 30),
            previous,
            weather={
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            cpi={"yoy_pct": 2.2, "index": 102.2},
            commodities={
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            exchange={"mvl_per_usd": 2.18},
            population=1_200_000,
            baseline=self.baseline,
        )

        matching = [
            event for event in events if "2025-Q3" in event["text"]
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("final", matching[0]["text"])
        q3_2025 = next(
            item
            for item in state["quarterly_history"]
            if item["period"] == "2025-Q3"
        )
        self.assertEqual(q3_2025["vintages"][-1]["vintage"], "final")

    def test_q2_provisional_release_occurs_exactly_90_days_after_quarter_end(self):
        previous = initialize_gdp_state(date(2026, 9, 27), self.baseline)

        public, state, events = gdp_step(
            date(2026, 9, 28),
            previous,
            weather={
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            cpi={"yoy_pct": 2.2, "index": 102.2},
            commodities={
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            exchange={"mvl_per_usd": 2.18},
            population=1_200_000,
            baseline=self.baseline,
        )

        q2_events = [event for event in events if "2026-Q2" in event["text"]]
        self.assertEqual(len(q2_events), 1)
        self.assertEqual(public["latest_release"]["period"], "2026-Q2")
        self.assertEqual(public["latest_release"]["vintage"], "provisional")
        self.assertEqual(public["latest_release"]["release_date"], "2026-09-28")
        q2 = next(
            item
            for item in state["quarterly_history"]
            if item["period"] == "2026-Q2"
        )
        self.assertEqual(
            [item["vintage"] for item in q2["vintages"]], ["provisional"]
        )

    def test_q2_revised_and_final_releases_follow_policy_without_duplicates(self):
        common = {
            "weather": {
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "commodities": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        before_revised = initialize_gdp_state(
            date(2026, 12, 26), self.baseline
        )
        _, revised_state, revised_events = gdp_step(
            date(2026, 12, 27), before_revised, **common
        )
        _, _, day_after_events = gdp_step(
            date(2026, 12, 28), revised_state, **common
        )
        before_final = initialize_gdp_state(
            date(2027, 6, 29), self.baseline
        )
        _, final_state, final_events = gdp_step(
            date(2027, 6, 30), before_final, **common
        )

        self.assertEqual(
            len([event for event in revised_events if "2026-Q2" in event["text"]]),
            1,
        )
        self.assertEqual(
            len([event for event in day_after_events if "2026-Q2" in event["text"]]),
            0,
        )
        self.assertEqual(
            len([event for event in final_events if "2026-Q2" in event["text"]]),
            1,
        )
        revised_q2 = next(
            account
            for account in revised_state["quarterly_history"]
            if account["period"] == "2026-Q2"
        )
        final_q2 = next(
            account
            for account in final_state["quarterly_history"]
            if account["period"] == "2026-Q2"
        )
        self.assertEqual(
            [item["vintage"] for item in revised_q2["vintages"]],
            ["provisional", "revised"],
        )
        self.assertEqual(
            [item["vintage"] for item in final_q2["vintages"]],
            ["provisional", "revised", "final"],
        )

    def test_neutral_2026_path_hits_annual_real_and_deflator_anchors(self):
        state = initialize_gdp_state(date(2025, 12, 31), self.baseline)
        public = None
        current = date(2026, 1, 1)
        while current <= date(2026, 12, 31):
            public, state, _ = gdp_step(
                current,
                state,
                weather={
                    "condition": "晴",
                    "cyclone_risk": "none",
                    "rainfall_mm": 0.0,
                },
                cpi={"yoy_pct": 2.2, "index": 102.2},
                commodities={
                    "sugar_usd_lb": 0.19789976464730627,
                    "gold_usd_oz": 2648.01,
                    "brent_usd_barrel": 73.833,
                },
                exchange={"mvl_per_usd": 2.18},
                population=1_200_000,
                baseline=self.baseline,
            )
            current += date.resolution

        self.assertIsNotNone(public)
        annual = public["annual_nowcast"]
        self.assertAlmostEqual(annual["real_growth_pct"], 2.4, places=10)
        self.assertAlmostEqual(annual["deflator_growth_pct"], 2.2, places=10)
        self.assertAlmostEqual(
            annual["nominal_gdp_mvl"], 17_110_732_800, delta=0.01
        )

    def test_long_running_state_bounds_closed_quarter_history(self):
        state = initialize_gdp_state(date(2040, 8, 11), self.baseline)

        self.assertLessEqual(len(state["quarterly_history"]), 40)
        self.assertEqual(state["quarterly_history"][-1]["period"], "2040-Q2")
        self.assertEqual(state["current_quarter"]["period"], "2040-Q3")

    def test_2027_growth_is_year_on_year_not_cumulative_from_2025(self):
        state = initialize_gdp_state(date(2026, 12, 31), self.baseline)
        public = None
        current = date(2027, 1, 1)
        while current <= date(2027, 12, 31):
            public, state, _ = gdp_step(
                current,
                state,
                weather={
                    "condition": "晴",
                    "cyclone_risk": "none",
                    "rainfall_mm": 0.0,
                },
                cpi={"yoy_pct": 2.2, "index": 104.4484},
                commodities={
                    "sugar_usd_lb": 0.19789976464730627,
                    "gold_usd_oz": 2648.01,
                    "brent_usd_barrel": 73.833,
                },
                exchange={"mvl_per_usd": 2.18},
                population=1_200_000,
                baseline=self.baseline,
            )
            current += date.resolution

        growth = public["annual_nowcast"]["real_growth_pct"]
        self.assertGreater(growth, 2.0)
        self.assertLess(growth, 3.0)

    def test_2027_quarter_yoy_uses_shocked_2026_closed_quarter(self):
        state = initialize_gdp_state(date(2025, 12, 31), self.baseline)
        common = {
            "cpi": {"yoy_pct": 2.2, "index": 102.2},
            "commodities": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
            },
            "exchange": {"mvl_per_usd": 2.18},
            "population": 1_200_000,
            "baseline": self.baseline,
        }
        current = date(2026, 1, 1)
        while current <= date(2026, 12, 31):
            cyclone_q1 = current.month <= 3
            _, state, _ = gdp_step(
                current,
                state,
                weather={
                    "condition": "台风" if cyclone_q1 else "晴",
                    "cyclone_risk": "high" if cyclone_q1 else "none",
                    "rainfall_mm": 180.0 if cyclone_q1 else 0.0,
                },
                **common,
            )
            current += date.resolution
        public, state, _ = gdp_step(
            date(2027, 1, 1),
            state,
            weather={
                "condition": "晴",
                "cyclone_risk": "none",
                "rainfall_mm": 0.0,
            },
            **common,
        )
        q1_2026 = next(
            account
            for account in state["quarterly_history"]
            if account["period"] == "2026-Q1"
        )
        q1_nowcast = public["current_quarter_nowcast"]
        expected_yoy = (
            q1_nowcast["real_gdp_mvl"]
            / q1_2026["production"]["real_gdp_mvl"]
            - 1.0
        ) * 100.0

        self.assertAlmostEqual(
            q1_nowcast["real_growth_yoy_pct"], expected_yoy, places=12
        )


if __name__ == "__main__":
    unittest.main()
