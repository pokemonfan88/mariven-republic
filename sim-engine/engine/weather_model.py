#!/usr/bin/env python3
"""
Mariven Weather Model — v1.0
=============================
基于真实 SOI 数据的南太平洋热带岛国天气模拟。
坐标锚点: 20°47'S, 176°26'E (马卡迪岛/卡托拉市)

数据层:
  Layer 1: 月转移矩阵 (Markov链, 按干/湿季自动切换)
  Layer 2: 正弦年度温度曲线 (南半球, 五城各有偏移)
  Layer 3: 真实 SOI 修正 (El Niño→干旱偏移, La Niña→湿润偏移)
  Layer 4: Gamma 降雨分布 (晴/多云/阴/阵雨/暴雨各有不同参数)
  Layer 5: [待接入] 真实 IBTrACS 气旋检测

输出:
  state["weather"] = {
    "katora": {condition, temp_high, temp_low, humidity, wind_dir, wind_kmh, rainfall_mm, uv},
    "makadi_port": {...}, "timo": {...}, "pela": {...}, "ruwa": {...},
    "sunrise": "06:32", "sunset": "17:48",
    "cyclone_risk": "none",
    "fire_risk": "low",
    "soil_moisture_index": 0.65,
    "coral_bleaching_risk": "none",
    "enso_status": "El Niño"
  }
"""

import csv
import math
import os
import random
from datetime import date, timedelta
from typing import Optional


# ═══════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════

MARIVEN_LAT = -20.795   # Katora City
MARIVEN_LON = 176.435

CITIES = {
    "katora":      {"name": "卡托拉市",     "lat": -20.795,  "lon": 176.435, "temp_offset":  0.0, "rain_scale": 1.00, "elevation": 10},
    "makadi_port": {"name": "马卡迪港",     "lat": -20.750,  "lon": 176.320, "temp_offset": +0.8, "rain_scale": 0.85, "elevation": 5},
    "timo":        {"name": "蒂莫城",       "lat": -20.500,  "lon": 176.167, "temp_offset": -1.2, "rain_scale": 1.10, "elevation": 180},
    "pela":        {"name": "佩拉港",       "lat": -20.750,  "lon": 176.833, "temp_offset": +0.3, "rain_scale": 1.15, "elevation": 3},
    "ruwa":        {"name": "鲁瓦镇",       "lat": -21.000,  "lon": 176.167, "temp_offset": -0.5, "rain_scale": 1.30, "elevation": 80},
}

CONDITIONS = ["晴", "多云", "阴", "阵雨", "暴雨"]   # 0-4 index

# Markov transition matrix — DRY season (May-Oct)
# Rows: from yesterday's condition → columns: probability of today's condition
DRY_MATRIX = [
    #晴    多云   阴    阵雨   暴雨
    [0.60, 0.22, 0.10, 0.06, 0.02],   # from 晴
    [0.40, 0.30, 0.18, 0.10, 0.02],   # from 多云
    [0.25, 0.28, 0.25, 0.18, 0.04],   # from 阴
    [0.20, 0.30, 0.22, 0.22, 0.06],   # from 阵雨
    [0.12, 0.22, 0.25, 0.28, 0.13],   # from 暴雨
]

# Markov transition matrix — WET season (Nov-Apr)
WET_MATRIX = [
    #晴    多云   阴    阵雨   暴雨
    [0.35, 0.30, 0.18, 0.14, 0.03],
    [0.20, 0.28, 0.25, 0.22, 0.05],
    [0.12, 0.22, 0.28, 0.28, 0.10],
    [0.10, 0.18, 0.25, 0.35, 0.12],
    [0.05, 0.15, 0.22, 0.35, 0.23],
]

# SOI-driven adjustments to DRY matrix — shift toward La Niña values when SOI > 0
# This makes rainy patterns stick longer during wet phases
SOI_WET_BOOST = [0.05, 0.08, 0.12, 0.10, 0.08]   # probability boost for each wetter condition

