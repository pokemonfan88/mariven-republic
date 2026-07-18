# Complete Dengue Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, persistent 2026 dengue model for seven Mariven provinces, five age groups, four serotypes, mosquito transmission, immunity, surveillance, healthcare pressure, wMar-1 pilots, and schema-v5 engine integration.

**Architecture:** `dengue_model.py` owns the public API, baseline loading, orchestration, snapshots, reconciliation, and validation. `dengue_dynamics.py` owns human/vector transitions and spatial mixing; `dengue_surveillance.py` owns clinical reporting, laboratory queues, releases, and alerts. The national single-age population model remains authoritative, while dengue keeps a reconciled seven-province health allocation.

**Tech Stack:** Python 3 standard library, immutable-style dictionaries, JSON baselines, `dataclasses`, `unittest`, existing named random streams, existing CLI/archive framework.

## Global Constraints

- Work only in `D:\马里文\.worktrees\dengue-2026` on branch `codex/dengue-2026`.
- Follow test-driven development: add one focused failing test, observe the expected failure, add the smallest production change, then rerun the focused test.
- Use `apply_patch` for source, test, JSON, Markdown, and README edits.
- Preserve the 169 existing tests and all legacy model random sequences.
- Human stocks and human flows are non-negative integers; vector stocks are finite non-negative floats.
- Seven dengue province-age stocks must reconcile exactly to the population model's national age bands after every tick.
- Keep DENV-1 through DENV-4, 16 immunity masks, 180-day cross-immunity ring, and limited wMar-1 pilots exactly as specified.
- The committed baseline date is `2026-08-11`; historical reported cases through `2026-08-10` total exactly 1,240.
- Weekly releases are provisional on Thursday after week end, revised at +14 days, and final at +28 days.
- Schema v5 adds required `model_state.dengue` and `public_health.dengue` dictionaries.
- Do not add third-party runtime dependencies or live network calls.
- Commit after each task only when its focused and regression tests pass.

## File Map

**Create**

- `sim-engine/data/sources/dengue_external_anchors_2026.json` — source provenance and extracted official/project anchors.
- `sim-engine/data/dengue_baseline_2026.json` — generated, versioned model parameters and 2026 anchor data.
- `sim-engine/scripts/build_dengue_baseline.py` — deterministic source-to-baseline builder.
- `sim-engine/engine/dengue_model.py` — baseline API, orchestration, initialization, validation, reconciliation, snapshot.
- `sim-engine/engine/dengue_dynamics.py` — age/serotype human transitions, vector SEI, weather mapping, mobility.
- `sim-engine/engine/dengue_surveillance.py` — care seeking, laboratory/reporting queues, releases, alerts.
- `sim-engine/tests/test_dengue_model.py` — baseline, initialization, orchestration, conservation, long-run tests.
- `sim-engine/tests/test_dengue_dynamics.py` — human, immunity, vector, weather, mobility tests.
- `sim-engine/tests/test_dengue_surveillance.py` — clinical, reporting, revision, alert tests.

**Modify**

- `sim-engine/engine/population_model.py` — structured cause-specific death requests and confirmed removal ledger.
- `sim-engine/engine/state.py` — schema v5 migration, defaults, validation, public-health namespace.
- `sim-engine/engine/engine.py` — resources, dengue random streams, tick ordering, death reconciliation, brief.
- `sim-engine/tests/test_population_model.py` — age-targeted dengue death behavior.
- `sim-engine/tests/test_state.py` — v4-to-v5 migration and validation.
- `sim-engine/tests/test_engine.py` — full integration, sequence isolation, deterministic resume.
- `sim-engine/tests/test_annual_calibration.py` — 365-day dengue invariants.
- `README.md` — mark dengue complete and document public output.
- `sim-engine/docs/model-catalog.md` — replace the planned SIR summary with the implemented state-space contract.

---

### Task 1: Source Extract and Reproducible Baseline

**Files:**

- Create: `sim-engine/data/sources/dengue_external_anchors_2026.json`
- Create: `sim-engine/data/dengue_baseline_2026.json`
- Create: `sim-engine/scripts/build_dengue_baseline.py`
- Create: `sim-engine/tests/test_dengue_model.py`

**Interfaces:**

- Produces: `build_baseline(source_path: Path = SOURCE_PATH) -> dict[str, Any]`
- Produces: CLI `python sim-engine/scripts/build_dengue_baseline.py --output PATH`
- Provides baseline version `mariven-dengue-2026-v1` to all later tasks.

- [ ] **Step 1: Write failing source and builder tests**

```python
class DengueBaselineBuilderTests(unittest.TestCase):
    def test_committed_baseline_is_reproducible(self):
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(build_baseline(), expected)

    def test_anchor_totals_and_provenance(self):
        baseline = build_baseline()
        self.assertEqual(sum(baseline["provinces"].values()), 1_200_000)
        self.assertEqual(
            sum(baseline["historical_2026"]["reported_by_province"].values()),
            1_240,
        )
        self.assertEqual(baseline["wmar1"]["other_provinces_coverage"], 0.0)
        self.assertEqual(
            baseline["metadata"]["source_classes"]["wmar1"],
            "fictional_intervention",
        )
```

- [ ] **Step 2: Run the focused test and observe the missing-module failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: `ImportError` for `build_dengue_baseline` or missing baseline files.

- [ ] **Step 3: Add the source extract with explicit provenance classes**

```json
{
  "_meta": {
    "version": "mariven-dengue-sources-2026-v1",
    "accessed_on": "2026-07-19"
  },
  "sources": {
    "who_fact_sheet": {
      "class": "official_external",
      "url": "https://www.who.int/news-room/fact-sheets/detail/dengue-and-severe-dengue",
      "use": ["human_incubation", "symptom_duration", "severe_dengue_context"]
    },
    "who_outbreak_toolbox": {
      "class": "official_external",
      "url": "https://www.who.int/emergencies/outbreak-toolkit/disease-outbreak-toolboxes/dengue-outbreak-toolbox",
      "use": ["case_definitions", "outbreak_investigation"]
    },
    "who_wpro_update_749": {
      "class": "official_external",
      "published_on": "2026-07-09",
      "url": "https://www.who.int/westernpacific/publications/m/item/dengue-situation-update---749--9-july-2026",
      "use": ["regional_plausibility_only"]
    },
    "mariven_canon": {
      "class": "project_canon",
      "files": ["06-administrative.md", "14-geography-climate.md", "19-healthcare.md"]
    },
    "wmar1": {
      "class": "fictional_intervention",
      "files": ["lancet-wmar1-2024.md", "lancet-wmar1-2024-zh.md"]
    }
  }
}
```

- [ ] **Step 4: Implement the deterministic builder**

