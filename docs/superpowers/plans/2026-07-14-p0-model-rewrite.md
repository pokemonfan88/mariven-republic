# P0 Core Model Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将天气、汇率、商品和 CPI 重写为确定性、显式状态模型，并由每日主 Tick、状态迁移和原子归档真实驱动。

**Architecture:** `engine.py` 只负责编排，四个 P0 模型使用纯函数接口 `(public_output, next_model_state, events)`。随机流按日期和模型稳定派生，所有跨日状态写入 schema v2 JSON，旧状态在首次 Tick 前迁移。

**Tech Stack:** Python 3.13 标准库、`unittest`、JSON、CSV、SQLite；不新增第三方依赖。

## Global Constraints

- 规范来源：`docs/superpowers/specs/2026-07-14-p0-model-rewrite-design.md`。
- 已有 `sim-engine/output/archive/*.json` 和 `sim-engine/output/events.db` 不得重写。
- 现有天气、经济、人口、政府、死亡和事件兼容字段必须保留。
- 禁止模块级可变随机状态和 `random.seed()`。
- 同一输入状态执行 Tick 必须逐字典相等。
- 模型失败时不得调用归档；JSON 不得留下截断文件，SQLite 写入必须整体提交或整体回滚。
- 测试只能写入 `tempfile.TemporaryDirectory()`。

---

## File Map

- Create `sim-engine/engine/random_streams.py`: 稳定种子派生与局部 RNG。
- Create `sim-engine/engine/state.py`: schema v2 构建、校验和迁移。
- Rewrite `sim-engine/engine/commodities_model.py`: 月度商品数据仓库与纯函数步骤。
- Rewrite `sim-engine/engine/exchange_model.py`: 报价标准化、篮子和均值回归。
- Rewrite `sim-engine/engine/weather_model.py`: SOI、Markov、温度、降雨和风险。
- Rewrite `sim-engine/engine/inflation_model.py`: CPI 指数、月度发布和分项贡献。
- Create `sim-engine/engine/events_model.py`: 现有非 P0 事件逻辑的确定性迁移。
- Rewrite `sim-engine/engine/engine.py`: 资源加载、每日编排、简报和 CLI。
- Modify `sim-engine/engine/archive.py`: 原子 JSON 和 SQLite 事务。
- Create `sim-engine/tests/test_*.py`: 单元、事件、集成、归档和年度校准测试。
- Modify `README.md`: 更新运行方式和 P0 状态说明。

---

### Task 1: Stable Random Streams

**Files:**
- Create: `sim-engine/engine/random_streams.py`
- Create: `sim-engine/tests/test_random_streams.py`

**Interfaces:**
- Produces: `derive_seed(base_seed, schema_version, d, model_name, stream_name="default") -> int`
- Produces: `make_rng(base_seed, schema_version, d, model_name, stream_name="default") -> random.Random`

- [ ] **Step 1: Write the failing deterministic-stream tests**

```python
# sim-engine/tests/test_random_streams.py
import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from random_streams import derive_seed, make_rng


class RandomStreamsTests(unittest.TestCase):
    def test_seed_is_stable(self):
        args = (42, 2, date(2026, 7, 14), "weather", "condition")
        self.assertEqual(derive_seed(*args), derive_seed(*args))

    def test_stream_names_are_isolated(self):
        a = make_rng(42, 2, date(2026, 7, 14), "weather", "condition")
        b = make_rng(42, 2, date(2026, 7, 14), "weather", "rain")
        self.assertNotEqual([a.random() for _ in range(4)], [b.random() for _ in range(4)])

    def test_global_random_state_is_untouched(self):
        random.seed(991)
        expected = random.random()
        random.seed(991)
        make_rng(42, 2, date(2026, 7, 14), "exchange").random()
        self.assertEqual(random.random(), expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_random_streams.py" -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'random_streams'`.

- [ ] **Step 3: Implement stable SHA-256 seed derivation**

```python
# sim-engine/engine/random_streams.py
import hashlib
import random
from datetime import date


def derive_seed(base_seed: int, schema_version: int, d: date,
                model_name: str, stream_name: str = "default") -> int:
    material = "|".join((
        str(int(base_seed)), str(int(schema_version)), d.isoformat(),
        model_name, stream_name,
    )).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:16], "big")


def make_rng(base_seed: int, schema_version: int, d: date,
             model_name: str, stream_name: str = "default") -> random.Random:
    return random.Random(derive_seed(
        base_seed, schema_version, d, model_name, stream_name,
    ))
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_random_streams.py" -v`

Expected: `Ran 3 tests` and `OK`.

