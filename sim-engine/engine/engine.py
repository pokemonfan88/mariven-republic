#!/usr/bin/env python3
"""Deterministic daily orchestrator for the Mariven simulation engine."""

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from commodities_model import CommoditySeries, commodities_step
from events_model import events_step
from exchange_model import FxDataset, exchange_step
from inflation_model import inflation_step
from random_streams import make_rng
from state import prepare_state, validate_state
from weather_model import SoiSeries, weather_step


@dataclass(frozen=True)
class EngineResources:
    """Read-only data sources shared by daily model steps."""

    soi_series: SoiSeries
    fx_dataset: FxDataset
    commodity_series: CommoditySeries
    nation_profile: dict

    @classmethod
    def load(cls, data_dir: Path) -> "EngineResources":
        data_dir = Path(data_dir)
        with (data_dir / "nation_profile.json").open(
            "r", encoding="utf-8"
        ) as source:
            nation_profile = json.load(source)
        return cls(
            soi_series=SoiSeries.from_csv(data_dir / "soi_monthly.csv"),
            fx_dataset=FxDataset.from_directory(data_dir),
            commodity_series=CommoditySeries.from_csv(
                data_dir / "commodities_real.csv"
            ),
            nation_profile=nation_profile,
        )


def tick(
    previous_state: Mapping[str, Any],
    *,
    resources: EngineResources | None = None,
) -> dict:
    """Advance one day without mutating or persisting the input state."""
    prepared = prepare_state(previous_state)
    next_state = copy.deepcopy(prepared)
    d = date.fromisoformat(prepared["date"]) + timedelta(days=1)
    resources = resources or EngineResources.load(_default_data_dir())
    base_seed = prepared["base_seed"]
    schema_version = prepared["schema_version"]
    model_state = prepared["model_state"]

    def weather_rng(stream_name: str):
        return make_rng(
            base_seed, schema_version, d, "weather", stream_name
        )

    def event_rng(stream_name: str):
        return make_rng(
            base_seed, schema_version, d, "events", stream_name
        )

    weather, weather_state, weather_events = weather_step(
        d,
        model_state["weather"],
        resources.soi_series,
        weather_rng,
    )
    exchange, exchange_state, exchange_events = exchange_step(
        d,
        model_state["exchange"],
        resources.fx_dataset,
        make_rng(base_seed, schema_version, d, "exchange"),
    )
    commodities, commodity_state, commodity_events = commodities_step(
        d,
        model_state["commodities"],
        resources.commodity_series,
    )
    cpi, inflation_state, cpi_events = inflation_step(
        d,
        model_state["inflation"],
        weather,
        commodities,
        exchange,
        resources.nation_profile,
        make_rng(base_seed, schema_version, d, "inflation"),
    )
    deaths, general_events = events_step(
        d, prepared, weather, event_rng
    )

    next_state["date"] = d.isoformat()
    next_state["weather"] = weather

    economy = next_state["economy"]
    economy["exchange_rates"] = exchange
    economy["commodities"] = commodities
    economy["cpi"] = cpi
    economy["exchange_rate_mvl_per_usd"] = exchange["mvl_per_usd"]
    economy["fuel_95_price_mvl"] = cpi["fuel_95_price_mvl"]
    economy["fuel_diesel_price_mvl"] = cpi["fuel_diesel_price_mvl"]
    economy["inflation_pct"] = cpi["yoy_pct"]

    next_state["deaths_today"] = deaths
    next_state["model_state"] = {
        "weather": weather_state,
        "exchange": exchange_state,
        "commodities": commodity_state,
        "inflation": inflation_state,
    }

    combined_events = (
        weather_events
        + exchange_events
        + commodity_events
        + cpi_events
        + general_events
    )
    event_date = d.isoformat()
    next_state["events_today"] = [
        {**copy.deepcopy(event), "_date": event_date}
        for event in combined_events
    ]
    next_state["_meta"]["ticks_run"] = (
        prepared["_meta"].get("ticks_run", 0) + 1
    )
    validate_state(next_state)
    return next_state


def render_brief(state: Mapping[str, Any]) -> str:
    """Render the legacy Markdown daily brief from a simulation state."""
    d = date.fromisoformat(state["date"])
    weather = state["weather"]
    economy = state["economy"]
    deaths = state["deaths_today"]
    lines = [
        f"## {d.isoformat()} {_day_of_week_cn(d)}",
        "",
        (
            f"**天气** {weather['condition']} | "
            f"{weather['temp_low']}–{weather['temp_high']}°C | "
            f"湿度 {weather['humidity']}% | {weather['notes']}"
        ),
        (
            f"**经济** 通胀 {economy['inflation_pct']}% "
            f"失业 {economy['unemployment_pct']}% "
            f"汇率 {economy['exchange_rate_mvl_per_usd']} MVL/USD "
            f"95#汽油 ${economy['fuel_95_price_mvl']}"
        ),
    ]
    if deaths["total"] > 0:
        parts = [
            f"{key}={value}"
            for key, value in deaths.items()
            if value > 0 and key != "total"
        ]
        lines.append(
            f"**死亡** 共 {deaths['total']} 人（{' | '.join(parts)}）"
        )
    else:
        lines.append("**死亡** 无")
    if state["events_today"]:
        lines.extend(("", "**事件**"))
        lines.extend(f"- {event['text']}" for event in state["events_today"])
    lines.extend(("", "---"))
    return "\n".join(lines)


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _day_of_week_cn(d: date) -> str:
    return ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[
        d.weekday()
    ]