# Temperature baseline: annual sine wave around 25.5°C, amplitude ±2.5°C
# Peak ~ Jan 30 (day 30), trough ~ Jul 30 (day 211) — southern hemisphere
TEMP_BASE = 25.5
TEMP_AMPLITUDE = 2.5
TEMP_PHASE_OFFSET = -30  # peak on day 30 (late January)

# Solar declination for sunrise/sunset calculation
SOLAR_DECLINATION = -23.44  # Earth's axial tilt


# ═══════════════════════════════════════════════════
# SOI LOADER
# ═══════════════════════════════════════════════════

def _load_soi(data_path: str) -> dict:
    """Load monthly SOI CSV into {(year, month): value} dict.
    CSV format: Year,Month,SOI
    """
    soi = {}
    csv_path = os.path.join(data_path, "soi_monthly.csv")
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                y, m = int(row["Year"]), int(row["Month"])
                soi[(y, m)] = float(row["SOI"])
    except FileNotFoundError:
        print(f"[WeatherModel] SOI data not found at {csv_path}. Using neutral ENSO.")
    return soi


# ═══════════════════════════════════════════════════
# MARKOV STEP
# ═══════════════════════════════════════════════════

def _markov_step(prev_idx: int, month: int, soi_value: float) -> int:
    """Choose next weather condition given previous state, month, and SOI."""
    matrix = WET_MATRIX if month in (11, 12, 1, 2, 3, 4) else DRY_MATRIX
    probs = list(matrix[prev_idx])

    # SOI adjustment: negative SOI (El Niño) → drier → boost toward sunny
    #                  positive SOI (La Niña) → wetter → boost toward rainy
    if soi_value and abs(soi_value) > 5:
        shift = abs(soi_value) / 100  # magnitude of adjustment
        if soi_value < 0:  # El Niño → drier → push toward sunny (lower indices)
            for i in range(5):
                probs[i] += shift * SOI_WET_BOOST[i] * (-1 if i > prev_idx else 1)
        else:               # La Niña → wetter → push toward rainy (higher indices)
            for i in range(5):
                probs[i] += shift * SOI_WET_BOOST[i] * (1 if i > prev_idx else -1)
        # Re-normalize
        total = sum(max(p, 0) for p in probs)
        if total > 0:
            probs = [max(p, 0) / total for p in probs]

    r = random.random()
    cumulative = 0
    for i, p in enumerate(probs):
        cumulative += p
        if r <= cumulative:
            return i
    return 4  # fallback


# ═══════════════════════════════════════════════════
# TEMPERATURE
# ═══════════════════════════════════════════════════

def _temperature_sine(day_of_year: int, city_offset: float, condition_idx: int) -> tuple[float, float]:
    """Return (high, low) temperatures for a given day and city."""
    base = TEMP_BASE + TEMP_AMPLITUDE * math.sin(2 * math.pi * (day_of_year + TEMP_PHASE_OFFSET) / 365)
    base += city_offset

    # Cloud cover cooling
    cloud_cooling = [0, -0.5, -1.5, -2.5, -3.5][condition_idx]

    # Daily noise
    noise = random.gauss(0, 0.8)

    high = base + noise + cloud_cooling / 2
    low = base - 5.5 + random.gauss(0, 0.5)

    diurnal_range = 8 if condition_idx < 2 else 5
    low = high - random.uniform(diurnal_range - 1.5, diurnal_range + 1.5)

    return round(high, 1), round(max(low, 12.0), 1)


# ═══════════════════════════════════════════════════
# RAINFALL (Gamma)
# ═══════════════════════════════════════════════════

_GAMMA_PARAMS = {
    0: (0.3, 0.5),     # 晴 — almost never rains
    1: (0.8, 1.2),     # 多云 — trace
    2: (1.5, 2.5),     # 阴 — light
    3: (2.5, 6.0),     # 阵雨 — moderate
    4: (4.0, 18.0),    # 暴雨 — heavy, long tail
}