- [ ] **Step 5: Commit the random stream foundation**

```bash
git add sim-engine/engine/random_streams.py sim-engine/tests/test_random_streams.py
git commit -m "feat: add deterministic model random streams"
```

---

### Task 2: State Schema, Validation, and v1 Migration

**Files:**
- Create: `sim-engine/engine/state.py`
- Create: `sim-engine/tests/test_state.py`
- Read: `sim-engine/data/state.json`
- Read: `sim-engine/data/nation_profile.json`

**Interfaces:**
- Produces: `SCHEMA_VERSION = 2`
- Produces: `StateValidationError(ValueError)`
- Produces: `migrate_state(raw: Mapping[str, Any], *, base_seed: int | None = None) -> dict`
- Produces: `validate_state(state: Mapping[str, Any]) -> None`
- Produces: `prepare_state(raw: Mapping[str, Any]) -> dict`

- [ ] **Step 1: Write migration, immutability, and validation tests**

```python
# sim-engine/tests/test_state.py
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from state import SCHEMA_VERSION, StateValidationError, prepare_state


V1 = {
    "_meta": {"random_seed": 42, "ticks_run": 30},
    "date": "2026-08-11",
    "weather": {"condition": "多云", "temp_high": 27, "temp_low": 18,
                "humidity": 67, "rainfall_mm": 0.0, "wind_kmh": 14,
                "cyclone_risk": "none", "notes": "兼容天气"},
    "economy": {"inflation_pct": 2.4, "unemployment_pct": 5.8,
                "interest_rate_pct": 2.5,
                "exchange_rate_mvl_per_usd": 2.18,
                "fuel_95_price_mvl": 2.85,
                "fuel_diesel_price_mvl": 2.03},
    "government": {"pm": "托马斯·马卡里"},
    "population": 1_200_000,
    "deaths_today": {"total": 0},
    "events_today": [],
}


class StateTests(unittest.TestCase):
    def test_prepare_migrates_without_mutating_input(self):
        original = copy.deepcopy(V1)
        migrated = prepare_state(V1)
        self.assertEqual(V1, original)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(migrated["base_seed"], 42)
        self.assertEqual(migrated["weather"]["condition"], "多云")
        self.assertEqual(set(migrated["model_state"]),
                         {"weather", "exchange", "commodities", "inflation"})

    def test_prepare_copies_v2_state(self):
        v2 = prepare_state(V1)
        copied = prepare_state(v2)
        self.assertEqual(copied, v2)
        self.assertIsNot(copied, v2)

    def test_invalid_date_reports_field_path(self):
        broken = copy.deepcopy(V1)
        broken["date"] = "14/07/2026"
        with self.assertRaisesRegex(StateValidationError, r"state.date"):
            prepare_state(broken)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_state.py" -v`

Expected: FAIL because `state.py` does not exist.

- [ ] **Step 3: Implement schema preparation and explicit model defaults**

Implement `state.py` with `copy.deepcopy`, `date.fromisoformat`, finite-number checks using `math.isfinite`, and these exact model-state keys:

```python
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
        "monthly_history": _baseline_cpi_history(current_date, inflation_pct),
    },
}
```

`_baseline_cpi_history` must return 13 month-end records with a constant monthly growth factor `(1 + yoy/100) ** (1/12)`, ending at index `100.0`. `validate_state` must reject missing dictionaries, invalid ISO dates, non-positive population, non-finite core economic values, and schema versions other than 2. Error messages must begin with the offending path such as `state.economy.inflation_pct`.

- [ ] **Step 4: Run state and random-stream tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_state.py" -v && python -m unittest discover -s sim-engine/tests -p "test_random_streams.py" -v`

Expected: both commands end with `OK`.

- [ ] **Step 5: Commit the schema foundation**

```bash
git add sim-engine/engine/state.py sim-engine/tests/test_state.py
git commit -m "feat: add versioned simulation state migration"
```

---

### Task 3: Commodity Data Model

**Files:**
- Rewrite: `sim-engine/engine/commodities_model.py`
- Create: `sim-engine/tests/test_commodities_model.py`
- Read: `sim-engine/data/commodities_real.csv`

**Interfaces:**
- Produces: `DataSourceError(RuntimeError)`
- Produces: immutable `CommodityObservation(month, sugar_usd_lb, gold_usd_oz, brent_usd_barrel)`
- Produces: `CommoditySeries.from_csv(path: Path) -> CommoditySeries`
- Produces: `CommoditySeries.lookup(d: date) -> CommodityObservation`
- Produces: `commodities_step(d, previous_state, series) -> tuple[dict, dict, list[dict]]`

