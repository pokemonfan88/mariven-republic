import copy
import json
import math
from calendar import monthrange
from collections.abc import Mapping
from datetime import date
from numbers import Real
from typing import Any


SCHEMA_VERSION = 2

_CORE_DICTIONARIES = (
    "_meta",
    "weather",
    "economy",
    "government",
    "deaths_today",
    "model_state",
)
_MODEL_DICTIONARIES = ("weather", "exchange", "commodities", "inflation")
_CORE_ECONOMIC_VALUES = (
    "inflation_pct",
    "unemployment_pct",
    "interest_rate_pct",
    "exchange_rate_mvl_per_usd",
    "fuel_95_price_mvl",
    "fuel_diesel_price_mvl",
)


class StateValidationError(ValueError):
    """Raised when a simulation state does not match schema v2."""


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


def validate_state(state: Mapping[str, Any]) -> None:
    """Validate a schema-v2 state, raising an error with a field path."""
    if not isinstance(state, Mapping):
        _fail("state", "expected a dictionary")

    if state.get("schema_version") != SCHEMA_VERSION:
        _fail(
            "state.schema_version",
            f"expected {SCHEMA_VERSION}",
        )

    _parse_date(state.get("date"))

    population = _finite_number(
        state.get("population"), "state.population"
    )
    if population <= 0:
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


def migrate_state(raw: Mapping[str, Any], *,
                  base_seed: int | None = None) -> dict:
    """Deep-copy a v1 state and add deterministic schema-v2 model state."""
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

    migrated["schema_version"] = SCHEMA_VERSION
    migrated["base_seed"] = selected_seed
    migrated["model_state"] = model_state
    validate_state(migrated)
    return migrated


def prepare_state(raw: Mapping[str, Any]) -> dict:
    """Return an independent, validated schema-v2 state."""
    if not isinstance(raw, Mapping):
        _fail("state", "expected a dictionary")
    if "schema_version" not in raw:
        return migrate_state(raw)

    prepared = copy.deepcopy(dict(raw))
    validate_state(prepared)
    return prepared
