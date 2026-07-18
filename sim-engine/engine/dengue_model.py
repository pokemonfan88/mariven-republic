"""Public API and strict baseline contract for the Mariven dengue model."""

from __future__ import annotations

import copy
import json
import math
import random
from collections.abc import Mapping, Sequence
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any


BASELINE_VERSION = "mariven-dengue-2026-v1"
AGE_GROUPS = ("0-4", "5-14", "15-29", "30-59", "60+")
SEROTYPES = ("DENV-1", "DENV-2", "DENV-3", "DENV-4")
PROVINCES = (
    "katora",
    "western",
    "central_highlands",
    "eastern_coast",
    "timo",
    "pela",
    "ruwa",
)
WEATHER_SOURCES = frozenset((
    "katora", "makadi_port", "timo", "pela", "ruwa",
))


class DengueDataError(RuntimeError):
    """Raised when dengue data or state violates its labeled contract."""


def _fail(path: str, message: str) -> None:
    raise DengueDataError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "expected a dictionary")
    return value


def _exact_keys(
    value: Mapping[str, Any], expected: Sequence[str], path: str,
) -> None:
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        missing = sorted(expected_set - actual)
        extra = sorted(actual - expected_set)
        _fail(path, f"expected exact keys; missing={missing}, extra={extra}")


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        _fail(path, "expected a finite number")
    try:
        converted = float(value)
    except OverflowError:
        _fail(path, "expected a finite number")
    if not math.isfinite(converted):
        _fail(path, "expected a finite number")
    return converted


def _probability(value: Any, path: str) -> float:
    probability = _finite(value, path)
    if not 0.0 <= probability <= 1.0:
        _fail(path, "expected a probability in [0, 1]")
    return probability


def _positive_integer(value: Any, path: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "expected an integer")
    if value < 0 if allow_zero else value <= 0:
        qualifier = "non-negative" if allow_zero else "positive"
        _fail(path, f"expected a {qualifier} integer")
    return value


def _distribution(
    value: Any,
    expected_keys: Sequence[str],
    path: str,
) -> dict[str, float]:
    raw = _mapping(value, path)
    _exact_keys(raw, expected_keys, path)
    result = {
        key: _probability(raw[key], f"{path}.{key}")
        for key in expected_keys
    }
    if not math.isclose(sum(result.values()), 1.0, abs_tol=1e-9):
        _fail(path, "probabilities must sum to one")
    return result


