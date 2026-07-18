"""Human dengue compartments, immunity histories, and integer allocation."""

from __future__ import annotations

import copy
import math
import random
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from dengue_model import (
    AGE_GROUPS,
    PROVINCES,
    SEROTYPES,
    DengueBaseline,
    DengueDataError,
)


AGE_BOUNDS = {
    "0-4": (0, 4),
    "5-14": (5, 14),
    "15-29": (15, 29),
    "30-59": (30, 59),
    "60+": (60, 100),
}
MASK_KEYS = tuple(format(mask, "04b") for mask in range(16))


def national_age_totals(
    population_state: Mapping[str, Any],
) -> dict[str, int]:
    """Aggregate national single-age, sex-specific cohorts to dengue ages."""
    cohorts = population_state.get("cohorts")
    if not isinstance(cohorts, Mapping):
        raise DengueDataError(
            "state.model_state.population.cohorts: expected a dictionary"
        )
    for sex in ("male", "female"):
        values = cohorts.get(sex)
        if not isinstance(values, list) or len(values) != 101:
            raise DengueDataError(
                f"state.model_state.population.cohorts.{sex}: "
                "expected 101 single-age values"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in values
        ):
            raise DengueDataError(
                f"state.model_state.population.cohorts.{sex}: "
                "expected non-negative integers"
            )
    return {
        label: sum(
            cohorts[sex][age]
            for sex in ("male", "female")
            for age in range(lower, upper + 1)
        )
        for label, (lower, upper) in AGE_BOUNDS.items()
    }


def _largest_remainder(
    total: int,
    weights: Sequence[float],
) -> list[int]:
    if total < 0 or not weights or any(weight < 0 for weight in weights):
        raise DengueDataError("allocation: invalid total or weights")
    weight_total = sum(weights)
    if weight_total <= 0:
        if total == 0:
            return [0] * len(weights)
        raise DengueDataError("allocation: positive total requires weight")
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


def _rounded_matrix(
    row_totals: Sequence[int],
    column_totals: Sequence[int],
) -> list[list[int]]:
    """Round an independence table while preserving both integer margins."""
    grand_total = sum(row_totals)
    if grand_total != sum(column_totals):
        raise DengueDataError("allocation: row and column totals differ")
    if grand_total == 0:
        return [[0] * len(column_totals) for _ in row_totals]

    raw = [
        [row * column / grand_total for column in column_totals]
        for row in row_totals
    ]
    result = [
        [math.floor(value) for value in row]
        for row in raw
    ]
    row_deficits = [
        expected - sum(row)
        for expected, row in zip(row_totals, result, strict=True)
    ]
    column_deficits = [
        expected - sum(result[row][column] for row in range(len(row_totals)))
        for column, expected in enumerate(column_totals)
    ]
    required = sum(row_deficits)
    if required == 0:
        return result

    row_count = len(row_totals)
    column_count = len(column_totals)
    source = 0
    first_row = 1
    first_column = first_row + row_count
    sink = first_column + column_count
    size = sink + 1
    capacity = [[0] * size for _ in range(size)]
    score: dict[tuple[int, int], float] = {}
    for row, deficit in enumerate(row_deficits):
        capacity[source][first_row + row] = deficit
    for column, deficit in enumerate(column_deficits):
        capacity[first_column + column][sink] = deficit
    for row in range(row_count):
        for column in range(column_count):
            fraction = raw[row][column] - result[row][column]
            if fraction > 1e-12:
                capacity[first_row + row][first_column + column] = 1
                score[(row, column)] = fraction

    adjacency = [set() for _ in range(size)]
    for start in range(size):
        for end in range(size):
            if capacity[start][end] > 0:
                adjacency[start].add(end)
                adjacency[end].add(start)
    for row in range(row_count):
        node = first_row + row
        ordered = sorted(
            adjacency[node],
            key=lambda other: (
                -score.get((row, other - first_column), -1.0),
                other,
            ),
        )
        adjacency[node] = ordered

    flow = [[0] * size for _ in range(size)]
    total_flow = 0
    while total_flow < required:
        parent = [-1] * size
        parent[source] = source
        queue = deque([source])
        while queue and parent[sink] == -1:
            node = queue.popleft()
            for target in adjacency[node]:
                if parent[target] == -1 and (
                    capacity[node][target] - flow[node][target] > 0
                ):
                    parent[target] = node
                    queue.append(target)
                    if target == sink:
                        break
        if parent[sink] == -1:
            raise DengueDataError("allocation: could not reconcile margins")
        node = sink
        while node != source:
            previous = parent[node]
            flow[previous][node] += 1
            flow[node][previous] -= 1
            node = previous
        total_flow += 1

    for row in range(row_count):
        for column in range(column_count):
            if flow[first_row + row][first_column + column] > 0:
                result[row][column] += 1
    return result


