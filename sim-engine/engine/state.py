import copy
import json
import math
from calendar import monthrange
from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from numbers import Real
from pathlib import Path
from typing import Any

from population_model import (
    PopulationBaseline,
    PopulationDataError,
    initialize_population_state,
    population_snapshot,
    validate_population_state,
)

SCHEMA_VERSION = 3

_CORE_DICTIONARIES = (
    "_meta",
    "weather",
    "economy",
    "government",
    "deaths_today",
    "demographics",
    "model_state",
)
_MODEL_DICTIONARIES = (
    "weather", "exchange", "commodities", "inflation", "population",
)
_CORE_ECONOMIC_VALUES = (
    "inflation_pct",
    "unemployment_pct",
    "interest_rate_pct",
    "exchange_rate_mvl_per_usd",
    "fuel_95_price_mvl",
    "fuel_diesel_price_mvl",
)


class StateValidationError(ValueError):
    """Raised when a simulation state does not match schema v3."""


def _fail(path: str, message: str) -> None:
    raise StateValidationError(f"{path}: {message}")


def _require_mapping(parent: Mapping[str, Any], key: str,
                     parent_path: str = "state") -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        _fail(f"{parent_path}.{key}", "expected a dictionary")
    return value


def _parse_date(value: Any) -> date:
    if not isinstance(value, str):
        _fail("state.date", "expected an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("state.date", "expected an ISO date")
    if parsed.isoformat() != value:
        _fail("state.date", "expected an ISO date")
    return parsed


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        _fail(path, "expected a finite number")
    try:
        converted = float(value)
    except OverflowError:
        _fail(path, "expected a finite number")
    if not math.isfinite(converted):
        _fail(path, "expected a finite number")
    return converted


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _shift_month(d: date, offset: int) -> date:
    month_index = d.year * 12 + d.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return _month_end(year, zero_based_month + 1)


def _baseline_cpi_history(current_date: date,
                          inflation_pct: float) -> list[dict[str, Any]]:
    inflation = _finite_number(
        inflation_pct, "state.economy.inflation_pct",
    )
    if inflation <= -100.0:
        _fail(
            "state.economy.inflation_pct",
            "must be greater than -100 to construct CPI history",
        )
    monthly_factor = (1.0 + inflation / 100.0) ** (1.0 / 12.0)
    return [
        {
            "date": _shift_month(current_date, month_offset).isoformat(),
            "index": 100.0 / monthly_factor ** -month_offset,
            "source": "migration_baseline",
        }
        for month_offset in range(-12, 1)
    ]


def validate_state(
    state: Mapping[str, Any],
    *,
    population_baseline: PopulationBaseline | None = None,
) -> None:
    """Validate a schema-v3 state, raising an error with a field path."""
    if not isinstance(state, Mapping):
        _fail("state", "expected a dictionary")

    if state.get("schema_version") != SCHEMA_VERSION:
        _fail(
            "state.schema_version",
            f"expected {SCHEMA_VERSION}",
        )

    current_date = _parse_date(state.get("date"))

    population_number = _finite_number(
        state.get("population"), "state.population"
    )
    population_value = state.get("population")
    if (
        isinstance(population_value, bool)
        or not isinstance(population_value, int)
    ):
        _fail("state.population", "expected a positive integer")
    if population_number <= 0:
        _fail("state.population", "expected a positive number")

    dictionaries = {
        key: _require_mapping(state, key) for key in _CORE_DICTIONARIES
    }
    model_state = dictionaries["model_state"]
    for key in _MODEL_DICTIONARIES:
        _require_mapping(model_state, key, "state.model_state")

    economy = dictionaries["economy"]
    for key in _CORE_ECONOMIC_VALUES:
        _finite_number(economy.get(key), f"state.economy.{key}")

    base_seed = state.get("base_seed")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int):
        _fail("state.base_seed", "expected an integer")

    if not isinstance(state.get("events_today"), list):
        _fail("state.events_today", "expected a list")

    demographics = dictionaries["demographics"]
    if demographics.get("population") != population_value:
        _fail(
            "state.demographics.population",
            "does not match state.population",
        )
    baseline = population_baseline or _default_population_baseline()
    try:
        validate_population_state(
            model_state["population"],
            population_value,
            baseline,
            current_date=current_date,
        )
    except PopulationDataError as exc:
        raise StateValidationError(str(exc)) from exc
    expected_demographics = population_snapshot(model_state["population"])
    for key in (
        "population",
        "male_population",
        "female_population",
        "median_age",
        "children_0_14",
        "working_age_15_64",
        "elderly_65_plus",
        "women_15_49",
        "dependency_ratio_pct",
        "annualized_growth_target_pct",
        "baseline_period_end",
        "partial_year",
        "five_year_age_groups",
    ):
        if demographics.get(key) != expected_demographics[key]:
            _fail(
                f"state.demographics.{key}",
                "does not match population cohorts",
            )
    non_negative_flow_fields = (
        "births_today",
        "deaths_all_causes_today",
        "baseline_deaths_today",
        "notable_deaths_today",
        "other_deaths_today",
        "excess_deaths_today",
        "returning_diaspora_today",
        "foreign_immigrants_today",
        "emigrants_today",
    )
    for key in non_negative_flow_fields:
        value = demographics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(
                f"state.demographics.{key}",
                "expected a non-negative integer",
            )
    for key in (
        "net_migration_today",
        "natural_increase_today",
        "population_change_today",
    ):
        value = demographics.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(f"state.demographics.{key}", "expected an integer")
    expected_net_migration = (
        demographics["returning_diaspora_today"]
        + demographics["foreign_immigrants_today"]
        - demographics["emigrants_today"]
    )
    if demographics["net_migration_today"] != expected_net_migration:
        _fail(
            "state.demographics.net_migration_today",
            "does not match migration flows",
        )
    expected_natural_increase = (
        demographics["births_today"]
        - demographics["deaths_all_causes_today"]
    )
    if demographics["natural_increase_today"] != expected_natural_increase:
        _fail(
            "state.demographics.natural_increase_today",
            "does not match births and deaths",
        )
    if demographics["population_change_today"] != (
        expected_natural_increase + expected_net_migration
    ):
        _fail(
            "state.demographics.population_change_today",
            "does not match natural increase and net migration",
        )

    deaths = dictionaries["deaths_today"]
    if "notable_total" in deaths:
        death_fields = (
            "total",
            "notable_total",
            "non_notable",
            "excess",
            "traffic",
            "drowning",
            "suicide",
            "murder",
            "workplace",
            "lightning",
            "other",
        )
        for key in death_fields:
            value = deaths.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(
                    f"state.deaths_today.{key}",
                    "expected a non-negative integer",
                )
        reconciled_pairs = (
            ("total", "deaths_all_causes_today"),
            ("notable_total", "notable_deaths_today"),
            ("non_notable", "other_deaths_today"),
            ("excess", "excess_deaths_today"),
        )
        for death_key, demographic_key in reconciled_pairs:
            if deaths[death_key] != demographics[demographic_key]:
                _fail(
                    f"state.deaths_today.{death_key}",
                    f"does not match state.demographics.{demographic_key}",
                )
        notable_sum = sum(
            deaths[key]
            for key in (
                "traffic",
                "drowning",
                "suicide",
                "murder",
                "workplace",
                "lightning",
                "other",
            )
        )
        if deaths["notable_total"] != notable_sum:
            _fail(
                "state.deaths_today.notable_total",
                "does not match notable death categories",
            )
        if deaths["total"] != deaths["notable_total"] + deaths["non_notable"]:
            _fail(
                "state.deaths_today.total",
                "does not match notable and non-notable deaths",
            )
        expected_excess = max(
            0,
            deaths["notable_total"] - demographics["baseline_deaths_today"],
        )
        if deaths["excess"] != expected_excess:
            _fail(
                "state.deaths_today.excess",
                "does not match notable deaths above baseline",
            )

    _validate_nested_numbers(state, "state", set())
    try:
        json.dumps(state, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        _fail("state", f"not JSON serializable: {exc}")


def _validate_nested_numbers(
    value: Any,
    path: str,
    seen: set[int],
) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail(path, "expected a finite number")

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for key, nested in value.items():
            _validate_nested_numbers(key, f"{path}.<key>", seen)
            nested_path = (
                f"{path}.{key}"
                if isinstance(key, str)
                else f"{path}[{key!r}]"
            )
            _validate_nested_numbers(nested, nested_path, seen)
        return

    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for index, nested in enumerate(value):
            _validate_nested_numbers(nested, f"{path}[{index}]", seen)


def _migrate_v1_to_v2(
    raw: Mapping[str, Any],
    *,
    base_seed: int | None = None,
) -> dict:
    """Deep-copy a v1 state and add the former schema-v2 model state."""
    if not isinstance(raw, Mapping):
        _fail("state", "expected a dictionary")

    migrated = copy.deepcopy(dict(raw))
    current_date = _parse_date(migrated.get("date"))
    weather = _require_mapping(migrated, "weather")
    economy = _require_mapping(migrated, "economy")

    condition = weather.get("condition")
    if not isinstance(condition, str):
        _fail("state.weather.condition", "expected a string")

    exchange_rate = _finite_number(
        economy.get("exchange_rate_mvl_per_usd"),
        "state.economy.exchange_rate_mvl_per_usd",
    )
    inflation_pct = _finite_number(
        economy.get("inflation_pct"), "state.economy.inflation_pct",
    )

    metadata = migrated.get("_meta")
    if metadata is None:
        metadata = {}
        migrated["_meta"] = metadata
    elif not isinstance(metadata, Mapping):
        _fail("state._meta", "expected a dictionary")

    selected_seed = (
        base_seed if base_seed is not None else metadata.get("random_seed", 42)
    )
    if isinstance(selected_seed, bool) or not isinstance(selected_seed, int):
        _fail("state.base_seed", "expected an integer")

    model_state = {
        "weather": {
            "previous_conditions": {city: condition for city in (
                "katora", "makadi_port", "timo", "pela", "ruwa"
            )},
            "rainfall_history": [],
        },
        "exchange": {"mvl_per_usd": float(exchange_rate)},
        "commodities": {"source_month": None},
        "inflation": {
            "published_index": 100.0,
            "published_yoy_pct": float(inflation_pct),
            "published_mom_pct": 0.0,
            "last_release_date": None,
            "daily_observations": [],
            "monthly_history": _baseline_cpi_history(
                current_date, inflation_pct,
            ),
        },
    }

    migrated["schema_version"] = 2
    migrated["base_seed"] = selected_seed
    migrated["model_state"] = model_state
    return migrated


def _migrate_v2_to_v3(
    raw: Mapping[str, Any],
    baseline: PopulationBaseline,
) -> dict:
    migrated = copy.deepcopy(dict(raw))
    current_date = _parse_date(migrated.get("date"))
    population_number = _finite_number(
        migrated.get("population"), "state.population"
    )
    population = migrated.get("population")
    if isinstance(population, bool) or not isinstance(population, int):
        _fail("state.population", "expected a positive integer")
    if population_number <= 0:
        _fail("state.population", "expected a positive number")
    model_state = _require_mapping(migrated, "model_state")
    selected_seed = migrated.get("base_seed")
    if isinstance(selected_seed, bool) or not isinstance(selected_seed, int):
        _fail("state.base_seed", "expected an integer")
    population_state = initialize_population_state(
        current_date,
        population,
        baseline,
        base_seed=selected_seed,
    )
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["model_state"] = copy.deepcopy(dict(model_state))
    migrated["model_state"]["population"] = population_state
    migrated["demographics"] = population_snapshot(population_state)
    validate_state(migrated, population_baseline=baseline)
    return migrated


def migrate_state(
    raw: Mapping[str, Any],
    *,
    base_seed: int | None = None,
    population_baseline: PopulationBaseline | None = None,
) -> dict:
    """Migrate a v1 or v2 state to deterministic schema v3."""
    if not isinstance(raw, Mapping):
        _fail("state", "expected a dictionary")
    baseline = population_baseline or _default_population_baseline()
    version = raw.get("schema_version")
    if version is None:
        v2 = _migrate_v1_to_v2(raw, base_seed=base_seed)
        return _migrate_v2_to_v3(v2, baseline)
    if version == 2:
        if base_seed is not None:
            v2 = copy.deepcopy(dict(raw))
            v2["base_seed"] = base_seed
        else:
            v2 = raw
        return _migrate_v2_to_v3(v2, baseline)
    if version == SCHEMA_VERSION:
        prepared = copy.deepcopy(dict(raw))
        validate_state(prepared, population_baseline=baseline)
        return prepared
    _fail("state.schema_version", f"expected 2 or {SCHEMA_VERSION}")


def prepare_state(
    raw: Mapping[str, Any],
    *,
    population_baseline: PopulationBaseline | None = None,
) -> dict:
    """Return an independent, validated schema-v3 state."""
    if not isinstance(raw, Mapping):
        _fail("state", "expected a dictionary")
    baseline = population_baseline or _default_population_baseline()
    if raw.get("schema_version") in (None, 2):
        return migrate_state(raw, population_baseline=baseline)

    prepared = copy.deepcopy(dict(raw))
    validate_state(prepared, population_baseline=baseline)
    return prepared


@lru_cache(maxsize=1)
def _default_population_baseline() -> PopulationBaseline:
    return PopulationBaseline.from_json(
        Path(__file__).resolve().parents[1]
        / "data"
        / "population_baseline_2026.json"
    )
