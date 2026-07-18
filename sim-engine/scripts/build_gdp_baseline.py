"""Build the versioned Mariven 2026 GDP baseline."""

import argparse
import json
from pathlib import Path


BASE_GDP = 16_350_000_000
SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sources"
    / "gdp_external_anchors_2026.json"
)


def build_baseline(source_path=SOURCE_PATH):
    """Return the deterministic 2025 benchmark and 2026 macro path."""
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    source_metadata = source["_meta"]
    sources = source["sources"]
    imf = sources["imf_fiji_2026_article_iv"]["extracted"]
    expenditure_prior = sources["fiji_2024_expenditure_accounts"]["extracted"]
    availability = sources["fiji_2026_release_calendar"]["extracted"]
    if imf["real_gdp_growth_pct"] != 2.4:
        raise ValueError("unexpected IMF 2026 real GDP growth anchor")
    if imf["gdp_deflator_growth_pct"] != 2.2:
        raise ValueError("unexpected IMF 2026 GDP deflator anchor")
    industries = {
        "agriculture_forestry_fishing": ("primary_and_mining", 8.0),
        "mining_quarrying": ("primary_and_mining", 6.2),
        "manufacturing": ("industry", 10.2),
        "electricity_water": ("industry", 2.3),
        "construction": ("industry", 5.3),
        "wholesale_retail": ("services", 10.2),
        "accommodation_food_tourism": ("services", 10.0),
        "transport_storage": ("services", 6.0),
        "information_communication": ("services", 2.2),
        "finance_insurance": ("services", 5.0),
        "real_estate_business": ("services", 7.0),
        "public_admin_education_health": ("services", 10.0),
        "other_services": ("services", 7.0),
        "net_product_taxes": ("net_product_taxes", 10.6),
    }
    paths = {
        "agriculture_forestry_fishing": (1.5, [0.20, 0.22, 0.27, 0.31]),
        "mining_quarrying": (4.0, [0.25, 0.25, 0.25, 0.25]),
        "manufacturing": (1.2, [0.24, 0.245, 0.25, 0.265]),
        "electricity_water": (2.0, [0.26, 0.24, 0.24, 0.26]),
        "construction": (4.0, [0.23, 0.25, 0.27, 0.25]),
        "wholesale_retail": (2.0, [0.23, 0.235, 0.255, 0.28]),
        "accommodation_food_tourism": (2.2, [0.21, 0.24, 0.29, 0.26]),
        "transport_storage": (2.0, [0.21, 0.24, 0.29, 0.26]),
        "information_communication": (5.0, [0.25, 0.25, 0.25, 0.25]),
        "finance_insurance": (2.8, [0.245, 0.25, 0.25, 0.255]),
        "real_estate_business": (2.4, [0.24, 0.25, 0.255, 0.255]),
        "public_admin_education_health": (3.0, [0.245, 0.25, 0.25, 0.255]),
        "other_services": (1.8, [0.24, 0.245, 0.255, 0.26]),
        "net_product_taxes": (
            2.48679245283019,
            [0.24, 0.245, 0.255, 0.26],
        ),
    }
    return {
        "version": "mariven-gdp-2026-v1",
        "base_year": 2025,
        "metadata": {
            "generated_on": "2026-07-18",
            "accessed_on": source_metadata["accessed_on"],
            "external_anchors": {
                "real_gdp_growth_2026_pct": imf["real_gdp_growth_pct"],
                "gdp_deflator_growth_2026_pct": imf[
                    "gdp_deflator_growth_pct"
                ],
            },
            "availability": {
                "fiji_2025_production_release_date": availability[
                    "gdp_production_2025_release_date"
                ],
                "fiji_2025_production_available": availability[
                    "complete_2025_production_data_available_on_access_date"
                ],
            },
            "expenditure_structure_prior_pct": {
                "final_consumption": expenditure_prior[
                    "final_consumption_expenditure_fjd_billion"
                ]
                / expenditure_prior["nominal_gdp_fjd_billion"]
                * 100.0,
                "gross_capital_formation": expenditure_prior[
                    "gross_capital_formation_fjd_billion"
                ]
                / expenditure_prior["nominal_gdp_fjd_billion"]
                * 100.0,
                "net_exports": expenditure_prior[
                    "net_exports_fjd_billion"
                ]
                / expenditure_prior["nominal_gdp_fjd_billion"]
                * 100.0,
            },
            "source_extract": "sources/gdp_external_anchors_2026.json",
        },
        "annual_accounts": {
            "2025": {
                "nominal_gdp_mvl": BASE_GDP,
                "real_growth_pct": 3.1,
            },
        },
        "annual_path": {
            "2026": {
                "real_growth_pct": 2.4,
                "deflator_growth_pct": 2.2,
                "nominal_gdp_mvl": BASE_GDP * 1.024 * 1.022,
            },
        },
        "production_accounts": {
            "industries": {
                key: {
                    "group": group,
                    "share_pct": share,
                    "nominal_mvl": BASE_GDP * share / 100.0,
                    "real_growth_2026_pct": paths[key][0],
                    "quarter_weights": paths[key][1],
                }
                for key, (group, share) in industries.items()
            },
        },
        "expenditure_accounts": {
            "2025": {
                "household_consumption_mvl": 11_445_000_000,
                "government_consumption_mvl": 3_188_250_000,
                "gross_fixed_capital_formation_mvl": 3_270_000_000,
                "changes_in_inventories_mvl": 114_450_000,
                "exports_goods_services_mvl": 7_700_850_000,
                "imports_goods_services_mvl": 9_368_550_000,
                "statistical_discrepancy_mvl": 0,
            },
        },
        "tourism_reconciliation": {
            "annual_arrivals_including_cruise": 1_100_000,
            "average_stay_days": 8.3,
            "spend_per_day_mvl": 680,
            "visitor_spending_mvl": 6_208_400_000,
            "direct_gva_mvl": 1_635_000_000,
            "direct_gva_share_pct": 10.0,
        },
        "release_policy": {
            "lags_days": {
                "provisional": 90,
                "revised": 180,
                "final": 365,
            },
        },
        "driver_parameters": {
            "version": "mariven-gdp-drivers-2026-v1",
            "reference_values": {
                "sugar_usd_lb": 0.19789976464730627,
                "gold_usd_oz": 2648.01,
                "brent_usd_barrel": 73.833,
                "mvl_per_usd": 2.18,
                "cpi_yoy_pct": 2.2,
                "population": 1_200_000,
            },
            "commodity_elasticities": {
                "sugar_usd_lb": {
                    "agriculture_forestry_fishing": 0.08,
                    "manufacturing": 0.03,
                },
                "gold_usd_oz": {"mining_quarrying": 0.15},
                "brent_usd_barrel": {
                    "manufacturing": -0.03,
                    "electricity_water": -0.08,
                    "accommodation_food_tourism": -0.04,
                    "transport_storage": -0.10,
                },
            },
            "exchange_elasticities": {
                "agriculture_forestry_fishing": 0.02,
                "mining_quarrying": 0.03,
                "manufacturing": 0.06,
                "wholesale_retail": -0.02,
                "accommodation_food_tourism": 0.08,
                "transport_storage": 0.02,
            },
            "population_elasticities": {
                "wholesale_retail": 0.70,
                "information_communication": 0.60,
                "real_estate_business": 0.80,
                "public_admin_education_health": 1.00,
                "other_services": 0.80,
            },
            "cpi_elasticities_per_pct_point": {
                "wholesale_retail": -0.010,
                "accommodation_food_tourism": -0.004,
                "other_services": -0.006,
                "net_product_taxes": -0.005,
            },
            "rainfall_elasticities_per_mm": {
                "agriculture_forestry_fishing": 0.001,
                "electricity_water": 0.0005,
                "construction": -0.0015,
                "accommodation_food_tourism": -0.001,
                "transport_storage": -0.001,
            },
            "ordinary_factor_bounds": [0.85, 1.15],
            "cyclone_high_factors": {
                "agriculture_forestry_fishing": 0.70,
                "manufacturing": 0.85,
                "electricity_water": 0.90,
                "construction": 0.45,
                "wholesale_retail": 0.80,
                "accommodation_food_tourism": 0.35,
                "transport_storage": 0.40,
                "other_services": 0.85,
                "net_product_taxes": 0.80,
            },
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "gdp_baseline_2026.json",
    )
    args = parser.parse_args(argv)
    args.output.write_text(
        json.dumps(build_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