- [ ] **Step 1: Write lookup, conversion, stale-data, and failure tests**

```python
# sim-engine/tests/test_commodities_model.py
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from commodities_model import CommoditySeries, DataSourceError, commodities_step


DATA = Path(__file__).resolve().parents[1] / "data" / "commodities_real.csv"


class CommodityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series = CommoditySeries.from_csv(DATA)

    def test_future_date_uses_last_real_observation(self):
        public, state, events = commodities_step(date(2026, 7, 14), {}, self.series)
        self.assertEqual(public["source_month"], "2024-12")
        self.assertAlmostEqual(public["brent_usd_barrel"], 73.833, places=3)
        self.assertTrue(public["is_stale"])
        self.assertGreater(public["staleness_days"], 365)
        self.assertEqual(state["source_month"], "2024-12")
        self.assertEqual(events, [])

    def test_sugar_is_converted_from_kg_to_lb(self):
        obs = self.series.lookup(date(2024, 12, 1))
        self.assertAlmostEqual(obs.sugar_usd_lb, 0.1979, places=4)

    def test_missing_required_column_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("date,gold_usd_oz\n2024-12,2648.01\n", encoding="utf-8")
            with self.assertRaisesRegex(DataSourceError, "sugar_usd_kg"):
                CommoditySeries.from_csv(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and observe failures against the old class API**

Run: `python -m unittest discover -s sim-engine/tests -p "test_commodities_model.py" -v`

Expected: FAIL importing `CommoditySeries`.

- [ ] **Step 3: Implement sorted immutable observations and bisect lookup**

Use `calendar.monthrange`, `bisect_right`, frozen dataclasses, and strict CSV headers. Store integer month keys as `year * 12 + month`; look up the final key not greater than the requested key. Compute staleness from the source month’s final calendar day to `d`, clamped at zero. Set `is_stale` when the source month differs from the requested month. Never return hardcoded market values.

- [ ] **Step 4: Run the commodity tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_commodities_model.py" -v`

Expected: `Ran 3 tests` and `OK`.

- [ ] **Step 5: Commit the commodity model**

```bash
git add sim-engine/engine/commodities_model.py sim-engine/tests/test_commodities_model.py
git commit -m "feat: rewrite commodity model with calendar lookup"
```

---

### Task 4: Exchange Rate Model

**Files:**
- Rewrite: `sim-engine/engine/exchange_model.py`
- Create: `sim-engine/tests/test_exchange_model.py`
- Read: `sim-engine/data/aud_usd.csv`
- Read: `sim-engine/data/nzd_usd.csv`
- Read: `sim-engine/data/usd_cny.csv`
- Read: `sim-engine/data/eur_usd.csv`

**Interfaces:**
- Produces: `FxDataset.from_directory(data_dir: Path) -> FxDataset`
- Produces: `FxDataset.rates_for(d: date) -> tuple[dict[str, float], dict[str, str]]`
- Produces: `exchange_step(d, previous_state, dataset, rng) -> tuple[dict, dict, list[dict]]`

- [ ] **Step 1: Write quote-direction, cross-rate, and calendar fallback tests**

```python
# sim-engine/tests/test_exchange_model.py
import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from exchange_model import FxDataset, exchange_step


DATA = Path(__file__).resolve().parents[1] / "data"


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = FxDataset.from_directory(DATA)

    def test_source_quotes_are_normalized_to_usd_per_unit(self):
        rates, months = self.dataset.rates_for(date(2026, 7, 14))
        self.assertAlmostEqual(rates["AUD"], 0.7025, places=4)
        self.assertAlmostEqual(rates["CNY"], 1 / 6.7758, places=7)
        self.assertEqual(months["AUD"], "2026-06")

    def test_cross_rates_multiply_canonical_quotes(self):
        public, next_state, _ = exchange_step(
            date(2026, 7, 14), {"mvl_per_usd": 2.2390},
            self.dataset, random.Random(5),
        )
        self.assertAlmostEqual(
            public["mvl_per_aud"],
            public["mvl_per_usd"] * public["usd_per_aud"], places=4,
        )
        self.assertAlmostEqual(
            public["mvl_per_eur"],
            public["mvl_per_usd"] * public["usd_per_eur"], places=4,
        )
        self.assertEqual(next_state["mvl_per_usd"], public["mvl_per_usd"])

    def test_repeated_input_and_rng_are_deterministic(self):
        args = (date(2026, 7, 14), {"mvl_per_usd": 2.18}, self.dataset)
        self.assertEqual(exchange_step(*args, random.Random(7)),
                         exchange_step(*args, random.Random(7)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify old API failures**

Run: `python -m unittest discover -s sim-engine/tests -p "test_exchange_model.py" -v`

Expected: FAIL importing `FxDataset`.

- [ ] **Step 3: Implement canonical quotes, basket target, and explicit OU state**

Define canonical base quotes from the latest common calibration month available in all series, and compute:

```python
log_move = sum(BASKET_WEIGHTS[cc] * math.log(rates[cc] / base_rates[cc])
               for cc in BASKET_WEIGHTS)