def allocate_province_ages(
    age_totals: Mapping[str, int],
    baseline: DengueBaseline,
) -> dict[str, dict[str, int]]:
    """Allocate national ages to provinces with both margins exact."""
    if tuple(age_totals) != AGE_GROUPS:
        raise DengueDataError(
            f"population.age_groups: expected ordered keys {AGE_GROUPS}"
        )
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for value in age_totals.values()
    ):
        raise DengueDataError(
            "population.age_groups: expected non-negative integers"
        )
    national_total = sum(age_totals.values())
    province_targets = _largest_remainder(
        national_total,
        [baseline.province_populations[key] for key in PROVINCES],
    )
    matrix = _rounded_matrix(
        province_targets,
        [age_totals[age] for age in AGE_GROUPS],
    )
    return {
        province: {
            age: matrix[province_index][age_index]
            for age_index, age in enumerate(AGE_GROUPS)
        }
        for province_index, province in enumerate(PROVINCES)
    }


def is_susceptible(mask: int, serotype_index: int) -> bool:
    """Return whether a lifetime-immunity mask permits this serotype."""
    if not 0 <= mask <= 15:
        raise DengueDataError("immunity.mask: expected an integer in [0, 15]")
    if not 0 <= serotype_index < len(SEROTYPES):
        raise DengueDataError("serotype_index: expected an integer in [0, 3]")
    return mask & (1 << serotype_index) == 0


def _mask_weights(age: str, baseline: DengueBaseline) -> list[float]:
    serotype_prior = baseline.raw["transmission"]["serotype_prior"]
    count_prior = baseline.raw["immunity"][
        "infection_count_given_ever"
    ][age]
    weights = [0.0] * 16
    for count in range(1, 5):
        candidates = [mask for mask in range(1, 16) if mask.bit_count() == count]
        candidate_weights = [
            math.prod(
                serotype_prior[SEROTYPES[index]]
                for index in range(4)
                if mask & (1 << index)
            )
            for mask in candidates
        ]
        subtotal = sum(candidate_weights)
        if subtotal == 0:
            continue
        for mask, candidate_weight in zip(
            candidates, candidate_weights, strict=True
        ):
            weights[mask] = (
                count_prior[str(count)] * candidate_weight / subtotal
            )
    return weights


