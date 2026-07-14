#!/usr/bin/env python3
"""
Mariven CPI Inflation Model — v1.0
===================================
月度消费者价格指数，基于加权篮子 + 上游模型联动。

篮子: 食品35% + 燃料18% + 住房15% + 交通12% + 其他20%
上游: 天气模型、商品模型、汇率模型
发布: 每月15日

输出:
  state["economy"]["inflation_pct"] = 2.40
  state["economy"]["fuel_95_price_mvl"] = 2.85
"""

import math
import random
from datetime import date, timedelta
from typing import Optional


# ═══════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════

BASKET = {
    "food":       0.35,
    "fuel":       0.18,
    "housing":    0.15,
    "transport":  0.12,
    "other":      0.20,
}

# Baseline inflation per component (annual %)
BASELINES = {
    "food":       2.5,
    "fuel":       3.0,
    "housing":    2.0,
    "transport":  2.0,
    "other":      2.0,
}

# Monthly weather normals for Katora (based on model calibration)
MONTHLY_RAIN_NORM = {
    1: 180, 2: 220, 3: 200, 4: 140, 5: 80, 6: 60,
    7: 55, 8: 60, 9: 70, 10: 95, 11: 130, 12: 170,
}

MONTHLY_TEMP_NORM = {
    1: 29, 2: 29, 3: 28, 4: 27, 5: 25, 6: 24,
    7: 23, 8: 24, 9: 25, 10: 26, 11: 27, 12: 28,
}

# Fuel price formula: (brent_usd × mvl_per_usd) / 159 + tax + margin
# Reference: brent=82.5, MVL=2.18 → pump ≈ 2.85 MVL/L
FUEL_TAX_MVL = 1.02      # excise + carbon tax per litre
FUEL_MARGIN_MVL = 0.70   # retail + distribution margin
BARREL_TO_LITRE = 158.98


# ═══════════════════════════════════════════════════
# CPI MODEL CLASS
# ═══════════════════════════════════════════════════

class InflationModel:
    """月度通胀计算器，依赖天气、商品、汇率上游模型。"""

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self._cpi = 2.40          # current CPI (annual %)
        self._prev_cpi = 2.40     # last month's published CPI
        self._fuel_95 = 2.85      # pump price MVL/L
        self._fuel_diesel = 2.35
        self._last_date: Optional[date] = None
        self._food_history: list[float] = []  # rolling 30-day food delta
        self._last_published_month: Optional[int] = None  # track when CPI was last "released"

    def compute_pump_price(self, brent_usd: float, mvl_per_usd: float) -> tuple[float, float]:
        """Calculate retail fuel price from Brent crude + exchange rate."""
        crude_cost_mvl = (brent_usd * mvl_per_usd) / BARREL_TO_LITRE
        petrol_95 = round(crude_cost_mvl + FUEL_TAX_MVL + FUEL_MARGIN_MVL, 2)
        diesel = round(crude_cost_mvl + FUEL_TAX_MVL * 0.4 + FUEL_MARGIN_MVL * 0.7, 2)
        return petrol_95, diesel

    def food_inflation(self, weather: dict) -> float:
        """
        Calculate food inflation from accumulated weather stress.
        Uses rolling 30-day average of daily weather deviation.
        """
        katora = weather.get("katora", {})
        rain_mm = katora.get("rainfall_mm", 0)
        temp = katora.get("temp_high", 25)
        month = self._last_date.month if self._last_date else 7

        rain_norm = MONTHLY_RAIN_NORM.get(month, 80)
        temp_norm = MONTHLY_TEMP_NORM.get(month, 26)

        # Daily food stress (this is tiny per day, accumulates over 30 days)
        rain_dev = (rain_mm - rain_norm) / max(rain_norm, 1)
        if rain_dev < 0:
            rain_impact = abs(rain_dev) * 0.08  # drought impact per day
        else:
            rain_impact = min(rain_dev * 0.02, 0.03)

        temp_dev = (temp - temp_norm) * 0.02

        daily_delta = rain_impact + temp_dev

        # Rolling 30-day average
        self._food_history.append(daily_delta)
        if len(self._food_history) > 30:
            self._food_history.pop(0)
        avg_delta = sum(self._food_history) / len(self._food_history)

        return BASELINES["food"] + avg_delta

    def fuel_inflation(self, brent_usd: float, mvl_per_usd: float) -> float:
        """Fuel inflation driven by crude oil and exchange rate changes."""
        # Reference: brent=82.5, MVL=2.18 → base pump price ≈ 2.85
        base_pump = (82.5 * 2.18) / BARREL_TO_LITRE + FUEL_TAX_MVL + FUEL_MARGIN_MVL
        current_pump = (brent_usd * mvl_per_usd) / BARREL_TO_LITRE + FUEL_TAX_MVL + FUEL_MARGIN_MVL
        return BASELINES["fuel"] + (current_pump - base_pump) / base_pump * 100

    def housing_inflation(self, urban_rate: float = 48.0) -> float:
        """Housing inflation: driven by urbanization + import costs."""
        # Baseline urbanization 48% → if growing, housing pressure increases
        urban_pressure = max(0, urban_rate - 48.0) * 0.08
        # Import cost pass-through (cement, steel from AUD zone)
        import_pass = random.gauss(0, 0.15)
        return BASELINES["housing"] + urban_pressure + import_pass

    def transport_inflation(self, fuel_inf: float) -> float:
        """Transport inflation: 80% driven by fuel costs."""
        return BASELINES["transport"] + (fuel_inf - BASELINES["fuel"]) * 0.80

    def tick(self, d: date,
             weather: Optional[dict] = None,
             commodities: Optional[dict] = None,
             exchange: Optional[dict] = None) -> dict:
        """
        Compute monthly CPI.

        Args:
            d: current date
            weather: weather model output (katora dict)
            commodities: commodity model output (sugar_usd_lb, gold_usd_oz, brent_usd_barrel)
            exchange: exchange model output (mvl_per_usd, aud_usd, ...)
        """
        self._last_date = d

        brent = commodities.get("brent_usd_barrel", 82.5) if commodities else 82.5
        mvl = exchange.get("mvl_per_usd", 2.18) if exchange else 2.18

        food = self.food_inflation(weather or {})
        fuel = self.fuel_inflation(brent, mvl)
        housing = self.housing_inflation()
        transport = self.transport_inflation(fuel)
        other = BASELINES["other"] + random.gauss(0, 0.1)

        cpi = (BASKET["food"] * food +
               BASKET["fuel"] * fuel +
               BASKET["housing"] * housing +
               BASKET["transport"] * transport +
               BASKET["other"] * other)

        # Apply smoothing (CPI doesn't jump wildly in one month)
        cpi = 0.85 * self._cpi + 0.15 * cpi + random.gauss(0, 0.02)
        self._cpi = round(cpi, 2)

        petrol_95, diesel = self.compute_pump_price(brent, mvl)
        self._fuel_95 = petrol_95
        self._fuel_diesel = diesel

        # ── Monthly release logic ──
        # CPI is "published" on the 15th of each month by Statistics Bureau
        is_release_day = (d.day == 15)
        if is_release_day and self._last_published_month != d.month:
            self._prev_cpi = self._cpi
            self._last_published_month = d.month

        cpi_yoy = round(self._cpi - self._prev_cpi, 2)  # month-over-month change

        return {
            "inflation_pct": self._cpi,
            "inflation_prev_month": self._prev_cpi,
            "inflation_mom_change": cpi_yoy,
            "is_release_day": is_release_day,
            "food_inflation": round(food, 2),
            "fuel_inflation": round(fuel, 2),
            "housing_inflation": round(housing, 2),
            "transport_inflation": round(transport, 2),
            "other_inflation": round(other, 2),
            "fuel_95_price_mvl": self._fuel_95,
            "fuel_diesel_price_mvl": self._fuel_diesel,
        }


