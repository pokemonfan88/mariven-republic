"""Build the versioned Mariven 2026 dengue baseline deterministically."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "data" / "sources" / "dengue_external_anchors_2026.json"
DEFAULT_OUTPUT = ROOT / "data" / "dengue_baseline_2026.json"
ANCHOR_DATE = "2026-08-11"

PROVINCES = (
    "katora",
    "western",
    "central_highlands",
    "eastern_coast",
    "timo",
    "pela",
    "ruwa",
)
PROVINCE_POPULATIONS = {
    "katora": 470_000,
    "western": 260_000,
    "central_highlands": 110_000,
    "eastern_coast": 78_000,
    "timo": 145_000,
    "pela": 82_000,
    "ruwa": 55_000,
}
REPORTED_BY_PROVINCE = {
    "katora": 520,
    "western": 340,
    "central_highlands": 70,
    "eastern_coast": 60,
    "timo": 110,
    "pela": 95,
    "ruwa": 45,
}


def _mobility_matrix() -> dict[str, dict[str, float]]:
    rows = {
        "katora": (.930, .025, .012, .014, .007, .009, .003),
        "western": (.035, .925, .015, .008, .004, .010, .003),
        "central_highlands": (.035, .025, .920, .015, .002, .002, .001),
        "eastern_coast": (.060, .015, .020, .895, .004, .004, .002),
        "timo": (.025, .010, .005, .005, .945, .007, .003),
        "pela": (.035, .020, .003, .003, .006, .930, .003),
        "ruwa": (.020, .020, .005, .005, .005, .005, .940),
    }
    matrix = {
        row: dict(zip(PROVINCES, values, strict=True))
        for row, values in rows.items()
    }
    for row, values in matrix.items():
        if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-12):
            raise ValueError(f"mobility.{row}: row does not sum to one")
    return matrix


def _weather_mapping() -> dict[str, dict[str, float | str]]:
    return {
        "katora": {
            "source": "katora",
            "temp_offset_c": 0.0,
            "rain_scale": 1.0,
            "humidity_offset_pct": 0.0,
        },
        "western": {
            "source": "makadi_port",
            "temp_offset_c": 0.0,
            "rain_scale": 1.0,
            "humidity_offset_pct": 0.0,
        },
        "central_highlands": {
            "source": "katora",
            "temp_offset_c": -4.0,
            "rain_scale": 1.25,
            "humidity_offset_pct": 5.0,
        },
        "eastern_coast": {
            "source": "katora",
            "temp_offset_c": 0.2,
            "rain_scale": 1.15,
            "humidity_offset_pct": 4.0,
        },
        "timo": {
            "source": "timo",
            "temp_offset_c": 0.0,
            "rain_scale": 1.0,
            "humidity_offset_pct": 0.0,
        },
        "pela": {
            "source": "pela",
            "temp_offset_c": 0.0,
            "rain_scale": 1.0,
            "humidity_offset_pct": 0.0,
        },
        "ruwa": {
            "source": "ruwa",
            "temp_offset_c": 0.0,
            "rain_scale": 1.0,
            "humidity_offset_pct": 0.0,
        },
    }


def _clinical_parameters() -> dict[str, Any]:
    return {
        "symptomatic_by_infection_order": {
            "1": 0.25,
            "2": 0.35,
            "3": 0.30,
            "4": 0.28,
        },
        "severe_by_infection_order": {
            "1": 0.005,
            "2": 0.025,
            "3": 0.012,
            "4": 0.010,
        },
        "age_severe_multiplier": {
            "0-4": 1.30,
            "5-14": 1.00,
            "15-29": 0.80,
            "30-59": 1.00,
            "60+": 1.60,
        },
        "warning_given_symptomatic": 0.08,
        "hospitalized_given_severe": 0.85,
        "treated_severe_fatality": 0.005,
        "overloaded_severe_fatality": 0.030,
        "soft_capacity_share": 0.70,
        "hard_capacity_share": 0.85,
    }


def _surveillance_parameters() -> dict[str, Any]:
    return {
        "report_probability": {
            "katora": 0.48,
            "western": 0.38,
            "central_highlands": 0.25,
            "eastern_coast": 0.26,
            "timo": 0.28,
            "pela": 0.40,
            "ruwa": 0.22,
        },
        "severe_report_probability": 0.95,
        "routine_sample_probability": 0.20,
        "alert_sample_probability": 0.35,
        "daily_lab_capacity": {
            "katora": 40,
            "western": 20,
            "central_highlands": 8,
            "eastern_coast": 6,
            "timo": 8,
            "pela": 8,
            "ruwa": 4,
        },
        "release_offsets_days": {
            "provisional": 4,
            "revised": 14,
            "final": 28,
        },
        "minimum_cases": {
            "watch": 5,
            "alert": 10,
            "outbreak": 15,
        },
        "rt_watch": 1.1,
        "history_weeks": 110,
        "reporting_queue_days": 60,
    }


def _largest_remainder(total: int, weights: list[float]) -> list[int]:
    weight_total = sum(weights)
    raw = [total * weight / weight_total for weight in weights]
    result = [math.floor(value) for value in raw]
    remainder = total - sum(result)
    order = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - result[index]), index),
    )
    for index in order[:remainder]:
        result[index] += 1
    return result


def _historical_weeks() -> list[dict[str, Any]]:
    week_ends: list[date] = []
    current = date(2026, 1, 4)
    final = date(2026, 8, 9)
    while current <= final:
        week_ends.append(current)
        current += timedelta(days=7)

    weekly_by_province: dict[str, list[int]] = {}
    weights = [
        1.8 if week_end.month <= 4 else 1.1 if week_end.month == 5 else 0.55
        for week_end in week_ends
    ]
    for province in PROVINCES:
        weekly_by_province[province] = _largest_remainder(
            REPORTED_BY_PROVINCE[province], weights
        )

    return [
        {
            "week_start": (week_end - timedelta(days=6)).isoformat(),
            "week_end": week_end.isoformat(),
            "reported_by_province": {
                province: weekly_by_province[province][index]
                for province in PROVINCES
            },
            "reported_national": sum(
                weekly_by_province[province][index]
                for province in PROVINCES
            ),
            "source": "calibration_history",
            "release_status": "final",
        }
        for index, week_end in enumerate(week_ends)
    ]


def build_baseline(source_path: Path = SOURCE_PATH) -> dict[str, Any]:
    """Return the deterministic complete-dengue calibration baseline."""
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    sources = source.get("sources", {})
    fact_sheet = sources.get("who_dengue_fact_sheet", {}).get(
        "extracted", {}
    )
    if fact_sheet.get("human_incubation_days_min") != 4:
        raise ValueError("unexpected WHO human incubation lower bound")
    if fact_sheet.get("human_incubation_days_max") != 10:
        raise ValueError("unexpected WHO human incubation upper bound")
    if sum(PROVINCE_POPULATIONS.values()) != 1_200_000:
        raise ValueError("province populations do not close")
    if sum(REPORTED_BY_PROVINCE.values()) != 1_240:
        raise ValueError("historical reported cases do not close")

    historical_weeks = _historical_weeks()
    return {
        "version": "mariven-dengue-2026-v1",
        "anchor_date": ANCHOR_DATE,
        "metadata": {
            "generated_on": "2026-07-19",
            "accessed_on": source["_meta"]["accessed_on"],
            "source_extract": "sources/dengue_external_anchors_2026.json",
            "source_classes": {
                "natural_history": "official_external",
                "regional_context": "official_external",
                "province_and_health_system": "project_canon",
                "mariven_parameters": "calibration_assumption",
                "wmar1": "fictional_intervention",
            },
        },
        "age_groups": ["0-4", "5-14", "15-29", "30-59", "60+"],
        "serotypes": ["DENV-1", "DENV-2", "DENV-3", "DENV-4"],
        "provinces": PROVINCE_POPULATIONS,
        "historical_2026": {
            "through_date": "2026-08-10",
            "reported_by_province": REPORTED_BY_PROVINCE,
            "weekly_ledger": historical_weeks,
        },
        "immunity": {
            "cross_protection_days": 180,
            "cross_protection_residual_susceptibility": 0.10,
            "ever_infected_prior": {
                "0-4": 0.08,
                "5-14": 0.30,
                "15-29": 0.55,
                "30-59": 0.68,
                "60+": 0.75,
            },
            "province_multipliers": {
                "katora": 1.10,
                "western": 1.08,
                "central_highlands": 0.80,
                "eastern_coast": 0.90,
                "timo": 0.85,
                "pela": 1.00,
                "ruwa": 0.75,
            },
        },
        "transmission": {
            "human_incubation_days": {
                "4": 0.03,
                "5": 0.10,
                "6": 0.22,
                "7": 0.28,
                "8": 0.20,
                "9": 0.11,
                "10": 0.06,
            },
            "infectious_days": {
                "2": 0.08,
                "3": 0.20,
                "4": 0.30,
                "5": 0.23,
                "6": 0.13,
                "7": 0.06,
            },
            "serotype_prior": {
                "DENV-1": 0.25,
                "DENV-2": 0.55,
                "DENV-3": 0.15,
                "DENV-4": 0.05,
            },
            "base_biting_rate": 0.31,
            "mosquito_to_human": 0.12,
            "human_to_mosquito": 0.18,
            "vector_eip_days": {
                "minimum": 5,
                "maximum": 14,
            },
        },
        "vector": {
            "adult_mean_lifetime_days": 12.0,
            "rainfall_lag_days": 14,
            "flush_threshold_mm": 120.0,
            "initial_adult_index": 1.0,
            "initial_larval_pressure": 0.85,
        },
        "importation": {
            "weekly_mean_wet": 0.8,
            "weekly_mean_dry": 0.4,
            "province_weights": {
                "katora": 0.50,
                "western": 0.15,
                "central_highlands": 0.02,
                "eastern_coast": 0.03,
                "timo": 0.05,
                "pela": 0.23,
                "ruwa": 0.02,
            },
        },
        "mobility": _mobility_matrix(),
        "weather_mapping": _weather_mapping(),
        "clinical": _clinical_parameters(),
        "surveillance": _surveillance_parameters(),
        "healthcare": {
            "national_beds_per_1000": 2.1,
            "main_hospital_beds": 420,
            "hospitals": 6,
            "health_centres": 22,
            "dengue_bed_share": 0.08,
        },
        "wmar1": {
            "katora": {
                "pilot_share": 0.10,
                "community_coverage": 0.65,
                "field_effectiveness": 0.45,
            },
            "western": {
                "pilot_share": 0.15,
                "community_coverage": 0.65,
                "field_effectiveness": 0.45,
            },
            "other_provinces_coverage": 0.0,
        },
        "state_limits": {
            "cross_immunity_days": 180,
            "weekly_history_weeks": 110,
            "release_vintages": 330,
            "daily_quality_history_days": 90,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
