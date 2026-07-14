"""Calendar-aware basket exchange-rate model for Mariven."""

from __future__ import annotations

import csv
import math
from bisect import bisect_right
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path


BASE_MVL_USD = 2.18
BASKET_WEIGHTS = {
    "AUD": 0.40,
    "NZD": 0.25,
    "USD": 0.20,
    "CNY": 0.10,
    "EUR": 0.05,
}

_SOURCE_FILES = {
    "AUD": ("aud_usd.csv", "EXUSAL", False),
    "NZD": ("nzd_usd.csv", "EXUSNZ", False),
    "CNY": ("usd_cny.csv", "EXCHUS", True),
    "EUR": ("eur_usd.csv", "EXUSEU", False),
}


class FxDataError(RuntimeError):
    """Raised when source exchange-rate data cannot satisfy the model contract."""


@dataclass(frozen=True)
class _FxSeries:
    month_keys: tuple[int, ...]
    months: tuple[str, ...]
    rates: tuple[float, ...]

    def rate_for(self, d: date) -> tuple[float, str]:
        index = bisect_right(self.month_keys, _month_key(d.year, d.month)) - 1
        if index < 0:
            raise FxDataError(
                f"no exchange-rate observation exists on or before {d.isoformat()}"
            )
        return self.rates[index], self.months[index]


@dataclass(frozen=True)
class FxDataset:
    """Canonical USD-per-currency exchange-rate series and calibration quotes."""

    _series: dict[str, _FxSeries]
    base_rates: dict[str, float]
    calibration_month: str

    @classmethod
    def from_directory(cls, data_dir: Path) -> FxDataset:
        """Load all exchange-rate sources and calibrate their latest common month."""
        series = {
            currency: _load_series(data_dir / filename, column, invert)
            for currency, (filename, column, invert) in _SOURCE_FILES.items()
        }

        common_keys = set.intersection(
            *(set(currency_series.month_keys) for currency_series in series.values())
        )
        if not common_keys:
            raise FxDataError("exchange-rate series have no common calibration month")

        calibration_key = max(common_keys)
        calibration_month = _month_text(calibration_key)
        base_rates = {"USD": 1.0}
        for currency, currency_series in series.items():
            index = bisect_right(currency_series.month_keys, calibration_key) - 1
            if currency_series.month_keys[index] != calibration_key:
                raise FxDataError(
                    f"missing {currency} quote for calibration month {calibration_month}"
                )
            base_rates[currency] = currency_series.rates[index]

        return cls(series, base_rates, calibration_month)

    def rates_for(self, d: date) -> tuple[dict[str, float], dict[str, str]]:
        """Return the latest canonical quotes not later than ``d`` and source months."""
        rates = {"USD": 1.0}
        source_months = {}
        for currency, series in self._series.items():
            rate, source_month = series.rate_for(d)
            rates[currency] = rate
            source_months[currency] = source_month
        return rates, source_months


def exchange_step(
    d: date,
    previous_state: dict,
    dataset: FxDataset,
    rng,
) -> tuple[dict, dict, list[dict]]:
    """Return public exchange rates, explicit next state, and generated events."""
    rates, source_months = dataset.rates_for(d)
    log_move = sum(
        BASKET_WEIGHTS[currency]
        * math.log(rates[currency] / dataset.base_rates[currency])
        for currency in BASKET_WEIGHTS
    )
    target = BASE_MVL_USD * math.exp(log_move)
    previous = float(previous_state.get("mvl_per_usd", BASE_MVL_USD))
    next_rate = previous + 0.12 * (target - previous) + rng.gauss(0.0, 0.0025)
    next_rate = min(2.80, max(1.80, next_rate))

    public = {
        "mvl_per_usd": next_rate,
        "mvl_per_aud": next_rate * rates["AUD"],
        "mvl_per_nzd": next_rate * rates["NZD"],
        "mvl_per_cny": next_rate * rates["CNY"],
        "mvl_per_eur": next_rate * rates["EUR"],
        "usd_per_aud": rates["AUD"],
        "usd_per_nzd": rates["NZD"],
        "usd_per_cny": rates["CNY"],
        "usd_per_eur": rates["EUR"],
        "source_months": source_months,
        "staleness_days": max(
            _staleness_days(d, source_month) for source_month in source_months.values()
        ),
    }
    next_state = {"mvl_per_usd": next_rate}
    return public, next_state, []


def _load_series(path: Path, column: str, invert: bool) -> _FxSeries:
    observations: dict[int, tuple[str, float]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            headers = reader.fieldnames or []
            if "observation_date" not in headers or column not in headers:
                raise FxDataError(
                    f"exchange-rate data is missing required columns in {path}"
                )

            for line_number, row in enumerate(reader, start=2):
                raw_value = row.get(column) or ""
                if not raw_value or raw_value == ".":
                    continue
                month = _parse_month(row.get("observation_date") or "", path, line_number)
                try:
                    source_rate = float(raw_value)
                except ValueError as exc:
                    raise FxDataError(
                        f"invalid exchange-rate observation at {path}:{line_number}"
                    ) from exc
                if not math.isfinite(source_rate) or source_rate <= 0.0:
                    raise FxDataError(
                        f"invalid exchange-rate observation at {path}:{line_number}"
                    )
                canonical_rate = 1.0 / source_rate if invert else source_rate
                key = _month_key_from_text(month)
                existing = observations.get(key)
                if existing is not None and existing != (month, canonical_rate):
                    raise FxDataError(f"conflicting observations for month {month} in {path}")
                observations[key] = (month, canonical_rate)
    except FxDataError:
        raise
    except (OSError, UnicodeError) as exc:
        raise FxDataError(f"cannot read exchange-rate data from {path}: {exc}") from exc

    if not observations:
        raise FxDataError(f"exchange-rate data contains no observations: {path}")
    keys = tuple(sorted(observations))
    return _FxSeries(
        month_keys=keys,
        months=tuple(observations[key][0] for key in keys),
        rates=tuple(observations[key][1] for key in keys),
    )


def _parse_month(value: str, path: Path, line_number: int) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FxDataError(
            f"invalid exchange-rate month at {path}:{line_number}: {value!r}"
        ) from exc
    if parsed.day != 1 or parsed.isoformat() != value:
        raise FxDataError(
            f"invalid exchange-rate month at {path}:{line_number}: {value!r}"
        )
    return parsed.strftime("%Y-%m")


def _month_key_from_text(value: str) -> int:
    year, month = map(int, value.split("-"))
    return _month_key(year, month)


def _month_key(year: int, month: int) -> int:
    return year * 12 + month


def _month_text(key: int) -> str:
    year, zero_based_month = divmod(key - 1, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def _staleness_days(d: date, source_month: str) -> int:
    source_year, source_month_number = map(int, source_month.split("-"))
    source_month_end = date(
        source_year,
        source_month_number,
        monthrange(source_year, source_month_number)[1],
    )
    return max(0, (d - source_month_end).days)
