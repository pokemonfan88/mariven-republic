"""Clinical outcomes, delayed surveillance, releases, and dengue alerts."""

from __future__ import annotations

import copy
import math
import random
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

from dengue_dynamics import _draw_binomial, _draw_multinomial
from dengue_model import PROVINCES, DengueBaseline, DengueDataError


def severe_probability(
    age_group: str,
    prior_mask: int,
    baseline: DengueBaseline,
) -> float:
    """Return age- and infection-order-specific severe probability."""
    if age_group not in baseline.age_groups:
        raise DengueDataError(
            f"clinical.age_group: unknown age group {age_group}"
        )
    if not isinstance(prior_mask, int) or not 0 <= prior_mask <= 15:
        raise DengueDataError("clinical.prior_mask: expected an integer in [0, 15]")
    order = min(4, prior_mask.bit_count() + 1)
    clinical = baseline.raw["clinical"]
    probability = (
        clinical["severe_by_infection_order"][str(order)]
        * clinical["age_severe_multiplier"][age_group]
    )
    return min(1.0, max(0.0, probability))


def treated_fatality_probability(
    pressure: float,
    baseline: DengueBaseline,
) -> float:
    """Interpolate treated severe fatality smoothly above soft capacity."""
    if (
        isinstance(pressure, bool)
        or not isinstance(pressure, (int, float))
        or not math.isfinite(float(pressure))
        or pressure < 0
    ):
        raise DengueDataError(
            "clinical.healthcare_pressure: expected a finite non-negative number"
        )
    clinical = baseline.raw["clinical"]
    low = float(clinical["treated_severe_fatality"])
    high = float(clinical["overloaded_severe_fatality"])
    soft = float(clinical["soft_capacity_share"])
    overload = min(1.0, max(0.0, (float(pressure) - soft) / (1.0 - soft)))
    return low + (high - low) * overload * overload


