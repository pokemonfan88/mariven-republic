"""Public API and strict baseline contract for the Mariven dengue model."""

from __future__ import annotations

import copy
import json
import math
import random
from collections.abc import Mapping, Sequence
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
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
    _distribution(
        surveillance.get("reporting_delay_days"),
        ("0", "1", "2", "3", "4"),
        "baseline.surveillance.reporting_delay_days",
    )
    _distribution(
        surveillance.get("laboratory_turnaround_days"),
        ("1", "2", "3", "4"),
        "baseline.surveillance.laboratory_turnaround_days",
    )
    _probability(
        surveillance.get("laboratory_positive_probability"),
        "baseline.surveillance.laboratory_positive_probability",
    )

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
            "clinical_queue": [],
            "weekly_ledger": weekly_ledger,
            "release_vintages": [],
            "daily_death_requests": [],
            "reporting_queue": [],
            "laboratory_queue": [],
            "daily_records": [],
            "alert_state": {
                province: "baseline" for province in PROVINCES
            },
            "daily_totals": {
                "date": current_date.isoformat(),
                "estimated_infections": 0,
                "symptomatic": 0,
                "reported": 0,
                "lab_processed": 0,
                "confirmed": 0,
                "severe": 0,
                "hospitalized": 0,
                "deaths": 0,
                "healthcare_pressure": 0.0,
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


def _human_states(state: Mapping[str, Any]) -> dict[str, Any]:
    provinces = _mapping(
        state.get("provinces"), "state.model_state.dengue.provinces"
    )
    return {
        province: _mapping(
            _mapping(
                provinces.get(province),
                f"state.model_state.dengue.provinces.{province}",
            ).get("human"),
            f"state.model_state.dengue.provinces.{province}.human",
        )
        for province in PROVINCES
    }


def _dengue_age_totals(state: Mapping[str, Any]) -> dict[str, int]:
    humans = _human_states(state)
    return {
        age: sum(humans[province]["population_by_age"][age] for province in PROVINCES)
        for age in AGE_GROUPS
    }


def _largest_remainder_counts(
    total: int, weights: Sequence[int | float], path: str
) -> list[int]:
    if total < 0 or any(float(weight) < 0 for weight in weights):
        _fail(path, "expected non-negative allocation inputs")
    denominator = sum(float(weight) for weight in weights)
    if denominator <= 0:
        if total == 0:
            return [0] * len(weights)
        _fail(path, "positive allocation requires positive stock")
    raw = [total * float(weight) / denominator for weight in weights]
    result = [math.floor(value) for value in raw]
    order = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - result[index]), index),
    )
    for index in order[: total - sum(result)]:
        result[index] += 1
    return result


def healthcare_pressure(
    surveillance_state: Mapping[str, Any],
    nation_profile: Mapping[str, Any],
    baseline: DengueBaseline,
) -> float:
    """Estimate dengue bed pressure from recent admissions and bed anchors."""
    baseline_beds = float(baseline.raw["healthcare"]["national_beds_per_1000"])
    services = nation_profile.get("public_services", {})
    profile_health = (
        services.get("healthcare", {}) if isinstance(services, Mapping) else {}
    )
    beds_per_1000 = (
        profile_health.get("beds_per_1000", baseline_beds)
        if isinstance(profile_health, Mapping)
        else baseline_beds
    )
    if (
        isinstance(beds_per_1000, bool)
        or not isinstance(beds_per_1000, Real)
        or not math.isfinite(float(beds_per_1000))
        or beds_per_1000 <= 0
    ):
        _fail("nation_profile.public_services.healthcare.beds_per_1000", "invalid")
    population = sum(baseline.province_populations.values())
    dengue_beds = (
        population
        * float(beds_per_1000)
        / 1_000.0
        * float(baseline.raw["healthcare"]["dengue_bed_share"])
    )
    ledger = surveillance_state.get("weekly_ledger", [])
    if not isinstance(ledger, list):
        _fail("state.model_state.dengue.surveillance.weekly_ledger", "expected a list")
    recent_admissions = sum(
        int(row.get("hospitalized_national", 0))
        for row in ledger[-2:]
        if isinstance(row, Mapping)
    )
    estimated_occupancy = recent_admissions * 5.0 / 14.0
    return 0.0 if dengue_beds <= 0 else estimated_occupancy / dengue_beds


