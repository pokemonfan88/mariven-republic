"""Pure, deterministic daily weather model for Mariven."""

from __future__ import annotations

import calendar
import csv
import math
import random
from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path


MARIVEN_LAT = -20.795

CITIES = {
    "katora": {
        "name": "卡托拉市",
        "temp_offset": 0.0,
        "rain_scale": 1.00,
    },
    "makadi_port": {
        "name": "马卡迪港",
        "temp_offset": 0.8,
        "rain_scale": 0.85,
    },
    "timo": {
        "name": "蒂莫城",
        "temp_offset": -1.2,
        "rain_scale": 1.10,
    },
    "pela": {
        "name": "佩拉湾",
        "temp_offset": 0.3,
        "rain_scale": 1.15,
    },
    "ruwa": {
        "name": "鲁瓦镇",
        "temp_offset": -0.5,
        "rain_scale": 1.30,
    },
}

CONDITIONS = ("晴", "多云", "阴", "阵雨", "暴雨")

# Rows are yesterday's condition and columns are today's condition.
DRY_MATRIX = (
    (0.60, 0.22, 0.10, 0.06, 0.02),
    (0.40, 0.30, 0.18, 0.10, 0.02),
    (0.25, 0.28, 0.25, 0.18, 0.04),
    (0.20, 0.30, 0.22, 0.22, 0.06),
    (0.12, 0.22, 0.25, 0.28, 0.13),
)

WET_MATRIX = (
    (0.35, 0.30, 0.18, 0.14, 0.03),
    (0.20, 0.28, 0.25, 0.22, 0.05),
    (0.12, 0.22, 0.28, 0.28, 0.10),
    (0.10, 0.18, 0.25, 0.35, 0.12),
    (0.05, 0.15, 0.22, 0.35, 0.23),
)

GAMMA_PARAMS = (
    (0.3, 0.5),
    (0.8, 1.2),
    (1.5, 2.5),
    (2.5, 6.0),
    (4.0, 18.0),
)

_DRY_MONTHS = frozenset((5, 6, 7, 8, 9, 10))
_SOI_LIMIT = 30.0
_MAX_SOI_MASS_SHIFT = 0.15


class WeatherDataError(RuntimeError):
    """Raised when the SOI source cannot satisfy the weather contract."""