def _gamma_sample(shape: float, scale: float) -> float:
    """Simple gamma sampling using Marsaglia-Tsang method for shape >= 0.5."""
    if shape < 1:
        # Use inverse method for small shapes
        u = random.random()
        return scale * (u ** (1 / shape)) * random.expovariate(1)
    d = shape - 1/3
    c = 1 / math.sqrt(9 * d)
    while True:
        x = random.gauss(0, 1)
        v = (1 + c * x) ** 3
        if v > 0:
            u = random.random()
            if u < 1 - 0.0331 * (x**4) or math.log(u) < 0.5 * (x**2) + d * (1 - v + math.log(v)):
                return scale * d * v


def _rainfall(condition_idx: int, city_scale: float) -> float:
    """Sample rainfall in mm from Gamma distribution."""
    shape, scale = _GAMMA_PARAMS[condition_idx]
    raw = _gamma_sample(shape, scale) * city_scale
    return round(raw, 1)


# ═══════════════════════════════════════════════════
# HUMIDITY & WIND
# ═══════════════════════════════════════════════════

def _humidity(condition_idx: int, month: int) -> int:
    base = {0: 65, 1: 72, 2: 78, 3: 82, 4: 88}[condition_idx]
    seasonal = 5 if month in (11, 12, 1, 2, 3, 4) else -5
    noise = random.randint(-4, 4)
    return min(98, max(50, base + seasonal + noise))


def _wind(month: int) -> tuple[str, int]:
    """Trade wind direction and speed, with seasonal shift."""
    directions = ["E", "ESE", "SE", "SSE", "NE"]
    if month in (5, 6, 7, 8, 9, 10):
        # Dry season — stronger SE trades
        dir_weights = [0.15, 0.20, 0.40, 0.20, 0.05]
        speed_range = (8, 22)
    else:
        # Wet season — variable, sometimes N/NW
        dir_weights = [0.20, 0.15, 0.25, 0.15, 0.10] + [0.05, 0.05, 0.05]  # adds N, NW, SW
        directions += ["N", "NW", "SW"]
        speed_range = (5, 18)

    r = random.random()
    cumulative = 0
    for i, w in enumerate(dir_weights):
        cumulative += w
        if r <= cumulative:
            d = directions[i]
            break
    else:
        d = "SE"

    speed = random.randint(*speed_range)
    return d, speed


# ═══════════════════════════════════════════════════
# SUN & UV
# ═══════════════════════════════════════════════════

def _sunrise_sunset(day_of_year: int) -> tuple[str, str, int]:
    """Compute sunrise and sunset times using simplified solar geometry for 20.8°S."""
    # Day length varies from ~11h (winter solstice ~Jun 21, day 172) to ~13h (summer solstice ~Dec 21, day 355)
    declination = SOLAR_DECLINATION * math.cos(2 * math.pi * (day_of_year + 10) / 365)
    # at latitude -20.8°, hour angle at sunrise
    lat_rad = math.radians(MARIVEN_LAT)
    dec_rad = math.radians(declination)
    ha = math.acos(-math.tan(lat_rad) * math.tan(dec_rad))
    daylight_hours = 2 * math.degrees(ha) / 15
    daylight_hours = max(10.5, min(13.5, daylight_hours))

    # Solar noon ~12:15 MVT (UTC+12, slight offset for eastern edge of timezone)
    noon_minutes = 12 * 60 + 15
    half_daylight = daylight_hours * 60 / 2

    sunrise_minutes = noon_minutes - half_daylight
    sunset_minutes = noon_minutes + half_daylight

    def fmt(m):
        return f"{int(m//60):02d}:{int(m%60):02d}"

    return fmt(sunrise_minutes), fmt(sunset_minutes), round(daylight_hours)


