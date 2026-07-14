"""Pure CPI index model with monthly official publication."""

from __future__ import annotations

import copy
import math
from calendar import monthrange
from datetime import date
from numbers import Real


BASKET_WEIGHTS = {
    "food": 0.35,
    "fuel": 0.18,
    "housing": 0.15,
    "transport": 0.12,
    "other": 0.20,
}

BASELINE_ANNUAL_RATES = {
    "food": 2.5,
    "fuel": 3.0,
    "housing": 2.0,
    "transport": 2.0,
    "other": 2.0,
}

MONTHLY_RAIN_NORM = {
    1: 180.0, 2: 220.0, 3: 200.0, 4: 140.0,
    5: 80.0, 6: 60.0, 7: 55.0, 8: 60.0,
    9: 70.0, 10: 95.0, 11: 130.0, 12: 170.0,
}

MONTHLY_TEMP_NORM = {
    1: 29.0, 2: 29.0, 3: 28.0, 4: 27.0,
    5: 25.0, 6: 24.0, 7: 23.0, 8: 24.0,
    9: 25.0, 10: 26.0, 11: 27.0, 12: 28.0,
}

REFERENCE_SUGAR_USD_LB = 0.20
REFERENCE_BRENT_USD_BARREL = 82.5
REFERENCE_MVL_PER_USD = 2.18
FUEL_TAX_MVL = 1.02
FUEL_MARGIN_MVL = 0.70
BARREL_TO_LITRE = 158.98
MAX_DAILY_OBSERVATIONS = 62
MAX_MONTHLY_HISTORY = 24
MIN_COMPONENT_CHANGE_PCT = -2.0
MAX_COMPONENT_CHANGE_PCT = 3.0


def inflation_step(
    d: date,
    previous_state: dict,
    weather: dict,
    commodities: dict,
    exchange: dict,
    profile: dict,
    rng,
) -> tuple[dict, dict, list[dict]]:
    """Return public CPI data, explicit next state, and release events."""
    if not isinstance(d, date):
        raise TypeError("d must be a date")

    next_state = copy.deepcopy(previous_state)
    observation, current_components, petrol_95, diesel = _daily_observation(
        d, weather, commodities, exchange, profile, rng,
    )
    next_state["daily_observations"] = _upsert_observation(
        next_state.get("daily_observations", []), observation,
    )
    next_state["monthly_history"] = copy.deepcopy(
        list(next_state.get("monthly_history", []))[-MAX_MONTHLY_HISTORY:]
    )

    events: list[dict] = []
    release_date = next_state.get("last_release_date")
    output_components = current_components
    is_new_release = d.day == 15 and release_date != d.isoformat()
    if is_new_release:
        output_components = _publish_previous_month(
            d, next_state, current_components,
        )
        release_date = d.isoformat()
        next_state["last_release_date"] = release_date
        next_state["published_components"] = copy.deepcopy(output_components)
        events.append({
            "type": "economy",
            "severity": "info",
            "text": (
                "Statistics Bureau released the monthly CPI: "
                f"{next_state['published_yoy_pct']:+.2f}% year over year"
            ),
            "release_date": release_date,
            "index": next_state["published_index"],
            "mom_pct": next_state["published_mom_pct"],
            "yoy_pct": next_state["published_yoy_pct"],
        })
    elif d.day == 15 and release_date == d.isoformat():
        output_components = copy.deepcopy(
            next_state.get("published_components", current_components)
        )

    published_index = _finite_real(
        next_state.get("published_index", 100.0), "published_index"
    )
    published_mom = _finite_real(
        next_state.get("published_mom_pct", 0.0), "published_mom_pct"
    )
    published_yoy = _finite_real(
        next_state.get("published_yoy_pct", 0.0), "published_yoy_pct"
    )
    public = {
        "index": published_index,
        "mom_pct": published_mom,
        "yoy_pct": published_yoy,
        "is_release_day": d.day == 15,
        "release_date": release_date,
        "components": output_components,
        "fuel_95_price_mvl": petrol_95,
        "fuel_diesel_price_mvl": diesel,
        "history": copy.deepcopy(next_state["monthly_history"]),
    }
    return public, next_state, events