def initialize_human_state(
    province_ages: Mapping[str, Mapping[str, int]],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> dict[str, dict[str, Any]]:
    """Create integer immunity stocks for every province and age."""
    del rng_factory  # Initial integer rounding is stable and seed independent.
    result: dict[str, dict[str, Any]] = {}
    for province in PROVINCES:
        ages = province_ages.get(province)
        if not isinstance(ages, Mapping):
            raise DengueDataError(
                f"province_ages.{province}: expected a dictionary"
            )
        susceptible: dict[str, dict[str, int]] = {}
        for age in AGE_GROUPS:
            total = ages.get(age)
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise DengueDataError(
                    f"province_ages.{province}.{age}: "
                    "expected a non-negative integer"
                )
            ever_probability = min(
                0.95,
                baseline.raw["immunity"]["ever_infected_prior"][age]
                * baseline.raw["immunity"]["province_multipliers"][province],
            )
            never, ever = _largest_remainder(
                total, [1.0 - ever_probability, ever_probability]
            )
            immune_counts = _largest_remainder(
                ever, _mask_weights(age, baseline)[1:]
            )
            susceptible[age] = {
                "0000": never,
                **{
                    format(mask, "04b"): immune_counts[mask - 1]
                    for mask in range(1, 16)
                },
            }
        result[province] = {
            "population_by_age": {
                age: int(ages[age]) for age in AGE_GROUPS
            },
            "susceptible": susceptible,
            "exposed": [],
            "infectious": [],
            "cross_protected": [
                []
                for _ in range(
                    baseline.raw["immunity"]["cross_protection_days"]
                )
            ],
            "cross_immunity_cursor": 0,
        }
    return result


def _draw_poisson(mean: float, rng: random.Random) -> int:
    threshold = math.exp(-mean)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def _draw_binomial(
    count: int,
    probability: float,
    rng: random.Random,
) -> int:
    if count < 0 or not 0.0 <= probability <= 1.0:
        raise DengueDataError("binomial: invalid count or probability")
    if count == 0 or probability == 0.0:
        return 0
    if probability == 1.0:
        return count
    if count <= 256:
        return sum(rng.random() < probability for _ in range(count))
    mean = count * probability
    inverse_mean = count * (1.0 - probability)
    if mean < 30.0:
        return min(count, _draw_poisson(mean, rng))
    if inverse_mean < 30.0:
        return count - min(count, _draw_poisson(inverse_mean, rng))
    deviation = math.sqrt(count * probability * (1.0 - probability))
    return min(count, max(0, round(rng.gauss(mean, deviation))))


def _draw_multinomial(
    count: int,
    weights: Sequence[float],
    rng: random.Random,
) -> list[int]:
    if count == 0:
        return [0] * len(weights)
    remaining_count = count
    remaining_weight = sum(weights)
    result: list[int] = []
    for weight in weights[:-1]:
        probability = 0.0 if remaining_weight <= 0 else weight / remaining_weight
        drawn = _draw_binomial(remaining_count, probability, rng)
        result.append(drawn)
        remaining_count -= drawn
        remaining_weight -= weight
    result.append(remaining_count)
    return result


def _duration_counts(
    count: int,
    distribution: Mapping[str, float],
    rng: random.Random,
) -> list[tuple[int, int]]:
    keys = list(distribution)
    allocated = _draw_multinomial(
        count, [distribution[key] for key in keys], rng
    )
    return [
        (int(key), value)
        for key, value in zip(keys, allocated, strict=True)
        if value
    ]


def _merged_cohorts(cohorts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], int] = {}
    for cohort in cohorts:
        count = cohort.get("count")
        if not isinstance(count, int) or count < 0:
            raise DengueDataError("human.cohort.count: expected non-negative integer")
        if count == 0:
            continue
        key = (
            cohort["age_group"],
            cohort["prior_mask"],
            cohort["serotype"],
            cohort["days_remaining"],
        )
        merged[key] = merged.get(key, 0) + count
    return [
        {
            "age_group": key[0],
            "prior_mask": key[1],
            "serotype": key[2],
            "days_remaining": key[3],
            "count": count,
        }
        for key, count in sorted(merged.items())
    ]


def total_humans(human_state: Mapping[str, Mapping[str, Any]]) -> int:
    """Return every mutually exclusive human stock exactly once."""
    total = 0
    for province in human_state.values():
        total += sum(
            count
            for masks in province["susceptible"].values()
            for count in masks.values()
        )
        total += sum(cohort["count"] for cohort in province["exposed"])
        total += sum(cohort["count"] for cohort in province["infectious"])
        total += sum(
            cohort["count"]
            for bucket in province["cross_protected"]
            for cohort in bucket
        )
    return total


def _add_susceptible(
    province: dict[str, Any],
    age: str,
    mask: int,
    count: int,
) -> None:
    key = format(mask, "04b")
    masks = province["susceptible"].setdefault(age, {})
    masks[key] = masks.get(key, 0) + count