target = BASE_MVL_USD * math.exp(log_move)
next_rate = previous + 0.12 * (target - previous) + rng.gauss(0.0, 0.0025)
next_rate = min(2.80, max(1.80, next_rate))
```

Set USD quote and base quote to `1.0`. Parse monthly keys exactly and use bisect lookup, not day subtraction. Return canonical source quotes as `usd_per_aud`, `usd_per_nzd`, `usd_per_cny`, `usd_per_eur`; return all MVL cross rates by multiplication; expose `source_months` and maximum `staleness_days`.

- [ ] **Step 4: Run exchange tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_exchange_model.py" -v`

Expected: `Ran 3 tests` and `OK`.

- [ ] **Step 5: Commit the exchange model**

```bash
git add sim-engine/engine/exchange_model.py sim-engine/tests/test_exchange_model.py
git commit -m "feat: rewrite basket exchange rate model"
```

---

### Task 5: Weather Model

**Files:**
- Rewrite: `sim-engine/engine/weather_model.py`
- Create: `sim-engine/tests/test_weather_model.py`
- Read: `sim-engine/data/soi_monthly.csv`

**Interfaces:**
- Produces: `SoiSeries.from_csv(path: Path) -> SoiSeries`
- Produces: `SoiSeries.value_for(d: date) -> tuple[float | None, str | None]`
- Produces: `temperature_baseline(d: date) -> float`
- Produces: `weather_step(d, previous_state, soi_series, rng_factory) -> tuple[dict, dict, list[dict]]`
- `rng_factory(stream_name: str) -> random.Random`

- [ ] **Step 1: Write phase, SOI, distribution, risk, and deterministic-step tests**

```python
# sim-engine/tests/test_weather_model.py
import random
import statistics
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from weather_model import (
    SoiSeries, coral_bleaching_risk, temperature_baseline, weather_step,
)


DATA = Path(__file__).resolve().parents[1] / "data" / "soi_monthly.csv"


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.soi = SoiSeries.from_csv(DATA)

    def test_southern_temperature_phase(self):
        self.assertGreater(temperature_baseline(date(2026, 1, 30)),
                           temperature_baseline(date(2026, 5, 1)))
        self.assertLess(temperature_baseline(date(2026, 7, 30)),
                        temperature_baseline(date(2026, 10, 30)))

    def test_soi_does_not_read_future(self):
        value, month = self.soi.value_for(date(1990, 12, 1))
        self.assertIsNone(value)
        self.assertIsNone(month)

    def test_standard_gamma_sampler_has_expected_mean(self):
        rng = random.Random(123)
        values = [rng.gammavariate(0.8, 1.2) for _ in range(20_000)]
        self.assertAlmostEqual(statistics.fmean(values), 0.96, delta=0.04)

    def test_critical_coral_risk_is_reachable(self):
        self.assertEqual(coral_bleaching_risk(date(2026, 3, 1), 30.0), "critical")

    def test_step_is_deterministic_and_outputs_five_cities(self):
        previous = {"previous_conditions": {}, "rainfall_history": []}
        def factory(name):
            return random.Random("2026-07-14:" + name)
        first = weather_step(date(2026, 7, 14), previous, self.soi, factory)
        second = weather_step(date(2026, 7, 14), previous, self.soi, factory)
        self.assertEqual(first, second)
        public = first[0]
        self.assertEqual(
            {"katora", "makadi_port", "timo", "pela", "ruwa"},
            {key for key in public if key in {
                "katora", "makadi_port", "timo", "pela", "ruwa"
            }},
        )
        self.assertEqual(public["condition"], public["katora"]["condition"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify old API failures**

Run: `python -m unittest discover -s sim-engine/tests -p "test_weather_model.py" -v`

Expected: FAIL importing the new public functions.

- [ ] **Step 3: Implement the pure weather pipeline**

Use the design formula exactly:

```python
year_days = 366 if calendar.isleap(d.year) else 365
phase_days = 30 * year_days / 365.2425
base = 25.5 + 2.5 * math.cos(2 * math.pi * (d.timetuple().tm_yday - phase_days) / year_days)
```

Use dry/wet Markov matrices, shift probability mass between indices `0:2` and `3:5` according to bounded SOI magnitude, normalize, and sample with the `condition` stream. Use `gammavariate` for rain. Persist `previous_conditions` and the last 14 national mean rainfall values. Generate all city values from named streams so adding a city does not perturb existing city sequences. Add flat Katora compatibility fields and risk events. Check `critical` coral conditions before `warning`.

- [ ] **Step 4: Run weather tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_weather_model.py" -v`

