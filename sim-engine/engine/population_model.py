"""Deterministic single-age population cohort model."""

import copy
import json
import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from random_streams import make_rng


SEXES = ("male", "female")
AGE_COUNT = 101
FERTILITY_AGE_COUNT = 35
MIGRATION_TYPES = (
    "returning_diaspora",
    "foreign_immigrants",
    "emigrants",
)
NOTABLE_DEATH_CATEGORIES = (
    "traffic",
    "drowning",
    "suicide",
    "murder",
    "workplace",
    "lightning",
    "other",
)
BASELINE_VERSION = "mariven-population-2026-v1"
PARAMETER_VERSION = "mariven-demographic-path-v1"
POPULATION_SCHEMA_VERSION = 3
PLAN_DAYS = 365


class PopulationDataError(ValueError):
    """Raised when population source data or state is invalid."""


def _fail(path: str, message: str) -> None:
    raise PopulationDataError(f"{path}: {message}")


def _population_date(value: Any, path: str) -> date:
    if not isinstance(value, str):
        _fail(path, "expected an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "expected an ISO date")
    if parsed.isoformat() != value:
        _fail(path, "expected an ISO date")
    return parsed


def _integer_list(value: Any, length: int, path: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        _fail(path, f"expected a list of {length} integers")
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            _fail(f"{path}[{index}]", "expected a non-negative integer")
    return list(value)


def _finite_weights(value: Any, length: int, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        _fail(path, f"expected a list of {length} weights")
    result = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _fail(f"{path}[{index}]", "expected a finite non-negative weight")
        converted = float(item)
        if not math.isfinite(converted) or converted < 0:
            _fail(f"{path}[{index}]", "expected a finite non-negative weight")
        result.append(converted)
    if sum(result) <= 0:
        _fail(path, "weights must have a positive sum")
    return result


def _probability_list(value: Any, length: int, path: str) -> list[float]:
    result = _finite_weights(value, length, path)
    for index, probability in enumerate(result):
        if probability > 1.0:
            _fail(f"{path}[{index}]", "expected a probability from 0 through 1")
    return result


def _sex_weight_map(value: Any, path: str) -> dict[str, list[float]]:
    if not isinstance(value, dict):
        _fail(path, "expected a dictionary")
    result = {
        sex: _finite_weights(value.get(sex), AGE_COUNT, f"{path}.{sex}")
        for sex in SEXES
    }
    total = sum(sum(result[sex]) for sex in SEXES)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        _fail(path, "combined sex weights must sum to 1")
    return result


@dataclass(frozen=True)
class PopulationBaseline:
    version: str
    anchor_date: date
    cohorts: dict[str, list[int]]
    birthday_buckets: dict[str, list[list[int]]]
    fertility_weights: list[float]
    mortality_rates: dict[str, list[float]]
    migration_weights: dict[str, dict[str, list[float]]]
    notable_death_weights: dict[str, dict[str, list[float]]]
    first_cycle_targets: dict[str, int]
    calibration: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def from_json(cls, path: Path) -> "PopulationBaseline":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PopulationDataError(f"population baseline {path}: {exc}") from exc
        if not isinstance(raw, dict):
            _fail("baseline", "expected a dictionary")
        version = raw.get("version")
        if version != BASELINE_VERSION:
            _fail("baseline.version", f"expected {BASELINE_VERSION}")
        try:
            anchor = date.fromisoformat(raw.get("anchor_date", ""))
        except (TypeError, ValueError):
            _fail("baseline.anchor_date", "expected an ISO date")

        raw_cohorts = raw.get("cohorts")
        if not isinstance(raw_cohorts, dict):
            _fail("baseline.cohorts", "expected a dictionary")
        cohorts = {
            sex: _integer_list(
                raw_cohorts.get(sex), AGE_COUNT, f"baseline.cohorts.{sex}"
            )
            for sex in SEXES
        }

        raw_buckets = raw.get("birthday_buckets")
        if not isinstance(raw_buckets, dict):
            _fail("baseline.birthday_buckets", "expected a dictionary")
        buckets: dict[str, list[list[int]]] = {}
        for sex in SEXES:
            sex_buckets = raw_buckets.get(sex)
            if not isinstance(sex_buckets, list) or len(sex_buckets) != AGE_COUNT:
                _fail(
                    f"baseline.birthday_buckets.{sex}",
                    f"expected {AGE_COUNT} age rows",
                )
            buckets[sex] = [
                _integer_list(
                    age_buckets,
                    12,
                    f"baseline.birthday_buckets.{sex}[{age}]",
                )
                for age, age_buckets in enumerate(sex_buckets)
            ]
            for age in range(AGE_COUNT):
                if sum(buckets[sex][age]) != cohorts[sex][age]:
                    _fail(
                        f"baseline.birthday_buckets.{sex}[{age}]",
                        "bucket sum does not match cohort",
                    )

        fertility = _finite_weights(
            raw.get("fertility_weights"),
            FERTILITY_AGE_COUNT,
            "baseline.fertility_weights",
        )
        if not math.isclose(sum(fertility), 1.0, rel_tol=0.0, abs_tol=1e-9):
            _fail("baseline.fertility_weights", "weights must sum to 1")

        raw_mortality = raw.get("mortality_rates")
        if not isinstance(raw_mortality, dict):
            _fail("baseline.mortality_rates", "expected a dictionary")
        mortality = {
            sex: _probability_list(
                raw_mortality.get(sex),
                AGE_COUNT,
                f"baseline.mortality_rates.{sex}",
            )
            for sex in SEXES
        }

        raw_migration = raw.get("migration_weights")
        if not isinstance(raw_migration, dict):
            _fail("baseline.migration_weights", "expected a dictionary")
        migration = {
            kind: _sex_weight_map(
                raw_migration.get(kind), f"baseline.migration_weights.{kind}"
            )
            for kind in MIGRATION_TYPES
        }

        raw_notable = raw.get("notable_death_weights")
        if not isinstance(raw_notable, dict) or not raw_notable:
            _fail("baseline.notable_death_weights", "expected a dictionary")
        if set(raw_notable) != set(NOTABLE_DEATH_CATEGORIES):
            _fail(
                "baseline.notable_death_weights",
                "unexpected notable death category keys",
            )
        notable = {
            category: _sex_weight_map(
                raw_notable[category],
                f"baseline.notable_death_weights.{category}",
            )
            for category in NOTABLE_DEATH_CATEGORIES
        }

        targets = raw.get("first_cycle_targets")
        if not isinstance(targets, dict):
            _fail("baseline.first_cycle_targets", "expected a dictionary")
        required_targets = {
            "births", "baseline_deaths", "returning_diaspora",
            "foreign_immigrants", "emigrants",
        }
        if set(targets) != required_targets:
            _fail("baseline.first_cycle_targets", "unexpected target keys")
        for key, value in targets.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(
                    f"baseline.first_cycle_targets.{key}",
                    "expected a non-negative integer",
                )

        calibration = raw.get("calibration")
        metadata = raw.get("_meta")
        if not isinstance(calibration, dict):
            _fail("baseline.calibration", "expected a dictionary")
        if not isinstance(metadata, dict):
            _fail("baseline._meta", "expected a dictionary")
        total_population = sum(sum(cohorts[sex]) for sex in SEXES)
        if calibration.get("total_population") != total_population:
            _fail("baseline.calibration.total_population", "does not match cohorts")

        return cls(
            version=version,
            anchor_date=anchor,
            cohorts=cohorts,
            birthday_buckets=buckets,
            fertility_weights=fertility,
            mortality_rates=mortality,
            migration_weights=migration,
            notable_death_weights=notable,
            first_cycle_targets=dict(targets),
            calibration=dict(calibration),
            metadata=dict(metadata),
        )


def median_age(cohorts: dict[str, list[int]]) -> float:
    """Return an interpolated median age from single-age sex cohorts."""
    totals = [
        cohorts["male"][age] + cohorts["female"][age]
        for age in range(AGE_COUNT)
    ]
    halfway = sum(totals) / 2
    cumulative = 0
    for age, count in enumerate(totals):
        if cumulative + count >= halfway:
            return age + (halfway - cumulative) / count
        cumulative += count
    return 100.0


def _largest_remainder(
    values: list[float],
    total: int,
    *,
    tie_breakers: list[float] | None = None,
) -> list[int]:
    if total < 0:
        raise ValueError("total must be non-negative")
    weight_total = sum(values)
    if weight_total <= 0:
        raise ValueError("weights must have a positive sum")
    scaled = [value * total / weight_total for value in values]
    result = [math.floor(value) for value in scaled]
    if tie_breakers is None:
        tie_breakers = [-index for index in range(len(values))]
    if len(tie_breakers) != len(values):
        raise ValueError("tie breakers must match values")
    order = sorted(
        range(len(values)),
        key=lambda index: (
            scaled[index] - result[index],
            tie_breakers[index],
        ),
        reverse=True,
    )
    for index in order[:total - sum(result)]:
        result[index] += 1
    return result


def _season_factor(stream_name: str, d: date) -> float:
    if stream_name == "births":
        return 1.0 + 0.05 * math.cos(
            2 * math.pi * (d.timetuple().tm_yday - 45) / 365.2425
        )
    if stream_name == "baseline_deaths":
        return 1.04 if d.month in (11, 12, 1, 2, 3, 4) else 0.96
    if stream_name == "returning_diaspora":
        return 1.55 if d.month in (12, 1) else 0.90
    if stream_name == "emigrants":
        return 1.15 if d.month in (1, 2, 7) else 0.96
    return 1.0


def build_balanced_plan(
    total: int,
    start_date: date,
    *,
    base_seed: int,
    stream_name: str,
) -> list[int]:
    """Distribute an exact integer quota across 365 deterministic days."""
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("total must be a non-negative integer")
    rng = make_rng(
        base_seed,
        POPULATION_SCHEMA_VERSION,
        start_date,
        "population",
        f"plan:{stream_name}",
    )
    weights = []
    for offset in range(PLAN_DAYS):
        d = start_date + timedelta(days=offset)
        random_factor = 0.72 + 0.56 * rng.random()
        weights.append(
            _season_factor(stream_name.rsplit(":", 1)[-1], d) * random_factor
        )
    tie_breakers = [rng.random() for _ in range(PLAN_DAYS)]
    return _largest_remainder(
        weights,
        total,
        tie_breakers=tie_breakers,
    )


def _split_plan_by_capacity(
    plan: list[int],
    first_total: int,
    *,
    base_seed: int,
    start_date: date,
    stream_name: str,
) -> tuple[list[int], list[int]]:
    total = sum(plan)
    if not 0 <= first_total <= total:
        raise ValueError("split total is outside plan capacity")
    if total == 0:
        return [0] * len(plan), [0] * len(plan)
    ratio = first_total / total
    raw = [value * ratio for value in plan]
    first = [math.floor(value) for value in raw]
    rng = make_rng(
        base_seed,
        POPULATION_SCHEMA_VERSION,
        start_date,
        "population",
        f"plan:{stream_name}",
    )
    tie_breakers = [rng.random() for _ in plan]
    candidates = [index for index, value in enumerate(plan) if first[index] < value]
    order = sorted(
        candidates,
        key=lambda index: (raw[index] - first[index], tie_breakers[index]),
        reverse=True,
    )
    for index in order[:first_total - sum(first)]:
        first[index] += 1
    second = [capacity - allocated for capacity, allocated in zip(plan, first)]
    return first, second


def _scaled_population(
    population: int,
    baseline: PopulationBaseline,
) -> tuple[dict[str, list[int]], dict[str, list[list[int]]]]:
    flattened = [
        baseline.cohorts[sex][age]
        for sex in SEXES
        for age in range(AGE_COUNT)
    ]
    scaled = _largest_remainder(flattened, population)
    cohorts = {
        sex: scaled[index * AGE_COUNT:(index + 1) * AGE_COUNT]
        for index, sex in enumerate(SEXES)
    }
    buckets: dict[str, list[list[int]]] = {"male": [], "female": []}
    for sex in SEXES:
        for age in range(AGE_COUNT):
            source = baseline.birthday_buckets[sex][age]
            target = cohorts[sex][age]
            if target == 0:
                buckets[sex].append([0] * 12)
            else:
                weights = [float(value) for value in source]
                if sum(weights) == 0:
                    weights = [1.0] * 12
                buckets[sex].append(_largest_remainder(weights, target))
    return cohorts, buckets


def _scaled_targets(
    population: int,
    baseline: PopulationBaseline,
) -> dict[str, int]:
    anchor_population = baseline.calibration["total_population"]
    return {
        key: round(value * population / anchor_population)
        for key, value in baseline.first_cycle_targets.items()
    }


def _new_cycle(
    start_date: date,
    targets: dict[str, int],
    *,
    base_seed: int,
    index: int,
    tfr: float,
    starting_population: int,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    plans = {
        key: build_balanced_plan(
            target,
            start_date,
            base_seed=base_seed,
            stream_name=f"cycle:{index}:{key}",
        )
        for key, target in targets.items()
    }
    male_births = round(targets["births"] * 105 / 205)
    births_male, births_female = _split_plan_by_capacity(
        plans["births"],
        male_births,
        base_seed=base_seed,
        start_date=start_date,
        stream_name=f"cycle:{index}:birth_sex",
    )
    plans["births_male"] = births_male
    plans["births_female"] = births_female
    return {
        "index": index,
        "start_date": start_date.isoformat(),
        "end_date": (start_date + timedelta(days=PLAN_DAYS - 1)).isoformat(),
        "offset": 0,
        "starting_population": starting_population,
        "tfr": tfr,
        "parameters": copy.deepcopy(dict(parameters)),
        "targets": copy.deepcopy(targets),
        "plans": plans,
        "cumulative": {key: 0 for key in targets},
        "excess_deaths": 0,
    }


def initialize_population_state(
    anchor_date: date,
    population: int,
    baseline: PopulationBaseline,
    *,
    base_seed: int,
) -> dict[str, Any]:
    """Create a versioned integer cohort state from an existing population."""
    if (
        isinstance(population, bool)
        or not isinstance(population, int)
        or population <= 0
    ):
        raise PopulationDataError("state.population: expected a positive integer")
    if (
        anchor_date == baseline.anchor_date
        and population == baseline.calibration["total_population"]
    ):
        cohorts = copy.deepcopy(baseline.cohorts)
        buckets = copy.deepcopy(baseline.birthday_buckets)
    else:
        cohorts, buckets = _scaled_population(population, baseline)
    targets = _scaled_targets(population, baseline)
    cycle_start = anchor_date + timedelta(days=1)
    state = {
        "baseline_version": baseline.version,
        "base_seed": base_seed,
        "anchor_date": anchor_date.isoformat(),
        "initial_population": population,
        "current_population": population,
        "cohorts": cohorts,
        "birthday_buckets": buckets,
        "last_aging_month": f"{anchor_date.year:04d}-{anchor_date.month:02d}",
        "cycle": _new_cycle(
            cycle_start,
            targets,
            base_seed=base_seed,
            index=0,
            tfr=2.3,
            starting_population=population,
            parameters={
                "version": PARAMETER_VERSION,
                "elapsed_years": 0.0,
                "mortality_improvement_factor": 1.0,
                "returning_diaspora_decay_factor": 1.0,
                "migration_population_scale": 1.0,
            },
        ),
        "calendar_year": {
            "year": anchor_date.year,
            "partial_year": True,
            "births": 0,
            "baseline_deaths": 0,
            "excess_deaths": 0,
            "returning_diaspora": 0,
            "foreign_immigrants": 0,
            "emigrants": 0,
        },
        "excess_deaths_total": 0,
    }
    validate_population_state(state, population, baseline)
    return state


def validate_population_state(
    state: Any,
    expected_population: int,
    baseline: PopulationBaseline,
    *,
    path: str = "state.model_state.population",
    current_date: date | None = None,
) -> None:
    """Validate cohort, birthday bucket and cycle invariants."""
    if not isinstance(state, dict):
        _fail(path, "expected a dictionary")
    if state.get("baseline_version") != baseline.version:
        _fail(f"{path}.baseline_version", f"expected {baseline.version}")
    base_seed = state.get("base_seed")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int):
        _fail(f"{path}.base_seed", "expected an integer")
    anchor = _population_date(state.get("anchor_date"), f"{path}.anchor_date")
    initial_population = state.get("initial_population")
    if (
        isinstance(initial_population, bool)
        or not isinstance(initial_population, int)
        or initial_population <= 0
    ):
        _fail(f"{path}.initial_population", "expected a positive integer")
    total_excess_deaths = state.get("excess_deaths_total")
    if (
        isinstance(total_excess_deaths, bool)
        or not isinstance(total_excess_deaths, int)
        or total_excess_deaths < 0
    ):
        _fail(
            f"{path}.excess_deaths_total",
            "expected a non-negative integer",
        )
    last_aging_month = state.get("last_aging_month")
    if not isinstance(last_aging_month, str):
        _fail(f"{path}.last_aging_month", "expected YYYY-MM")
    try:
        aging_month = date.fromisoformat(f"{last_aging_month}-01")
    except ValueError:
        _fail(f"{path}.last_aging_month", "expected YYYY-MM")
    if aging_month.strftime("%Y-%m") != last_aging_month:
        _fail(f"{path}.last_aging_month", "expected YYYY-MM")
    if current_date is not None:
        if current_date < anchor:
            _fail(f"{path}.anchor_date", "cannot be after state date")
        if last_aging_month != current_date.strftime("%Y-%m"):
            _fail(
                f"{path}.last_aging_month",
                "does not match the state date month",
            )
    cohorts_raw = state.get("cohorts")
    buckets_raw = state.get("birthday_buckets")
    if not isinstance(cohorts_raw, dict):
        _fail(f"{path}.cohorts", "expected a dictionary")
    if not isinstance(buckets_raw, dict):
        _fail(f"{path}.birthday_buckets", "expected a dictionary")
    population_total = 0
    for sex in SEXES:
        cohorts = _integer_list(
            cohorts_raw.get(sex), AGE_COUNT, f"{path}.cohorts.{sex}"
        )
        sex_buckets = buckets_raw.get(sex)
        if not isinstance(sex_buckets, list) or len(sex_buckets) != AGE_COUNT:
            _fail(f"{path}.birthday_buckets.{sex}", "expected 101 age rows")
        for age, cohort in enumerate(cohorts):
            row = _integer_list(
                sex_buckets[age],
                12,
                f"{path}.birthday_buckets.{sex}[{age}]",
            )
            if sum(row) != cohort:
                _fail(
                    f"{path}.birthday_buckets.{sex}[{age}]",
                    "bucket sum does not match cohort",
                )
        population_total += sum(cohorts)
    if population_total != expected_population:
        _fail(path, "cohort total does not match state.population")
    if state.get("current_population") != expected_population:
        _fail(f"{path}.current_population", "does not match state.population")

    cycle = state.get("cycle")
    if not isinstance(cycle, dict):
        _fail(f"{path}.cycle", "expected a dictionary")
    try:
        start = date.fromisoformat(cycle.get("start_date", ""))
        end = date.fromisoformat(cycle.get("end_date", ""))
    except (TypeError, ValueError):
        _fail(f"{path}.cycle", "expected ISO cycle dates")
    if end != start + timedelta(days=PLAN_DAYS - 1):
        _fail(f"{path}.cycle.end_date", "cycle must contain 365 days")
    cycle_index = cycle.get("index")
    if (
        isinstance(cycle_index, bool)
        or not isinstance(cycle_index, int)
        or cycle_index < 0
    ):
        _fail(f"{path}.cycle.index", "expected a non-negative integer")
    expected_cycle_start = anchor + timedelta(
        days=1 + cycle_index * PLAN_DAYS
    )
    if start != expected_cycle_start:
        _fail(
            f"{path}.cycle.start_date",
            f"expected {expected_cycle_start}",
        )
    tfr = cycle.get("tfr")
    if (
        isinstance(tfr, bool)
        or not isinstance(tfr, (int, float))
        or not math.isfinite(float(tfr))
        or tfr <= 0
    ):
        _fail(f"{path}.cycle.tfr", "expected a positive finite number")
    parameters = cycle.get("parameters")
    if not isinstance(parameters, dict):
        _fail(f"{path}.cycle.parameters", "expected a dictionary")
    if parameters.get("version") != PARAMETER_VERSION:
        _fail(
            f"{path}.cycle.parameters.version",
            f"expected {PARAMETER_VERSION}",
        )
    for key in (
        "elapsed_years",
        "mortality_improvement_factor",
        "returning_diaspora_decay_factor",
        "migration_population_scale",
    ):
        value = parameters.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            _fail(
                f"{path}.cycle.parameters.{key}",
                "expected a finite non-negative number",
            )
    offset = cycle.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= PLAN_DAYS:
        _fail(f"{path}.cycle.offset", "expected an integer from 0 through 365")
    if current_date is not None:
        expected_current_date = start + timedelta(days=offset - 1)
        if current_date != expected_current_date:
            _fail(
                f"{path}.cycle.offset",
                f"expected state date {expected_current_date}",
            )
    targets = cycle.get("targets")
    plans = cycle.get("plans")
    cumulative = cycle.get("cumulative")
    if not isinstance(targets, dict) or not isinstance(plans, dict):
        _fail(f"{path}.cycle", "expected targets and plans dictionaries")
    if not isinstance(cumulative, dict):
        _fail(f"{path}.cycle.cumulative", "expected a dictionary")
    for key in baseline.first_cycle_targets:
        target = targets.get(key)
        if isinstance(target, bool) or not isinstance(target, int) or target < 0:
            _fail(f"{path}.cycle.targets.{key}", "expected a non-negative integer")
        plan = _integer_list(
            plans.get(key), PLAN_DAYS, f"{path}.cycle.plans.{key}"
        )
        if sum(plan) != target:
            _fail(f"{path}.cycle.plans.{key}", "plan does not match target")
        completed = cumulative.get(key)
        if (
            isinstance(completed, bool)
            or not isinstance(completed, int)
            or not 0 <= completed <= target
        ):
            _fail(
                f"{path}.cycle.cumulative.{key}",
                "expected a completed quota within target",
            )
        if completed != sum(plan[:offset]):
            _fail(
                f"{path}.cycle.cumulative.{key}",
                "does not match the completed plan days",
            )
    male_births = _integer_list(
        plans.get("births_male"), PLAN_DAYS, f"{path}.cycle.plans.births_male"
    )
    female_births = _integer_list(
        plans.get("births_female"),
        PLAN_DAYS,
        f"{path}.cycle.plans.births_female",
    )
    if [male + female for male, female in zip(male_births, female_births)] != plans["births"]:
        _fail(f"{path}.cycle.plans", "birth sex plans do not match total births")
    starting_population = cycle.get("starting_population")
    if (
        isinstance(starting_population, bool)
        or not isinstance(starting_population, int)
        or starting_population <= 0
    ):
        _fail(
            f"{path}.cycle.starting_population",
            "expected a positive integer",
        )
    excess_deaths = cycle.get("excess_deaths")
    if (
        isinstance(excess_deaths, bool)
        or not isinstance(excess_deaths, int)
        or excess_deaths < 0
    ):
        _fail(
            f"{path}.cycle.excess_deaths",
            "expected a non-negative integer",
        )
    accounted_population = (
        starting_population
        + cumulative["births"]
        - cumulative["baseline_deaths"]
        - excess_deaths
        + cumulative["returning_diaspora"]
        + cumulative["foreign_immigrants"]
        - cumulative["emigrants"]
    )
    if accounted_population != expected_population:
        _fail(
            f"{path}.cycle.starting_population",
            "cycle flows do not reconcile to current population",
        )
    if cycle_index == 0 and starting_population != initial_population:
        _fail(
            f"{path}.cycle.starting_population",
            "does not match initial population",
        )
    if excess_deaths > total_excess_deaths:
        _fail(
            f"{path}.cycle.excess_deaths",
            "cannot exceed total excess deaths",
        )

    calendar_year = state.get("calendar_year")
    if not isinstance(calendar_year, dict):
        _fail(f"{path}.calendar_year", "expected a dictionary")
    calendar_value = calendar_year.get("year")
    if (
        isinstance(calendar_value, bool)
        or not isinstance(calendar_value, int)
    ):
        _fail(f"{path}.calendar_year.year", "expected an integer")
    if current_date is not None and calendar_value != current_date.year:
        _fail(
            f"{path}.calendar_year.year",
            "does not match state date year",
        )
    partial_year = calendar_year.get("partial_year")
    if not isinstance(partial_year, bool):
        _fail(f"{path}.calendar_year.partial_year", "expected a boolean")
    if current_date is not None and partial_year != (
        current_date.year == anchor.year
    ):
        _fail(
            f"{path}.calendar_year.partial_year",
            "does not match the population anchor year",
        )
    for key in (
        "births",
        "baseline_deaths",
        "excess_deaths",
        "returning_diaspora",
        "foreign_immigrants",
        "emigrants",
    ):
        value = calendar_year.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(
                f"{path}.calendar_year.{key}",
                "expected a non-negative integer",
            )
    if calendar_year["excess_deaths"] > total_excess_deaths:
        _fail(
            f"{path}.calendar_year.excess_deaths",
            "cannot exceed total excess deaths",
        )


def age_population(state: Mapping[str, Any], d: date) -> dict[str, Any]:
    """Advance the current month's birthday buckets exactly once."""
    aged = copy.deepcopy(dict(state))
    month_key = f"{d.year:04d}-{d.month:02d}"
    if aged.get("last_aging_month") == month_key:
        return aged
    month_index = d.month - 1
    cohorts = aged["cohorts"]
    buckets = aged["birthday_buckets"]
    for sex in SEXES:
        for age in range(99, -1, -1):
            count = buckets[sex][age][month_index]
            if count == 0:
                continue
            buckets[sex][age][month_index] -= count
            buckets[sex][age + 1][month_index] += count
            cohorts[sex][age] -= count
            cohorts[sex][age + 1] += count
    aged["last_aging_month"] = month_key
    return aged


def _weighted_index(weights: list[float], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        raise PopulationDataError("population allocation: no eligible population")
    threshold = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return len(weights) - 1


def _weighted_cell(
    weights: Mapping[str, list[float]],
    rng: random.Random,
    *,
    cohorts: Mapping[str, list[int]] | None = None,
    mortality_rates: Mapping[str, list[float]] | None = None,
) -> tuple[str, int]:
    cells: list[tuple[str, int]] = []
    cell_weights: list[float] = []
    for sex in SEXES:
        for age in range(AGE_COUNT):
            if cohorts is not None and cohorts[sex][age] <= 0:
                continue
            weight = weights[sex][age]
            if mortality_rates is not None and cohorts is not None:
                weight = cohorts[sex][age] * mortality_rates[sex][age]
            if weight <= 0:
                continue
            cells.append((sex, age))
            cell_weights.append(weight)
    return cells[_weighted_index(cell_weights, rng)]


def _remove_from_cell(
    state: dict[str, Any],
    sex: str,
    age: int,
    rng: random.Random,
) -> None:
    row = state["birthday_buckets"][sex][age]
    bucket = _weighted_index([float(value) for value in row], rng)
    row[bucket] -= 1
    state["cohorts"][sex][age] -= 1


def _remove_people(
    state: dict[str, Any],
    count: int,
    weights: Mapping[str, list[float]],
    rng: random.Random,
    *,
    mortality_rates: Mapping[str, list[float]] | None = None,
    path: str,
) -> None:
    if mortality_rates is None:
        preference_weights = weights
    else:
        preference_weights = {
            sex: [
                state["cohorts"][sex][age] * mortality_rates[sex][age]
                for age in range(AGE_COUNT)
            ]
            for sex in SEXES
        }

    def adjacent_available(preferred_sex: str, preferred_age: int):
        other_sex = "female" if preferred_sex == "male" else "male"
        for sex in (preferred_sex, other_sex):
            for distance in range(AGE_COUNT):
                candidates = (
                    (preferred_age,)
                    if distance == 0
                    else (preferred_age - distance, preferred_age + distance)
                )
                for age in candidates:
                    if (
                        0 <= age < AGE_COUNT
                        and state["cohorts"][sex][age] > 0
                    ):
                        return sex, age
        raise PopulationDataError(
            f"{path}: insufficient population capacity"
        )

    for _ in range(count):
        preferred_sex, preferred_age = _weighted_cell(
            preference_weights,
            rng,
        )
        sex, age = adjacent_available(preferred_sex, preferred_age)
        _remove_from_cell(state, sex, age, rng)


def _add_people(
    state: dict[str, Any],
    count: int,
    weights: Mapping[str, list[float]],
    rng: random.Random,
) -> None:
    for _ in range(count):
        sex, age = _weighted_cell(weights, rng)
        month = rng.randrange(12)
        state["birthday_buckets"][sex][age][month] += 1
        state["cohorts"][sex][age] += 1


def _all_age_weights() -> dict[str, list[float]]:
    return {sex: [1.0] * AGE_COUNT for sex in SEXES}


def _five_year_groups(cohorts: Mapping[str, list[int]]) -> list[dict[str, Any]]:
    groups = []
    for lower in range(0, 100, 5):
        upper = lower + 4
        male = sum(cohorts["male"][lower:upper + 1])
        female = sum(cohorts["female"][lower:upper + 1])
        groups.append({
            "age_group": f"{lower}-{upper}",
            "male": male,
            "female": female,
            "total": male + female,
        })
    male = cohorts["male"][100]
    female = cohorts["female"][100]
    groups.append({
        "age_group": "100+",
        "male": male,
        "female": female,
        "total": male + female,
    })
    return groups


def _public_demographics(
    state: Mapping[str, Any],
    flows: Mapping[str, int],
) -> dict[str, Any]:
    cohorts = state["cohorts"]
    male = sum(cohorts["male"])
    female = sum(cohorts["female"])
    totals = [
        cohorts["male"][age] + cohorts["female"][age]
        for age in range(AGE_COUNT)
    ]
    children = sum(totals[:15])
    working_age = sum(totals[15:65])
    elderly = sum(totals[65:])
    cycle = state["cycle"]
    targets = cycle["targets"]
    target_net = (
        targets["births"]
        - targets["baseline_deaths"]
        + targets["returning_diaspora"]
        + targets["foreign_immigrants"]
        - targets["emigrants"]
    )
    target_growth = target_net / cycle["starting_population"] * 100
    return {
        "population": male + female,
        "male_population": male,
        "female_population": female,
        "births_today": flows["births"],
        "deaths_all_causes_today": flows["deaths_all_causes"],
        "baseline_deaths_today": flows["baseline_deaths"],
        "notable_deaths_today": flows["notable_deaths"],
        "other_deaths_today": flows["non_notable_deaths"],
        "excess_deaths_today": flows["excess_deaths"],
        "returning_diaspora_today": flows["returning_diaspora"],
        "foreign_immigrants_today": flows["foreign_immigrants"],
        "emigrants_today": flows["emigrants"],
        "net_migration_today": (
            flows["returning_diaspora"]
            + flows["foreign_immigrants"]
            - flows["emigrants"]
        ),
        "natural_increase_today": flows["births"] - flows["deaths_all_causes"],
        "population_change_today": flows["population_change"],
        "median_age": round(median_age(cohorts), 1),
        "children_0_14": children,
        "working_age_15_64": working_age,
        "elderly_65_plus": elderly,
        "women_15_49": sum(cohorts["female"][15:50]),
        "dependency_ratio_pct": round((children + elderly) / working_age * 100, 2),
        "annualized_growth_target_pct": round(target_growth, 4),
        "baseline_period_end": cycle["end_date"],
        "partial_year": state["calendar_year"]["partial_year"],
        "five_year_age_groups": _five_year_groups(cohorts),
    }


def population_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return public demographic stocks with zero daily flows."""
    return _public_demographics(
        state,
        {
            "births": 0,
            "deaths_all_causes": 0,
            "baseline_deaths": 0,
            "notable_deaths": 0,
            "non_notable_deaths": 0,
            "excess_deaths": 0,
            "returning_diaspora": 0,
            "foreign_immigrants": 0,
            "emigrants": 0,
            "population_change": 0,
        },
    )


def _validated_notable_deaths(
    notable_deaths: Mapping[str, Any],
) -> dict[str, int]:
    if not isinstance(notable_deaths, Mapping):
        raise PopulationDataError("notable_deaths: expected a dictionary")
    result = {}
    for category in NOTABLE_DEATH_CATEGORIES:
        value = notable_deaths.get(category, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PopulationDataError(
                f"notable_deaths.{category}: expected a non-negative integer"
            )
        result[category] = value
    total = notable_deaths.get("total", sum(result.values()))
    if total != sum(result.values()):
        raise PopulationDataError(
            "notable_deaths.total: does not match notable categories"
        )
    return result


def _long_term_cycle_parameters(
    state: Mapping[str, Any],
    baseline: PopulationBaseline,
    start_date: date,
) -> tuple[dict[str, int], float, dict[str, Any]]:
    anchor = date.fromisoformat(state["anchor_date"])
    elapsed_years = max(0.0, (start_date - anchor).days / 365.2425)
    years_to_2035 = (date(2035, 8, 11) - baseline.anchor_date).days / 365.2425
    tfr = 2.3 - 0.3 * min(1.0, elapsed_years / years_to_2035)
    cohorts = state["cohorts"]
    population = state["current_population"]
    baseline_population = baseline.calibration["total_population"]
    fertility_exposure = sum(
        cohorts["female"][age] * baseline.fertility_weights[age - 15]
        for age in range(15, 50)
    )
    baseline_fertility_exposure = sum(
        baseline.cohorts["female"][age]
        * baseline.fertility_weights[age - 15]
        for age in range(15, 50)
    )
    births = round(
        baseline.first_cycle_targets["births"]
        * fertility_exposure / baseline_fertility_exposure
        * tfr / 2.3
    )
    current_mortality_mass = sum(
        cohorts[sex][age] * baseline.mortality_rates[sex][age]
        for sex in SEXES
        for age in range(AGE_COUNT)
    )
    baseline_mortality_mass = sum(
        baseline.cohorts[sex][age] * baseline.mortality_rates[sex][age]
        for sex in SEXES
        for age in range(AGE_COUNT)
    )
    mortality_improvement = 0.997 ** elapsed_years
    deaths = round(
        baseline.first_cycle_targets["baseline_deaths"]
        * current_mortality_mass / baseline_mortality_mass
        * mortality_improvement
    )
    scale = (population / baseline_population) ** 0.25
    returning_decay = max(0.45, math.exp(-0.12 * elapsed_years))
    targets = {
        "births": max(0, births),
        "baseline_deaths": max(0, deaths),
        "returning_diaspora": round(
            baseline.first_cycle_targets["returning_diaspora"]
            * returning_decay
        ),
        "foreign_immigrants": round(
            baseline.first_cycle_targets["foreign_immigrants"] * scale
        ),
        "emigrants": round(
            baseline.first_cycle_targets["emigrants"] * scale
        ),
    }
    parameters = {
        "version": PARAMETER_VERSION,
        "elapsed_years": elapsed_years,
        "mortality_improvement_factor": mortality_improvement,
        "returning_diaspora_decay_factor": returning_decay,
        "migration_population_scale": scale,
    }
    return targets, tfr, parameters


def _roll_cycle_if_needed(
    state: dict[str, Any],
    baseline: PopulationBaseline,
    d: date,
) -> None:
    cycle = state["cycle"]
    if cycle["offset"] < PLAN_DAYS:
        return
    expected = date.fromisoformat(cycle["end_date"]) + timedelta(days=1)
    if d != expected:
        raise PopulationDataError(
            f"state.model_state.population.cycle.offset: expected {expected}"
        )
    targets, tfr, parameters = _long_term_cycle_parameters(
        state, baseline, d
    )
    state["cycle"] = _new_cycle(
        d,
        targets,
        base_seed=state["base_seed"],
        index=cycle["index"] + 1,
        tfr=tfr,
        starting_population=state["current_population"],
        parameters=parameters,
    )


def population_step(
    d: date,
    previous_state: Mapping[str, Any],
    notable_deaths: Mapping[str, Any],
    baseline: PopulationBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int], list[dict]]:
    """Advance births, deaths, migration and age-sex population one day."""
    next_state = age_population(previous_state, d)
    _roll_cycle_if_needed(next_state, baseline, d)
    cycle = next_state["cycle"]
    offset = cycle["offset"]
    expected_date = date.fromisoformat(cycle["start_date"]) + timedelta(days=offset)
    if d != expected_date:
        raise PopulationDataError(
            f"state.model_state.population.cycle.offset: expected {expected_date}"
        )
    if next_state["calendar_year"]["year"] != d.year:
        next_state["calendar_year"] = {
            "year": d.year,
            "partial_year": False,
            "births": 0,
            "baseline_deaths": 0,
            "excess_deaths": 0,
            "returning_diaspora": 0,
            "foreign_immigrants": 0,
            "emigrants": 0,
        }

    plans = cycle["plans"]
    births = plans["births"][offset]
    male_births = plans["births_male"][offset]
    female_births = plans["births_female"][offset]
    current_month = d.month - 1
    next_state["cohorts"]["male"][0] += male_births
    next_state["cohorts"]["female"][0] += female_births
    next_state["birthday_buckets"]["male"][0][current_month] += male_births
    next_state["birthday_buckets"]["female"][0][current_month] += female_births

    notable = _validated_notable_deaths(notable_deaths)
    notable_total = sum(notable.values())
    for category, count in notable.items():
        if count:
            _remove_people(
                next_state,
                count,
                baseline.notable_death_weights[category],
                rng_factory(f"death:notable:{category}"),
                path=f"state.deaths_today.{category}",
            )
    baseline_deaths = plans["baseline_deaths"][offset]
    non_notable = max(0, baseline_deaths - notable_total)
    excess_deaths = max(0, notable_total - baseline_deaths)
    if non_notable:
        _remove_people(
            next_state,
            non_notable,
            _all_age_weights(),
            rng_factory("death:non_notable"),
            mortality_rates=baseline.mortality_rates,
            path="state.demographics.other_deaths_today",
        )
    all_cause_deaths = notable_total + non_notable

    returning = plans["returning_diaspora"][offset]
    foreign = plans["foreign_immigrants"][offset]
    emigrants = plans["emigrants"][offset]
    _add_people(
        next_state,
        returning,
        baseline.migration_weights["returning_diaspora"],
        rng_factory("migration:returning_diaspora"),
    )
    _add_people(
        next_state,
        foreign,
        baseline.migration_weights["foreign_immigrants"],
        rng_factory("migration:foreign_immigrants"),
    )
    _remove_people(
        next_state,
        emigrants,
        baseline.migration_weights["emigrants"],
        rng_factory("migration:emigrants"),
        path="state.demographics.emigrants_today",
    )

    population_change = births - all_cause_deaths + returning + foreign - emigrants
    next_population = (
        sum(next_state["cohorts"]["male"])
        + sum(next_state["cohorts"]["female"])
    )
    if next_population != next_state["current_population"] + population_change:
        raise PopulationDataError("population accounting identity failed")
    next_state["current_population"] = next_population
    for key, value in (
        ("births", births),
        ("baseline_deaths", baseline_deaths),
        ("returning_diaspora", returning),
        ("foreign_immigrants", foreign),
        ("emigrants", emigrants),
    ):
        cycle["cumulative"][key] += value
        next_state["calendar_year"][key] += value
    cycle["excess_deaths"] += excess_deaths
    cycle["offset"] += 1
    next_state["calendar_year"]["excess_deaths"] += excess_deaths
    next_state["excess_deaths_total"] += excess_deaths

    reconciled_deaths = {
        "total": all_cause_deaths,
        "notable_total": notable_total,
        "non_notable": non_notable,
        "excess": excess_deaths,
        **notable,
    }
    flows = {
        "births": births,
        "deaths_all_causes": all_cause_deaths,
        "baseline_deaths": baseline_deaths,
        "notable_deaths": notable_total,
        "non_notable_deaths": non_notable,
        "excess_deaths": excess_deaths,
        "returning_diaspora": returning,
        "foreign_immigrants": foreign,
        "emigrants": emigrants,
        "population_change": population_change,
    }
    public = _public_demographics(next_state, flows)
    validate_population_state(next_state, next_population, baseline)
    return public, next_state, reconciled_deaths, []