def advance_human_state(
    previous: Mapping[str, Mapping[str, Any]],
    force: Mapping[str, Mapping[str, float]],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Advance human E/I/R states one day without mutating the input."""
    next_state = copy.deepcopy(dict(previous))
    starting_total = total_humans(previous)
    flows: dict[str, Any] = {
        "new_infections": 0,
        "exposed_to_infectious": 0,
        "recoveries": 0,
        "cross_protection_expired": 0,
        "infections_by_cohort": [],
        "new_infections_by_province": {
            province: 0 for province in previous
        },
        "new_infections_by_serotype": {
            serotype: 0 for serotype in SEROTYPES
        },
        "exposed_to_infectious_by_serotype": {
            serotype: 0 for serotype in SEROTYPES
        },
        "recoveries_by_serotype": {
            serotype: 0 for serotype in SEROTYPES
        },
    }
    incubation = baseline.raw["transmission"]["human_incubation_days"]
    infectious_duration = baseline.raw["transmission"]["infectious_days"]

    for province_name in previous:
        province = next_state[province_name]
        ring = province["cross_protected"]
        cursor = province["cross_immunity_cursor"]
        if not isinstance(cursor, int) or not 0 <= cursor < len(ring):
            raise DengueDataError(
                f"human.{province_name}.cross_immunity_cursor: out of range"
            )

        expiring = ring[cursor]
        for cohort in expiring:
            _add_susceptible(
                province,
                cohort["age_group"],
                cohort["new_mask"],
                cohort["count"],
            )
            flows["cross_protection_expired"] += cohort["count"]
        ring[cursor] = []

        remaining_infectious: list[dict[str, Any]] = []
        for cohort in province["infectious"]:
            if cohort["days_remaining"] > 1:
                remaining_infectious.append({
                    **cohort,
                    "days_remaining": cohort["days_remaining"] - 1,
                })
                continue
            serotype_index = SEROTYPES.index(cohort["serotype"])
            new_mask = cohort["prior_mask"] | (1 << serotype_index)
            ring[cursor].append({
                "age_group": cohort["age_group"],
                "new_mask": new_mask,
                "count": cohort["count"],
            })
            flows["recoveries"] += cohort["count"]
            flows["recoveries_by_serotype"][cohort["serotype"]] += (
                cohort["count"]
            )
        province["infectious"] = _merged_cohorts(remaining_infectious)

        remaining_exposed: list[dict[str, Any]] = []
        newly_infectious: list[dict[str, Any]] = []
        for cohort in province["exposed"]:
            if cohort["days_remaining"] > 1:
                remaining_exposed.append({
                    **cohort,
                    "days_remaining": cohort["days_remaining"] - 1,
                })
                continue
            rng = rng_factory(
                f"infectious-duration:{province_name}:"
                f"{cohort['age_group']}:{cohort['prior_mask']}:"
                f"{cohort['serotype']}"
            )
            for duration, count in _duration_counts(
                cohort["count"], infectious_duration, rng
            ):
                newly_infectious.append({
                    "age_group": cohort["age_group"],
                    "prior_mask": cohort["prior_mask"],
                    "serotype": cohort["serotype"],
                    "days_remaining": duration,
                    "count": count,
                })
            flows["exposed_to_infectious"] += cohort["count"]
            flows["exposed_to_infectious_by_serotype"][
                cohort["serotype"]
            ] += cohort["count"]
        province["exposed"] = _merged_cohorts(remaining_exposed)
        province["infectious"] = _merged_cohorts(
            province["infectious"] + newly_infectious
        )

        new_exposed: list[dict[str, Any]] = []
        province_force = force.get(province_name, {})
        for age in AGE_GROUPS:
            masks = province["susceptible"].get(age, {})
            for mask_key in sorted(masks):
                available = masks[mask_key]
                if available <= 0:
                    continue
                mask = int(mask_key, 2)
                hazards: list[float] = []
                for serotype_index, serotype in enumerate(SEROTYPES):
                    raw_hazard = province_force.get(serotype, 0.0)
                    if (
                        isinstance(raw_hazard, bool)
                        or not isinstance(raw_hazard, (int, float))
                        or not math.isfinite(float(raw_hazard))
                        or raw_hazard < 0
                    ):
                        raise DengueDataError(
                            f"force.{province_name}.{serotype}: "
                            "expected a finite non-negative number"
                        )
                    hazards.append(
                        float(raw_hazard)
                        if is_susceptible(mask, serotype_index)
                        else 0.0
                    )
                total_hazard = sum(hazards)
                if total_hazard <= 0:
                    continue
                probability = 1.0 - math.exp(-total_hazard)
                infection_rng = rng_factory(
                    f"infection:{province_name}:{age}:{mask_key}"
                )
                infected = _draw_binomial(
                    available, probability, infection_rng
                )
                if infected == 0:
                    continue
                masks[mask_key] -= infected
                by_serotype = _draw_multinomial(
                    infected, hazards, infection_rng
                )
                for serotype_index, serotype_count in enumerate(by_serotype):
                    if serotype_count == 0:
                        continue
                    serotype = SEROTYPES[serotype_index]
                    duration_rng = rng_factory(
                        f"incubation:{province_name}:{age}:"
                        f"{mask_key}:{serotype}"
                    )
                    for duration, count in _duration_counts(
                        serotype_count, incubation, duration_rng
                    ):
                        new_exposed.append({
                            "age_group": age,
                            "prior_mask": mask,
                            "serotype": serotype,
                            "days_remaining": duration,
                            "count": count,
                        })
                    flows["infections_by_cohort"].append({
                        "province": province_name,
                        "age_group": age,
                        "prior_mask": mask,
                        "serotype": serotype,
                        "count": serotype_count,
                    })
                    flows["new_infections_by_serotype"][serotype] += (
                        serotype_count
                    )
                flows["new_infections"] += infected
                flows["new_infections_by_province"][province_name] += infected
        province["exposed"] = _merged_cohorts(
            province["exposed"] + new_exposed
        )
        province["cross_immunity_cursor"] = (cursor + 1) % len(ring)

    if total_humans(next_state) != starting_total:
        raise DengueDataError("human: population conservation failed")
    return next_state, flows


def derive_province_weather(
    weather: Mapping[str, Any],
    baseline: DengueBaseline,
) -> dict[str, dict[str, float | str]]:
    """Map the five-city weather output to seven dengue provinces."""
    result: dict[str, dict[str, float | str]] = {}
    mapping = baseline.raw["weather_mapping"]
    for province in PROVINCES:
        rule = mapping[province]
        source_key = rule["source"]
        source = weather.get(source_key)
        quality = "city"
        if not isinstance(source, Mapping):
            source = weather
            quality = "national_fallback"
        values: dict[str, float] = {}
        for key in ("temp_high", "temp_low", "humidity", "rainfall_mm"):
            raw_value = source.get(key)
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or not math.isfinite(float(raw_value))
            ):
                raise DengueDataError(
                    f"weather.{source_key}.{key}: expected a finite number"
                )
            values[key] = float(raw_value)
        rainfall_14d = weather.get(
            "rainfall_14d_mm", values["rainfall_mm"] * 7.0
        )
        soil_moisture = weather.get("soil_moisture_index", 0.5)
        for key, value in (
            ("rainfall_14d_mm", rainfall_14d),
            ("soil_moisture_index", soil_moisture),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise DengueDataError(
                    f"weather.{key}: expected a finite number"
                )
        temperature_offset = float(rule["temp_offset_c"])
        rain_scale = float(rule["rain_scale"])
        humidity = min(
            100.0,
            max(0.0, values["humidity"] + float(rule["humidity_offset_pct"])),
        )
        result[province] = {
            "temp_high_c": values["temp_high"] + temperature_offset,
            "temp_low_c": values["temp_low"] + temperature_offset,
            "temp_mean_c": (
                (values["temp_high"] + values["temp_low"]) / 2.0
                + temperature_offset
            ),
            "humidity_pct": humidity,
            "rainfall_mm": max(0.0, values["rainfall_mm"] * rain_scale),
            "rainfall_14d_mm": max(0.0, float(rainfall_14d) * rain_scale),
            "soil_moisture_index": min(1.0, max(0.0, float(soil_moisture))),
            "data_quality": quality,
        }
    return result


def vector_suitability(
    temp_mean_c: float,
    humidity_pct: float,
    rainfall_14d_mm: float,
) -> float:
    """Return a bounded environmental mosquito suitability index."""
    values = (temp_mean_c, humidity_pct, rainfall_14d_mm)
    if any(not math.isfinite(float(value)) for value in values):
        raise DengueDataError("vector.weather: expected finite values")
    temperature = max(0.0, 1.0 - ((temp_mean_c - 28.0) / 12.0) ** 2)
    moisture = min(
        1.5,
        max(0.2, 0.45 + humidity_pct / 200.0 + rainfall_14d_mm / 350.0),
    )
    return min(1.5, max(0.0, temperature * moisture))


def extrinsic_incubation_days(temp_mean_c: float) -> int:
    """Return temperature-dependent mosquito EIP bounded to 5–14 days."""
    if not math.isfinite(float(temp_mean_c)):
        raise DengueDataError("vector.temp_mean_c: expected a finite number")
    return min(14, max(5, round(14.0 - (temp_mean_c - 20.0) * 0.75)))


def _zero_serotypes() -> dict[str, float]:
    return {serotype: 0.0 for serotype in SEROTYPES}


def initialize_vector_state(
    baseline: DengueBaseline,
) -> dict[str, dict[str, Any]]:
    """Create normalized mosquito SEI stocks for every province."""
    adult_total = float(baseline.raw["vector"]["initial_adult_index"])
    infectious_total = adult_total * 0.004
    serotype_prior = baseline.raw["transmission"]["serotype_prior"]
    maximum_eip = baseline.raw["transmission"]["vector_eip_days"]["maximum"]
    rainfall_days = baseline.raw["vector"]["rainfall_lag_days"]
    return {
        province: {
            "larval_pressure": float(
                baseline.raw["vector"]["initial_larval_pressure"]
            ),
            "adult_total": adult_total,
            "susceptible": adult_total - infectious_total,
            "exposed": {
                serotype: [0.0] * maximum_eip
                for serotype in SEROTYPES
            },
            "infectious": {
                serotype: infectious_total * serotype_prior[serotype]
                for serotype in SEROTYPES
            },
            "rainfall_queue": [0.0] * rainfall_days,
        }
        for province in PROVINCES
    }


def _residual_competence(intervention: Mapping[str, Any]) -> float:
    affected = 1.0
    for key in ("pilot_share", "community_coverage", "field_effectiveness"):
        value = intervention.get(key, 0.0)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0
        ):
            raise DengueDataError(
                f"interventions.{key}: expected a probability"
            )
        affected *= float(value)
    return 1.0 - affected


def vector_competence_by_province(
    baseline: DengueBaseline,
) -> dict[str, float]:
    """Return province-effective competence after limited wMar-1 pilots."""
    empty = {
        "pilot_share": 0.0,
        "community_coverage": 0.0,
        "field_effectiveness": 0.0,
    }
    return {
        province: _residual_competence(
            baseline.raw["wmar1"].get(province, empty)
        )
        for province in PROVINCES
    }


def infectiousness_by_province(
    human_state: Mapping[str, Mapping[str, Any]],
    baseline: DengueBaseline,
) -> dict[str, dict[str, float]]:
    """Return infectious-human fractions by province and serotype."""
    del baseline
    result: dict[str, dict[str, float]] = {}
    for province, state in human_state.items():
        population = sum(state["population_by_age"].values())
        by_serotype = _zero_serotypes()
        for cohort in state["infectious"]:
            by_serotype[cohort["serotype"]] += cohort["count"]
        result[province] = {
            serotype: 0.0 if population == 0 else count / population
            for serotype, count in by_serotype.items()
        }
    return result


def advance_vector_state(
    previous: Mapping[str, Mapping[str, Any]],
    province_weather: Mapping[str, Mapping[str, Any]],
    human_infectiousness: Mapping[str, Mapping[str, float]],
    interventions: Mapping[str, Mapping[str, Any]],
    baseline: DengueBaseline,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Advance normalized mosquito SEI stocks with delayed rainfall."""
    next_state = copy.deepcopy(dict(previous))
    flows: dict[str, Any] = {
        "local_force": {},
        "new_vector_infections": {},
        "suitability": {},
    }
    vector_parameters = baseline.raw["vector"]
    transmission = baseline.raw["transmission"]
    mean_lifetime = float(vector_parameters["adult_mean_lifetime_days"])
    flush_threshold = float(vector_parameters["flush_threshold_mm"])
    maximum_eip = int(transmission["vector_eip_days"]["maximum"])

    for province in previous:
        state = next_state[province]
        weather = province_weather.get(province)
        if not isinstance(weather, Mapping):
            raise DengueDataError(
                f"province_weather.{province}: expected a dictionary"
            )
        suitability = vector_suitability(
            float(weather["temp_mean_c"]),
            float(weather["humidity_pct"]),
            float(weather["rainfall_14d_mm"]),
        )
        current_rain = float(weather["rainfall_mm"])
        queue = list(state["rainfall_queue"])
        if len(queue) != vector_parameters["rainfall_lag_days"]:
            raise DengueDataError(
                f"vector.{province}.rainfall_queue: unexpected length"
            )
        prior_rainfall = sum(queue)
        delayed_rain = queue.pop(0)
        queue.append(current_rain)
        state["rainfall_queue"] = queue

        previous_larvae = float(state["larval_pressure"])
        rain_gain = min(1.25, current_rain / 40.0)
        flushing = (
            min(0.65, (current_rain - flush_threshold) / flush_threshold)
            if current_rain > flush_threshold
            else 0.0
        )
        state["larval_pressure"] = max(
            0.02,
            previous_larvae * (0.88 - flushing)
            + suitability * (0.06 + 0.16 * rain_gain),
        )

        mortality = min(
            0.22,
            max(
                0.04,
                (1.0 / mean_lifetime)
                * (1.0 + abs(float(weather["temp_mean_c"]) - 28.0) / 18.0),
            ),
        )
        survival = 1.0 - mortality
        maturation_suitability = vector_suitability(
            float(weather["temp_mean_c"]),
            float(weather["humidity_pct"]),
            prior_rainfall,
        )
        delayed_emergence = previous_larvae * maturation_suitability * (
            0.055 + min(0.10, delayed_rain / 400.0)
        )

        susceptible = float(state["susceptible"]) * survival + delayed_emergence
        infectious = {
            serotype: float(state["infectious"][serotype]) * survival
            for serotype in SEROTYPES
        }
        exposed: dict[str, list[float]] = {}
        for serotype in SEROTYPES:
            old_queue = list(state["exposed"][serotype])
            if len(old_queue) != maximum_eip:
                raise DengueDataError(
                    f"vector.{province}.exposed.{serotype}: unexpected length"
                )
            mature = old_queue.pop(0) * survival
            exposed[serotype] = [value * survival for value in old_queue] + [0.0]
            infectious[serotype] += mature

        human_force = human_infectiousness.get(province, {})
        hazards = [
            max(0.0, float(human_force.get(serotype, 0.0)))
            for serotype in SEROTYPES
        ]
        total_hazard = (
            transmission["base_biting_rate"]
            * transmission["human_to_mosquito"]
            * sum(hazards)
        )
        newly_infected = susceptible * (1.0 - math.exp(-total_hazard))
        if newly_infected > 0 and sum(hazards) > 0:
            susceptible -= newly_infected
            eip_days = extrinsic_incubation_days(
                float(weather["temp_mean_c"])
            )
            insertion_index = min(maximum_eip - 1, eip_days - 1)
            for serotype, hazard in zip(SEROTYPES, hazards, strict=True):
                exposed[serotype][insertion_index] += (
                    newly_infected * hazard / sum(hazards)
                )

        state["susceptible"] = susceptible
        state["exposed"] = exposed
        state["infectious"] = infectious
        adult_total = (
            susceptible
            + sum(infectious.values())
            + sum(sum(values) for values in exposed.values())
        )
        state["adult_total"] = adult_total
        competence = _residual_competence(interventions.get(province, {}))
        local_force = {
            serotype: (
                0.0
                if adult_total <= 0
                else transmission["base_biting_rate"]
                * transmission["mosquito_to_human"]
                * infectious[serotype]
                / adult_total
                * competence
            )
            for serotype in SEROTYPES
        }
        all_values = [
            state["larval_pressure"],
            adult_total,
            susceptible,
            *infectious.values(),
            *(value for values in exposed.values() for value in values),
            *local_force.values(),
        ]
        if any(not math.isfinite(value) or value < 0 for value in all_values):
            raise DengueDataError(
                f"vector.{province}: expected finite non-negative stocks"
            )
        flows["local_force"][province] = local_force
        flows["new_vector_infections"][province] = newly_infected
        flows["suitability"][province] = suitability
    return next_state, flows


def mix_force_of_infection(
    local_force: Mapping[str, Mapping[str, float]],
    mobility: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    """Mix province infection pressure without moving population stocks."""
    result: dict[str, dict[str, float]] = {}
    for resident in PROVINCES:
        if resident not in mobility:
            raise DengueDataError(
                f"mobility.{resident}: expected a matrix row"
            )
        result[resident] = {}
        for serotype in SEROTYPES:
            value = sum(
                float(mobility[resident][source])
                * float(local_force[source][serotype])
                for source in PROVINCES
            )
            if not math.isfinite(value) or value < 0:
                raise DengueDataError(
                    f"force.{resident}.{serotype}: invalid mixed force"
                )
            result[resident][serotype] = value
    return result