Expected: `Ran 5 tests` and `OK`.

- [ ] **Step 5: Commit the weather model**

```bash
git add sim-engine/engine/weather_model.py sim-engine/tests/test_weather_model.py
git commit -m "feat: rewrite deterministic weather model"
```

---

### Task 6: CPI Index and Monthly Publication Model

**Files:**
- Rewrite: `sim-engine/engine/inflation_model.py`
- Create: `sim-engine/tests/test_inflation_model.py`
- Read: `sim-engine/data/nation_profile.json`

**Interfaces:**
- Produces: `inflation_step(d, previous_state, weather, commodities, exchange, profile, rng) -> tuple[dict, dict, list[dict]]`
- Public output includes `index`, `mom_pct`, `yoy_pct`, `is_release_day`, `release_date`, component rates/contributions, and pump prices.

- [ ] **Step 1: Write publication, hold, weather-unit, and linkage tests**

```python
# sim-engine/tests/test_inflation_model.py
import copy
import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from inflation_model import inflation_step
from state import prepare_state


class InflationTests(unittest.TestCase):
    def setUp(self):
        self.state = prepare_state({
            "_meta": {"random_seed": 42}, "date": "2026-07-31",
            "weather": {"condition": "晴", "temp_high": 26, "temp_low": 20,
                        "humidity": 70, "rainfall_mm": 2, "wind_kmh": 12,
                        "cyclone_risk": "none", "notes": ""},
            "economy": {"inflation_pct": 2.4, "unemployment_pct": 5.8,
                        "interest_rate_pct": 2.5,
                        "exchange_rate_mvl_per_usd": 2.18,
                        "fuel_95_price_mvl": 2.85,
                        "fuel_diesel_price_mvl": 2.03},
            "government": {}, "population": 1_200_000,
            "deaths_today": {"total": 0}, "events_today": [],
        })["model_state"]["inflation"]
        self.weather = {"katora": {"rainfall_mm": 2.0, "temp_high": 26.0}}
        self.commodities = {"sugar_usd_lb": 0.20, "brent_usd_barrel": 74.0}
        self.exchange = {"mvl_per_usd": 2.18, "basket_index": 1.0}
        self.profile = {"demographics": {"urbanization_pct": 53.6}}

    def step(self, d, state):
        return inflation_step(d, state, self.weather, self.commodities,
                              self.exchange, self.profile, random.Random(d.isoformat()))

    def test_official_value_holds_between_release_days(self):
        public1, state1, _ = self.step(date(2026, 8, 14), self.state)
        public2, _, _ = self.step(date(2026, 8, 16), state1)
        self.assertEqual(public1["index"], public2["index"])
        self.assertEqual(public1["yoy_pct"], public2["yoy_pct"])

    def test_release_day_preserves_previous_month_for_mom(self):
        _, state1, _ = self.step(date(2026, 8, 14), self.state)
        public, state2, events = self.step(date(2026, 8, 15), state1)
        self.assertTrue(public["is_release_day"])
        self.assertEqual(public["release_date"], "2026-08-15")
        self.assertNotEqual(public["mom_pct"], 0.0)
        self.assertEqual(state2["last_release_date"], "2026-08-15")
        self.assertEqual(events[0]["type"], "economy")

    def test_normal_daily_rain_is_not_compared_to_month_total(self):
        public, _, _ = self.step(date(2026, 7, 31), self.state)
        self.assertLess(abs(public["components"]["food"]["weather_pressure"]), 0.5)

    def test_higher_brent_increases_pump_price(self):
        low, _, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 60.0}, self.exchange,
            self.profile, random.Random(1),
        )
        high, _, _ = inflation_step(
            date(2026, 8, 1), copy.deepcopy(self.state), self.weather,
            {**self.commodities, "brent_usd_barrel": 100.0}, self.exchange,
            self.profile, random.Random(1),
        )
        self.assertGreater(high["fuel_95_price_mvl"], low["fuel_95_price_mvl"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure against the old class API**

Run: `python -m unittest discover -s sim-engine/tests -p "test_inflation_model.py" -v`

Expected: FAIL importing `inflation_step`.

- [ ] **Step 3: Implement index history, daily observations, and release state machine**

Append one JSON observation per date with daily-normal rainfall `MONTHLY_RAIN_NORM[month] / monthrange(year, month)[1]`, temperature deviation, sugar, Brent, MVL/USD, and component pressures. Replace an observation with the same date instead of duplicating it.

On day 15, if `last_release_date != d.isoformat()`, aggregate observations belonging to the previous calendar month, calculate bounded component monthly changes, update the prior index, then compute:

```python
mom_pct = (new_index / previous_index - 1.0) * 100
yoy_pct = (new_index / index_12_months_ago - 1.0) * 100
```

Append one monthly history record, retain the newest 24, update published fields, and emit one release event. On other days retain published index, MoM, YoY, and release date unchanged while still updating pump prices and daily observations.

- [ ] **Step 4: Run CPI and state tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_inflation_model.py" -v && python -m unittest discover -s sim-engine/tests -p "test_state.py" -v`