def _iso_date(value: Any, path: str) -> date:
    if not isinstance(value, str):
        _fail(path, "expected an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "expected an ISO date")
    if parsed.isoformat() != value:
        _fail(path, "expected an ISO date")
    return parsed


def _validate_historical(raw: Mapping[str, Any]) -> None:
    path = "baseline.historical_2026"
    _iso_date(raw.get("through_date"), f"{path}.through_date")
    totals = _mapping(raw.get("reported_by_province"), f"{path}.reported_by_province")
    _exact_keys(totals, PROVINCES, f"{path}.reported_by_province")
    expected_totals = {
        province: _positive_integer(
            totals[province], f"{path}.reported_by_province.{province}"
        )
        for province in PROVINCES
    }
    if sum(expected_totals.values()) != 1_240:
        _fail(f"{path}.reported_by_province", "expected national total 1240")

    ledger = raw.get("weekly_ledger")
    if not isinstance(ledger, list) or not ledger:
        _fail(f"{path}.weekly_ledger", "expected a non-empty list")
    accumulated = {province: 0 for province in PROVINCES}
    previous_end: date | None = None
    for index, row_value in enumerate(ledger):
        row_path = f"{path}.weekly_ledger[{index}]"
        row = _mapping(row_value, row_path)
        start = _iso_date(row.get("week_start"), f"{row_path}.week_start")
        end = _iso_date(row.get("week_end"), f"{row_path}.week_end")
        if (end - start).days != 6:
            _fail(row_path, "expected a seven-day epidemiological week")
        if previous_end is not None and (end - previous_end).days != 7:
            _fail(f"{row_path}.week_end", "expected consecutive weeks")
        previous_end = end
        by_province = _mapping(
            row.get("reported_by_province"),
            f"{row_path}.reported_by_province",
        )
        _exact_keys(by_province, PROVINCES, f"{row_path}.reported_by_province")
        row_total = 0
        for province in PROVINCES:
            count = _positive_integer(
                by_province[province],
                f"{row_path}.reported_by_province.{province}",
                allow_zero=True,
            )
            accumulated[province] += count
            row_total += count
        if row.get("reported_national") != row_total:
            _fail(f"{row_path}.reported_national", "does not match provinces")
        if row.get("release_status") != "final":
            _fail(f"{row_path}.release_status", "expected final")
    if accumulated != expected_totals:
        _fail(f"{path}.weekly_ledger", "does not match province totals")


def validate_baseline(raw: Mapping[str, Any]) -> None:
    """Validate every dimension and probability needed by the model."""
    if not isinstance(raw, Mapping):
        _fail("baseline", "expected a dictionary")
    if raw.get("version") != BASELINE_VERSION:
        _fail("baseline.version", f"expected {BASELINE_VERSION}")
    anchor = _iso_date(raw.get("anchor_date"), "baseline.anchor_date")
    if anchor != date(2026, 8, 11):
        _fail("baseline.anchor_date", "expected 2026-08-11")
    if raw.get("age_groups") != list(AGE_GROUPS):
        _fail("baseline.age_groups", f"expected {list(AGE_GROUPS)}")
    if raw.get("serotypes") != list(SEROTYPES):
        _fail("baseline.serotypes", f"expected {list(SEROTYPES)}")

    provinces = _mapping(raw.get("provinces"), "baseline.provinces")
    _exact_keys(provinces, PROVINCES, "baseline.provinces")
    province_total = sum(
        _positive_integer(provinces[key], f"baseline.provinces.{key}")
        for key in PROVINCES
    )
    if province_total != 1_200_000:
        _fail("baseline.provinces", "expected national total 1200000")

    metadata = _mapping(raw.get("metadata"), "baseline.metadata")
    if metadata.get("source_extract") != (
        "sources/dengue_external_anchors_2026.json"
    ):
        _fail("baseline.metadata.source_extract", "unexpected source file")
    source_classes = _mapping(
        metadata.get("source_classes"), "baseline.metadata.source_classes"
    )
    if source_classes.get("wmar1") != "fictional_intervention":
        _fail("baseline.metadata.source_classes.wmar1", "expected fictional_intervention")

    _validate_historical(
        _mapping(raw.get("historical_2026"), "baseline.historical_2026")
    )

    immunity = _mapping(raw.get("immunity"), "baseline.immunity")
    if immunity.get("cross_protection_days") != 180:
        _fail("baseline.immunity.cross_protection_days", "expected 180")
    _probability(
        immunity.get("cross_protection_residual_susceptibility"),
        "baseline.immunity.cross_protection_residual_susceptibility",
    )
    ever_infected = _mapping(
        immunity.get("ever_infected_prior"),
        "baseline.immunity.ever_infected_prior",
    )
    _exact_keys(ever_infected, AGE_GROUPS, "baseline.immunity.ever_infected_prior")
    for age in AGE_GROUPS:
        _probability(
            ever_infected[age], f"baseline.immunity.ever_infected_prior.{age}"
        )
    multipliers = _mapping(
        immunity.get("province_multipliers"),
        "baseline.immunity.province_multipliers",
    )
    _exact_keys(multipliers, PROVINCES, "baseline.immunity.province_multipliers")
    for province in PROVINCES:
        if _finite(
            multipliers[province],
            f"baseline.immunity.province_multipliers.{province}",
        ) <= 0:
            _fail(
                f"baseline.immunity.province_multipliers.{province}",
                "expected a positive multiplier",
            )

    infection_counts = _mapping(
        immunity.get("infection_count_given_ever"),
        "baseline.immunity.infection_count_given_ever",
    )
    _exact_keys(
        infection_counts,
        AGE_GROUPS,
        "baseline.immunity.infection_count_given_ever",
    )
    for age in AGE_GROUPS:
        _distribution(
            infection_counts[age],
            ("1", "2", "3", "4"),
            f"baseline.immunity.infection_count_given_ever.{age}",
        )

    transmission = _mapping(
        raw.get("transmission"), "baseline.transmission"
    )
    _distribution(
        transmission.get("human_incubation_days"),
        ("4", "5", "6", "7", "8", "9", "10"),
        "baseline.transmission.human_incubation_days",
    )
    _distribution(
        transmission.get("infectious_days"),
        ("2", "3", "4", "5", "6", "7"),
        "baseline.transmission.infectious_days",
    )
    _distribution(
        transmission.get("serotype_prior"),
        SEROTYPES,
        "baseline.transmission.serotype_prior",
    )
    for key in ("mosquito_to_human", "human_to_mosquito"):
        _probability(transmission.get(key), f"baseline.transmission.{key}")
    if _finite(
        transmission.get("base_biting_rate"),
        "baseline.transmission.base_biting_rate",
    ) <= 0:
        _fail("baseline.transmission.base_biting_rate", "expected positive")
    eip = _mapping(
        transmission.get("vector_eip_days"),
        "baseline.transmission.vector_eip_days",
    )
    minimum_eip = _positive_integer(
        eip.get("minimum"), "baseline.transmission.vector_eip_days.minimum"
    )
    maximum_eip = _positive_integer(
        eip.get("maximum"), "baseline.transmission.vector_eip_days.maximum"
    )
    if minimum_eip > maximum_eip:
        _fail("baseline.transmission.vector_eip_days", "minimum exceeds maximum")

    mobility = _mapping(raw.get("mobility"), "baseline.mobility")
    _exact_keys(mobility, PROVINCES, "baseline.mobility")
    for resident in PROVINCES:
        row_path = f"baseline.mobility.{resident}"
        row = _mapping(mobility[resident], row_path)
        _exact_keys(row, PROVINCES, row_path)
        total = sum(
            _probability(row[source], f"{row_path}.{source}")
            for source in PROVINCES
        )
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            _fail(row_path, "row must sum to one")

    weather = _mapping(raw.get("weather_mapping"), "baseline.weather_mapping")
    _exact_keys(weather, PROVINCES, "baseline.weather_mapping")
    for province in PROVINCES:
        item_path = f"baseline.weather_mapping.{province}"
        item = _mapping(weather[province], item_path)
        if item.get("source") not in WEATHER_SOURCES:
            _fail(f"{item_path}.source", "unknown weather source")
        _finite(item.get("temp_offset_c"), f"{item_path}.temp_offset_c")
        if _finite(item.get("rain_scale"), f"{item_path}.rain_scale") <= 0:
            _fail(f"{item_path}.rain_scale", "expected positive")
        _finite(
            item.get("humidity_offset_pct"),
            f"{item_path}.humidity_offset_pct",
        )

    clinical = _mapping(raw.get("clinical"), "baseline.clinical")
    for group, keys in (
        ("symptomatic_by_infection_order", ("1", "2", "3", "4")),
        ("severe_by_infection_order", ("1", "2", "3", "4")),
    ):
        values = _mapping(clinical.get(group), f"baseline.clinical.{group}")
        _exact_keys(values, keys, f"baseline.clinical.{group}")
        for key in keys:
            _probability(values[key], f"baseline.clinical.{group}.{key}")
    age_risk = _mapping(
        clinical.get("age_severe_multiplier"),
        "baseline.clinical.age_severe_multiplier",
    )
    _exact_keys(age_risk, AGE_GROUPS, "baseline.clinical.age_severe_multiplier")
    for age in AGE_GROUPS:
        if _finite(age_risk[age], f"baseline.clinical.age_severe_multiplier.{age}") <= 0:
            _fail(f"baseline.clinical.age_severe_multiplier.{age}", "expected positive")
    for key in (
        "warning_given_symptomatic",
        "hospitalized_given_severe",
        "treated_severe_fatality",
        "overloaded_severe_fatality",
        "soft_capacity_share",
        "hard_capacity_share",
    ):
        _probability(clinical.get(key), f"baseline.clinical.{key}")

    surveillance = _mapping(
        raw.get("surveillance"), "baseline.surveillance"
    )
    report_probability = _mapping(
        surveillance.get("report_probability"),
        "baseline.surveillance.report_probability",
    )
    _exact_keys(report_probability, PROVINCES, "baseline.surveillance.report_probability")
    for province in PROVINCES:
        _probability(
            report_probability[province],
            f"baseline.surveillance.report_probability.{province}",
        )
    for key in (
        "severe_report_probability",
        "routine_sample_probability",
        "alert_sample_probability",
    ):
        _probability(surveillance.get(key), f"baseline.surveillance.{key}")
    capacities = _mapping(
        surveillance.get("daily_lab_capacity"),
        "baseline.surveillance.daily_lab_capacity",
    )
    _exact_keys(capacities, PROVINCES, "baseline.surveillance.daily_lab_capacity")
    for province in PROVINCES:
        _positive_integer(
            capacities[province],
            f"baseline.surveillance.daily_lab_capacity.{province}",
        )
    releases = _mapping(
        surveillance.get("release_offsets_days"),
        "baseline.surveillance.release_offsets_days",
    )
    if dict(releases) != {"provisional": 4, "revised": 14, "final": 28}:
        _fail("baseline.surveillance.release_offsets_days", "unexpected release policy")

    wmar1 = _mapping(raw.get("wmar1"), "baseline.wmar1")
    for province in ("katora", "western"):
        pilot = _mapping(wmar1.get(province), f"baseline.wmar1.{province}")
        for key in ("pilot_share", "community_coverage", "field_effectiveness"):
            _probability(pilot.get(key), f"baseline.wmar1.{province}.{key}")
    if wmar1.get("other_provinces_coverage") != 0.0:
        _fail("baseline.wmar1.other_provinces_coverage", "expected zero")


@dataclass(frozen=True)
class DengueBaseline:
    """Validated, read-only dengue baseline used by model steps."""

    raw: dict[str, Any]
    version: str
    anchor_date: date
    age_groups: tuple[str, ...]
    serotypes: tuple[str, ...]
    province_populations: dict[str, int]

    @classmethod
    def from_json(cls, path: Path) -> "DengueBaseline":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DengueDataError(f"baseline: {exc}") from exc
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DengueBaseline":
        validate_baseline(raw)
        copied = copy.deepcopy(dict(raw))
        return cls(
            raw=copied,
            version=copied["version"],
            anchor_date=date.fromisoformat(copied["anchor_date"]),
            age_groups=tuple(copied["age_groups"]),
            serotypes=tuple(copied["serotypes"]),
            province_populations=dict(copied["provinces"]),
        )


def initialize_dengue_state(
    current_date: date,
    population_state: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
    initialization_source: str,
) -> dict[str, Any]:
    """Create a dated dengue state reconciled to national age cohorts."""
    from dengue_dynamics import (
        allocate_province_ages,
        initialize_human_state,
        initialize_vector_state,
        national_age_totals,
    )

    allowed_sources = {
        "calibration_reconstruction",
        "anchor_snapshot",
        "legacy_replay",
        "native_v5",
    }
    if initialization_source not in allowed_sources:
        _fail(
            "state.model_state.dengue.initialization_source",
            f"expected one of {sorted(allowed_sources)}",
        )
    if current_date < date(2026, 1, 1):
        _fail("state.date", "dengue baseline begins on 2026-01-01")

    age_totals = national_age_totals(population_state)
    province_ages = allocate_province_ages(age_totals, baseline)
    human_state = initialize_human_state(
        province_ages, baseline, rng_factory
    )
    vector_state = initialize_vector_state(baseline)
    through_date = min(current_date, date(2026, 8, 10))
    weekly_ledger = [
        copy.deepcopy(row)
        for row in baseline.raw["historical_2026"]["weekly_ledger"]
        if date.fromisoformat(row["week_end"]) <= through_date
    ]
    cumulative_reported = sum(
        row["reported_national"] for row in weekly_ledger
    )

    return {
        "version": "mariven-dengue-state-v1",
        "baseline_version": baseline.version,
        "random_schema_version": 4,
        "last_processed_date": current_date.isoformat(),
        "initialization_source": initialization_source,
        "provinces": {
            province: {
                "human": human_state[province],
                "vector": vector_state[province],
                "interventions": copy.deepcopy(
                    baseline.raw["wmar1"].get(
                        province,
                        {
                            "pilot_share": 0.0,
                            "community_coverage": 0.0,
                            "field_effectiveness": 0.0,
                        },
                    )
                ),
            }
            for province in PROVINCES
        },
        "surveillance": {
            "weekly_ledger": weekly_ledger,
            "release_vintages": [],
            "reporting_queue": [],
            "laboratory_queue": [],
            "alert_state": {
                province: "baseline" for province in PROVINCES
            },
        },
        "cumulative_annual": {
            "year": current_date.year,
            "estimated_infections": 0,
            "reported": cumulative_reported,
            "confirmed": 0,
            "severe": 0,
            "hospitalized": 0,
            "deaths": 0,
        },
        "data_quality": [],
    }
