"""Calendar-aware access to real monthly commodity observations."""

from __future__ import annotations

import csv
from bisect import bisect_right
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path


KG_TO_LB = 0.45359237
REQUIRED_COLUMNS = ("date", "sugar_usd_kg", "gold_usd_oz", "brent_usd_bbl")


class DataSourceError(RuntimeError):
    """Raised when commodity source data cannot satisfy the model contract."""


@dataclass(frozen=True)
class CommodityObservation:
    """A single immutable monthly commodity price observation."""

    month: str
    sugar_usd_lb: float
    gold_usd_oz: float
    brent_usd_barrel: float


@dataclass(frozen=True)
class CommoditySeries:
    """Sorted immutable commodity observations indexed by calendar month."""

    _month_keys: tuple[int, ...]
    _observations: tuple[CommodityObservation, ...]

    @classmethod
    def from_csv(cls, path: Path) -> CommoditySeries:
        """Load and validate monthly commodity observations from ``path``."""
        try:
            with path.open("r", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                headers = reader.fieldnames or []
                missing = [column for column in REQUIRED_COLUMNS if column not in headers]
                if missing:
                    raise DataSourceError(
                        f"commodity data is missing required column(s): {', '.join(missing)}"
                    )

                observations_by_key: dict[int, CommodityObservation] = {}
                for line_number, row in enumerate(reader, start=2):
                    observation = _parse_row(row, path, line_number)
                    key = _month_key_from_text(observation.month)
                    existing = observations_by_key.get(key)
                    if existing is not None and existing != observation:
                        raise DataSourceError(
                            f"conflicting observations for month {observation.month} in {path}"
                        )
                    observations_by_key[key] = observation
        except DataSourceError:
            raise
        except (OSError, UnicodeError) as exc:
            raise DataSourceError(f"cannot read commodity data from {path}: {exc}") from exc

        if not observations_by_key:
            raise DataSourceError(f"commodity data contains no observations: {path}")

        keys = tuple(sorted(observations_by_key))
        observations = tuple(observations_by_key[key] for key in keys)
        return cls(keys, observations)

    def lookup(self, d: date) -> CommodityObservation:
        """Return the final observation whose month is not later than ``d``."""
        index = bisect_right(self._month_keys, _month_key(d.year, d.month)) - 1
        if index < 0:
            raise DataSourceError(f"no commodity observation exists on or before {d.isoformat()}")
        return self._observations[index]


def commodities_step(
    d: date,
    previous_state: dict,
    series: CommoditySeries,
) -> tuple[dict, dict, list[dict]]:
    """Return public commodity values, next model state, and generated events."""
    del previous_state
    observation = series.lookup(d)
    source_year, source_month = map(int, observation.month.split("-"))
    source_month_end = date(
        source_year,
        source_month,
        monthrange(source_year, source_month)[1],
    )
    source_key = _month_key(source_year, source_month)
    requested_key = _month_key(d.year, d.month)

    public = {
        "sugar_usd_lb": observation.sugar_usd_lb,
        "gold_usd_oz": observation.gold_usd_oz,
        "brent_usd_barrel": observation.brent_usd_barrel,
        "source_month": observation.month,
        "staleness_days": max(0, (d - source_month_end).days),
        "is_stale": source_key != requested_key,
    }
    state = {"source_month": observation.month}
    return public, state, []


def _parse_row(row: dict[str, str | None], path: Path, line_number: int) -> CommodityObservation:
    try:
        month = row["date"] or ""
        _month_key_from_text(month)
        sugar_usd_kg = float(row["sugar_usd_kg"] or "")
        gold_usd_oz = float(row["gold_usd_oz"] or "")
        brent_usd_barrel = float(row["brent_usd_bbl"] or "")
        for column, value in (
            ("sugar_usd_kg", sugar_usd_kg),
            ("gold_usd_oz", gold_usd_oz),
            ("brent_usd_bbl", brent_usd_barrel),
        ):
            if not isfinite(value):
                raise DataSourceError(
                    f"invalid commodity observation at {path}:{line_number}: "
                    f"{column} must be finite"
                )

        sugar_usd_lb = sugar_usd_kg * KG_TO_LB
        if not isfinite(sugar_usd_lb):
            raise DataSourceError(
                f"invalid commodity observation at {path}:{line_number}: "
                "sugar_usd_lb must be finite after conversion"
            )

        return CommodityObservation(
            month=month,
            sugar_usd_lb=sugar_usd_lb,
            gold_usd_oz=gold_usd_oz,
            brent_usd_barrel=brent_usd_barrel,
        )
    except (TypeError, ValueError) as exc:
        raise DataSourceError(
            f"invalid commodity observation at {path}:{line_number}: {exc}"
        ) from exc


def _month_key_from_text(value: str) -> int:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise DataSourceError(f"invalid commodity month {value!r}") from exc
    if parsed.strftime("%Y-%m") != value:
        raise DataSourceError(f"invalid commodity month {value!r}")
    return _month_key(parsed.year, parsed.month)


def _month_key(year: int, month: int) -> int:
    return year * 12 + month