@dataclass(frozen=True)
class SoiSeries:
    """Sorted immutable monthly Southern Oscillation Index observations."""

    _month_keys: tuple[int, ...]
    _values: tuple[float, ...]
    _months: tuple[str, ...]

    @classmethod
    def from_csv(cls, path: Path) -> SoiSeries:
        """Load and validate monthly SOI observations from ``path``."""
        try:
            with path.open("r", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                headers = reader.fieldnames or []
                required = ("Year", "Month", "SOI")
                missing = [column for column in required if column not in headers]
                if missing:
                    raise WeatherDataError(
                        "SOI data is missing required column(s): "
                        + ", ".join(missing)
                    )

                values_by_key: dict[int, float] = {}
                for line_number, row in enumerate(reader, start=2):
                    try:
                        year = int(row["Year"] or "")
                        month = int(row["Month"] or "")
                        value = float(row["SOI"] or "")
                        observation_date = date(year, month, 1)
                    except (TypeError, ValueError) as exc:
                        raise WeatherDataError(
                            f"invalid SOI observation at {path}:{line_number}: {exc}"
                        ) from exc
                    if not math.isfinite(value):
                        raise WeatherDataError(
                            f"invalid SOI observation at {path}:{line_number}: "
                            "SOI must be finite"
                        )

                    key = _month_key(year, month)
                    existing = values_by_key.get(key)
                    if existing is not None and existing != value:
                        raise WeatherDataError(
                            "conflicting SOI observations for "
                            f"{observation_date:%Y-%m} in {path}"
                        )
                    values_by_key[key] = value
        except WeatherDataError:
            raise
        except (OSError, UnicodeError) as exc:
            raise WeatherDataError(f"cannot read SOI data from {path}: {exc}") from exc

        if not values_by_key:
            raise WeatherDataError(f"SOI data contains no observations: {path}")

        keys = tuple(sorted(values_by_key))
        values = tuple(values_by_key[key] for key in keys)
        months = tuple(_month_text(key) for key in keys)
        return cls(keys, values, months)

    def value_for(self, d: date) -> tuple[float | None, str | None]:
        """Return the latest observation not later than ``d``'s month."""
        index = bisect_right(self._month_keys, _month_key(d.year, d.month)) - 1
        if index < 0:
            return None, None
        return self._values[index], self._months[index]


def temperature_baseline(d: date) -> float:
    """Return Mariven's leap-year-aware seasonal mean temperature."""
    year_days = 366 if calendar.isleap(d.year) else 365
    phase_days = 30 * year_days / 365.2425
    return 25.5 + 2.5 * math.cos(
        2 * math.pi * (d.timetuple().tm_yday - phase_days) / year_days
    )


def coral_bleaching_risk(d: date, sst_c: float) -> str:
    """Classify seasonal coral bleaching risk, checking critical first."""
    day_of_year = d.timetuple().tm_yday
    if 15 <= day_of_year < 135 and sst_c > 29.5:
        return "critical"
    if 30 <= day_of_year < 120 and sst_c > 28.5:
        return "warning"
    return "none"


def weather_step(
    d: date,
    previous_state: Mapping[str, object],
    soi_series: SoiSeries,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict, dict, list[dict]]:
    """Return public weather, next model state, and weather-risk events."""
    soi_value, soi_month = soi_series.value_for(d)
    enso_status = _enso_status(soi_value)
    previous_conditions = previous_state.get("previous_conditions", {})
    if not isinstance(previous_conditions, Mapping):
        previous_conditions = {}

    public: dict[str, object] = {}
    next_conditions: dict[str, str] = {}
    rainfall_total = 0.0
    sunrise, sunset, daylight_hours = _sun_times(d)

    for city_key, city in CITIES.items():
        previous_index = _condition_index(previous_conditions.get(city_key))
        probabilities = _condition_probabilities(
            previous_index, d.month, soi_value
        )
        condition_index = _sample_index(
            probabilities, rng_factory(f"condition:{city_key}")
        )
        condition = CONDITIONS[condition_index]
        next_conditions[city_key] = condition

        high, low = _temperatures(
            d,
            float(city["temp_offset"]),
            condition_index,
            rng_factory(f"temperature:{city_key}"),
        )
        rain_shape, rain_scale = GAMMA_PARAMS[condition_index]
        rainfall_mm = round(
            rng_factory(f"rain:{city_key}").gammavariate(
                rain_shape, rain_scale
            ) * float(city["rain_scale"]),
            1,
        )
        humidity = _humidity(
            condition_index, d.month, rng_factory(f"humidity:{city_key}")
        )
        wind_direction, wind_kmh = _wind(
            d.month, rng_factory(f"wind:{city_key}")
        )
        city_weather = {
            "name": city["name"],
            "condition": condition,
            "condition_idx": condition_index,
            "temp_high": high,
            "temp_low": low,
            "humidity": humidity,
            "rainfall_mm": rainfall_mm,
            "wind_dir": wind_direction,
            "wind_kmh": wind_kmh,
            "uv": _uv_index(condition_index, daylight_hours),
        }
        public[city_key] = city_weather
        rainfall_total += rainfall_mm

    national_rainfall = round(rainfall_total / len(CITIES), 2)
    rainfall_history = _rainfall_history(previous_state)
    rainfall_history.append(national_rainfall)
    rainfall_history = rainfall_history[-14:]
    rainfall_14d = sum(rainfall_history)
    rainfall_7d = sum(rainfall_history[-7:])

    katora = public["katora"]
    assert isinstance(katora, dict)
    soil_moisture = min(1.0, max(0.1, rainfall_14d / 80.0))
    sst_c = _sea_surface_temperature(d, soi_value)
    fire_risk = _fire_risk(
        d.month, rainfall_7d, int(katora["condition_idx"])
    )
    coral_risk = coral_bleaching_risk(d, sst_c)
    cyclone_risk = _cyclone_risk(
        d.month, enso_status, rng_factory("risk:cyclone")
    )

    public.update({
        "sunrise": sunrise,
        "sunset": sunset,
        "daylight_hours": round(daylight_hours, 2),
        "cyclone_risk": cyclone_risk,
        "cyclone_risk_basis": "climate_statistics",
        "fire_risk": fire_risk,
        "soil_moisture_index": round(soil_moisture, 2),
        "sst_c": round(sst_c, 1),
        "coral_bleaching_risk": coral_risk,
        "enso_status": enso_status,
        "soi_value": round(soi_value, 2) if soi_value is not None else None,
        "soi_source_month": soi_month,
        "rainfall_7d_mm": round(rainfall_7d, 1),
        "rainfall_14d_mm": round(rainfall_14d, 1),
        "national_rainfall_mm": national_rainfall,
        "condition": katora["condition"],
        "temp_high": katora["temp_high"],
        "temp_low": katora["temp_low"],
        "humidity": katora["humidity"],
        "rainfall_mm": katora["rainfall_mm"],
        "wind_kmh": katora["wind_kmh"],
        "notes": _weather_note(str(katora["condition"]), float(katora["temp_high"])),
    })

    next_state = {
        "previous_conditions": next_conditions,
        "rainfall_history": rainfall_history,
    }
    events = _risk_events(public)
    return public, next_state, events


def _condition_probabilities(
    previous_index: int, month: int, soi_value: float | None
) -> tuple[float, ...]:
    matrix = DRY_MATRIX if month in _DRY_MONTHS else WET_MATRIX
    probabilities = list(matrix[previous_index])
    if soi_value is not None and soi_value != 0:
        magnitude = min(abs(soi_value), _SOI_LIMIT) / _SOI_LIMIT
        requested_shift = magnitude * _MAX_SOI_MASS_SHIFT
        if soi_value > 0:
            _move_probability_mass(probabilities, (0, 1), (3, 4), requested_shift)
        else:
            _move_probability_mass(probabilities, (3, 4), (0, 1), requested_shift)
    total = sum(max(0.0, probability) for probability in probabilities)
    if total <= 0:
        raise ValueError("weather condition probabilities must have positive mass")
    return tuple(max(0.0, probability) / total for probability in probabilities)


def _move_probability_mass(
    probabilities: list[float],
    source_indices: tuple[int, int],
    target_indices: tuple[int, int],
    requested_shift: float,
) -> None:
    available = sum(max(0.0, probabilities[index]) for index in source_indices)
    shift = min(max(0.0, requested_shift), available)
    if shift == 0:
        return

    for index in source_indices:
        share = max(0.0, probabilities[index]) / available
        probabilities[index] -= shift * share

    target_mass = sum(max(0.0, probabilities[index]) for index in target_indices)
    if target_mass == 0:
        for index in target_indices:
            probabilities[index] += shift / len(target_indices)
    else:
        for index in target_indices:
            share = max(0.0, probabilities[index]) / target_mass
            probabilities[index] += shift * share


def _sample_index(probabilities: tuple[float, ...], rng: random.Random) -> int:
    draw = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if draw <= cumulative:
            return index
    return len(probabilities) - 1


def _condition_index(value: object) -> int:
    if isinstance(value, str) and value in CONDITIONS:
        return CONDITIONS.index(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(CONDITIONS):
        return value
    return 0


def _temperatures(
    d: date,
    city_offset: float,
    condition_index: int,
    rng: random.Random,
) -> tuple[float, float]:
    cloud_cooling = (0.0, -0.5, -1.5, -2.5, -3.5)[condition_index]
    high = temperature_baseline(d) + city_offset + rng.gauss(0.0, 0.8)
    high += cloud_cooling / 2.0
    diurnal_range = 8.0 if condition_index < 2 else 5.0
    low = high - rng.uniform(diurnal_range - 1.5, diurnal_range + 1.5)
    return round(high, 1), round(max(low, 12.0), 1)


def _humidity(condition_index: int, month: int, rng: random.Random) -> int:
    baseline = (65, 72, 78, 82, 88)[condition_index]
    seasonal = -5 if month in _DRY_MONTHS else 5
    return min(98, max(50, baseline + seasonal + rng.randint(-4, 4)))


def _wind(month: int, rng: random.Random) -> tuple[str, int]:
    if month in _DRY_MONTHS:
        directions = ("E", "ESE", "SE", "SSE", "NE")
        weights = (0.15, 0.20, 0.40, 0.20, 0.05)
        speed_range = (8, 22)
    else:
        directions = ("E", "ESE", "SE", "SSE", "NE", "N", "NW", "SW")
        weights = (0.20, 0.15, 0.25, 0.15, 0.10, 0.05, 0.05, 0.05)
        speed_range = (5, 18)
    direction_index = _sample_index(weights, rng)
    return directions[direction_index], rng.randint(*speed_range)


def _sun_times(d: date) -> tuple[str, str, float]:
    year_days = 366 if calendar.isleap(d.year) else 365
    day_of_year = d.timetuple().tm_yday
    declination = -23.44 * math.cos(
        2 * math.pi * (day_of_year + 10) / year_days
    )
    hour_angle = math.acos(
        -math.tan(math.radians(MARIVEN_LAT))
        * math.tan(math.radians(declination))
    )
    daylight_hours = max(10.5, min(13.5, 2 * math.degrees(hour_angle) / 15))
    solar_noon_minutes = 12 * 60 + 15
    half_daylight_minutes = daylight_hours * 30
    sunrise = _format_minutes(solar_noon_minutes - half_daylight_minutes)
    sunset = _format_minutes(solar_noon_minutes + half_daylight_minutes)
    return sunrise, sunset, daylight_hours


def _format_minutes(value: float) -> str:
    return f"{int(value // 60):02d}:{int(value % 60):02d}"


def _uv_index(condition_index: int, daylight_hours: float) -> int:
    baseline = 8 if daylight_hours > 12 else 6
    return max(0, baseline - (0, 1, 3, 5, 6)[condition_index])


def _rainfall_history(previous_state: Mapping[str, object]) -> list[float]:
    raw_history = previous_state.get("rainfall_history", [])
    if not isinstance(raw_history, list):
        return []
    history: list[float] = []
    for value in raw_history[-13:]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            converted = float(value)
            if math.isfinite(converted) and converted >= 0:
                history.append(converted)
    return history


def _sea_surface_temperature(d: date, soi_value: float | None) -> float:
    year_days = 366 if calendar.isleap(d.year) else 365
    sst = 27.5 + 1.5 * math.cos(
        2 * math.pi * (d.timetuple().tm_yday - 60) / year_days
    )
    if soi_value is not None and soi_value < -7:
        sst += 0.6
    elif soi_value is not None and soi_value > 7:
        sst -= 0.3
    return sst


def _fire_risk(month: int, rainfall_7d: float, condition_index: int) -> str:
    if month not in _DRY_MONTHS:
        return "low"
    if condition_index == 0 and rainfall_7d < 5:
        return "high"
    if condition_index < 2 and rainfall_7d < 15:
        return "medium"
    return "low"


def _cyclone_risk(
    month: int, enso_status: str, rng: random.Random
) -> str:
    if month in _DRY_MONTHS:
        return "none"
    probability = 0.02 if month in (1, 2) else 0.01
    if enso_status == "La Niña":
        probability *= 1.5
    elif enso_status == "El Niño":
        probability *= 0.3
    return "monitored" if rng.random() < probability else "none"


def _enso_status(soi_value: float | None) -> str:
    if soi_value is None:
        return "Neutral"
    if soi_value > 7:
        return "La Niña"
    if soi_value < -7:
        return "El Niño"
    return "Neutral"


def _weather_note(condition: str, temperature: float) -> str:
    if condition == "暴雨":
        return "暴雨可能导致卡托拉市低洼地区积水。"
    if condition == "阵雨":
        return "午后短时阵雨，西部平原蔗田受益。"
    if temperature >= 29:
        return "气温略高于季节均值。"
    return "典型季节天气。"


def _risk_events(public: Mapping[str, object]) -> list[dict]:
    events: list[dict] = []
    condition = public["condition"]
    if condition == "暴雨":
        events.append({
            "type": "weather",
            "severity": "warning",
            "text": "暴雨预警——卡托拉市低洼区注意积水",
        })
    elif condition == "阵雨":
        events.append({
            "type": "weather",
            "severity": "info",
            "text": "午后阵雨——预计持续1-2小时",
        })
    if public["cyclone_risk"] == "monitored":
        events.append({
            "type": "weather",
            "severity": "warning",
            "text": "气旋气候风险已进入监测状态",
        })
    if public["fire_risk"] == "high":
        events.append({
            "type": "weather",
            "severity": "warning",
            "text": "西部平原火险等级升至高",
        })
    coral_risk = public["coral_bleaching_risk"]
    if coral_risk in ("warning", "critical"):
        events.append({
            "type": "weather",
            "severity": "critical" if coral_risk == "critical" else "warning",
            "text": f"佩拉礁珊瑚白化风险为{coral_risk}",
        })
    return events


def _month_key(year: int, month: int) -> int:
    return year * 12 + month - 1


def _month_text(key: int) -> str:
    year, zero_based_month = divmod(key, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"