Expected: both commands end with `OK`.

- [ ] **Step 5: Commit the CPI model**

```bash
git add sim-engine/engine/inflation_model.py sim-engine/tests/test_inflation_model.py
git commit -m "feat: rewrite CPI as monthly published index"
```

---

### Task 7: Deterministic Events and Main Tick Integration

**Files:**
- Create: `sim-engine/engine/events_model.py`
- Rewrite: `sim-engine/engine/engine.py`
- Create: `sim-engine/tests/test_events_model.py`
- Create: `sim-engine/tests/test_engine.py`

**Interfaces:**
- Produces: `EngineResources.load(data_dir: Path) -> EngineResources`
- Produces: `events_step(d, state, weather, rng_factory) -> tuple[dict, list[dict]]`
- Produces: `tick(previous_state, *, resources: EngineResources | None = None) -> dict`
- Produces: `render_brief(state: Mapping[str, Any]) -> str`

- [ ] **Step 1: Write event isolation plus end-to-end determinism, integration, and resume tests**

```python
# sim-engine/tests/test_events_model.py
import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from events_model import events_step


class EventsTests(unittest.TestCase):
    def test_same_named_streams_produce_same_events(self):
        state = {"population": 1_200_000, "government": {}}
        weather = {"condition": "晴"}
        def factory(name):
            return random.Random("2026-08-12:" + name)
        first = events_step(date(2026, 8, 12), state, weather, factory)
        second = events_step(date(2026, 8, 12), state, weather, factory)
        self.assertEqual(first, second)

    def test_unrelated_random_draw_does_not_change_events(self):
        random.Random(123).random()
        state = {"population": 1_200_000, "government": {}}
        weather = {"condition": "晴"}
        def factory(name):
            return random.Random("2026-08-12:" + name)
        expected = events_step(date(2026, 8, 12), state, weather, factory)
        random.Random(999).random()
        self.assertEqual(expected, events_step(
            date(2026, 8, 12), state, weather, factory,
        ))


if __name__ == "__main__":
    unittest.main()
```