def _advance_cumulative_annual(
    state: dict[str, Any], d: date, daily: Mapping[str, Any]
) -> None:
    cumulative = state.get("cumulative_annual")
    if not isinstance(cumulative, dict) or cumulative.get("year") != d.year:
        cumulative = {
            "year": d.year,
            "estimated_infections": 0,
            "reported": 0,
            "confirmed": 0,
            "severe": 0,
            "hospitalized": 0,
            "deaths": 0,
        }
        state["cumulative_annual"] = cumulative
    for cumulative_key, daily_key in (
        ("estimated_infections", "estimated_infections"),
        ("reported", "reported"),
        ("confirmed", "confirmed"),
        ("severe", "severe"),
        ("hospitalized", "hospitalized"),
    ):
        cumulative[cumulative_key] += int(daily.get(daily_key, 0))


def dengue_step(
    d: date,
    previous_state: Mapping[str, Any],
    population_state: Mapping[str, Any],
    weather: Mapping[str, Any],
    nation_profile: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Advance the complete dengue system by one contiguous day."""
    from dengue_dynamics import (
        advance_human_state,
        advance_vector_state,
        derive_province_weather,
        infectiousness_by_province,
        mix_force_of_infection,
        national_age_totals,
    )
    from dengue_surveillance import (
        advance_surveillance,
        classify_clinical_outcomes,
    )

    if not callable(rng_factory):
        _fail("dengue.rng_factory", "expected a callable")
    previous_date_raw = previous_state.get("last_processed_date")
    try:
        previous_date = date.fromisoformat(previous_date_raw)
    except (TypeError, ValueError) as exc:
        raise DengueDataError(
            "state.model_state.dengue.last_processed_date: expected an ISO date"
        ) from exc
    expected = previous_date + timedelta(days=1)
    if d != expected:
        _fail(
            "state.model_state.dengue.last_processed_date",
            f"expected {expected.isoformat()} before processing {d.isoformat()}",
        )
    age_totals = national_age_totals(population_state)
    validate_dengue_state(previous_state, previous_date, age_totals, baseline)
    next_state = copy.deepcopy(dict(previous_state))
    province_weather = derive_province_weather(weather, baseline)
    previous_humans = {
        province: next_state["provinces"][province]["human"]
        for province in PROVINCES
    }
    previous_vectors = {
        province: next_state["provinces"][province]["vector"]
        for province in PROVINCES
    }
    interventions = {
        province: next_state["provinces"][province]["interventions"]
        for province in PROVINCES
    }
    infectiousness = infectiousness_by_province(previous_humans, baseline)
    vector_state, vector_flows = advance_vector_state(
        previous_vectors,
        province_weather,
        infectiousness,
        interventions,
        baseline,
    )
    force = mix_force_of_infection(
        vector_flows["local_force"], baseline.raw["mobility"]
    )
    human_state, infection_flows = advance_human_state(
        previous_humans,
        force,
        baseline,
        lambda name: rng_factory(f"human:{name}"),
    )
    pressure = healthcare_pressure(
        next_state["surveillance"], nation_profile, baseline
    )
    clinical = classify_clinical_outcomes(
        infection_flows,
        pressure,
        baseline,
        lambda name: rng_factory(f"clinical:{name}"),
    )
    surveillance, release_events = advance_surveillance(
        d,
        next_state["surveillance"],
        clinical,
        baseline,
        lambda name: rng_factory(f"surveillance:{name}"),
    )
    surveillance["daily_totals"]["healthcare_pressure"] = pressure
    for province in PROVINCES:
        next_state["provinces"][province]["human"] = human_state[province]
        next_state["provinces"][province]["vector"] = vector_state[province]
    next_state["surveillance"] = surveillance
    next_state["last_processed_date"] = d.isoformat()
    _advance_cumulative_annual(
        next_state, d, surveillance["daily_totals"]
    )
    validate_dengue_state(next_state, d, age_totals, baseline)
    daily_flow = {
        "date": d.isoformat(),
        "estimated_infections": clinical["infections"],
        "symptomatic": clinical["symptomatic"],
        "reported": surveillance["daily_totals"]["reported"],
        "confirmed": surveillance["daily_totals"]["confirmed"],
        "severe": surveillance["daily_totals"]["severe"],
        "hospitalized": surveillance["daily_totals"]["hospitalized"],
        "deaths_requested": surveillance["daily_totals"]["deaths"],
        "new_infections_by_province": copy.deepcopy(
            infection_flows["new_infections_by_province"]
        ),
        "new_infections_by_serotype": copy.deepcopy(
            infection_flows["new_infections_by_serotype"]
        ),
        "vector_suitability": copy.deepcopy(vector_flows["suitability"]),
        "healthcare_pressure": pressure,
    }
    death_requests = copy.deepcopy(
        surveillance.get("daily_death_requests", [])
    )
    return daily_flow, next_state, death_requests, release_events


def _validate_non_negative_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a non-negative integer")
    return value


def _validate_human_cohort(
    cohort: Any, path: str, *, cross_protected: bool = False
) -> tuple[str, int]:
    item = _mapping(cohort, path)
    age = item.get("age_group")
    if age not in AGE_GROUPS:
        _fail(f"{path}.age_group", "unknown age group")
    count = _validate_non_negative_integer(item.get("count"), f"{path}.count")
    mask_key = "new_mask" if cross_protected else "prior_mask"
    mask = item.get(mask_key)
    if isinstance(mask, bool) or not isinstance(mask, int) or not 0 <= mask <= 15:
        _fail(f"{path}.{mask_key}", "expected an integer in [0, 15]")
    if not cross_protected:
        if item.get("serotype") not in SEROTYPES:
            _fail(f"{path}.serotype", "unknown serotype")
        remaining = item.get("days_remaining")
        if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining <= 0:
            _fail(f"{path}.days_remaining", "expected a positive integer")
    return age, count


def validate_dengue_state(
    state: Mapping[str, Any],
    d: date,
    national_age_totals: Mapping[str, int],
    baseline: DengueBaseline,
) -> None:
    """Validate dimensions, exclusivity, conservation, and bounded histories."""
    root = "state.model_state.dengue"
    state = _mapping(state, root)
    if state.get("version") != "mariven-dengue-state-v1":
        _fail(f"{root}.version", "unsupported state version")
    if state.get("baseline_version") != baseline.version:
        _fail(f"{root}.baseline_version", "does not match loaded baseline")
    if state.get("random_schema_version") != 4:
        _fail(f"{root}.random_schema_version", "expected 4")
    if state.get("last_processed_date") != d.isoformat():
        _fail(f"{root}.last_processed_date", f"expected {d.isoformat()}")
    expected_age_totals = {
        age: _validate_non_negative_integer(
            national_age_totals.get(age), f"population.age_groups.{age}"
        )
        for age in AGE_GROUPS
    }
    _exact_keys(
        national_age_totals, AGE_GROUPS, "population.age_groups"
    )
    provinces = _mapping(state.get("provinces"), f"{root}.provinces")
    _exact_keys(provinces, PROVINCES, f"{root}.provinces")
    observed_age_totals = {age: 0 for age in AGE_GROUPS}
    mask_keys = tuple(format(mask, "04b") for mask in range(16))
    cross_days = int(baseline.raw["immunity"]["cross_protection_days"])
    maximum_eip = int(
        baseline.raw["transmission"]["vector_eip_days"]["maximum"]
    )
    rainfall_days = int(baseline.raw["vector"]["rainfall_lag_days"])
    for province in PROVINCES:
        province_path = f"{root}.provinces.{province}"
        province_state = _mapping(provinces[province], province_path)
        _exact_keys(
            province_state,
            ("human", "vector", "interventions"),
            province_path,
        )
        human = _mapping(province_state["human"], f"{province_path}.human")
        population_by_age = _mapping(
            human.get("population_by_age"),
            f"{province_path}.human.population_by_age",
        )
        _exact_keys(population_by_age, AGE_GROUPS, f"{province_path}.human.population_by_age")
        susceptible = _mapping(
            human.get("susceptible"), f"{province_path}.human.susceptible"
        )
        _exact_keys(susceptible, AGE_GROUPS, f"{province_path}.human.susceptible")
        stocks_by_age = {age: 0 for age in AGE_GROUPS}
        for age in AGE_GROUPS:
            population = _validate_non_negative_integer(
                population_by_age[age],
                f"{province_path}.human.population_by_age.{age}",
            )
            observed_age_totals[age] += population
            masks = _mapping(
                susceptible[age], f"{province_path}.human.susceptible.{age}"
            )
            _exact_keys(masks, mask_keys, f"{province_path}.human.susceptible.{age}")
            stocks_by_age[age] += sum(
                _validate_non_negative_integer(
                    masks[mask],
                    f"{province_path}.human.susceptible.{age}.{mask}",
                )
                for mask in mask_keys
            )
        for collection_name in ("exposed", "infectious"):
            collection = human.get(collection_name)
            if not isinstance(collection, list):
                _fail(f"{province_path}.human.{collection_name}", "expected a list")
            for index, cohort in enumerate(collection):
                age, count = _validate_human_cohort(
                    cohort,
                    f"{province_path}.human.{collection_name}[{index}]",
                )
                stocks_by_age[age] += count
        ring = human.get("cross_protected")
        if not isinstance(ring, list) or len(ring) != cross_days:
            _fail(
                f"{province_path}.human.cross_protected",
                f"expected {cross_days} buckets",
            )
        for bucket_index, bucket in enumerate(ring):
            if not isinstance(bucket, list):
                _fail(
                    f"{province_path}.human.cross_protected[{bucket_index}]",
                    "expected a list",
                )
            for cohort_index, cohort in enumerate(bucket):
                age, count = _validate_human_cohort(
                    cohort,
                    f"{province_path}.human.cross_protected[{bucket_index}]"
                    f"[{cohort_index}]",
                    cross_protected=True,
                )
                stocks_by_age[age] += count
        cursor = human.get("cross_immunity_cursor")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor < cross_days:
            _fail(f"{province_path}.human.cross_immunity_cursor", "out of range")
        for age in AGE_GROUPS:
            if stocks_by_age[age] != population_by_age[age]:
                _fail(
                    f"{province_path}.human.population_by_age.{age}",
                    f"stock total {stocks_by_age[age]} does not match {population_by_age[age]}",
                )

        vector = _mapping(province_state["vector"], f"{province_path}.vector")
        _exact_keys(
            vector,
            (
                "larval_pressure",
                "adult_total",
                "susceptible",
                "exposed",
                "infectious",
                "rainfall_queue",
            ),
            f"{province_path}.vector",
        )
        larval = _finite(vector["larval_pressure"], f"{province_path}.vector.larval_pressure")
        adult = _finite(vector["adult_total"], f"{province_path}.vector.adult_total")
        vector_susceptible = _finite(
            vector["susceptible"], f"{province_path}.vector.susceptible"
        )
        if min(larval, adult, vector_susceptible) < 0:
            _fail(f"{province_path}.vector", "stocks must be non-negative")
        exposed = _mapping(vector["exposed"], f"{province_path}.vector.exposed")
        infectious = _mapping(vector["infectious"], f"{province_path}.vector.infectious")
        _exact_keys(exposed, SEROTYPES, f"{province_path}.vector.exposed")
        _exact_keys(infectious, SEROTYPES, f"{province_path}.vector.infectious")
        component_total = vector_susceptible
        for serotype in SEROTYPES:
            queue = exposed[serotype]
            if not isinstance(queue, list) or len(queue) != maximum_eip:
                _fail(
                    f"{province_path}.vector.exposed.{serotype}",
                    f"expected {maximum_eip} values",
                )
            for index, value in enumerate(queue):
                parsed = _finite(
                    value, f"{province_path}.vector.exposed.{serotype}[{index}]"
                )
                if parsed < 0:
                    _fail(f"{province_path}.vector.exposed.{serotype}[{index}]", "negative")
                component_total += parsed
            parsed = _finite(
                infectious[serotype], f"{province_path}.vector.infectious.{serotype}"
            )
            if parsed < 0:
                _fail(f"{province_path}.vector.infectious.{serotype}", "negative")
            component_total += parsed
        if not math.isclose(adult, component_total, rel_tol=1e-9, abs_tol=1e-9):
            _fail(f"{province_path}.vector.adult_total", "component identity failed")
        rainfall_queue = vector["rainfall_queue"]
        if not isinstance(rainfall_queue, list) or len(rainfall_queue) != rainfall_days:
            _fail(
                f"{province_path}.vector.rainfall_queue",
                f"expected {rainfall_days} values",
            )
        for index, value in enumerate(rainfall_queue):
            if _finite(value, f"{province_path}.vector.rainfall_queue[{index}]") < 0:
                _fail(f"{province_path}.vector.rainfall_queue[{index}]", "negative")
        interventions = _mapping(
            province_state["interventions"], f"{province_path}.interventions"
        )
        for key in ("pilot_share", "community_coverage", "field_effectiveness"):
            _probability(interventions.get(key), f"{province_path}.interventions.{key}")

    for age in AGE_GROUPS:
        if observed_age_totals[age] != expected_age_totals[age]:
            _fail(
                f"{root}.human.population_by_age.{age}",
                f"expected {expected_age_totals[age]}, got {observed_age_totals[age]}",
            )
    surveillance = _mapping(state.get("surveillance"), f"{root}.surveillance")
    for key in (
        "clinical_queue",
        "reporting_queue",
        "laboratory_queue",
        "daily_records",
        "weekly_ledger",
        "release_vintages",
        "daily_death_requests",
    ):
        if not isinstance(surveillance.get(key), list):
            _fail(f"{root}.surveillance.{key}", "expected a list")
    daily = _mapping(
        surveillance.get("daily_totals"), f"{root}.surveillance.daily_totals"
    )
    if daily.get("date") != d.isoformat():
        _fail(f"{root}.surveillance.daily_totals.date", f"expected {d.isoformat()}")
    for key in (
        "estimated_infections",
        "symptomatic",
        "reported",
        "lab_processed",
        "confirmed",
        "severe",
        "hospitalized",
        "deaths",
    ):
        _validate_non_negative_integer(daily.get(key), f"{root}.surveillance.daily_totals.{key}")
    pressure = daily.get("healthcare_pressure", 0.0)
    if _finite(pressure, f"{root}.surveillance.daily_totals.healthcare_pressure") < 0:
        _fail(f"{root}.surveillance.daily_totals.healthcare_pressure", "negative")
    alert_state = _mapping(
        surveillance.get("alert_state"), f"{root}.surveillance.alert_state"
    )
    _exact_keys(alert_state, PROVINCES, f"{root}.surveillance.alert_state")
    allowed_alerts = {"baseline", "watch", "alert", "outbreak", "recovery"}
    for province in PROVINCES:
        alert = alert_state[province]
        level = alert.get("level") if isinstance(alert, Mapping) else alert
        if level not in allowed_alerts:
            _fail(
                f"{root}.surveillance.alert_state.{province}",
                "unknown alert level",
            )
    for index, request in enumerate(surveillance["daily_death_requests"]):
        request_path = f"{root}.surveillance.daily_death_requests[{index}]"
        item = _mapping(request, request_path)
        if item.get("cause") != "dengue":
            _fail(f"{request_path}.cause", "expected dengue")
        if item.get("province") not in PROVINCES:
            _fail(f"{request_path}.province", "unknown province")
        if item.get("age_group") not in AGE_GROUPS:
            _fail(f"{request_path}.age_group", "unknown age group")
        _validate_non_negative_integer(
            item.get("count"), f"{request_path}.count"
        )
    week_ends = [
        row.get("week_end")
        for row in surveillance["weekly_ledger"]
        if isinstance(row, Mapping)
    ]
    if week_ends != sorted(week_ends):
        _fail(f"{root}.surveillance.weekly_ledger", "must be ordered")
    for index, row in enumerate(surveillance["weekly_ledger"]):
        row_path = f"{root}.surveillance.weekly_ledger[{index}]"
        row = _mapping(row, row_path)
        try:
            week_start = date.fromisoformat(row.get("week_start"))
            week_end = date.fromisoformat(row.get("week_end"))
        except (TypeError, ValueError) as exc:
            raise DengueDataError(f"{row_path}: invalid week dates") from exc
        if week_end - week_start != timedelta(days=6):
            _fail(row_path, "expected a seven-day Monday-Sunday week")
        _validate_non_negative_integer(
            row.get("reported_national"), f"{row_path}.reported_national"
        )
        for key in (
            "confirmed_national",
            "severe_national",
            "hospitalized_national",
            "deaths_national",
        ):
            if key in row:
                _validate_non_negative_integer(row[key], f"{row_path}.{key}")
    published_dates: list[str] = []
    vintage_keys: set[tuple[str, str]] = set()
    for index, release in enumerate(surveillance["release_vintages"]):
        release_path = f"{root}.surveillance.release_vintages[{index}]"
        release = _mapping(release, release_path)
        vintage = release.get("vintage")
        if vintage not in {"provisional", "revised", "final"}:
            _fail(f"{release_path}.vintage", "unknown release vintage")
        key = (release.get("week_end"), vintage)
        if key in vintage_keys:
            _fail(release_path, "duplicate week vintage")
        vintage_keys.add(key)
        published = release.get("published_on")
        try:
            date.fromisoformat(published)
        except (TypeError, ValueError) as exc:
            raise DengueDataError(
                f"{release_path}.published_on: invalid date"
            ) from exc
        published_dates.append(published)
        expected_revision = (
            None
            if vintage == "provisional"
            else "provisional" if vintage == "revised" else "revised"
        )
        if release.get("revision_of") != expected_revision:
            _fail(f"{release_path}.revision_of", "invalid revision chain")
    if published_dates != sorted(published_dates):
        _fail(f"{root}.surveillance.release_vintages", "must be ordered")
    limits = baseline.raw["state_limits"]
    if len(surveillance["weekly_ledger"]) > limits["weekly_history_weeks"]:
        _fail(f"{root}.surveillance.weekly_ledger", "history limit exceeded")
    if len(surveillance["daily_records"]) > limits["daily_quality_history_days"]:
        _fail(f"{root}.surveillance.daily_records", "history limit exceeded")
    if len(surveillance["release_vintages"]) > limits["release_vintages"]:
        _fail(f"{root}.surveillance.release_vintages", "history limit exceeded")
    annual = _mapping(state.get("cumulative_annual"), f"{root}.cumulative_annual")
    if annual.get("year") != d.year:
        _fail(f"{root}.cumulative_annual.year", f"expected {d.year}")
    for key in (
        "estimated_infections",
        "reported",
        "confirmed",
        "severe",
        "hospitalized",
        "deaths",
    ):
        _validate_non_negative_integer(annual.get(key), f"{root}.cumulative_annual.{key}")
    if not isinstance(state.get("data_quality"), list):
        _fail(f"{root}.data_quality", "expected a list")


def _remove_from_human_age(
    human: dict[str, Any], age: str, count: int, path: str
) -> None:
    stocks: list[tuple[str, Any, Any, int]] = []
    for mask in sorted(human["susceptible"][age]):
        value = human["susceptible"][age][mask]
        stocks.append(("mapping", human["susceptible"][age], mask, value))
    for collection_name in ("exposed", "infectious"):
        for item in human[collection_name]:
            if item["age_group"] == age:
                stocks.append(("cohort", item, "count", item["count"]))
    for bucket in human["cross_protected"]:
        for item in bucket:
            if item["age_group"] == age:
                stocks.append(("cohort", item, "count", item["count"]))
    available = sum(item[3] for item in stocks)
    if count > available:
        _fail(path, f"requested {count}, only {available} available")
    removals = _largest_remainder_counts(
        count, [item[3] for item in stocks], path
    )
    for (_, container, key, _), removal in zip(stocks, removals, strict=True):
        container[key] -= removal
    human["exposed"] = [item for item in human["exposed"] if item["count"]]
    human["infectious"] = [item for item in human["infectious"] if item["count"]]
    human["cross_protected"] = [
        [item for item in bucket if item["count"]]
        for bucket in human["cross_protected"]
    ]
    human["population_by_age"][age] -= count


def _add_age_delta(
    state: dict[str, Any], age: str, count: int, baseline: DengueBaseline
) -> None:
    from dengue_dynamics import initialize_human_state

    allocations = _largest_remainder_counts(
        count,
        [baseline.province_populations[province] for province in PROVINCES],
        f"reconcile.{age}",
    )
    if age == "0-4":
        for province, addition in zip(PROVINCES, allocations, strict=True):
            human = state["provinces"][province]["human"]
            human["susceptible"][age]["0000"] += addition
            human["population_by_age"][age] += addition
        return
    province_ages = {
        province: {
            candidate: allocations[index] if candidate == age else 0
            for candidate in AGE_GROUPS
        }
        for index, province in enumerate(PROVINCES)
    }
    additions = initialize_human_state(
        province_ages, baseline, lambda name: random.Random(name)
    )
    for province in PROVINCES:
        human = state["provinces"][province]["human"]
        for mask, addition in additions[province]["susceptible"][age].items():
            human["susceptible"][age][mask] += addition
        human["population_by_age"][age] += allocations[PROVINCES.index(province)]


def _remove_age_delta(
    state: dict[str, Any], age: str, count: int
) -> None:
    weights = [
        state["provinces"][province]["human"]["population_by_age"][age]
        for province in PROVINCES
    ]
    allocations = _largest_remainder_counts(count, weights, f"reconcile.{age}")
    for province, removal in zip(PROVINCES, allocations, strict=True):
        if removal:
            _remove_from_human_age(
                state["provinces"][province]["human"],
                age,
                removal,
                f"reconcile.{province}.{age}",
            )


def reconcile_dengue_population(
    state: Mapping[str, Any],
    before_population: Mapping[str, Any],
    after_population: Mapping[str, Any],
    confirmed_deaths: list[Mapping[str, Any]],
    baseline: DengueBaseline,
) -> dict[str, Any]:
    """Reconcile disease stocks to the authoritative population model."""
    from dengue_dynamics import national_age_totals

    before = national_age_totals(before_population)
    validate_dengue_state(
        state,
        date.fromisoformat(state["last_processed_date"]),
        before,
        baseline,
    )
    next_state = copy.deepcopy(dict(state))
    confirmed_total = 0
    if not isinstance(confirmed_deaths, list):
        _fail("confirmed_deaths", "expected a list")
    for index, request in enumerate(confirmed_deaths):
        path = f"confirmed_deaths[{index}]"
        item = _mapping(request, path)
        if item.get("cause") != "dengue":
            _fail(f"{path}.cause", "expected dengue")
        province = item.get("province")
        age = item.get("age_group")
        if province not in PROVINCES:
            _fail(f"{path}.province", "unknown province")
        if age not in AGE_GROUPS:
            _fail(f"{path}.age_group", "unknown age group")
        count = _validate_non_negative_integer(item.get("count"), f"{path}.count")
        if count:
            _remove_from_human_age(
                next_state["provinces"][province]["human"],
                age,
                count,
                path,
            )
            confirmed_total += count
    target = national_age_totals(after_population)
    current = _dengue_age_totals(next_state)
    for age in AGE_GROUPS:
        delta = target[age] - current[age]
        if delta > 0:
            _add_age_delta(next_state, age, delta, baseline)
        elif delta < 0:
            _remove_age_delta(next_state, age, -delta)
    next_state["cumulative_annual"]["deaths"] += confirmed_total
    validate_dengue_state(
        next_state,
        date.fromisoformat(next_state["last_processed_date"]),
        target,
        baseline,
    )
    return next_state


def dengue_snapshot(
    d: date, state: Mapping[str, Any], baseline: DengueBaseline
) -> dict[str, Any]:
    """Build the queue-free public dengue view from validated state only."""
    from dengue_surveillance import surveillance_snapshot

    internal_ages = _dengue_age_totals(state)
    validate_dengue_state(state, d, internal_ages, baseline)
    humans = _human_states(state)
    population_by_province = {
        province: sum(humans[province]["population_by_age"].values())
        for province in PROVINCES
    }
    public = surveillance_snapshot(
        d, state["surveillance"], population_by_province, baseline
    )
    public["national"]["population"] = sum(
        population_by_province.values()
    )
    infectious_by_serotype = {serotype: 0 for serotype in SEROTYPES}
    for province in PROVINCES:
        for cohort in humans[province]["infectious"]:
            infectious_by_serotype[cohort["serotype"]] += cohort["count"]
    sample_size = sum(infectious_by_serotype.values())
    public["serotypes"] = {
        "infectious_by_serotype": infectious_by_serotype,
        "share": {
            serotype: (
                0.0
                if sample_size == 0
                else infectious_by_serotype[serotype] / sample_size
            )
            for serotype in SEROTYPES
        },
        "sample_size": sample_size,
    }
    public["healthcare_pressure"] = float(
        state["surveillance"]["daily_totals"].get(
            "healthcare_pressure", 0.0
        )
    )
    public["interventions"] = {
        province: {
            "wmar1_coverage": (
                state["provinces"][province]["interventions"]["pilot_share"]
                * state["provinces"][province]["interventions"]["community_coverage"]
            )
        }
        for province in PROVINCES
    }
    public["cumulative_annual"] = copy.deepcopy(state["cumulative_annual"])
    public["data_quality"] = copy.deepcopy(state["data_quality"])
    return public