```python
ANCHOR_DATE = "2026-08-11"
PROVINCES = {
    "katora": 470_000,
    "western": 260_000,
    "central_highlands": 110_000,
    "eastern_coast": 78_000,
    "timo": 145_000,
    "pela": 82_000,
    "ruwa": 55_000,
}
REPORTED_BY_PROVINCE = {
    "katora": 520,
    "western": 340,
    "central_highlands": 70,
    "eastern_coast": 60,
    "timo": 110,
    "pela": 95,
    "ruwa": 45,
}

def build_baseline(source_path: Path = SOURCE_PATH) -> dict[str, Any]:
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    return {
        "version": "mariven-dengue-2026-v1",
        "anchor_date": ANCHOR_DATE,
        "metadata": {
            "generated_on": "2026-07-19",
            "source_extract": "sources/dengue_external_anchors_2026.json",
            "source_classes": {
                "natural_history": "official_external",
                "mariven_parameters": "calibration_assumption",
                "wmar1": "fictional_intervention",
            },
        },
        "age_groups": ["0-4", "5-14", "15-29", "30-59", "60+"],
        "serotypes": ["DENV-1", "DENV-2", "DENV-3", "DENV-4"],
        "provinces": PROVINCES,
        "historical_2026": {
            "through_date": "2026-08-10",
            "reported_by_province": REPORTED_BY_PROVINCE,
        },
        "immunity": {
            "cross_protection_days": 180,
            "ever_infected_prior": {
                "0-4": 0.08, "5-14": 0.30, "15-29": 0.55,
                "30-59": 0.68, "60+": 0.75,
            },
            "province_multipliers": {
                "katora": 1.10, "western": 1.08,
                "central_highlands": 0.80, "eastern_coast": 0.90,
                "timo": 0.85, "pela": 1.00, "ruwa": 0.75,
            },
        },
        "transmission": {
            "human_incubation_days": {"4": .03, "5": .10, "6": .22, "7": .28, "8": .20, "9": .11, "10": .06},
            "infectious_days": {"2": .08, "3": .20, "4": .30, "5": .23, "6": .13, "7": .06},
            "serotype_prior": {"DENV-1": .25, "DENV-2": .55, "DENV-3": .15, "DENV-4": .05},
            "base_biting_rate": 0.31,
            "mosquito_to_human": 0.12,
            "human_to_mosquito": 0.18,
            "vector_eip_days": {"minimum": 5, "maximum": 14},
        },
        "mobility": mobility_matrix(),
        "weather_mapping": weather_mapping(),
        "clinical": clinical_parameters(),
        "surveillance": surveillance_parameters(),
        "wmar1": {
            "katora": {"pilot_share": .10, "community_coverage": .65, "field_effectiveness": .45},
            "western": {"pilot_share": .15, "community_coverage": .65, "field_effectiveness": .45},
            "other_provinces_coverage": 0.0,
        },
    }
```

Use these exact helper tables and formulas:

```python
def mobility_matrix() -> dict[str, dict[str, float]]:
    rows = {
        "katora":              [.930, .025, .012, .014, .007, .009, .003],
        "western":             [.035, .925, .015, .008, .004, .010, .003],
        "central_highlands":   [.035, .025, .920, .015, .002, .002, .001],
        "eastern_coast":       [.060, .015, .020, .895, .004, .004, .002],
        "timo":                [.025, .010, .005, .005, .945, .007, .003],
        "pela":                [.035, .020, .003, .003, .006, .930, .003],
        "ruwa":                [.020, .020, .005, .005, .005, .005, .940],
    }
    matrix = {row: dict(zip(PROVINCES, values, strict=True)) for row, values in rows.items()}
    if any(abs(sum(values.values()) - 1.0) > 1e-9 for values in matrix.values()):
        raise ValueError("mobility row does not sum to one")
    return matrix

def weather_mapping() -> dict[str, dict[str, float | str]]:
    return {
        "katora": {"source": "katora", "temp_offset_c": 0.0, "rain_scale": 1.0, "humidity_offset_pct": 0.0},
        "western": {"source": "makadi_port", "temp_offset_c": 0.0, "rain_scale": 1.0, "humidity_offset_pct": 0.0},
        "central_highlands": {"source": "katora", "temp_offset_c": -4.0, "rain_scale": 1.25, "humidity_offset_pct": 5.0},
        "eastern_coast": {"source": "katora", "temp_offset_c": 0.2, "rain_scale": 1.15, "humidity_offset_pct": 4.0},
        "timo": {"source": "timo", "temp_offset_c": 0.0, "rain_scale": 1.0, "humidity_offset_pct": 0.0},
        "pela": {"source": "pela", "temp_offset_c": 0.0, "rain_scale": 1.0, "humidity_offset_pct": 0.0},
        "ruwa": {"source": "ruwa", "temp_offset_c": 0.0, "rain_scale": 1.0, "humidity_offset_pct": 0.0},
    }

def clinical_parameters() -> dict[str, Any]:
    return {
        "symptomatic_by_infection_order": {"1": .25, "2": .35, "3": .30, "4": .28},
        "severe_by_infection_order": {"1": .005, "2": .025, "3": .012, "4": .010},
        "age_severe_multiplier": {"0-4": 1.30, "5-14": 1.00, "15-29": .80, "30-59": 1.00, "60+": 1.60},
        "hospitalized_given_severe": .85,
        "treated_severe_fatality": .005,
        "overloaded_severe_fatality": .030,
        "soft_capacity_share": .70,
        "hard_capacity_share": .85,
    }

def surveillance_parameters() -> dict[str, Any]:
    return {
        "report_probability": {
            "katora": .48, "western": .38, "central_highlands": .25,
            "eastern_coast": .26, "timo": .28, "pela": .40, "ruwa": .22,
        },
        "severe_report_probability": .95,
        "daily_lab_capacity": {
            "katora": 40, "western": 20, "central_highlands": 8,
            "eastern_coast": 6, "timo": 8, "pela": 8, "ruwa": 4,
        },
        "release_offsets_days": {"provisional": 4, "revised": 14, "final": 28},
        "minimum_cases": {"watch": 5, "alert": 10, "outbreak": 15},
        "rt_watch": 1.1,
    }
```

Build the historical weekly ledger by distributing each province's fixed cumulative total across epidemiological weeks ending from `2026-01-04` through `2026-08-09`. Use wet-season weight `1.8` for January–April, taper weight `1.1` for May, dry-season weight `0.55` for June–August, normalize within each province, and apply stable largest-remainder rounding. This creates exact province totals without pretending the weekly pattern is observed.