def _daily_observation(
    d: date,
    weather: dict,
    commodities: dict,
    exchange: dict,
    profile: dict,
    rng,
) -> tuple[dict, dict, float, float]:
    katora = weather.get("katora", {})
    rainfall = _finite_real(katora.get("rainfall_mm", 0.0), "rainfall_mm")
    temperature = _finite_real(
        katora.get("temp_high", MONTHLY_TEMP_NORM[d.month]), "temp_high"
    )
    sugar = _finite_real(
        commodities.get("sugar_usd_lb", REFERENCE_SUGAR_USD_LB),
        "sugar_usd_lb",
    )
    brent = _finite_real(
        commodities.get("brent_usd_barrel", REFERENCE_BRENT_USD_BARREL),
        "brent_usd_barrel",
    )
    mvl_per_usd = _positive_finite_real(
        exchange.get("mvl_per_usd", REFERENCE_MVL_PER_USD), "mvl_per_usd"
    )
    urbanization = _finite_real(
        profile.get("demographics", {}).get("urbanization_pct", 48.0),
        "urbanization_pct",
    )

    rainfall_normal = (
        MONTHLY_RAIN_NORM[d.month] / monthrange(d.year, d.month)[1]
    )
    rain_deviation = (rainfall - rainfall_normal) / rainfall_normal
    temperature_deviation = temperature - MONTHLY_TEMP_NORM[d.month]
    if rain_deviation < 0.0:
        rain_pressure = -rain_deviation * 0.10
    else:
        rain_pressure = min(rain_deviation * 0.02, 0.30)
    weather_pressure = _bounded(
        rain_pressure + temperature_deviation * 0.02, -0.5, 1.0
    )

    sugar_pressure = _bounded(
        (sugar / REFERENCE_SUGAR_USD_LB - 1.0) * 0.20, -0.5, 0.8
    )
    import_pressure = _bounded(
        (mvl_per_usd / REFERENCE_MVL_PER_USD - 1.0) * 2.0, -0.6, 0.8
    )
    petrol_95, diesel = _pump_prices(brent, mvl_per_usd)
    reference_petrol, _ = _pump_prices(
        REFERENCE_BRENT_USD_BARREL, REFERENCE_MVL_PER_USD
    )
    brent_pressure = _bounded(
        (petrol_95 / reference_petrol - 1.0) * 15.0, -1.5, 2.0
    )

    food_rate = _component_bound(
        BASELINE_ANNUAL_RATES["food"] / 12.0
        + weather_pressure + sugar_pressure + import_pressure * 0.20
    )
    fuel_rate = _component_bound(
        BASELINE_ANNUAL_RATES["fuel"] / 12.0 + brent_pressure
    )
    housing_rate = _component_bound(
        BASELINE_ANNUAL_RATES["housing"] / 12.0
        + max(0.0, urbanization - 48.0) * 0.005
        + import_pressure * 0.25
        + _finite_real(rng.gauss(0.0, 0.015), "housing RNG pressure")
    )
    transport_rate = _component_bound(
        BASELINE_ANNUAL_RATES["transport"] / 12.0
        + (fuel_rate - BASELINE_ANNUAL_RATES["fuel"] / 12.0) * 0.55
    )
    other_rate = _component_bound(
        BASELINE_ANNUAL_RATES["other"] / 12.0
        + import_pressure * 0.12
        + _finite_real(rng.gauss(0.0, 0.01), "other RNG pressure")
    )

    rates = {
        "food": food_rate,
        "fuel": fuel_rate,
        "housing": housing_rate,
        "transport": transport_rate,
        "other": other_rate,
    }
    components = _component_output(rates)
    components["food"].update({
        "weather_pressure": _rounded(weather_pressure),
        "sugar_pressure": _rounded(sugar_pressure),
        "import_pressure": _rounded(import_pressure * 0.20),
    })
    components["fuel"].update({
        "brent_pressure": _rounded(brent_pressure),
        "import_pressure": _rounded(import_pressure),
    })
    components["housing"]["import_pressure"] = _rounded(
        import_pressure * 0.25
    )
    components["transport"]["fuel_pass_through"] = _rounded(
        (fuel_rate - BASELINE_ANNUAL_RATES["fuel"] / 12.0) * 0.55
    )
    components["other"]["import_pressure"] = _rounded(
        import_pressure * 0.12
    )

    observation = {
        "date": d.isoformat(),
        "rainfall_mm": rainfall,
        "rainfall_normal_mm": rainfall_normal,
        "temperature_deviation_c": temperature_deviation,
        "sugar_usd_lb": sugar,
        "brent_usd_barrel": brent,
        "mvl_per_usd": mvl_per_usd,
        "component_pressures": {
            name: details["rate_pct"] for name, details in components.items()
        },
    }
    return observation, components, petrol_95, diesel