# ═══════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    m = InflationModel(seed=42)

    # Simulate a dry July day
    weather_sample = {
        "katora": {"rainfall_mm": 10, "temp_high": 27, "condition": "晴"},
    }
    commod_sample = {"brent_usd_barrel": 82.5}
    exchange_sample = {"mvl_per_usd": 2.18}

    print("═" * 60)
    print("MARIVEN CPI MODEL — 基准测试 (2026年7月)")
    print("═" * 60)
    r = m.tick(date(2026, 7, 14), weather_sample, commod_sample, exchange_sample)
    print(f"  总CPI: {r['inflation_pct']}% | 上月: {r['inflation_prev_month']}% | 月环比: {r['inflation_mom_change']:+.2f}%")
    print(f"  发布日: {'是 ✅' if r['is_release_day'] else '否 (每月15日发布)'}")
    print(f"  食品: {r['food_inflation']}%  | 燃料: {r['fuel_inflation']}%  | 住房: {r['housing_inflation']}%")
    print(f"  交通: {r['transport_inflation']}%  | 其他: {r['other_inflation']}%")
    print(f"  95#汽油: ${r['fuel_95_price_mvl']} MVL/L  | 柴油: ${r['fuel_diesel_price_mvl']} MVL/L")

    print()
    print("情景1: 干旱7月 (降雨5mm, 温度29°C)")
    w = {"katora": {"rainfall_mm": 5, "temp_high": 29, "condition": "晴"}}
    r = m.tick(date(2026, 7, 15), w, commod_sample, exchange_sample)
    print(f"  总CPI: {r['inflation_pct']}% 食品: {r['food_inflation']}% ← 干旱推高食品")

    print()
    print("情景2: 油价飙升 (布伦特 $95)")
    c = {"brent_usd_barrel": 95.0}
    r = m.tick(date(2026, 7, 16), weather_sample, c, exchange_sample)
    print(f"  总CPI: {r['inflation_pct']}% 燃料: {r['fuel_inflation']}% 汽油: ${r['fuel_95_price_mvl']} ← 油价传导")

    print()
    print("情景3: 汇率贬值 (MVL 2.35/USD)")
    e = {"mvl_per_usd": 2.35}
    r = m.tick(date(2026, 7, 17), weather_sample, commod_sample, e)
    print(f"  总CPI: {r['inflation_pct']}% 汽油: ${r['fuel_95_price_mvl']} ← 进口成本上升")

    print()
    print("情景4: 15日发布日 (统计局公布上月CPI)")
    r = m.tick(date(2026, 8, 15), weather_sample, commod_sample, exchange_sample)
    print(f"  总CPI: {r['inflation_pct']}% | 上月: {r['inflation_prev_month']}% | 环比: {r['inflation_mom_change']:+.2f}%")
    print(f"  发布日: {'是 ✅ 统计局发布新闻' if r['is_release_day'] else '否'}")