```python
# sim-engine/tests/test_engine.py
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick


ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = EngineResources.load(ROOT / "data")
        cls.v1 = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))

    def test_tick_does_not_mutate_input_and_is_deterministic(self):
        original = copy.deepcopy(self.v1)
        first = tick(self.v1, resources=self.resources)
        second = tick(self.v1, resources=self.resources)
        self.assertEqual(self.v1, original)
        self.assertEqual(first, second)

    def test_tick_uses_all_p0_models(self):
        result = tick(self.v1, resources=self.resources)
        self.assertEqual(result["schema_version"], 2)
        self.assertIn("katora", result["weather"])
        self.assertIn("exchange_rates", result["economy"])
        self.assertIn("commodities", result["economy"])
        self.assertIn("cpi", result["economy"])
        self.assertEqual(result["economy"]["inflation_pct"],
                         result["economy"]["cpi"]["yoy_pct"])

    def test_serialized_resume_matches_continuous_run(self):
        day1 = tick(self.v1, resources=self.resources)
        continuous = tick(day1, resources=self.resources)
        reloaded = json.loads(json.dumps(day1, ensure_ascii=False))
        resumed = tick(reloaded, resources=self.resources)
        self.assertEqual(continuous, resumed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail against the old engine**

Run: `python -m unittest discover -s sim-engine/tests -p "test_events_model.py" -v && python -m unittest discover -s sim-engine/tests -p "test_engine.py" -v`

Expected: FAIL importing `events_model` and `EngineResources`.

- [ ] **Step 3: Move legacy event rules and implement the P0 orchestrator**

`EngineResources` is a frozen dataclass containing `SoiSeries`, `FxDataset`, `CommoditySeries`, and nation profile. `tick` must:

```python
prepared = prepare_state(previous_state)
next_state = copy.deepcopy(prepared)
d = date.fromisoformat(prepared["date"]) + timedelta(days=1)
weather, weather_state, weather_events = weather_step(...)
exchange, exchange_state, exchange_events = exchange_step(...)
commodities, commodity_state, commodity_events = commodities_step(...)
cpi, inflation_state, cpi_events = inflation_step(...)
deaths, general_events = events_step(...)
```

Use `make_rng` or named weather/event RNG factories for every call. Merge flat compatibility fields exactly, set `economy.exchange_rate_mvl_per_usd`, `economy.fuel_95_price_mvl`, `economy.fuel_diesel_price_mvl`, and `economy.inflation_pct`, update all four `model_state` entries, combine structured events, increment `_meta.ticks_run`, validate, and return. Delete old `WEATHER_PROBS`, `JULY_TEMP_RANGE`, `ECON_SIGMA`, `roll_weather`, and `perturb_economy` paths.

- [ ] **Step 4: Run the full test suite**

Run: `python -m unittest discover -s sim-engine/tests -p "test*.py" -v`

Expected: all tests through Task 7 pass.

- [ ] **Step 5: Commit the integrated engine**

```bash
git add sim-engine/engine/events_model.py sim-engine/engine/engine.py sim-engine/tests/test_events_model.py sim-engine/tests/test_engine.py
git commit -m "feat: integrate P0 models into daily tick"
```

---

### Task 8: Atomic Archive and Safe CLI

**Files:**
- Modify: `sim-engine/engine/archive.py`
- Modify: `sim-engine/engine/engine.py`
- Create: `sim-engine/tests/test_archive.py`
- Create: `sim-engine/tests/test_cli.py`

**Interfaces:**
- Produces: `archive_day(state, *, state_path: Path, archive_dir: Path, db_path: Path) -> None`
- Produces: `run_days(state, days, resources) -> tuple[dict, list[dict]]`
- Produces: `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write temporary-directory archive and dry-run tests**

```python
# sim-engine/tests/test_archive.py
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from archive import archive_day


class ArchiveTests(unittest.TestCase):
    def test_archive_writes_json_and_sqlite_atomically(self):
        state = {
            "schema_version": 2, "date": "2026-08-12",
            "weather": {"condition": "晴", "temp_high": 28, "temp_low": 21,
                        "rainfall_mm": 0.0},
            "economy": {"inflation_pct": 2.4, "unemployment_pct": 5.8,
                        "exchange_rate_mvl_per_usd": 2.18,
                        "fuel_95_price_mvl": 2.85},
            "deaths_today": {"total": 0}, "events_today": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_day(state, state_path=root / "state.json",
                        archive_dir=root / "archive", db_path=root / "events.db")
            loaded = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded, state)
            self.assertFalse(list(root.rglob("*.tmp")))
            with sqlite3.connect(root / "events.db") as conn:
                count = conn.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
```

```python
# sim-engine/tests/test_cli.py
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CliTests(unittest.TestCase):
    def test_dry_run_does_not_modify_tracked_runtime_files(self):
        state = ROOT / "data" / "state.json"
        database = ROOT / "output" / "events.db"
        before = (digest(state), digest(database))
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "engine" / "engine.py"),
             "--days", "2", "--dry-run"],
            cwd=ROOT, text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, (digest(state), digest(database)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify signature/CLI failures**

Run: `python -m unittest discover -s sim-engine/tests -p "test_archive.py" -v && python -m unittest discover -s sim-engine/tests -p "test_cli.py" -v`

Expected: FAIL until keyword paths and `--dry-run` exist.

- [ ] **Step 3: Implement atomic replace, SQLite transaction, and argparse CLI**

Serialize JSON to `NamedTemporaryFile(delete=False, dir=target.parent, suffix=".tmp")`, flush, `os.fsync`, then `os.replace`. Clean the temp file in `finally`. Open SQLite with a context manager and perform summary plus event inserts inside one transaction. Add `argparse` options `--days` (positive integer, default 1) and `--dry-run`. Dry run prints briefs but never calls `archive_day`.

- [ ] **Step 4: Run archive, CLI, and engine tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_archive.py" -v && python -m unittest discover -s sim-engine/tests -p "test_cli.py" -v && python -m unittest discover -s sim-engine/tests -p "test_engine.py" -v`

Expected: all three commands end with `OK`.

- [ ] **Step 5: Commit persistence and CLI safety**

```bash
git add sim-engine/engine/archive.py sim-engine/engine/engine.py sim-engine/tests/test_archive.py sim-engine/tests/test_cli.py
git commit -m "feat: add atomic archive and dry-run CLI"
```