def _validate_count(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DengueDataError(f"{path}: expected a non-negative integer")
    return value


def classify_clinical_outcomes(
    infection_flows: Mapping[str, Any],
    pressure: float,
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> dict[str, Any]:
    """Classify aggregate infection cohorts with a bounded probability tree."""
    totals: dict[str, Any] = {
        "infections": 0,
        "symptomatic": 0,
        "warning": 0,
        "severe": 0,
        "hospitalized": 0,
        "deaths": 0,
        "reported": 0,
        "sampled": 0,
        "confirmed": 0,
        "cohort_outcomes": [],
    }
    clinical = baseline.raw["clinical"]
    surveillance = baseline.raw["surveillance"]
    for index, cohort_value in enumerate(
        infection_flows.get("infections_by_cohort", [])
    ):
        if not isinstance(cohort_value, Mapping):
            raise DengueDataError(
                f"infection_flows.infections_by_cohort[{index}]: "
                "expected a dictionary"
            )
        cohort = dict(cohort_value)
        count = _validate_count(
            cohort.get("count"),
            f"infection_flows.infections_by_cohort[{index}].count",
        )
        province = cohort.get("province")
        age_group = cohort.get("age_group")
        prior_mask = cohort.get("prior_mask")
        if province not in PROVINCES:
            raise DengueDataError(
                f"infection_flows.infections_by_cohort[{index}].province: unknown"
            )
        if age_group not in baseline.age_groups:
            raise DengueDataError(
                f"infection_flows.infections_by_cohort[{index}].age_group: unknown"
            )
        if not isinstance(prior_mask, int) or not 0 <= prior_mask <= 15:
            raise DengueDataError(
                f"infection_flows.infections_by_cohort[{index}].prior_mask: invalid"
            )
        order = min(4, prior_mask.bit_count() + 1)
        prefix = (
            f"{province}:{age_group}:{prior_mask}:"
            f"{cohort.get('serotype')}:{index}"
        )
        symptomatic = _draw_binomial(
            count,
            clinical["symptomatic_by_infection_order"][str(order)],
            rng_factory(f"symptomatic:{prefix}"),
        )
        severe = _draw_binomial(
            symptomatic,
            severe_probability(age_group, prior_mask, baseline),
            rng_factory(f"severe:{prefix}"),
        )
        warning = _draw_binomial(
            symptomatic - severe,
            clinical["warning_given_symptomatic"],
            rng_factory(f"warning:{prefix}"),
        )
        hospitalized = _draw_binomial(
            severe,
            clinical["hospitalized_given_severe"],
            rng_factory(f"hospitalized:{prefix}"),
        )
        deaths = _draw_binomial(
            severe,
            treated_fatality_probability(pressure, baseline),
            rng_factory(f"fatal:{prefix}"),
        )
        severe_reported = _draw_binomial(
            severe,
            surveillance["severe_report_probability"],
            rng_factory(f"report-severe:{prefix}"),
        )
        non_severe_reported = _draw_binomial(
            symptomatic - severe,
            surveillance["report_probability"][province],
            rng_factory(f"report-nonsevere:{prefix}"),
        )
        reported = severe_reported + non_severe_reported
        sample_probability = (
            surveillance["alert_sample_probability"]
            if pressure >= clinical["soft_capacity_share"]
            else surveillance["routine_sample_probability"]
        )
        sampled = _draw_binomial(
            reported,
            sample_probability,
            rng_factory(f"sampled:{prefix}"),
        )
        outcome = {
            **cohort,
            "infections": count,
            "symptomatic": symptomatic,
            "warning": warning,
            "severe": severe,
            "hospitalized": hospitalized,
            "deaths": deaths,
            "reported": reported,
            "sampled": sampled,
        }
        totals["cohort_outcomes"].append(outcome)
        for key in (
            "infections",
            "symptomatic",
            "warning",
            "severe",
            "hospitalized",
            "deaths",
            "reported",
            "sampled",
        ):
            totals[key] += outcome[key]

    expected_infections = _validate_count(
        infection_flows.get("new_infections", 0),
        "infection_flows.new_infections",
    )
    if totals["infections"] != expected_infections:
        raise DengueDataError(
            "infection_flows.infections_by_cohort: does not match new_infections"
        )
    return totals


def epidemiological_week(d: date) -> tuple[date, date]:
    """Return the Monday and Sunday containing a date."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def release_dates(week_end: date) -> dict[str, date]:
    """Return provisional, revised, and final publication dates."""
    return {
        "provisional": week_end + timedelta(days=4),
        "revised": week_end + timedelta(days=14),
        "final": week_end + timedelta(days=28),
    }


def province_alert(
    *,
    cases: int,
    p75: int,
    p90: int,
    p95: int,
    rt: float,
    confirmed: int,
    pressure: float,
    previous: str,
) -> str:
    """Evaluate one province's current threshold state."""
    for name, value in (
        ("cases", cases),
        ("p75", p75),
        ("p90", p90),
        ("p95", p95),
        ("confirmed", confirmed),
    ):
        _validate_count(value, f"alert.{name}")
    if previous in ("alert", "outbreak", "recovery") and cases < p90 and rt < 1.0:
        return "recovery"
    if (cases >= max(15, p95) and confirmed >= 3) or pressure >= 0.85:
        return "outbreak"
    if (cases >= max(10, p90) and rt >= 1.1) or pressure >= 0.70:
        return "alert"
    if cases >= max(5, p75) or rt >= 1.1:
        return "watch"
    return "baseline"


def advance_alert_state(
    previous: Mapping[str, Any],
    candidate: str,
) -> dict[str, Any]:
    """Apply two-week outbreak and three-week recovery persistence."""
    if candidate not in {"baseline", "watch", "alert", "outbreak", "recovery"}:
        raise DengueDataError(f"alert.candidate: unknown level {candidate}")
    state = {
        "level": previous.get("level", "baseline"),
        "outbreak_weeks": _validate_count(
            previous.get("outbreak_weeks", 0), "alert.outbreak_weeks"
        ),
        "recovery_weeks": _validate_count(
            previous.get("recovery_weeks", 0), "alert.recovery_weeks"
        ),
    }
    if candidate == "outbreak":
        state["outbreak_weeks"] += 1
        state["recovery_weeks"] = 0
        if state["outbreak_weeks"] >= 2:
            state["level"] = "outbreak"
        elif state["level"] not in ("alert", "outbreak"):
            state["level"] = "alert"
        return state
    state["outbreak_weeks"] = 0
    if candidate == "recovery":
        state["recovery_weeks"] += 1
        state["level"] = (
            "baseline" if state["recovery_weeks"] >= 3 else "recovery"
        )
        return state
    state["recovery_weeks"] = 0
    state["level"] = candidate
    return state


def _bounded_children(capacities: list[int], total: int) -> list[int]:
    """Allocate a child count across parent chunks without exceeding them."""
    if total < 0 or total > sum(capacities):
        raise DengueDataError("surveillance.allocation: child exceeds parent")
    result: list[int] = []
    remaining_child = total
    remaining_parent = sum(capacities)
    for index, capacity in enumerate(capacities):
        if index == len(capacities) - 1:
            allocated = remaining_child
        elif remaining_parent == 0:
            allocated = 0
        else:
            lower = max(0, remaining_child - (remaining_parent - capacity))
            upper = min(capacity, remaining_child)
            allocated = min(
                upper,
                max(lower, round(remaining_child * capacity / remaining_parent)),
            )
        result.append(allocated)
        remaining_child -= allocated
        remaining_parent -= capacity
    return result


def _delay_chunks(
    count: int,
    distributions: list[Mapping[str, float]],
    rng: random.Random,
) -> list[tuple[int, int]]:
    combined = {0: 1.0}
    for distribution in distributions:
        next_combined: dict[int, float] = {}
        for left, left_weight in combined.items():
            for right, right_weight in distribution.items():
                delay = left + int(right)
                next_combined[delay] = (
                    next_combined.get(delay, 0.0)
                    + left_weight * float(right_weight)
                )
        combined = next_combined
    delays = sorted(combined)
    allocated = _draw_multinomial(
        count, [combined[delay] for delay in delays], rng
    )
    return [
        (delay, value)
        for delay, value in zip(delays, allocated, strict=True)
        if value
    ]


def _schedule_clinical_flows(
    d: date,
    state: dict[str, Any],
    clinical_flows: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> None:
    incubation = baseline.raw["transmission"]["human_incubation_days"]
    reporting_delay = baseline.raw["surveillance"]["reporting_delay_days"]
    for index, outcome_value in enumerate(
        clinical_flows.get("cohort_outcomes", [])
    ):
        if not isinstance(outcome_value, Mapping):
            raise DengueDataError(
                f"clinical_flows.cohort_outcomes[{index}]: expected a dictionary"
            )
        outcome = dict(outcome_value)
        infections = _validate_count(
            outcome.get("infections"),
            f"clinical_flows.cohort_outcomes[{index}].infections",
        )
        onset_chunks = _delay_chunks(
            infections,
            [incubation],
            rng_factory(f"onset:{index}:{outcome['province']}"),
        )
        onset_counts = [count for _, count in onset_chunks]
        severe_counts = _bounded_children(
            onset_counts, _validate_count(outcome.get("severe", 0), "clinical.severe")
        )
        hospitalized_counts = _bounded_children(
            severe_counts,
            _validate_count(outcome.get("hospitalized", 0), "clinical.hospitalized"),
        )
        death_counts = _bounded_children(
            severe_counts,
            _validate_count(outcome.get("deaths", 0), "clinical.deaths"),
        )
        for chunk_index, ((onset_delay, count), severe, hospitalized, deaths) in enumerate(
            zip(
                onset_chunks,
                severe_counts,
                hospitalized_counts,
                death_counts,
                strict=True,
            )
        ):
            if severe or hospitalized or deaths:
                onset_date = d + timedelta(days=onset_delay)
                state["clinical_queue"].append({
                    "due_date": onset_date.isoformat(),
                    "onset_date": onset_date.isoformat(),
                    "province": outcome["province"],
                    "age_group": outcome["age_group"],
                    "serotype": outcome["serotype"],
                    "severe": severe,
                    "hospitalized": hospitalized,
                    "deaths": deaths,
                })

        reported = _validate_count(outcome.get("reported", 0), "clinical.reported")
        sampled = _validate_count(outcome.get("sampled", 0), "clinical.sampled")
        report_chunks = _delay_chunks(
            reported,
            [incubation, reporting_delay],
            rng_factory(f"report-delay:{index}:{outcome['province']}"),
        )
        report_counts = [count for _, count in report_chunks]
        sample_counts = _bounded_children(report_counts, sampled)
        for delay, count, sample_count in (
            (delay, count, sample_counts[chunk_index])
            for chunk_index, (delay, count) in enumerate(report_chunks)
        ):
            onset_date = d + timedelta(days=max(4, delay - 4))
            state["reporting_queue"].append({
                "due_date": (d + timedelta(days=delay)).isoformat(),
                "infection_date": d.isoformat(),
                "onset_date": onset_date.isoformat(),
                "province": outcome["province"],
                "age_group": outcome["age_group"],
                "serotype": outcome["serotype"],
                "count": count,
                "sampled": sample_count,
            })


def _new_week_row(week_start: date, week_end: date) -> dict[str, Any]:
    zeros = {province: 0 for province in PROVINCES}
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "reported_by_province": dict(zeros),
        "confirmed_by_province": dict(zeros),
        "severe_by_province": dict(zeros),
        "hospitalized_by_province": dict(zeros),
        "deaths_by_province": dict(zeros),
        "reported_national": 0,
        "confirmed_national": 0,
        "severe_national": 0,
        "hospitalized_national": 0,
        "deaths_national": 0,
        "source": "dynamic",
    }


def _weekly_row(state: dict[str, Any], onset: date) -> dict[str, Any]:
    week_start, week_end = epidemiological_week(onset)
    for row in state["weekly_ledger"]:
        if row["week_end"] == week_end.isoformat():
            return row
    row = _new_week_row(week_start, week_end)
    state["weekly_ledger"].append(row)
    state["weekly_ledger"].sort(key=lambda item: item["week_end"])
    return row


def _process_clinical_queue(d: date, state: dict[str, Any]) -> None:
    retained: list[dict[str, Any]] = []
    for item in state["clinical_queue"]:
        if date.fromisoformat(item["due_date"]) > d:
            retained.append(item)
            continue
        for key in ("severe", "hospitalized", "deaths"):
            state["daily_totals"][key] += item[key]
        row = _weekly_row(state, date.fromisoformat(item["onset_date"]))
        province = item["province"]
        for key in ("severe", "hospitalized", "deaths"):
            row[f"{key}_by_province"][province] += item[key]
            row[f"{key}_national"] += item[key]
    state["clinical_queue"] = retained


def _process_reporting_queue(
    d: date,
    state: dict[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> None:
    retained: list[dict[str, Any]] = []
    turnaround = baseline.raw["surveillance"]["laboratory_turnaround_days"]
    for index, item in enumerate(state["reporting_queue"]):
        if date.fromisoformat(item["due_date"]) > d:
            retained.append(item)
            continue
        count = item["count"]
        sampled = item["sampled"]
        state["daily_totals"]["reported"] += count
        record = {
            "report_date": d.isoformat(),
            "infection_date": item["infection_date"],
            "onset_date": item["onset_date"],
            "province": item["province"],
            "age_group": item["age_group"],
            "serotype": item["serotype"],
            "reported": count,
            "sampled": sampled,
        }
        state["daily_records"].append(record)
        row = _weekly_row(state, date.fromisoformat(item["onset_date"]))
        row["reported_by_province"][item["province"]] += count
        row["reported_national"] += count
        for delay, sample_count in _delay_chunks(
            sampled,
            [turnaround],
            rng_factory(f"lab-turnaround:{d}:{index}:{item['province']}"),
        ):
            state["laboratory_queue"].append({
                "due_date": (d + timedelta(days=delay)).isoformat(),
                "onset_date": item["onset_date"],
                "province": item["province"],
                "age_group": item["age_group"],
                "serotype": item["serotype"],
                "count": sample_count,
            })
    state["reporting_queue"] = retained


def _process_laboratory_queue(
    d: date,
    state: dict[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[int, int]:
    capacities = baseline.raw["surveillance"]["daily_lab_capacity"]
    remaining_capacity = dict(capacities)
    retained: list[dict[str, Any]] = []
    processed = 0
    confirmed = 0
    for index, item_value in enumerate(state["laboratory_queue"]):
        if not isinstance(item_value, Mapping):
            raise DengueDataError(
                f"surveillance.laboratory_queue[{index}]: expected a dictionary"
            )
        item = copy.deepcopy(dict(item_value))
        province = item.get("province")
        if province not in PROVINCES:
            raise DengueDataError(
                f"surveillance.laboratory_queue[{index}].province: unknown"
            )
        due = date.fromisoformat(item["due_date"])
        count = _validate_count(
            item.get("count"),
            f"surveillance.laboratory_queue[{index}].count",
        )
        if due > d or remaining_capacity[province] == 0:
            retained.append(item)
            continue
        accepted = min(count, remaining_capacity[province])
        processed += accepted
        positives = _draw_binomial(
            accepted,
            baseline.raw["surveillance"]["laboratory_positive_probability"],
            rng_factory(f"lab-positive:{d}:{index}:{province}"),
        )
        confirmed += positives
        if "onset_date" in item:
            row = _weekly_row(state, date.fromisoformat(item["onset_date"]))
            row["confirmed_by_province"][province] += positives
            row["confirmed_national"] += positives
        remaining_capacity[province] -= accepted
        if accepted < count:
            item["count"] = count - accepted
            retained.append(item)
    state["laboratory_queue"] = retained
    return processed, confirmed


def _release_due_vintages(
    d: date,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    existing = {
        (item["week_end"], item["vintage"])
        for item in state["release_vintages"]
    }
    events: list[dict[str, Any]] = []
    for row in state["weekly_ledger"]:
        week_end = date.fromisoformat(row["week_end"])
        for vintage, release_date in release_dates(week_end).items():
            key = (row["week_end"], vintage)
            if release_date != d or key in existing:
                continue
            release = {
                **copy.deepcopy(row),
                "vintage": vintage,
                "revision_of": (
                    None
                    if vintage == "provisional"
                    else "provisional" if vintage == "revised" else "revised"
                ),
                "published_on": d.isoformat(),
                "data_through": row["week_end"],
            }
            state["release_vintages"].append(release)
            existing.add(key)
            events.append({
                "type": "public_health",
                "severity": "info",
                "title": "登革热周报发布",
                "description": (
                    f"{row['week_end']} 流行病学周 {vintage} 版："
                    f"报告 {row['reported_national']} 例。"
                ),
            })
    return events


def advance_surveillance(
    d: date,
    previous: Mapping[str, Any],
    clinical_flows: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Advance queues and publish due weekly vintages without mutation."""
    state = copy.deepcopy(dict(previous))
    for key in (
        "clinical_queue",
        "reporting_queue",
        "laboratory_queue",
        "daily_records",
        "weekly_ledger",
        "release_vintages",
    ):
        state.setdefault(key, [])
    state.setdefault(
        "alert_state", {province: "baseline" for province in PROVINCES}
    )
    state["daily_totals"] = {
        "date": d.isoformat(),
        "estimated_infections": _validate_count(
            clinical_flows.get("infections", 0), "clinical_flows.infections"
        ),
        "symptomatic": _validate_count(
            clinical_flows.get("symptomatic", 0), "clinical_flows.symptomatic"
        ),
        "reported": 0,
        "lab_processed": 0,
        "confirmed": 0,
        "severe": 0,
        "hospitalized": 0,
        "deaths": 0,
    }
    _schedule_clinical_flows(
        d, state, clinical_flows, baseline, rng_factory
    )
    _process_clinical_queue(d, state)
    _process_reporting_queue(d, state, baseline, rng_factory)
    processed, confirmed = _process_laboratory_queue(
        d, state, baseline, rng_factory
    )
    state["daily_totals"]["lab_processed"] = processed
    state["daily_totals"]["confirmed"] = confirmed
    events = _release_due_vintages(d, state)
    history_limit = baseline.raw["state_limits"]["daily_quality_history_days"]
    state["daily_records"] = state["daily_records"][-history_limit:]
    state["weekly_ledger"] = state["weekly_ledger"][
        -baseline.raw["state_limits"]["weekly_history_weeks"]:
    ]
    return state, events


def surveillance_snapshot(
    d: date,
    state: Mapping[str, Any],
    population_by_province: Mapping[str, int],
    baseline: DengueBaseline,
) -> dict[str, Any]:
    """Return a public monitoring snapshot without internal queues."""
    daily = state.get("daily_totals", {})
    alert_state = state.get("alert_state", {})
    levels = {
        province: (
            value.get("level", "baseline")
            if isinstance(value, Mapping)
            else value
        )
        for province, value in alert_state.items()
    }
    rank = {"baseline": 0, "watch": 1, "recovery": 2, "alert": 3, "outbreak": 4}
    national_level = max(
        levels.values(), key=lambda level: rank.get(level, -1), default="baseline"
    )
    records_today = [
        item
        for item in state.get("daily_records", [])
        if item.get("report_date") == d.isoformat()
    ]
    provinces: dict[str, dict[str, Any]] = {}
    for province in PROVINCES:
        reported = sum(
            item["reported"]
            for item in records_today
            if item["province"] == province
        )
        population = population_by_province[province]
        provinces[province] = {
            "population": population,
            "reported_cases": reported,
            "incidence_per_100k": round(
                0.0 if population == 0 else reported / population * 100_000,
                3,
            ),
            "alert_level": levels.get(province, "baseline"),
        }
    latest_release = (
        copy.deepcopy(state.get("release_vintages", [])[-1])
        if state.get("release_vintages")
        else None
    )
    future_dates = [
        release_date
        for row in state.get("weekly_ledger", [])
        for vintage, release_date in release_dates(
            date.fromisoformat(row["week_end"])
        ).items()
        if release_date > d
        and (row["week_end"], vintage) not in {
            (item["week_end"], item["vintage"])
            for item in state.get("release_vintages", [])
        }
    ]
    iso_year, iso_week, _ = d.isocalendar()
    return {
        "as_of_date": d.isoformat(),
        "epidemiological_week": f"{iso_year}-W{iso_week:02d}",
        "release_status": (
            latest_release["vintage"] if latest_release else None
        ),
        "national": {
            "estimated_infections": daily.get("estimated_infections", 0),
            "symptomatic_infections": daily.get("symptomatic", 0),
            "reported_cases": daily.get("reported", 0),
            "lab_confirmed": daily.get("confirmed", 0),
            "severe": daily.get("severe", 0),
            "hospitalized": daily.get("hospitalized", 0),
            "deaths": daily.get("deaths", 0),
            "alert_level": national_level,
        },
        "provinces": provinces,
        "latest_release": latest_release,
        "next_release_date": min(future_dates).isoformat() if future_dates else None,
        "data_quality": copy.deepcopy(state.get("data_quality", [])),
        "baseline_version": baseline.version,
    }
