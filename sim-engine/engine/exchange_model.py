#!/usr/bin/env python3
"""
Mariven Exchange Rate Model — v2.0
===================================
马里文里拉 (MVL) 汇率生成器。
锚定真实一篮子货币数据: AUD/NZD/USD/CNY/EUR，按贸易权重加权。

数据源: FRED (美联储经济数据库) 月度汇率
  - aud_usd.csv, nzd_usd.csv, usd_cny.csv, eur_usd.csv

贸易权重:
  AUD 40% · NZD 25% · USD 20% · CNY 10% · EUR 5%

输出: 各类 MVL 交叉汇率
"""

import csv
import math
import os
import random
from datetime import date, timedelta
from typing import Optional


BASE_MVL_USD = 2.18
BASKET_WEIGHTS = {"AUD": 0.40, "NZD": 0.25, "USD": 0.20, "CNY": 0.10, "EUR": 0.05}


class ExchangeModel:
    """从真实 FRED CSV 读取汇率，计算 MVL 篮子汇率。"""

    def __init__(self, data_dir: str = "data", seed: int = 42):
        random.seed(seed)
        base = os.path.dirname(os.path.dirname(__file__))
        self._fx: dict[str, dict] = {}  # {"AUD": {date_key: rate}, ...}
        self._mvl_usd = BASE_MVL_USD

        pairs = [
            ("AUD", "aud_usd.csv", "EXUSAL"),
            ("NZD", "nzd_usd.csv", "EXUSNZ"),
            ("CNY", "usd_cny.csv", "EXCHUS"),
            ("EUR", "eur_usd.csv", "EXUSEU"),
        ]
        for cc, filename, fred_col in pairs:
            self._fx[cc] = {}
            path = os.path.join(base, data_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = row.get("observation_date", row.get("DATE", ""))
                    v = row.get(fred_col, "")
                    if d and v and v != ".":
                        try:
                            self._fx[cc][d] = float(v)
                        except ValueError:
                            pass

    def get_rate(self, currency: str, d: date) -> Optional[float]:
        """Get exchange rate for currency on a given date (monthly)."""
        key = d.strftime("%Y-%m-01")
        return self._fx[currency].get(key)

    def get_or_previous(self, currency: str, d: date) -> float:
        """Get rate, falling back to most recent known month."""
        key = d.strftime("%Y-%m-01")
        if key in self._fx[currency]:
            return self._fx[currency][key]
        for offset in range(1, 120):
            prev = (d.replace(day=1) - timedelta(days=offset * 30)).strftime("%Y-%m-01")
            if prev in self._fx[currency]:
                return self._fx[currency][prev]
        # Fallback to known baseline
        fallbacks = {"AUD": 0.665, "NZD": 0.615, "CNY": 7.25, "EUR": 0.920}
        return fallbacks.get(currency, 1.0)

    def compute(self, d: date) -> dict:
        """Compute all MVL cross-rates for a given date."""
        aud = self.get_or_previous("AUD", d)
        nzd = self.get_or_previous("NZD", d)
        cny = self.get_or_previous("CNY", d)
        eur = self.get_or_previous("EUR", d)

        # AUD baseline for basket comparison
        aud_base = 0.665
        nzd_base = 0.615
        cny_base = 7.25
        eur_base = 0.920

        changes = {
            "AUD": (aud / aud_base - 1.0),
            "NZD": (nzd / nzd_base - 1.0),
            "CNY": (cny_base / cny - 1.0),  # USDCNY: higher CNY = weaker CNY
            "EUR": (eur / eur_base - 1.0),
        }

        basket_move = sum(BASKET_WEIGHTS[cc] * changes.get(cc, 0) for cc in BASKET_WEIGHTS if cc != "USD")

        raw_mvl = BASE_MVL_USD * (1.0 + basket_move)
        intervention = 0.02 * (BASE_MVL_USD - self._mvl_usd)
        noise = random.gauss(0, 0.0015)

        self._mvl_usd = max(1.80, min(2.80, raw_mvl + intervention + noise))
        mvl = round(self._mvl_usd, 4)

        return {
            "mvl_per_usd": mvl,
            "mvl_per_aud": round(mvl / aud, 4),
            "mvl_per_nzd": round(mvl / nzd, 4),
            "mvl_per_cny": round(mvl / cny, 4),
            "mvl_per_eur": round(mvl / eur, 4),
            "aud_usd": aud,
            "nzd_usd": nzd,
            "usd_cny": cny,
            "eur_usd": eur,
        }


# ═══════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    m = ExchangeModel(seed=42)
    tests = [
        date(2024, 12, 15),
        date(2025, 6, 1),
        date(2026, 7, 14),
    ]
    print(f"{'Date':<14} {'MVL/USD':>8} {'MVL/AUD':>8} {'AUD':>8} {'NZD':>8} {'CNY':>8} {'EUR':>8}")
    print("-" * 60)
    for d in tests:
        r = m.compute(d)
        print(f"{d}  {r['mvl_per_usd']:>8.4f}  {r['mvl_per_aud']:>8.4f}  {r['aud_usd']:>8.4f}  {r['nzd_usd']:>8.4f}  {r['usd_cny']:>8.4f}  {r['eur_usd']:>8.4f}")