- [ ] **Step 5: Add a CLI that writes canonical UTF-8 JSON**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(build_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0
```

- [ ] **Step 6: Generate the baseline and run focused tests**

Run: `python sim-engine/scripts/build_dengue_baseline.py`

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: builder tests pass; committed JSON equals `build_baseline()`.

- [ ] **Step 7: Commit Task 1**

```powershell
git add sim-engine/data/sources/dengue_external_anchors_2026.json sim-engine/data/dengue_baseline_2026.json sim-engine/scripts/build_dengue_baseline.py sim-engine/tests/test_dengue_model.py
git commit -m "feat: add dengue baseline sources"
```

### Task 2: Baseline Loader and Strict Validation

**Files:**

- Create: `sim-engine/engine/dengue_model.py`
- Modify: `sim-engine/tests/test_dengue_model.py`

**Interfaces:**

- Produces: `DengueDataError(RuntimeError)`
- Produces: `DengueBaseline.from_json(path: Path) -> DengueBaseline`
- Produces: `validate_baseline(raw: Mapping[str, Any]) -> None`

- [ ] **Step 1: Add failing loader and invalid-data tests**

```python
class DengueBaselineTests(unittest.TestCase):
    def test_loader_exposes_complete_dimensions(self):
        baseline = DengueBaseline.from_json(BASELINE_PATH)
        self.assertEqual(baseline.age_groups, AGE_GROUPS)
        self.assertEqual(baseline.serotypes, SEROTYPES)
        self.assertEqual(sum(baseline.province_populations.values()), 1_200_000)

    def test_loader_rejects_bad_mobility_row(self):
        raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        raw["mobility"]["katora"]["katora"] -= 0.1
        with self.assertRaisesRegex(DengueDataError, "baseline.mobility.katora"):
            DengueBaseline.from_mapping(raw)
```

- [ ] **Step 2: Run the focused test and observe the missing-class failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: import failure for `DengueBaseline`.

- [ ] **Step 3: Implement the immutable baseline interface**

```python
AGE_GROUPS = ("0-4", "5-14", "15-29", "30-59", "60+")
SEROTYPES = ("DENV-1", "DENV-2", "DENV-3", "DENV-4")
PROVINCES = (
    "katora", "western", "central_highlands", "eastern_coast",
    "timo", "pela", "ruwa",
)

class DengueDataError(RuntimeError):
    pass

@dataclass(frozen=True)
class DengueBaseline:
    raw: dict[str, Any]
    version: str
    anchor_date: date
    age_groups: tuple[str, ...]
    serotypes: tuple[str, ...]
    province_populations: dict[str, int]

    @classmethod
    def from_json(cls, path: Path) -> "DengueBaseline":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DengueDataError(f"baseline: {exc}") from exc
        return cls.from_mapping(raw)
```

Validate exact dimensions, unique keys, finite probabilities, distribution sums within `1e-9`, mobility row sums within `1e-9`, non-negative capacities, source metadata, the 1.2 million province total, and the 1,240 historical total. Error messages begin with the exact JSON field path.

- [ ] **Step 4: Run loader tests and the full baseline suite**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: all `DengueBaselineTests` pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add sim-engine/engine/dengue_model.py sim-engine/tests/test_dengue_model.py
git commit -m "feat: validate dengue baseline"
```

### Task 3: Human State, Immunity Masks, and Initialization

**Files:**

- Create: `sim-engine/engine/dengue_dynamics.py`
- Create: `sim-engine/tests/test_dengue_dynamics.py`
- Modify: `sim-engine/engine/dengue_model.py`
- Modify: `sim-engine/tests/test_dengue_model.py`

**Interfaces:**

- Produces: `national_age_totals(population_state: Mapping[str, Any]) -> dict[str, int]`
- Produces: `allocate_province_ages(age_totals, baseline) -> dict[str, dict[str, int]]`
- Produces: `initialize_human_state(province_ages, baseline, rng_factory) -> dict`
- Produces: `advance_human_state(previous, force, baseline, rng_factory) -> tuple[dict, dict]`
- Produces: `initialize_dengue_state(current_date, population_state, baseline, rng_factory, initialization_source) -> dict`

- [ ] **Step 1: Add failing age-allocation and immunity tests**

```python
class DengueHumanStateTests(unittest.TestCase):
    def test_province_age_allocation_reconciles_exactly(self):
        totals = national_age_totals(self.population_state)
        allocated = allocate_province_ages(totals, self.baseline)
        for age in AGE_GROUPS:
            self.assertEqual(sum(p[age] for p in allocated.values()), totals[age])

    def test_same_serotype_cannot_reinfect_immune_mask(self):
        self.assertFalse(is_susceptible(mask=0b0010, serotype_index=1))
        self.assertTrue(is_susceptible(mask=0b0010, serotype_index=0))

    def test_cross_immunity_expires_on_day_180(self):
        state = seeded_cross_protected_state(count=7, remaining_days=1)
        next_state, flows = advance_human_state(state, zero_force(), self.baseline, self.rng_factory)
        self.assertEqual(flows["cross_protection_expired"], 7)
        self.assertEqual(next_state["susceptible"]["0-4"]["0001"], 7)
```

- [ ] **Step 2: Run the focused dynamics test and observe missing functions**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_dynamics.py" -v`

Expected: import failure for `national_age_totals` or `is_susceptible`.

- [ ] **Step 3: Implement age aggregation and exact provincial allocation**

```python
AGE_BOUNDS = {"0-4": (0, 4), "5-14": (5, 14), "15-29": (15, 29), "30-59": (30, 59), "60+": (60, 100)}

def national_age_totals(population_state: Mapping[str, Any]) -> dict[str, int]:
    cohorts = population_state["cohorts"]
    return {
        label: sum(
            cohorts[sex][age]
            for sex in ("male", "female")
            for age in range(lower, upper + 1)
        )
        for label, (lower, upper) in AGE_BOUNDS.items()
    }

def is_susceptible(mask: int, serotype_index: int) -> bool:
    return mask & (1 << serotype_index) == 0
```

Use one reusable largest-remainder allocator with stable province-order tie breaking. First allocate each age group by province population share; then allocate each province-age total across 16 immunity masks using the approved age prior and province multiplier.

- [ ] **Step 4: Implement sparse staged compartments and ring advancement**

```python
def empty_human_state(province_ages: Mapping[str, Mapping[str, int]]) -> dict:
    return {
        province: {
            "population_by_age": dict(ages),
            "susceptible": {age: {"0000": count} for age, count in ages.items()},
            "exposed": [],
            "infectious": [],
            "cross_protected": [[] for _ in range(180)],
        }
        for province, ages in province_ages.items()
    }

def recovered_mask(prior_mask: int, serotype_index: int) -> int:
    return prior_mask | (1 << serotype_index)
```

Each exposed/infectious sparse cohort stores `age_group`, `prior_mask`, `serotype`, `days_remaining`, `count`, and clinical classification. Advance existing cohorts before adding new infections, merge identical keys, remove zero-count cohorts, and rotate exactly one cross-protection ring bucket per day.

- [ ] **Step 5: Implement stochastic integer transitions with isolated draws**

```python
def draw_binomial(count: int, probability: float, rng: random.Random) -> int:
    if count < 0 or not 0.0 <= probability <= 1.0:
        raise DengueDataError("binomial: invalid count or probability")
    return sum(rng.random() < probability for _ in range(count))

def infection_order(mask: int) -> int:
    return mask.bit_count() + 1
```

Use a multinomial-by-sequential-binomial allocation for competing serotypes so allocated infections never exceed the susceptible stock. Stream names include province, age, mask, serotype, and transition.

- [ ] **Step 6: Implement dated initialization**

```python
def initialize_dengue_state(
    current_date: date,
    population_state: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
    initialization_source: str,
) -> dict[str, Any]:
    age_totals = national_age_totals(population_state)
    province_ages = allocate_province_ages(age_totals, baseline)
    return {
        "version": "mariven-dengue-state-v1",
        "baseline_version": baseline.version,
        "random_schema_version": 4,
        "last_processed_date": current_date.isoformat(),
        "initialization_source": initialization_source,
        "provinces": initialize_human_state(province_ages, baseline, rng_factory),
        "cross_immunity_cursor": 0,
    }
```

Seed the historical ledger only through `min(current_date - 1 day, 2026-08-10)`. For `2026-08-11`, seed the approved active E/I and vector snapshot deterministically; do not emit historical events.

- [ ] **Step 7: Run focused tests and commit Task 3**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_dynamics.py" -v`

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: all human-state, immunity, initialization, and loader tests pass.

```powershell
git add sim-engine/engine/dengue_dynamics.py sim-engine/engine/dengue_model.py sim-engine/tests/test_dengue_dynamics.py sim-engine/tests/test_dengue_model.py
git commit -m "feat: add dengue human immunity state"
```

### Task 4: Weather, Mosquito SEI, Mobility, and wMar-1

**Files:**

- Modify: `sim-engine/engine/dengue_dynamics.py`
- Modify: `sim-engine/tests/test_dengue_dynamics.py`

**Interfaces:**

- Produces: `derive_province_weather(weather, baseline) -> dict[str, dict[str, float]]`
- Produces: `advance_vector_state(previous, province_weather, human_infectiousness, interventions, baseline) -> tuple[dict, dict]`
- Produces: `mix_force_of_infection(local_force, mobility) -> dict`

- [ ] **Step 1: Add failing lag, matrix, and pilot tests**

```python
def test_rainfall_changes_larval_pressure_after_lag(self):
    dry = advance_vector_state(self.vector, weather(rain=0), zero_human_force(), self.interventions, self.baseline)
    wet = advance_vector_state(self.vector, weather(rain=40), zero_human_force(), self.interventions, self.baseline)
    self.assertEqual(dry[0]["katora"]["adult_total"], wet[0]["katora"]["adult_total"])
    self.assertGreater(wet[0]["katora"]["rainfall_queue"][-1], dry[0]["katora"]["rainfall_queue"][-1])

def test_wmar1_reduces_only_pilot_provinces(self):
    treated = vector_competence_by_province(self.baseline)
    self.assertLess(treated["katora"], 1.0)
    self.assertLess(treated["western"], 1.0)
    self.assertEqual(treated["timo"], 1.0)
```

- [ ] **Step 2: Run focused tests and observe missing vector functions**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_dynamics.py" -v`

Expected: new vector tests fail with missing functions.

- [ ] **Step 3: Implement province weather derivation and bounded suitability**

```python
def vector_suitability(temp_mean: float, humidity: float, rain_14d: float) -> float:
    temperature = max(0.0, 1.0 - ((temp_mean - 28.0) / 12.0) ** 2)
    moisture = min(1.5, max(0.2, 0.45 + humidity / 200.0 + rain_14d / 350.0))
    return min(1.5, max(0.0, temperature * moisture))

def extrinsic_incubation_days(temp_mean: float) -> int:
    return min(14, max(5, round(14.0 - (temp_mean - 20.0) * 0.75)))
```

Map Katora, Western, Timo, Pela, and Ruwa directly to the existing five weather keys. Apply versioned temperature/rain modifiers to Central Highlands and Eastern Coast without mutating public weather.

- [ ] **Step 4: Implement vector SEI and delayed rainfall queues**

```python
def wmar_residual_competence(intervention: Mapping[str, float]) -> float:
    affected = (
        intervention["pilot_share"]
        * intervention["community_coverage"]
        * intervention["field_effectiveness"]
    )
    return min(1.0, max(0.0, 1.0 - affected))
```

Store `larval_pressure`, `susceptible`, four EIP bucket lists, four infectious indices, `rainfall_queue`, and `adult_total`. Flush extreme-rain effects at 1–3 days and emergence effects at 7–14 days. Reject negative or non-finite vector values before return.

- [ ] **Step 5: Implement mobility mixing with no population movement**

```python
def mix_force_of_infection(local_force, mobility):
    return {
        resident: {
            serotype: sum(
                mobility[resident][source] * local_force[source][serotype]
                for source in PROVINCES
            )
            for serotype in SEROTYPES
        }
        for resident in PROVINCES
    }
```

- [ ] **Step 6: Run focused tests and commit Task 4**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_dynamics.py" -v`

Expected: immunity, weather, vector, mobility, and wMar-1 tests all pass.

```powershell
git add sim-engine/engine/dengue_dynamics.py sim-engine/tests/test_dengue_dynamics.py
git commit -m "feat: add dengue vector transmission"
```

### Task 5: Clinical Outcomes, Reporting, Releases, and Alerts

**Files:**

- Create: `sim-engine/engine/dengue_surveillance.py`
- Create: `sim-engine/tests/test_dengue_surveillance.py`

**Interfaces:**

- Produces: `classify_clinical_outcomes(infection_flows, pressure, baseline, rng_factory) -> dict`
- Produces: `advance_surveillance(d, previous, clinical_flows, baseline, rng_factory) -> tuple[dict, list[dict]]`
- Produces: `surveillance_snapshot(d, state, population_by_province, baseline) -> dict`

- [ ] **Step 1: Add failing reporting and release tests**

```python
class DengueSurveillanceTests(unittest.TestCase):
    def test_reported_confirmed_and_true_infections_are_distinct(self):
        flows = classify_clinical_outcomes(sample_infections(100), 0.2, self.baseline, self.rng_factory)
        self.assertEqual(flows["infections"], 100)
        self.assertLessEqual(flows["reported"], flows["symptomatic"])
        self.assertLessEqual(flows["confirmed"], flows["reported"])

    def test_release_dates_are_plus_4_14_28(self):
        week_end = date(2026, 8, 16)
        self.assertEqual(release_dates(week_end), {
            "provisional": date(2026, 8, 20),
            "revised": date(2026, 8, 30),
            "final": date(2026, 9, 13),
        })
```

- [ ] **Step 2: Run the focused test and observe the missing-module failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_surveillance.py" -v`

Expected: `ImportError` for `dengue_surveillance`.

- [ ] **Step 3: Implement clinical multinomial outcomes**

```python
def severe_probability(age: str, prior_mask: int, clinical: Mapping[str, Any]) -> float:
    order = prior_mask.bit_count() + 1
    base = clinical["severe_by_infection_order"][str(min(order, 4))]
    return min(1.0, base * clinical["age_severe_multiplier"][age])

def treated_fatality_probability(pressure: float, clinical: Mapping[str, Any]) -> float:
    low = clinical["treated_severe_fatality"]
    high = clinical["overloaded_severe_fatality"]
    overload = min(1.0, max(0.0, (pressure - 0.70) / 0.30))
    return low + (high - low) * overload * overload
```

Use sequential binomial draws in this order: symptomatic, warning signs, severe, hospital, fatal, care seeking, reported, sampled, confirmed. Each count must be bounded by its parent count.

- [ ] **Step 4: Implement laboratory and report queues**

```python
def release_dates(week_end: date) -> dict[str, date]:
    return {
        "provisional": week_end + timedelta(days=4),
        "revised": week_end + timedelta(days=14),
        "final": week_end + timedelta(days=28),
    }

def epidemiological_week(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)
```

Queue each report with infection date, onset date, report date, province, age, serotype, and classification. Aggregate queues before publication; revisions append vintages with deltas and never replace prior vintages.

- [ ] **Step 5: Implement province and national alert state machines**

```python
def province_alert(cases, p75, p90, p95, rt, confirmed, pressure, previous):
    if previous in ("alert", "outbreak", "recovery") and cases < p90 and rt < 1.0:
        return "recovery"
    if (cases >= max(15, p95) and confirmed >= 3) or pressure >= 0.85:
        return "outbreak"
    if (cases >= max(10, p90) and rt >= 1.1) or pressure >= 0.70:
        return "alert"
    if cases >= max(5, p75) or rt >= 1.1:
        return "watch"
    return "baseline"
```

Keep counters for the required two-week growth/outbreak and three-week recovery persistence; a single daily call cannot skip persistence requirements. National emergency is true only for at least two outbreak provinces plus one alert province, or national pressure at or above 0.85 for two weeks.

- [ ] **Step 6: Run surveillance tests and commit Task 5**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_surveillance.py" -v`

Expected: clinical, lab, release, revision, and alert tests pass.

```powershell
git add sim-engine/engine/dengue_surveillance.py sim-engine/tests/test_dengue_surveillance.py
git commit -m "feat: add dengue surveillance releases"
```

### Task 6: Daily Dengue Orchestration, Snapshot, and Reconciliation

**Files:**

- Modify: `sim-engine/engine/dengue_model.py`
- Modify: `sim-engine/tests/test_dengue_model.py`

**Interfaces:**

- Produces: `dengue_step(d: date, previous_state: Mapping[str, Any], population_state: Mapping[str, Any], weather: Mapping[str, Any], nation_profile: Mapping[str, Any], baseline: DengueBaseline, rng_factory: Callable[[str], random.Random]) -> tuple[dict, dict, list[dict], list[dict]]`
- Produces: `reconcile_dengue_population(state: Mapping[str, Any], before_population: Mapping[str, Any], after_population: Mapping[str, Any], confirmed_deaths: list[Mapping[str, Any]], baseline: DengueBaseline) -> dict`
- Produces: `dengue_snapshot(d: date, state: Mapping[str, Any], baseline: DengueBaseline) -> dict`
- Produces: `validate_dengue_state(state: Mapping[str, Any], d: date, national_age_totals: Mapping[str, int], baseline: DengueBaseline) -> None`

- [ ] **Step 1: Add failing pure-step, conservation, and snapshot tests**

```python
def test_daily_step_is_pure_deterministic_and_conserving(self):
    original = copy.deepcopy(self.state)
    first = dengue_step(self.day, self.state, self.population_state, self.weather, self.profile, self.baseline, self.rng_factory)
    second = dengue_step(self.day, self.state, self.population_state, self.weather, self.profile, self.baseline, self.rng_factory)
    self.assertEqual(first, second)
    self.assertEqual(self.state, original)
    self.assertEqual(total_humans(first[1]), sum(national_age_totals(self.population_state).values()))

def test_snapshot_separates_estimated_and_reported(self):
    public = dengue_snapshot(self.day, self.state, self.baseline)
    self.assertIn("estimated_infections", public["national"])
    self.assertIn("reported_cases", public["national"])
```

- [ ] **Step 2: Run focused tests and observe missing orchestration**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue_model.py" -v`

Expected: new orchestration tests fail.

- [ ] **Step 3: Implement the public daily function**

```python
def dengue_step(
    d: date,
    previous_state: Mapping[str, Any],
    population_state: Mapping[str, Any],
    weather: Mapping[str, Any],
    nation_profile: Mapping[str, Any],
    baseline: DengueBaseline,
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict, dict, list[dict], list[dict]]:
    next_state = copy.deepcopy(dict(previous_state))
    expected = date.fromisoformat(next_state["last_processed_date"]) + timedelta(days=1)
    if d != expected:
        raise DengueDataError(f"state.model_state.dengue.last_processed_date: expected {expected}")
    province_weather = derive_province_weather(weather, baseline)
    previous_humans = {
        province: next_state["provinces"][province]["human"]
        for province in PROVINCES
    }
    previous_vectors = {
        province: next_state["provinces"][province]["vector"]
        for province in PROVINCES
    }
    infectiousness = infectiousness_by_province(previous_humans, baseline)
    interventions = {
        province: next_state["provinces"][province]["interventions"]
        for province in PROVINCES
    }
    vector_state, vector_flows = advance_vector_state(
        previous_vectors,
        province_weather,
        infectiousness,
        interventions,
        baseline,
    )
    force = mix_force_of_infection(vector_flows["local_force"], baseline.raw["mobility"])
    human_state, infection_flows = advance_human_state(
        previous_humans,
        force,
        baseline,
        lambda name: rng_factory(f"human:{name}"),
    )
    clinical = classify_clinical_outcomes(
        infection_flows,
        healthcare_pressure(next_state["surveillance"], nation_profile, baseline),
        baseline,
        lambda name: rng_factory(f"clinical:{name}"),
    )
    surveillance, release_events = advance_surveillance(
        d,
        next_state["surveillance"],
        clinical,
        baseline,
        lambda name: rng_factory(f"surveillance:{name}"),
    )
    death_requests = build_death_requests(clinical)
    for province in PROVINCES:
        next_state["provinces"][province]["human"] = human_state[province]
        next_state["provinces"][province]["vector"] = vector_state[province]
    next_state["surveillance"] = surveillance
    next_state["last_processed_date"] = d.isoformat()
    validate_dengue_state(next_state, d, national_age_totals(population_state), baseline)
    return daily_dengue_flows(infection_flows, clinical), next_state, death_requests, release_events
```

- [ ] **Step 4: Implement population reconciliation**

```python
def reconcile_dengue_population(
    state: Mapping[str, Any],
    before_population: Mapping[str, Any],
    after_population: Mapping[str, Any],
    confirmed_deaths: list[Mapping[str, Any]],
    baseline: DengueBaseline,
) -> dict[str, Any]:
    next_state = copy.deepcopy(dict(state))
    apply_confirmed_dengue_deaths(next_state, confirmed_deaths)
    target = national_age_totals(after_population)
    current = dengue_age_totals(next_state)
    for age in AGE_GROUPS:
        reconcile_age_delta(next_state, age, target[age] - current[age], baseline)
    validate_dengue_state(next_state, date.fromisoformat(next_state["last_processed_date"]), target, baseline)
    return next_state
```

Positive age deltas add births to `0-4/0000`; other additions use province shares and age-specific immigrant immunity priors. Negative residuals remove proportionally from susceptible/cross-protected/E/I stocks using deterministic largest-remainder allocation, never removing more than a stock contains.

- [ ] **Step 5: Implement strict state and snapshot validation**

Validate date continuity, versions, all required province/age/serotype dimensions, integer human stocks, finite vectors/probabilities, mutual exclusivity, population equality, ring length/cursor, bounded histories, release ordering, and annual ledger identities. Build `public_health.dengue` exclusively from validated internal state.

- [ ] **Step 6: Run all dengue tests and commit Task 6**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue*.py" -v`

Expected: all dengue model, dynamics, and surveillance tests pass.

```powershell
git add sim-engine/engine/dengue_model.py sim-engine/tests/test_dengue_model.py
git commit -m "feat: orchestrate daily dengue state"
```

### Task 7: Cause-Specific Deaths in the Population Model

**Files:**

- Modify: `sim-engine/engine/population_model.py`
- Modify: `sim-engine/tests/test_population_model.py`

**Interfaces:**

- Extends: `population_step(d: date, previous_state: Mapping[str, Any], notable_deaths: Mapping[str, Any], baseline: PopulationBaseline, rng_factory: Callable[[str], random.Random], *, cause_specific_deaths: Sequence[Mapping[str, Any]] = ())`
- Adds: `demographics.cause_specific_deaths_today`
- Adds: `deaths_today.dengue`

- [ ] **Step 1: Add failing age-targeted death tests**

```python
def test_cause_specific_death_is_removed_once_from_requested_age_group(self):
    before = age_band_total(self.state, "5-14")
    public, next_state, deaths, _ = population_step(
        date(2026, 8, 12), self.state, {"total": 0}, self.baseline,
        self.rng_factory,
        cause_specific_deaths=[{"cause": "dengue", "province": "western", "age_group": "5-14", "count": 1}],
    )
    self.assertEqual(deaths["dengue"], 1)
    self.assertEqual(age_band_total(next_state, "5-14"), before - 1 + public["births_today"] * 0)
    self.assertEqual(public["cause_specific_deaths_today"][0]["count"], 1)
```

- [ ] **Step 2: Run the focused population test and observe signature failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_population_model.py" -v`

Expected: `population_step()` rejects `cause_specific_deaths`.

- [ ] **Step 3: Return exact removed cells from `_remove_people`**

```python
def _remove_people(
    state: dict[str, Any],
    count: int,
    weights: Mapping[str, list[float]],
    rng: random.Random,
    *,
    mortality_rates: Mapping[str, list[float]] | None = None,
    path: str,
) -> dict[str, list[int]]:
    removed = {sex: [0] * AGE_COUNT for sex in SEXES}
    for _ in range(count):
        preferred_sex, preferred_age = _weighted_cell(preference_weights, rng)
        sex, age = adjacent_available(preferred_sex, preferred_age)
        _remove_from_cell(state, sex, age, rng)
        removed[sex][age] += 1
    return removed
```

Existing callers ignore the return value and keep identical draw order.

- [ ] **Step 4: Validate and apply structured requests before non-notable deaths**

```python
AGE_BOUNDS = {"0-4": (0, 4), "5-14": (5, 14), "15-29": (15, 29), "30-59": (30, 59), "60+": (60, 100)}

def _cause_weights(age_group: str) -> dict[str, list[float]]:
    lower, upper = AGE_BOUNDS[age_group]
    return {
        sex: [1.0 if lower <= age <= upper else 0.0 for age in range(AGE_COUNT)]
        for sex in SEXES
    }
```

Validate `cause == "dengue"`, known province, known age group, and non-negative integer count. Include cause-specific counts in `notable_total`, so baseline deaths absorb them first and only the amount above baseline becomes excess. Return the exact age/sex removal cells in `demographics.cause_specific_deaths_today`.

- [ ] **Step 5: Run population and engine regression tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_population_model.py" -v`

Run: `python -m unittest discover -s sim-engine/tests -p "test_engine.py" -v`

Expected: new cause-specific tests and all legacy death-accounting tests pass.

- [ ] **Step 6: Commit Task 7**

```powershell
git add sim-engine/engine/population_model.py sim-engine/tests/test_population_model.py
git commit -m "feat: reconcile cause-specific deaths"
```

### Task 8: Schema v5 Migration and Validation

**Files:**

- Modify: `sim-engine/engine/state.py`
- Modify: `sim-engine/tests/test_state.py`

**Interfaces:**

- Changes: `SCHEMA_VERSION = 5`
- Extends: `validate_state(state: Mapping[str, Any], *, population_baseline: PopulationBaseline | None = None, gdp_baseline: GdpBaseline | None = None, dengue_baseline: DengueBaseline | None = None) -> None`
- Extends: `migrate_state(raw: Mapping[str, Any], *, base_seed: int | None = None, population_baseline: PopulationBaseline | None = None, gdp_baseline: GdpBaseline | None = None, dengue_baseline: DengueBaseline | None = None) -> dict`
- Extends: `prepare_state(raw: Mapping[str, Any], *, population_baseline: PopulationBaseline | None = None, gdp_baseline: GdpBaseline | None = None, dengue_baseline: DengueBaseline | None = None) -> dict`

- [ ] **Step 1: Add failing migration and validation tests**

```python
def test_prepare_migrates_v4_to_v5_with_dengue(self):
    v4 = migrate_to_v4(V1)
    migrated = prepare_state(v4)
    self.assertEqual(migrated["schema_version"], 5)
    self.assertIn("dengue", migrated["model_state"])
    self.assertIn("dengue", migrated["public_health"])

def test_early_2026_migration_uses_calibration_reconstruction(self):
    early = copy.deepcopy(V1)
    early["date"] = "2026-04-01"
    migrated = migrate_state(early)
    self.assertEqual(migrated["model_state"]["dengue"]["initialization_source"], "calibration_reconstruction")
```

- [ ] **Step 2: Run state tests and observe expected schema failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_state.py" -v`

Expected: tests expect schema 5 while implementation still returns 4.

- [ ] **Step 3: Add v4-to-v5 migration**

```python
def _migrate_v4_to_v5(raw, population_baseline, gdp_baseline, dengue_baseline):
    migrated = copy.deepcopy(dict(raw))
    current_date = _parse_date(migrated.get("date"))
    if current_date < date(2026, 1, 1):
        _fail("state.date", "dengue schema v5 requires 2026-01-01 or later")
    population_state = _require_mapping(_require_mapping(migrated, "model_state"), "population", "state.model_state")
    source = (
        "calibration_reconstruction" if current_date < dengue_baseline.anchor_date
        else "anchor_snapshot" if current_date == dengue_baseline.anchor_date
        else "legacy_replay"
    )
    dengue_state = initialize_dengue_state(
        current_date, population_state, dengue_baseline,
        migration_rng_factory(migrated["base_seed"], current_date), source,
    )
    migrated["schema_version"] = 5
    migrated["model_state"]["dengue"] = dengue_state
    migrated["public_health"] = {
        **copy.deepcopy(dict(migrated.get("public_health", {}))),
        "dengue": dengue_snapshot(current_date, dengue_state, dengue_baseline),
    }
    return migrated
```

Route schema `None -> 2 -> 3 -> 4 -> 5`, `2 -> 3 -> 4 -> 5`, `3 -> 4 -> 5`, and `4 -> 5`; deep-copy schema 5 states before validation. Keep existing base-seed override behavior.

- [ ] **Step 4: Extend strict whole-state validation**

Require `public_health` in `_CORE_DICTIONARIES`, add `dengue` to `_MODEL_DICTIONARIES`, invoke `validate_dengue_state`, and verify that the public snapshot date and national population match the internal state. Preserve unknown dictionaries and fields.

- [ ] **Step 5: Run state and full regression tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_state.py" -v`

Run: `python -m unittest discover -s sim-engine/tests`

Expected: schema tests pass and the original 169 tests remain green after expectation updates from schema 4 to schema 5.

- [ ] **Step 6: Commit Task 8**

```powershell
git add sim-engine/engine/state.py sim-engine/tests/test_state.py
git commit -m "feat: migrate state to dengue schema v5"
```

### Task 9: Main Engine Integration

**Files:**

- Modify: `sim-engine/engine/engine.py`
- Modify: `sim-engine/tests/test_engine.py`

**Interfaces:**

- Adds: `EngineResources.dengue_baseline: DengueBaseline`
- Adds: dengue random schema version 4 and namespaced daily streams.
- Adds: dengue public-health line to `render_brief`.

- [ ] **Step 1: Add failing integration and stream-isolation tests**

```python
def test_tick_uses_dengue_model_and_public_health(self):
    next_state = tick(self.state, resources=self.resources)
    self.assertEqual(next_state["model_state"]["dengue"]["last_processed_date"], next_state["date"])
    self.assertIn("reported_cases", next_state["public_health"]["dengue"]["national"])

def test_dengue_integration_does_not_perturb_legacy_streams(self):
    integrated = tick(self.state, resources=self.resources)
    self.assertEqual(integrated["weather"], self.legacy_expected["weather"])
    self.assertEqual(integrated["economy"]["exchange_rates"], self.legacy_expected["economy"]["exchange_rates"])
```

- [ ] **Step 2: Run engine tests and observe missing resource/model failures**

Run: `python -m unittest discover -s sim-engine/tests -p "test_engine.py" -v`

Expected: `EngineResources` lacks `dengue_baseline` or public health is absent.

- [ ] **Step 3: Load the dengue baseline and add an isolated RNG factory**

```python
def dengue_rng(stream_name: str):
    return make_rng(base_seed, 4, d, "dengue", stream_name)
```

Pass `resources.dengue_baseline` into `prepare_state()` and `validate_state()`. Do not change existing random schema numbers or stream names.

- [ ] **Step 4: Insert dengue before unified population removal and reconcile after it**

```python
daily_dengue, dengue_state, dengue_deaths, dengue_events = dengue_step(
    d, model_state["dengue"], model_state["population"], weather,
    resources.nation_profile, resources.dengue_baseline, dengue_rng,
)
notable_deaths, general_events = events_step(d, next_state, weather, event_rng)
demographics, population_state, deaths, population_events = population_step(
    d, model_state["population"], notable_deaths,
    resources.population_baseline, population_rng,
    cause_specific_deaths=dengue_deaths,
)
dengue_state = reconcile_dengue_population(
    dengue_state, model_state["population"], population_state,
    demographics["cause_specific_deaths_today"], resources.dengue_baseline,
)
next_state["model_state"]["dengue"] = dengue_state
next_state["public_health"]["dengue"] = dengue_snapshot(
    d, dengue_state, resources.dengue_baseline,
)
```

Append `dengue_events` before population events and general events. Deduplicate stable event keys exactly as existing weather alerts are handled.

- [ ] **Step 5: Render a concise dengue brief**

```python
dengue = state.get("public_health", {}).get("dengue")
if dengue:
    national = dengue["national"]
    lines.append(
        f"**登革热** 第{dengue['epidemiological_week']}周 "
        f"报告 {national['reported_cases']} 例 | "
        f"住院 {national['hospitalized']} | "
        f"预警 {national['alert_level']}"
    )
```

- [ ] **Step 6: Run engine tests, strict JSON tests, and commit Task 9**

Run: `python -m unittest discover -s sim-engine/tests -p "test_engine.py" -v`

Expected: deterministic tick, serialized resume, death reconciliation, public health, strict JSON, and legacy random isolation tests pass.

```powershell
git add sim-engine/engine/engine.py sim-engine/tests/test_engine.py
git commit -m "feat: integrate dengue into daily engine"
```

### Task 10: Annual Calibration, Long-Run Stability, and Counterfactuals

**Files:**

- Modify: `sim-engine/tests/test_dengue_model.py`
- Modify: `sim-engine/tests/test_annual_calibration.py`
- Modify: `sim-engine/data/dengue_baseline_2026.json`
- Modify: `sim-engine/scripts/build_dengue_baseline.py`

**Interfaces:**

- Verifies only; no new public production interface.

- [ ] **Step 1: Add failing 365-day and central-scenario tests**

```python
def test_central_2026_reported_cases_are_in_target_band(self):
    state = migrate_state(copy.deepcopy(BASE_STATE))
    while state["date"] < "2026-12-31":
        state = tick(state, resources=self.resources)
    reported = state["model_state"]["dengue"]["cumulative_annual"]["reported"]
    self.assertGreaterEqual(reported, 1_500)
    self.assertLessEqual(reported, 2_000)

def test_365_days_preserve_dengue_population_and_bounds(self):
    states = run_days(copy.deepcopy(BASE_STATE), 365, resources=self.resources)
    final = states[-1]
    self.assertEqual(total_humans(final["model_state"]["dengue"]), final["population"])
    self.assertLess(serialized_dengue_size(final), 8_000_000)
```

- [ ] **Step 2: Run annual tests and record the exact failure**

Run: `python -m unittest discover -s sim-engine/tests -p "test_annual_calibration.py" -v`

Expected before calibration: target-band or long-run-bound assertion fails; record the observed count in the implementation notes.

- [ ] **Step 3: Fix calibration using only declared baseline levers**

Keep `human_incubation_days`, `infectious_days`, immunity priors, 1,240 historical cases, mobility, and wMar-1 fixed. Adjust only these builder constants as one coherent calibration vector:

```python
CALIBRATION = {
    "base_biting_rate": 0.31,
    "mosquito_to_human": 0.12,
    "human_to_mosquito": 0.18,
    "care_seeking_scale": 1.00,
    "importation_weekly_scale": 1.00,
}
```

Regenerate the baseline after every change. Accept the first vector for which the fixed seed 42 finishes in 1,500–2,000 and the 12-seed median also finishes in that band; do not add a year-end correction or case-count clamp.

- [ ] **Step 4: Add paired counterfactual and 10-year soak tests**

```python
def test_wmar_pair_reduces_mean_pilot_transmission(self):
    treated = paired_runs(seeds=range(12), wmar=True)
    untreated = paired_runs(seeds=range(12), wmar=False)
    self.assertLess(mean_pilot_infections(treated), mean_pilot_infections(untreated))

def test_ten_year_soak_keeps_state_finite_and_bounded(self):
    final = run_dengue_only_days(self.initial, 3652)
    validate_dengue_state(final, date.fromisoformat(final["last_processed_date"]), dengue_age_totals(final), self.baseline)
    self.assertLess(len(final["weekly_ledger"]), 110)
```

Use paired named streams so wMar-1 and rain interventions do not change unrelated random draws. Keep the soak test in the dengue-only layer so the normal full suite remains fast.

- [ ] **Step 5: Run all dengue, annual, and full tests**

Run: `python -m unittest discover -s sim-engine/tests -p "test_dengue*.py" -v`

Run: `python -m unittest discover -s sim-engine/tests -p "test_annual_calibration.py" -v`

Run: `python -m unittest discover -s sim-engine/tests`

Expected: target band, paired effects, 365-day invariants, 10-year bounded state, and all old/new tests pass.

- [ ] **Step 6: Commit Task 10**

```powershell
git add sim-engine/scripts/build_dengue_baseline.py sim-engine/data/dengue_baseline_2026.json sim-engine/tests/test_dengue_model.py sim-engine/tests/test_annual_calibration.py
git commit -m "test: calibrate complete dengue model"
```

### Task 11: Documentation and Final Verification

**Files:**

- Modify: `README.md`
- Modify: `sim-engine/docs/model-catalog.md`

**Interfaces:**

- Documents schema v5, public dengue output, source distinctions, run commands, and model limitations.

- [ ] **Step 1: Update README model status and data inventory**

Replace the dengue P0 planned row with an implemented row that states: seven provinces, five ages, four serotypes, immune history, mosquito SEI, weekly releases, healthcare pressure, and wMar-1 limited pilots. Add the two dengue JSON files and baseline builder command to the reproducibility section.

- [ ] **Step 2: Replace the catalog's planned SIR entry**

Document the actual public contract:

```text
public_health.dengue.national
public_health.dengue.provinces
public_health.dengue.serotypes
public_health.dengue.healthcare_pressure
public_health.dengue.interventions
public_health.dengue.latest_release
```

State that estimated infections are not reported cases, wMar-1 is fictional project canon, and external Fiji/WHO data are calibration context rather than Mariven observations.

- [ ] **Step 3: Validate generated data and compile Python**

Run: `python sim-engine/scripts/build_dengue_baseline.py --output "$env:TEMP\dengue_baseline_2026.json"`

Run: `python -c "import json, pathlib; json.loads(pathlib.Path('sim-engine/data/dengue_baseline_2026.json').read_text(encoding='utf-8')); print('dengue JSON OK')"`

Run: `python -m compileall -q sim-engine/engine sim-engine/scripts sim-engine/tests`

Expected: `dengue JSON OK`; compile command exits 0.

- [ ] **Step 4: Verify byte-exact baseline reproduction**

Run: `python -c "import sys, pathlib; a=pathlib.Path('sim-engine/data/dengue_baseline_2026.json').read_bytes(); b=pathlib.Path(__import__('os').environ['TEMP'])/'dengue_baseline_2026.json'; print('byte exact' if a == b.read_bytes() else 'mismatch'); sys.exit(0 if a == b.read_bytes() else 1)"`

Expected: `byte exact`.

- [ ] **Step 5: Run final full suite and dry-run**

Run: `python -c "import sys, unittest; suite=unittest.defaultTestLoader.discover('sim-engine/tests'); result=unittest.TextTestRunner(stream=sys.stdout, verbosity=0).run(suite); print(f'tests={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}'); sys.exit(0 if result.wasSuccessful() else 1)"`

Run: `python sim-engine/engine/engine.py --days 365 --dry-run`

Expected: all tests pass; dry-run exits 0 and leaves `sim-engine/data/state.json`, SQLite, and archives byte-identical.

- [ ] **Step 6: Inspect final repository diff**

Run: `git diff --check`

Run: `git status --short`

Run: `git log --oneline origin/master..HEAD`

Expected: no whitespace errors; only intended dengue, population-integration, schema, test, README, catalog, design, and plan files appear.

- [ ] **Step 7: Commit Task 11**

```powershell
git add README.md sim-engine/docs/model-catalog.md
git commit -m "docs: document complete dengue model"
```

- [ ] **Step 8: Request code review and address only verified findings**

Read every changed file, compare each specification section to a test or implementation path, rerun any affected focused test after corrections, and rerun the final full suite before declaring completion.