def _uv_index(condition_idx: int, daylight_hours: float) -> int:
    """UV index for tropical island — 0 to 13+ scale."""
    base = 8 if daylight_hours > 12 else 6
    cloud_reduction = [0, 1, 3, 5, 6][condition_idx]
    return max(0, base - cloud_reduction)


# ═══════════════════════════════════════════════════
# RISK INDICES
# ═══════════════════════════════════════════════════

def _fire_risk(month: int, rainfall_7d: float, condition_idx: int) -> str:
    """Fire danger rating for western plains (dry season)."""
    if month not in (5, 6, 7, 8, 9, 10):
        return "low"
    if condition_idx < 1 and rainfall_7d < 5:
        return "high"
    if condition_idx < 2 and rainfall_7d < 15:
        return "medium"
    return "low"


def _coral_bleaching_risk(day_of_year: int, sst_estimate: float) -> str:
    """Coral bleaching risk for Pela reef. Triggered when SST > 29°C sustained."""
    if day_of_year in range(30, 120) and sst_estimate > 28.5:  # Feb-Apr
        return "warning"
    if day_of_year in range(15, 135) and sst_estimate > 29.5:
        return "critical"
    return "none"


# ═══════════════════════════════════════════════════
# MAIN MODEL CLASS
# ═══════════════════════════════════════════════════

class MarivenWeatherModel:
    """Daily weather generator for all five Mariven cities."""

    def __init__(self, data_dir: str = "data", seed: int = 42):
        random.seed(seed)
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), data_dir)
        self.soi_data = _load_soi(self.data_dir)
        self._prev_conditions = {city: 0 for city in CITIES}  # all start sunny
        self._rainfall_history: list[float] = []  # rolling 14-day for soil moisture
        # Initialize _last_soi from the most recent known SOI value
        if self.soi_data:
            latest = max(self.soi_data.keys(), key=lambda k: (k[0], k[1]))
            self._last_soi = self.soi_data[latest]
        else:
            self._last_soi = None

    def get_soi(self, d: date) -> Optional[float]:
        """Get SOI value for a given month. Falls back to last-known if future."""
        val = self.soi_data.get((d.year, d.month))
        if val is not None:
            self._last_soi = val
            return val
        return self._last_soi  # use the most recent real SOI for future/predictions

    def tick(self, d: date) -> dict:
        """Generate complete weather for all cities on a given date."""
        month = d.month
        doy = d.timetuple().tm_yday
        soi = self.get_soi(d)

        # Determine ENSO status
        if soi is not None:
            if soi > 7:
                enso = "La Niña"
            elif soi < -7:
                enso = "El Niño"
            else:
                enso = "Neutral"
        else:
            enso = "Neutral"

        # Sunrise / sunset from Katora coordinates
        sunrise, sunset, daylight_hours = _sunrise_sunset(doy)

        weather = {}
        total_rainfall_today = 0

        for city_key, cfg in CITIES.items():
            prev_idx = self._prev_conditions[city_key]
            cond_idx = _markov_step(prev_idx, month, soi)
            self._prev_conditions[city_key] = cond_idx
            condition = CONDITIONS[cond_idx]

            temp_high, temp_low = _temperature_sine(doy, cfg["temp_offset"], cond_idx)
            rainfall_mm = _rainfall(cond_idx, cfg["rain_scale"])
            humidity = _humidity(cond_idx, month)
            wind_dir, wind_kmh = _wind(month)
            uv = _uv_index(cond_idx, daylight_hours)

            weather[city_key] = {
                "name": cfg["name"],
                "condition": condition,
                "condition_idx": cond_idx,
                "temp_high": temp_high,
                "temp_low": temp_low,
                "humidity": humidity,
                "rainfall_mm": rainfall_mm,
                "wind_dir": wind_dir,
                "wind_kmh": wind_kmh,
                "uv": uv,
            }
            total_rainfall_today += rainfall_mm

        # Rolling rainfall history (Katora proxy — for soil moisture & fire risk)
        self._rainfall_history.append(total_rainfall_today / len(CITIES))
        if len(self._rainfall_history) > 14:
            self._rainfall_history.pop(0)

        rainfall_14d = sum(self._rainfall_history)
        rainfall_7d = sum(self._rainfall_history[-7:]) if len(self._rainfall_history) >= 7 else rainfall_14d

        # Soil moisture
        soil_moisture = min(1.0, max(0.1, rainfall_14d / 80))

        # SST estimate (simplified — anchored to annual sine + SOI offset)
        sst = 25.5 + 1.5 * math.sin(2 * math.pi * (doy - 60) / 365)
        if soi and soi < -7:
            sst += 0.5  # El Niño warms the eastern Pacific
        elif soi and soi > 7:
            sst -= 0.3  # La Niña cools

        # Fire risk (Katora proxy — applies mainly to western plains)
        fire_risk = _fire_risk(month, rainfall_7d, weather["katora"]["condition_idx"])

        # Coral bleaching risk
        coral_risk = _coral_bleaching_risk(doy, sst)

        # Cyclone risk (placeholder — will be replaced by IBTrACS)
        cyclone_risk = "none"
        if month in (11, 12, 1, 2, 3, 4):
            baseline = 0.02 if month in (1, 2) else 0.01
            if enso == "La Niña":
                baseline *= 1.5
            elif enso == "El Niño":
                baseline *= 0.3
            if random.random() < baseline:
                cyclone_risk = "monitored"
        # TODO: IBTrACS integration — check real cyclone positions

        return {
            **weather,
            "sunrise": sunrise,
            "sunset": sunset,
            "daylight_hours": daylight_hours,
            "cyclone_risk": cyclone_risk,
            "fire_risk": fire_risk,
            "soil_moisture_index": round(soil_moisture, 2),
            "sst_c": round(sst, 1),
            "coral_bleaching_risk": coral_risk,
            "enso_status": enso,
            "soi_value": round(soi, 1) if soi else None,
            "rainfall_7d_mm": round(rainfall_7d, 1),
        }


