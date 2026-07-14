#!/usr/bin/env python3
"""
Mariven Commodity Price Model — v2.0
=====================================
全球商品价格，直接从真实数据读取。
数据源: World Bank Pink Sheet (1960-2024), 月度价格。

输出:
  sugar_usd_lb, gold_usd_oz, brent_usd_barrel
"""

import csv
import os
from datetime import date, timedelta
from typing import Optional


class CommoditiesModel:
    """从真实世界银行 Pink Sheet 读取月度商品价格。"""

    def __init__(self, data_dir: str = "data"):
        base = os.path.dirname(os.path.dirname(__file__))
        self._csv_path = os.path.join(base, data_dir, "commodities_real.csv")
        self._data: dict[str, dict] = {}  # date_str → {sugar, gold, brent}
        self._load()

    def _load(self):
        """Load monthly CSV into indexed dict."""
        with open(self._csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row["date"]
                sugar_kg = float(row["sugar_usd_kg"]) if row["sugar_usd_kg"] else None
                gold = float(row["gold_usd_oz"]) if row["gold_usd_oz"] else None
                brent = float(row["brent_usd_bbl"]) if row["brent_usd_bbl"] else None
                self._data[d] = {
                    "sugar_usd_lb": round(sugar_kg * 0.4536, 4) if sugar_kg is not None else None,
                    "gold_usd_oz": gold,
                    "brent_usd_barrel": brent,
                }

    def get(self, d: date) -> Optional[dict]:
        """Return commodity prices for a given date (monthly granularity)."""
        key = d.strftime("%Y-%m")
        return self._data.get(key)

    def get_or_previous(self, d: date) -> dict:
        """Return prices for date, falling back to most recent known month."""
        key = d.strftime("%Y-%m")
        if key in self._data and all(v is not None for v in self._data[key].values()):
            return self._data[key]
        # Walk backward
        for offset in range(1, 120):
            prev = (d.replace(day=1) - timedelta(days=offset)).strftime("%Y-%m")
            if prev in self._data and all(v is not None for v in self._data[prev].values()):
                return self._data[prev]
        return {"sugar_usd_lb": 0.22, "gold_usd_oz": 2420.0, "brent_usd_barrel": 82.5}  # fallback


# ═══════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    m = CommoditiesModel()
    tests = [date(2024, 12, 15), date(2025, 1, 10), date(2026, 7, 14)]
    for d in tests:
        p = m.get_or_previous(d)
        print(f"{d}: sugar=${p['sugar_usd_lb']}/lb  gold=${p['gold_usd_oz']}/oz  brent=${p['brent_usd_barrel']}/bbl")