---

### Task 9: Annual Calibration, Documentation, and Final Verification

**Files:**
- Create: `sim-engine/tests/test_annual_calibration.py`
- Modify: `README.md`
- Modify: `sim-engine/docs/model-catalog.md`

**Interfaces:**
- Consumes: `EngineResources.load`, `tick`, schema v2 output.
- Produces: an executable 365-day calibration gate and accurate user documentation.

- [ ] **Step 1: Write the 365-day calibration test**

```python
# sim-engine/tests/test_annual_calibration.py
import json
import math
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from engine import EngineResources, tick


ROOT = Path(__file__).resolve().parents[1]


class AnnualCalibrationTests(unittest.TestCase):
    def test_full_year_climate_and_economy_invariants(self):
        resources = EngineResources.load(ROOT / "data")
        state = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
        rainfall = 0.0
        monthly_temps = defaultdict(list)
        monthly_rain = defaultdict(float)
        releases = 0
        for _ in range(365):
            state = tick(state, resources=resources)
            month = int(state["date"][5:7])
            katora = state["weather"]["katora"]
            rainfall += katora["rainfall_mm"]
            monthly_rain[month] += katora["rainfall_mm"]
            monthly_temps[month].append(katora["temp_high"])
            releases += int(state["economy"]["cpi"]["is_release_day"])
            self.assertTrue(1.80 <= state["economy"]["exchange_rate_mvl_per_usd"] <= 2.80)
            json.dumps(state, ensure_ascii=False, allow_nan=False)
        self.assertTrue(2240 <= rainfall <= 3360, rainfall)
        wet = sum(monthly_rain[m] for m in (11, 12, 1, 2, 3, 4))
        dry = sum(monthly_rain[m] for m in (5, 6, 7, 8, 9, 10))
        self.assertGreater(wet, dry)
        means = {m: sum(v) / len(v) for m, v in monthly_temps.items()}
        self.assertIn(max(means, key=means.get), (12, 1, 2))
        self.assertIn(min(means, key=means.get), (6, 7, 8))
        self.assertEqual(releases, 12)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run calibration and adjust only named model constants until it passes**

Run: `python -m unittest discover -s sim-engine/tests -p "test_annual_calibration.py" -v`

Expected: `Ran 1 test` and `OK`. Calibration changes may only modify weather Gamma parameters, temperature noise bounds, exchange `kappa`/shock sigma, or CPI component pass-through constants; interfaces and assertions remain unchanged.

- [ ] **Step 3: Update README and model catalog with exact runtime semantics**

Document these commands:

```text
cd sim-engine
python engine/engine.py --days 1
python engine/engine.py --days 30
python engine/engine.py --days 365 --dry-run
python -m unittest discover -s tests -p "test*.py" -v
```

State that P0 is implemented through the main Tick, CPI publishes monthly on the 15th, commodity data exposes staleness, and `--dry-run` never writes archives.

- [ ] **Step 4: Run full verification from a clean status baseline**

Run:

```text
python -m py_compile sim-engine/engine/random_streams.py sim-engine/engine/state.py sim-engine/engine/weather_model.py sim-engine/engine/exchange_model.py sim-engine/engine/commodities_model.py sim-engine/engine/inflation_model.py sim-engine/engine/events_model.py sim-engine/engine/engine.py sim-engine/engine/archive.py
python -m unittest discover -s sim-engine/tests -p "test*.py" -v
python -X utf8 sim-engine/engine/engine.py --days 365 --dry-run
git diff --check
git status --short
```

Expected: compilation exits 0; all tests pass with a non-zero test count; dry run exits 0 without changing `state.json`, archives, or SQLite; `git diff --check` prints nothing; status lists only the intended source, test, and documentation changes.

- [ ] **Step 5: Commit calibration and documentation**

```bash
git add README.md sim-engine/docs/model-catalog.md sim-engine/tests/test_annual_calibration.py sim-engine/engine/weather_model.py sim-engine/engine/exchange_model.py sim-engine/engine/inflation_model.py
git commit -m "test: calibrate and document P0 simulation models"
```

- [ ] **Step 6: Perform final scope audit**

Run: `rg -n "WEATHER_PROBS|JULY_TEMP_RANGE|ECON_SIGMA|def roll_weather|def perturb_economy|random\.seed" sim-engine/engine`

Expected: no matches. Confirm with `git diff HEAD~9 --name-only` that historical archive JSON files, `sim-engine/data/state.json`, and `sim-engine/output/events.db` are absent from the changed-file list.