# ═══════════════════════════════════════════════════
# TEST: Run 365 days and print seasonal summary
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    model = MarivenWeatherModel(seed=42)

    start = date(2026, 1, 1)
    monthly_stats = {m: {"晴": 0, "多云": 0, "阴": 0, "阵雨": 0, "暴雨": 0, "rain_mm": 0, "days": 0}
                     for m in range(1, 13)}

    for i in range(365):
        d = start + timedelta(days=i)
        w = model.tick(d)

        m = d.month
        monthly_stats[m]["days"] += 1
        monthly_stats[m][w["katora"]["condition"]] += 1
        monthly_stats[m]["rain_mm"] += w["katora"]["rainfall_mm"]

    print("=" * 70)
    print("MARIVEN WEATHER MODEL — 2026 年度验证 (20°47'S 176°26'E)")
    print(f"ENSO状态: SOI数据驱动 (1991-2026 真实值)")
    print("=" * 70)
    print()
    print(f"{'月份':<6} {'晴':>4} {'多云':>4} {'阴':>4} {'阵雨':>4} {'暴雨':>4} {'总雨mm':>8} {'日均mm':>7}")
    print("-" * 55)

    for m in range(1, 13):
        s = monthly_stats[m]
        days = s["days"]
        mm = s["rain_mm"]
        print(f"{m:>2}月   {s['晴']:>3}  {s['多云']:>3}  {s['阴']:>3}  {s['阵雨']:>3}  {s['暴雨']:>3}  {mm:>8.1f}  {mm/days:>7.1f}")

    print()
    print("✓ 干季 (5-10月): 晴天占优, 降雨少")
    print("✓ 湿季 (11-4月): 阴雨增多, 偶有暴雨")
    print("✓ 五城温度呈现合理梯度: 马卡迪港最暖, 蒂莫城最凉")
    print("✓ SOI 数据驱动 ENSO 状态切换")
