#!/usr/bin/env python3
"""Deterministic daily orchestrator for the Mariven simulation engine."""

import argparse
import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from archive import archive_day
from commodities_model import CommoditySeries, commodities_step
from events_model import events_step
from exchange_model import FxDataset, exchange_step
from gdp_model import (
    GdpBaseline, gdp_headline_growth, gdp_snapshot, gdp_step,
)
from inflation_model import inflation_step
from population_model import PopulationBaseline, population_step
from random_streams import make_rng
from state import prepare_state, validate_state
from weather_model import SoiSeries, weather_step


@dataclass(frozen=True)
class EngineResources:
    """Read-only data sources shared by daily model steps."""

    soi_series: SoiSeries
    fx_dataset: FxDataset
    commodity_series: CommoditySeries
    population_baseline: PopulationBaseline
    gdp_baseline: GdpBaseline
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
            population_baseline=PopulationBaseline.from_json(
                data_dir / "population_baseline_2026.json"
            ),
            gdp_baseline=GdpBaseline.from_json(
                data_dir / "gdp_baseline_2026.json"
            ),
            nation_profile=nation_profile,
        )


def tick(
    previous_state: Mapping[str, Any],
    *,
    resources: EngineResources | None = None,
) -> dict:
    """Advance one day without mutating or persisting the input state."""
    resources = resources or EngineResources.load(_default_data_dir())
    prepared = prepare_state(
        previous_state,
        population_baseline=resources.population_baseline,
        gdp_baseline=resources.gdp_baseline,
    )
    next_state = copy.deepcopy(prepared)
    d = date.fromisoformat(prepared["date"]) + timedelta(days=1)
    base_seed = prepared["base_seed"]
    legacy_random_schema_version = 2
    population_random_schema_version = 3
    model_state = prepared["model_state"]

    def weather_rng(stream_name: str):
        return make_rng(
            base_seed,
            legacy_random_schema_version,
            d,
            "weather",
            stream_name,
        )

    def event_rng(stream_name: str):
        return make_rng(
            base_seed,
            legacy_random_schema_version,
            d,
            "events",
            stream_name,
        )

    def population_rng(stream_name: str):
        return make_rng(
            base_seed,
            population_random_schema_version,
            d,
            "population",
            stream_name,
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
        make_rng(
            base_seed, legacy_random_schema_version, d, "exchange"
        ),
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
        make_rng(
            base_seed, legacy_random_schema_version, d, "inflation"
        ),
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

    gdp, gdp_state, gdp_events = gdp_step(
        d,
        model_state["gdp"],
        weather,
        cpi,
        commodities,
        exchange,
        prepared["population"],
        resources.gdp_baseline,
    )
    economy["gdp"] = gdp
    economy["gdp_growth_pct"] = gdp_headline_growth(
        gdp, resources.gdp_baseline
    )

    next_model_state = copy.deepcopy(prepared["model_state"])
    next_model_state.update({
        "weather": weather_state,
        "exchange": exchange_state,
        "commodities": commodity_state,
        "inflation": inflation_state,
        "gdp": gdp_state,
    })
    next_state["model_state"] = next_model_state

    notable_deaths, general_events = events_step(
        d, next_state, weather, event_rng
    )
    demographics, population_state, deaths, population_events = population_step(
        d,
        model_state["population"],
        notable_deaths,
        resources.population_baseline,
        population_rng,
    )
    next_state["population"] = demographics["population"]
    next_state["demographics"] = demographics
    next_state["deaths_today"] = deaths
    next_state["model_state"]["population"] = population_state
    refreshed_gdp = gdp_snapshot(
        d,
        gdp_state,
        demographics["population"],
        exchange,
        resources.gdp_baseline,
    )
    next_state["economy"]["gdp"] = refreshed_gdp
    next_state["economy"]["gdp_growth_pct"] = gdp_headline_growth(
        refreshed_gdp, resources.gdp_baseline
    )

    combined_events = (
        weather_events
        + exchange_events
        + commodity_events
        + cpi_events
        + gdp_events
        + population_events
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
    validate_state(
        next_state,
        population_baseline=resources.population_baseline,
        gdp_baseline=resources.gdp_baseline,
    )
    return next_state


def render_brief(state: Mapping[str, Any]) -> str:
    """Render the legacy Markdown daily brief from a simulation state."""
    d = date.fromisoformat(state["date"])
    weather = state["weather"]
    economy = state["economy"]
    deaths = state["deaths_today"]
    demographics = state.get("demographics")
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
    gdp = economy.get("gdp")
    if gdp is not None:
        annual = gdp["annual_nowcast"]
        current_quarter = gdp["current_quarter_nowcast"]
        latest = gdp["latest_release"]
        if latest is None:
            latest_text = "尚无季度正式值"
        elif latest["real_growth_yoy_pct"] is None:
            latest_text = (
                f"最新 {latest['period']} {latest['vintage']} "
                "基准期同比不适用"
            )
        else:
            latest_text = (
                f"最新 {latest['period']} {latest['vintage']} "
                f"实际同比 {latest['real_growth_yoy_pct']:.1f}%"
            )
        lines.append(
            f"**GDP** {current_quarter['period']} nowcast | "
            f"{latest_text} | 年度预测 "
            f"{annual['nominal_gdp_mvl'] / 1_000_000:.1f} 百万 MVL"
        )
    if demographics is not None:
        lines.append(
            f"**人口** {demographics['population']:,} | "
            f"出生 {demographics['births_today']} | "
            f"全因死亡 {demographics['deaths_all_causes_today']} | "
            f"净迁移 {demographics['net_migration_today']:+d} | "
            f"净变动 {demographics['population_change_today']:+d}"
        )
    if deaths["total"] > 0:
        notable_parts = [
            f"{key}={value}"
            for key in (
                "traffic",
                "drowning",
                "suicide",
                "murder",
                "workplace",
                "lightning",
                "other",
            )
            if (value := deaths.get(key, 0)) > 0
        ]
        death_summary = f"**死亡** 全因 {deaths['total']} 人"
        if deaths.get("notable_total", 0) > 0:
            death_summary += (
                f" | 显著 {deaths['notable_total']} 人"
                f"（{' | '.join(notable_parts)}）"
            )
        if deaths.get("non_notable", 0) > 0:
            death_summary += (
                f" | 其他疾病/自然 {deaths['non_notable']} 人"
            )
        if deaths.get("excess", 0) > 0:
            death_summary += f" | 超额 {deaths['excess']} 人"
        lines.append(death_summary)
    else:
        lines.append("**死亡** 无")
    if state["events_today"]:
        lines.extend(("", "**事件**"))
        lines.extend(f"- {event['text']}" for event in state["events_today"])
    lines.extend(("", "---"))
    return "\n".join(lines)


def run_days(
    state: Mapping[str, Any],
    days: int,
    resources: EngineResources,
) -> tuple[dict, list[dict]]:
    """Run a sequence of pure daily ticks and return every daily state."""
    current = copy.deepcopy(state)
    daily_states = []
    for _ in range(days):
        current = tick(current, resources=resources)
        daily_states.append(current)
    return current, daily_states


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--days must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Run the command-line simulation, optionally without persistence."""
    parser = argparse.ArgumentParser(
        description="Run the Mariven daily simulation"
    )
    parser.add_argument("--days", type=_positive_int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    state_path = data_dir / "state.json"
    archive_dir = root / "output" / "archive"
    db_path = root / "output" / "events.db"
    with state_path.open("r", encoding="utf-8") as source:
        initial_state = json.load(source)

    resources = EngineResources.load(data_dir)
    _, daily_states = run_days(initial_state, args.days, resources)
    for daily_state in daily_states:
        print(render_brief(daily_state))
        if not args.dry_run:
            archive_day(
                daily_state,
                state_path=state_path,
                archive_dir=archive_dir,
                db_path=db_path,
            )
    return 0


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _day_of_week_cn(d: date) -> str:
    return ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[
        d.weekday()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