def _publish_previous_month(
    d: date,
    state: dict,
    current_components: dict,
) -> dict:
    target_year, target_month = _shift_month(d.year, d.month, -1)
    target_prefix = f"{target_year:04d}-{target_month:02d}-"
    observations = [
        observation for observation in state["daily_observations"]
        if str(observation.get("date", "")).startswith(target_prefix)
    ]

    component_changes = {}
    for name in BASKET_WEIGHTS:
        values = []
        for observation in observations:
            pressures = observation.get("component_pressures", {})
            if name in pressures:
                values.append(_finite_real(pressures[name], f"{name} pressure"))
        if values:
            change = math.fsum(values) / len(values)
        else:
            change = BASELINE_ANNUAL_RATES[name] / 12.0
        component_changes[name] = _component_bound(change)

    monthly_change = math.fsum(
        BASKET_WEIGHTS[name] * component_changes[name]
        for name in BASKET_WEIGHTS
    )
    previous_index = _positive_finite_real(
        state.get("published_index", 100.0), "published_index"
    )
    new_index = _positive_finite_real(
        previous_index * (1.0 + monthly_change / 100.0), "new CPI index"
    )
    mom_pct = (new_index / previous_index - 1.0) * 100.0
    year_ago_index = _index_for_month(
        state["monthly_history"], target_year - 1, target_month
    )
    if year_ago_index is None:
        prior_yoy = _finite_real(
            state.get("published_yoy_pct", 0.0), "published_yoy_pct"
        )
        denominator = 1.0 + prior_yoy / 100.0
        year_ago_index = (
            previous_index / denominator
            if denominator > 0.0 else previous_index
        )
    yoy_pct = (new_index / year_ago_index - 1.0) * 100.0

    published_components = _component_output(component_changes)
    for name, details in current_components.items():
        for key, value in details.items():
            if key not in ("rate_pct", "contribution_pct"):
                published_components[name][key] = value

    month_end = date(
        target_year, target_month, monthrange(target_year, target_month)[1]
    )
    record = {
        "date": month_end.isoformat(),
        "index": _rounded(new_index, 6),
        "mom_pct": _rounded(mom_pct),
        "yoy_pct": _rounded(yoy_pct),
        "components": {
            name: _rounded(change) for name, change in component_changes.items()
        },
        "release_date": d.isoformat(),
        "source": "monthly_release",
    }
    state["monthly_history"] = (
        list(state["monthly_history"]) + [record]
    )[-MAX_MONTHLY_HISTORY:]
    state["published_index"] = record["index"]
    state["published_mom_pct"] = record["mom_pct"]
    state["published_yoy_pct"] = record["yoy_pct"]
    return published_components


def _component_output(rates: dict[str, float]) -> dict[str, dict[str, float]]:
    return {
        name: {
            "rate_pct": _rounded(rate),
            "contribution_pct": _rounded(BASKET_WEIGHTS[name] * rate),
        }
        for name, rate in rates.items()
    }


def _upsert_observation(history: list, observation: dict) -> list[dict]:
    observation_date = observation["date"]
    retained = [
        copy.deepcopy(item) for item in history
        if item.get("date") != observation_date
    ]
    retained.append(observation)
    retained.sort(key=lambda item: str(item.get("date", "")))
    return retained[-MAX_DAILY_OBSERVATIONS:]


def _index_for_month(history: list, year: int, month: int) -> float | None:
    prefix = f"{year:04d}-{month:02d}-"
    matches = [
        item for item in history
        if str(item.get("date", "")).startswith(prefix)
    ]
    if not matches:
        return None
    return _positive_finite_real(matches[-1].get("index"), "historical CPI index")


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month_index = year * 12 + month - 1 + offset
    shifted_year, zero_based_month = divmod(month_index, 12)
    return shifted_year, zero_based_month + 1


def _pump_prices(brent_usd: float, mvl_per_usd: float) -> tuple[float, float]:
    crude_cost_mvl = brent_usd * mvl_per_usd / BARREL_TO_LITRE
    petrol_95 = crude_cost_mvl + FUEL_TAX_MVL + FUEL_MARGIN_MVL
    diesel = crude_cost_mvl + FUEL_TAX_MVL * 0.4 + FUEL_MARGIN_MVL * 0.7
    return round(petrol_95, 2), round(diesel, 2)


def _component_bound(value: float) -> float:
    return _bounded(value, MIN_COMPONENT_CHANGE_PCT, MAX_COMPONENT_CHANGE_PCT)


def _bounded(value: float, lower: float, upper: float) -> float:
    value = _finite_real(value, "derived CPI value")
    return min(upper, max(lower, value))


def _rounded(value: float, digits: int = 4) -> float:
    return round(_finite_real(value, "CPI output"), digits)


def _finite_real(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be a finite real number")
    return converted


def _positive_finite_real(value, label: str) -> float:
    converted = _finite_real(value, label)
    if converted <= 0.0:
        raise ValueError(f"{label} must be a finite positive real number")
    return converted
