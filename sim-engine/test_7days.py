"""7-day engine output test."""
import json
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "engine"))
from engine import EngineResources, tick
from state import prepare_state

with open(
    Path(__file__).parent / "data" / "state.json",
    "r",
    encoding="utf-8",
) as f:
    raw = json.load(f)

state = prepare_state(raw)
resources = EngineResources.load(Path(__file__).parent / "data")
start = date.fromisoformat(state["date"])

print("=" * 70)
print(f"MARIVEN ENGINE v2 - 7-day output")
print(f"Start: {start}  Seed: {state['base_seed']}  Population: {state['population']:,}")
print("=" * 70)

for _ in range(7):
    state = tick(state, resources=resources)
    d = date.fromisoformat(state["date"])
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    w = state["weather"]
    e = state["economy"]
    ms = state["model_state"]
    k = w["katora"]

    print()
    print(f"{d} {days[d.weekday()]}")
    print(f"  Weather: {k['condition']} {k['temp_low']:.0f}-{k['temp_high']:.0f}C  RH{k['humidity']}%  {k['wind_dir']}{k['wind_kmh']}km/h  rain{k['rainfall_mm']}mm")
    print(f"  Pela: {w['pela']['condition']}  Ruwa: {w['ruwa']['condition']}")
    print(f"  Sun: {w['sunrise']}-{w['sunset']}  UV{k['uv']}  ENSO:{w['enso_status']}  SOI:{w['soi_value']}")
    print(f"  Risk: fire={w['fire_risk']}  coral={w['coral_bleaching_risk']}  cyclone={w['cyclone_risk']}  SST={w['sst_c']}C")

    print(f"  MVL/USD: {e['exchange_rate_mvl_per_usd']:.4f}  CPI: {ms['inflation']['published_yoy_pct']:.2f}%  95#: ${e['fuel_95_price_mvl']}")

    cm = e.get("commodities", {})
    if cm.get("sugar_usd_lb"):
        print(f"  sugar=${cm['sugar_usd_lb']:.4f}/lb  gold=${cm.get('gold_usd_oz','?'):.0f}/oz  brent=${cm.get('brent_usd_barrel','?'):.1f}")

    events = state.get("events_today", [])
    if events:
        print(f"  Events ({len(events)}):")
        for ev in events:
            print(f"    [{ev['type']}] {ev['text']}")

    deaths = state.get("deaths_today", {})
    if deaths.get("total", 0) > 0:
        parts = [f"{k}={v}" for k, v in deaths.items() if v > 0 and k != "total"]
        print(f"  Deaths: {deaths['total']} ({', '.join(parts)})")

print()
print("=" * 70)
print("7-day test complete")
