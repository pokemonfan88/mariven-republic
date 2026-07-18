"""Deterministic quarterly GDP national-accounts model."""

import copy
import json
import math
from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


MAX_CLOSED_QUARTERS = 40
BASELINE_VERSION = "mariven-gdp-2026-v1"
DRIVER_VERSION = "mariven-gdp-drivers-2026-v1"
GDP_GROUP_SHARES = {
    "primary_and_mining": 14.2,
    "industry": 17.8,
    "services": 57.4,
    "net_product_taxes": 10.6,
}
EXPENDITURE_KEYS = {
    "household_consumption_mvl",
    "government_consumption_mvl",
    "gross_fixed_capital_formation_mvl",
    "changes_in_inventories_mvl",
    "exports_goods_services_mvl",
    "imports_goods_services_mvl",
    "statistical_discrepancy_mvl",
}
VINTAGE_ORDER = ("provisional", "revised", "final")


class GdpDataError(ValueError):
    """Raised when GDP calibration data or runtime state is invalid."""


def _fail(path: str, message: str) -> None:
    raise GdpDataError(f"{path}: {message}")


def _finite(value, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "expected a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        _fail(path, "expected a finite number")
    return converted


def _positive(value, path: str) -> float:
    converted = _finite(value, path)
    if converted <= 0.0:
        _fail(path, "expected a positive number")
    return converted


@dataclass(frozen=True)
class IndustrySpec:
    """One production-account industry in the 2025 benchmark."""

    group: str
    share_pct: float
    nominal_mvl: float
    real_growth_2026_pct: float
    quarter_weights: tuple[float, float, float, float]


@dataclass(frozen=True)
class GdpBaseline:
    """Validated, versioned GDP calibration data."""

    version: str
    base_year: int
    base_nominal_gdp_mvl: float
    real_growth_2025_pct: float
    real_growth_2026_pct: float
    deflator_growth_2026_pct: float
    nominal_target_2026_mvl: float
    industries: dict[str, IndustrySpec]
    expenditure: dict[str, float]
    tourism: dict[str, float]
    release_lags_days: dict[str, int]
    metadata: dict
    driver_parameters: dict

    @classmethod
    def from_json(cls, path: Path) -> "GdpBaseline":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GdpDataError(f"GDP baseline {path}: {exc}") from exc
        if not isinstance(raw, Mapping):
            _fail("baseline", "expected a dictionary")
        if raw.get("version") != BASELINE_VERSION:
            _fail("baseline.version", f"expected {BASELINE_VERSION}")
        base_year = raw.get("base_year")
        if (
            isinstance(base_year, bool)
            or not isinstance(base_year, int)
            or base_year != 2025
        ):
            _fail("baseline.base_year", "expected 2025")
        metadata = raw.get("metadata")
        if not isinstance(metadata, Mapping):
            _fail("baseline.metadata", "expected a dictionary")
        base_nominal_gdp = _positive(
            raw["annual_accounts"]["2025"]["nominal_gdp_mvl"],
            "baseline.annual_accounts.2025.nominal_gdp_mvl",
        )
        real_growth_2025 = _finite(
            raw["annual_accounts"]["2025"].get("real_growth_pct"),
            "baseline.annual_accounts.2025.real_growth_pct",
        )
        if not math.isclose(real_growth_2025, 3.1, abs_tol=1e-12):
            _fail(
                "baseline.annual_accounts.2025.real_growth_pct",
                "expected the 3.1 percent project benchmark",
            )
        annual_path = raw["annual_path"]["2026"]
        real_growth = _finite(
            annual_path.get("real_growth_pct"),
            "baseline.annual_path.2026.real_growth_pct",
        )
        deflator_growth = _finite(
            annual_path.get("deflator_growth_pct"),
            "baseline.annual_path.2026.deflator_growth_pct",
        )
        nominal_target = _positive(
            annual_path.get("nominal_gdp_mvl"),
            "baseline.annual_path.2026.nominal_gdp_mvl",
        )
        anchors = metadata.get("external_anchors")
        if not isinstance(anchors, Mapping):
            _fail(
                "baseline.metadata.external_anchors",
                "expected a dictionary",
            )
        anchor_real = _finite(
            anchors.get("real_gdp_growth_2026_pct"),
            "baseline.metadata.external_anchors.real_gdp_growth_2026_pct",
        )
        anchor_deflator = _finite(
            anchors.get("gdp_deflator_growth_2026_pct"),
            "baseline.metadata.external_anchors.gdp_deflator_growth_2026_pct",
        )
        if not math.isclose(real_growth, anchor_real, abs_tol=1e-12):
            _fail(
                "baseline.annual_path.2026.real_growth_pct",
                "does not match the external anchor",
            )
        if not math.isclose(deflator_growth, anchor_deflator, abs_tol=1e-12):
            _fail(
                "baseline.annual_path.2026.deflator_growth_pct",
                "does not match the external anchor",
            )
        expected_nominal = (
            base_nominal_gdp
            * (1.0 + real_growth / 100.0)
            * (1.0 + deflator_growth / 100.0)
        )
        if not math.isclose(
            nominal_target, expected_nominal, rel_tol=0.0, abs_tol=0.01
        ):
            _fail(
                "baseline.annual_path.2026.nominal_gdp_mvl",
                "does not match the real-growth and deflator path",
            )
        raw_expenditure = raw["expenditure_accounts"]["2025"]
        if not isinstance(raw_expenditure, Mapping):
            _fail(
                "baseline.expenditure_accounts.2025",
                "expected a dictionary",
            )
        if set(raw_expenditure) != EXPENDITURE_KEYS:
            _fail(
                "baseline.expenditure_accounts.2025",
                "unexpected expenditure keys",
            )
        expenditure_values = {
            key: _finite(
                value, f"baseline.expenditure_accounts.2025.{key}"
            )
            for key, value in raw_expenditure.items()
        }
        expenditure_total = (
            expenditure_values["household_consumption_mvl"]
            + expenditure_values["government_consumption_mvl"]
            + expenditure_values["gross_fixed_capital_formation_mvl"]
            + expenditure_values["changes_in_inventories_mvl"]
            + expenditure_values["exports_goods_services_mvl"]
            - expenditure_values["imports_goods_services_mvl"]
            + expenditure_values["statistical_discrepancy_mvl"]
        )
        if not math.isclose(
            expenditure_total,
            base_nominal_gdp,
            rel_tol=0.0,
            abs_tol=0.01,
        ):
            _fail(
                "baseline.expenditure_accounts.2025",
                "expenditure identity does not match nominal GDP",
            )
        raw_industries = raw["production_accounts"]["industries"]
        if not isinstance(raw_industries, Mapping) or not raw_industries:
            _fail(
                "baseline.production_accounts.industries",
                "expected a non-empty dictionary",
            )
        converted_industries = {}
        for key, value in raw_industries.items():
            item_path = f"baseline.production_accounts.industries.{key}"
            if not isinstance(value, Mapping):
                _fail(item_path, "expected a dictionary")
            group = value.get("group")
            if group not in GDP_GROUP_SHARES:
                _fail(f"{item_path}.group", "unexpected GDP group")
            converted_industries[key] = {
                "group": group,
                "share_pct": _positive(
                    value.get("share_pct"), f"{item_path}.share_pct"
                ),
                "nominal_mvl": _positive(
                    value.get("nominal_mvl"), f"{item_path}.nominal_mvl"
                ),
                "real_growth_2026_pct": _finite(
                    value.get("real_growth_2026_pct"),
                    f"{item_path}.real_growth_2026_pct",
                ),
            }
        share_total = sum(
            value["share_pct"] for value in converted_industries.values()
        )
        if not math.isclose(share_total, 100.0, rel_tol=0.0, abs_tol=1e-9):
            _fail(
                "baseline.production_accounts.industries",
                "shares must sum to 100",
            )
        group_shares = {
            group: sum(
                item["share_pct"]
                for item in converted_industries.values()
                if item["group"] == group
            )
            for group in GDP_GROUP_SHARES
        }
        for group, expected_share in GDP_GROUP_SHARES.items():
            if not math.isclose(
                group_shares[group], expected_share, abs_tol=1e-9
            ):
                _fail(
                    "baseline.production_accounts.industries",
                    f"{group} share must equal {expected_share}",
                )
        nominal_total = sum(
            value["nominal_mvl"] for value in converted_industries.values()
        )
        if not math.isclose(
            nominal_total,
            base_nominal_gdp,
            rel_tol=0.0,
            abs_tol=0.01,
        ):
            _fail(
                "baseline.production_accounts.industries",
                "nominal values do not match nominal GDP",
            )
        for key, value in raw_industries.items():
            weights_path = (
                "baseline.production_accounts.industries."
                f"{key}.quarter_weights"
            )
            weights = value.get("quarter_weights")
            if not isinstance(weights, list) or len(weights) != 4:
                _fail(weights_path, "expected four quarter weights")
            converted_weights = [
                _finite(item, f"{weights_path}[{index}]")
                for index, item in enumerate(weights)
            ]
            if any(item <= 0.0 for item in converted_weights):
                _fail(weights_path, "weights must be positive")
            if not math.isclose(
                sum(converted_weights), 1.0, rel_tol=0.0, abs_tol=1e-9
            ):
                _fail(weights_path, "weights must sum to 1")
            converted_industries[key]["quarter_weights"] = tuple(
                converted_weights
            )
        weighted_growth = sum(
            item["share_pct"] * item["real_growth_2026_pct"] / 100.0
            for item in converted_industries.values()
        )
        if not math.isclose(
            weighted_growth, real_growth, rel_tol=0.0, abs_tol=1e-12
        ):
            _fail(
                "baseline.production_accounts.industries",
                "weighted growth does not match the annual path",
            )
        industries = {
            key: IndustrySpec(
                group=value["group"],
                share_pct=value["share_pct"],
                nominal_mvl=value["nominal_mvl"],
                real_growth_2026_pct=value["real_growth_2026_pct"],
                quarter_weights=value["quarter_weights"],
            )
            for key, value in converted_industries.items()
        }
        tourism = _validated_tourism(
            raw.get("tourism_reconciliation"), base_nominal_gdp
        )
        release_lags = _validated_release_lags(raw.get("release_policy"))
        drivers = _validated_driver_parameters(
            raw.get("driver_parameters"), set(industries)
        )
        _validate_source_extract(
            path, metadata, real_growth, deflator_growth
        )
        return cls(
            version=BASELINE_VERSION,
            base_year=base_year,
            base_nominal_gdp_mvl=base_nominal_gdp,
            real_growth_2025_pct=real_growth_2025,
            real_growth_2026_pct=real_growth,
            deflator_growth_2026_pct=deflator_growth,
            nominal_target_2026_mvl=nominal_target,
            industries=industries,
            expenditure=expenditure_values,
            tourism=tourism,
            release_lags_days=release_lags,
            metadata=copy.deepcopy(dict(metadata)),
            driver_parameters=drivers,
        )


def _validated_tourism(raw, base_nominal_gdp: float) -> dict:
    path = "baseline.tourism_reconciliation"
    if not isinstance(raw, Mapping):
        _fail(path, "expected a dictionary")
    result = {
        "annual_arrivals_including_cruise": _positive(
            raw.get("annual_arrivals_including_cruise"),
            f"{path}.annual_arrivals_including_cruise",
        ),
        "average_stay_days": _positive(
            raw.get("average_stay_days"), f"{path}.average_stay_days"
        ),
        "spend_per_day_mvl": _positive(
            raw.get("spend_per_day_mvl"), f"{path}.spend_per_day_mvl"
        ),
        "visitor_spending_mvl": _positive(
            raw.get("visitor_spending_mvl"),
            f"{path}.visitor_spending_mvl",
        ),
        "direct_gva_mvl": _positive(
            raw.get("direct_gva_mvl"), f"{path}.direct_gva_mvl"
        ),
        "direct_gva_share_pct": _positive(
            raw.get("direct_gva_share_pct"),
            f"{path}.direct_gva_share_pct",
        ),
    }
    expected_spending = (
        result["annual_arrivals_including_cruise"]
        * result["average_stay_days"]
        * result["spend_per_day_mvl"]
    )
    if not math.isclose(
        result["visitor_spending_mvl"],
        expected_spending,
        rel_tol=0.0,
        abs_tol=0.01,
    ):
        _fail(
            f"{path}.visitor_spending_mvl",
            "does not match arrivals, stay and daily spending",
        )
    expected_gva = (
        base_nominal_gdp * result["direct_gva_share_pct"] / 100.0
    )
    if not math.isclose(
        result["direct_gva_mvl"], expected_gva, rel_tol=0.0, abs_tol=0.01
    ):
        _fail(
            f"{path}.direct_gva_mvl",
            "does not equal the stated GDP share",
        )
    if not math.isclose(
        result["direct_gva_share_pct"], 10.0, abs_tol=1e-12
    ):
        _fail(f"{path}.direct_gva_share_pct", "expected 10 percent")
    return result


def _validated_release_lags(raw) -> dict[str, int]:
    path = "baseline.release_policy"
    if not isinstance(raw, Mapping) or not isinstance(
        raw.get("lags_days"), Mapping
    ):
        _fail(path, "expected lags_days dictionary")
    lags = raw["lags_days"]
    if set(lags) != set(VINTAGE_ORDER):
        _fail(f"{path}.lags_days", "unexpected vintage keys")
    result = {}
    for vintage in VINTAGE_ORDER:
        value = lags[vintage]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            _fail(
                f"{path}.lags_days.{vintage}",
                "expected a positive integer",
            )
        result[vintage] = value
    if list(result.values()) != sorted(set(result.values())):
        _fail(f"{path}.lags_days", "release lags must be increasing")
    return result


def _validated_driver_parameters(raw, industry_keys: set[str]) -> dict:
    path = "baseline.driver_parameters"
    if not isinstance(raw, Mapping):
        _fail(path, "expected a dictionary")
    if raw.get("version") != DRIVER_VERSION:
        _fail(f"{path}.version", f"expected {DRIVER_VERSION}")
    references = raw.get("reference_values")
    if not isinstance(references, Mapping):
        _fail(f"{path}.reference_values", "expected a dictionary")
    required_references = {
        "sugar_usd_lb", "gold_usd_oz", "brent_usd_barrel",
        "mvl_per_usd", "cpi_yoy_pct", "population",
    }
    if set(references) != required_references:
        _fail(f"{path}.reference_values", "unexpected reference keys")
    for key, value in references.items():
        validator = _finite if key == "cpi_yoy_pct" else _positive
        validator(value, f"{path}.reference_values.{key}")

    commodity = raw.get("commodity_elasticities")
    if not isinstance(commodity, Mapping):
        _fail(f"{path}.commodity_elasticities", "expected a dictionary")
    for commodity_key, mapping in commodity.items():
        if commodity_key not in references or not isinstance(mapping, Mapping):
            _fail(
                f"{path}.commodity_elasticities.{commodity_key}",
                "expected a referenced commodity mapping",
            )
        _validate_sector_mapping(
            mapping,
            industry_keys,
            f"{path}.commodity_elasticities.{commodity_key}",
        )
    for field in (
        "exchange_elasticities",
        "population_elasticities",
        "cpi_elasticities_per_pct_point",
        "rainfall_elasticities_per_mm",
    ):
        mapping = raw.get(field)
        if not isinstance(mapping, Mapping):
            _fail(f"{path}.{field}", "expected a dictionary")
        _validate_sector_mapping(mapping, industry_keys, f"{path}.{field}")

    bounds = raw.get("ordinary_factor_bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        _fail(f"{path}.ordinary_factor_bounds", "expected two bounds")
    lower = _positive(bounds[0], f"{path}.ordinary_factor_bounds[0]")
    upper = _positive(bounds[1], f"{path}.ordinary_factor_bounds[1]")
    if lower >= upper:
        _fail(
            f"{path}.ordinary_factor_bounds",
            "lower bound must be below upper bound",
        )
    cyclone = raw.get("cyclone_high_factors")
    if not isinstance(cyclone, Mapping):
        _fail(f"{path}.cyclone_high_factors", "expected a dictionary")
    _validate_sector_mapping(
        cyclone, industry_keys, f"{path}.cyclone_high_factors"
    )
    for sector, factor in cyclone.items():
        if not 0.0 < float(factor) <= 1.0:
            _fail(
                f"{path}.cyclone_high_factors.{sector}",
                "expected a factor from 0 through 1",
            )
    return copy.deepcopy(dict(raw))


def _validate_sector_mapping(raw, industry_keys: set[str], path: str) -> None:
    for sector, value in raw.items():
        if sector not in industry_keys:
            _fail(f"{path}.{sector}", "unknown industry")
        _finite(value, f"{path}.{sector}")


def _validate_source_extract(
    baseline_path: Path,
    metadata: Mapping,
    real_growth: float,
    deflator_growth: float,
) -> None:
    path = "baseline.metadata.source_extract"
    reference = metadata.get("source_extract")
    if not isinstance(reference, str) or not reference:
        _fail(path, "expected a relative JSON path")
    source_path = baseline_path.parent / reference
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GdpDataError(f"{path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        _fail(path, "expected a dictionary")
    source_meta = raw.get("_meta")
    if not isinstance(source_meta, Mapping):
        _fail(f"{path}._meta", "expected a dictionary")
    accessed_on = source_meta.get("accessed_on")
    if not isinstance(accessed_on, str) or not accessed_on:
        _fail(f"{path}._meta.accessed_on", "expected an access date")
    if accessed_on != metadata.get("accessed_on"):
        _fail(f"{path}._meta.accessed_on", "does not match baseline metadata")
    sources = raw.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        _fail(f"{path}.sources", "expected a non-empty dictionary")
    for key, source in sources.items():
        source_path_label = f"{path}.sources.{key}"
        if not isinstance(source, Mapping):
            _fail(source_path_label, "expected a dictionary")
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            _fail(
                f"{source_path_label}.url",
                "expected an official HTTPS URL",
            )
        for field in ("publisher", "title", "published_on", "use"):
            if not isinstance(source.get(field), str) or not source[field]:
                _fail(f"{source_path_label}.{field}", "expected text")
        if not isinstance(source.get("extracted"), Mapping) or not source[
            "extracted"
        ]:
            _fail(f"{source_path_label}.extracted", "expected extracted values")
    imf = sources.get("imf_fiji_2026_article_iv", {}).get("extracted", {})
    if not math.isclose(
        _finite(
            imf.get("real_gdp_growth_pct"),
            f"{path}.sources.imf_fiji_2026_article_iv.extracted."
            "real_gdp_growth_pct",
        ),
        real_growth,
        abs_tol=1e-12,
    ):
        _fail(path, "IMF real-growth anchor does not match the baseline")
    if not math.isclose(
        _finite(
            imf.get("gdp_deflator_growth_pct"),
            f"{path}.sources.imf_fiji_2026_article_iv.extracted."
            "gdp_deflator_growth_pct",
        ),
        deflator_growth,
        abs_tol=1e-12,
    ):
        _fail(path, "IMF deflator anchor does not match the baseline")


def _expenditure_total(values: Mapping) -> float:
    return (
        values["household_consumption_mvl"]
        + values["government_consumption_mvl"]
        + values["gross_fixed_capital_formation_mvl"]
        + values["changes_in_inventories_mvl"]
        + values["exports_goods_services_mvl"]
        - values["imports_goods_services_mvl"]
        + values["statistical_discrepancy_mvl"]
    )


def _period_tuple(period: str, path: str) -> tuple[int, int]:
    try:
        year_text, quarter_text = period.split("-Q")
        result = int(year_text), int(quarter_text)
    except (AttributeError, TypeError, ValueError):
        _fail(path, "expected YYYY-Qn")
    if result[0] < 2025 or result[1] not in range(1, 5):
        _fail(path, "expected YYYY-Qn")
    if period != f"{result[0]}-Q{result[1]}":
        _fail(path, "expected YYYY-Qn")
    return result


def _next_period(period: tuple[int, int]) -> tuple[int, int]:
    year, quarter = period
    return (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def initialize_gdp_state(current_date: date, baseline: GdpBaseline) -> dict:
    """Create a deterministic GDP ledger aligned to an existing state date."""
    if current_date < date(2025, 1, 1):
        _fail("state.model_state.gdp", "cannot initialize before 2025-01-01")
    current_year, current_quarter_number = _quarter_for_date(current_date)
    history = []
    year, quarter = 2025, 1
    while (year, quarter) < (current_year, current_quarter_number):
        account = _planned_quarter_account(year, quarter, baseline)
        account["vintages"] = _published_vintages(
            account, current_date, baseline, history
        )
        history.append(account)
        if quarter == 4:
            year, quarter = year + 1, 1
        else:
            quarter += 1
    history = history[-MAX_CLOSED_QUARTERS:]

    planned_current = _planned_quarter_account(
        current_year, current_quarter_number, baseline
    )
    quarter_start = date.fromisoformat(planned_current["start_date"])
    days_elapsed = (current_date - quarter_start).days + 1
    fraction = days_elapsed / planned_current["days_in_quarter"]
    current_accumulator = {
        "period": planned_current["period"],
        "start_date": planned_current["start_date"],
        "end_date": planned_current["end_date"],
        "days_elapsed": days_elapsed,
        "real_gva_mvl_by_industry": {
            key: value * fraction
            for key, value in planned_current["production"][
                "real_gva_mvl_by_industry"
            ].items()
        },
        "nominal_gva_mvl_by_industry": {
            key: value * fraction
            for key, value in planned_current["production"][
                "nominal_gva_mvl_by_industry"
            ].items()
        },
    }
    published = [
        vintage
        for account in history
        for vintage in account["vintages"]
    ]
    latest_release = max(
        published,
        key=lambda item: (item["period"], item["release_date"]),
        default=None,
    )
    return {
        "version": 1,
        "baseline_version": baseline.version,
        "last_processed_date": current_date.isoformat(),
        "quarterly_history": history,
        "current_quarter": current_accumulator,
        "latest_release": latest_release,
    }


def validate_gdp_state(
    state: dict,
    current_date: date,
    baseline: GdpBaseline,
) -> None:
    """Validate the persistent GDP ledger against its public date."""
    if not isinstance(state, dict):
        _fail("state.model_state.gdp", "expected a dictionary")
    if state.get("version") != 1:
        _fail("state.model_state.gdp.version", "expected 1")
    if state.get("baseline_version") != baseline.version:
        _fail(
            "state.model_state.gdp.baseline_version",
            f"expected {baseline.version}",
        )
    if state.get("last_processed_date") != current_date.isoformat():
        _fail(
            "state.model_state.gdp.last_processed_date",
            "does not match state.date",
        )
    history = state.get("quarterly_history")
    if not isinstance(history, list):
        _fail(
            "state.model_state.gdp.quarterly_history",
            "expected a list",
        )
    if len(history) > MAX_CLOSED_QUARTERS:
        _fail(
            "state.model_state.gdp.quarterly_history",
            f"expected no more than {MAX_CLOSED_QUARTERS} quarters",
        )
    current = state.get("current_quarter")
    if not isinstance(current, dict):
        _fail(
            "state.model_state.gdp.current_quarter",
            "expected a dictionary",
        )
    seen_periods = set()
    previous_period = None
    all_vintages = []
    for index, account in enumerate(history):
        path = f"state.model_state.gdp.quarterly_history[{index}]"
        if not isinstance(account, dict):
            _fail(path, "expected a dictionary")
        period = account.get("period")
        if not isinstance(period, str) or period in seen_periods:
            _fail(f"{path}.period", "expected a unique quarter")
        period_tuple = _period_tuple(period, f"{path}.period")
        if previous_period is not None and period_tuple != _next_period(
            previous_period
        ):
            _fail(
                f"{path}.period",
                "quarters must be ordered and consecutive",
            )
        previous_period = period_tuple
        seen_periods.add(period)
        expected_start, expected_end = _quarter_dates(*period_tuple)
        if account.get("start_date") != expected_start.isoformat():
            _fail(f"{path}.start_date", "does not match the quarter")
        if account.get("end_date") != expected_end.isoformat():
            _fail(f"{path}.end_date", "does not match the quarter")
        expected_days = (expected_end - expected_start).days + 1
        days = account.get("days_in_quarter")
        if isinstance(days, bool) or days != expected_days:
            _fail(f"{path}.days_in_quarter", f"expected {expected_days}")
        production = account.get("production")
        if not isinstance(production, dict):
            _fail(f"{path}.production", "expected a dictionary")
        real_by_industry = production.get("real_gva_mvl_by_industry")
        nominal_by_industry = production.get("nominal_gva_mvl_by_industry")
        if not isinstance(real_by_industry, dict):
            _fail(
                f"{path}.production.real_gva_mvl_by_industry",
                "expected a dictionary",
            )
        if not isinstance(nominal_by_industry, dict):
            _fail(
                f"{path}.production.nominal_gva_mvl_by_industry",
                "expected a dictionary",
            )
        if set(real_by_industry) != set(baseline.industries):
            _fail(
                f"{path}.production.real_gva_mvl_by_industry",
                "industry keys do not match the baseline",
            )
        if set(nominal_by_industry) != set(baseline.industries):
            _fail(
                f"{path}.production.nominal_gva_mvl_by_industry",
                "industry keys do not match the baseline",
            )
        real_total = sum(
            _finite(value, f"{path}.production.real_gva_mvl_by_industry.{key}")
            for key, value in real_by_industry.items()
        )
        nominal_total = sum(
            _finite(value, f"{path}.production.nominal_gva_mvl_by_industry.{key}")
            for key, value in nominal_by_industry.items()
        )
        if real_total <= 0.0 or nominal_total <= 0.0:
            _fail(f"{path}.production", "GDP totals must be positive")
        if not math.isclose(
            real_total,
            _finite(
                production.get("real_gdp_mvl"),
                f"{path}.production.real_gdp_mvl",
            ),
            rel_tol=0.0,
            abs_tol=0.01,
        ):
            _fail(
                f"{path}.production.real_gdp_mvl",
                "does not match the industry sum",
            )
        if not math.isclose(
            nominal_total,
            _finite(
                production.get("nominal_gdp_mvl"),
                f"{path}.production.nominal_gdp_mvl",
            ),
            rel_tol=0.0,
            abs_tol=0.01,
        ):
            _fail(
                f"{path}.production.nominal_gdp_mvl",
                "does not match the industry sum",
            )
        deflator = _positive(
            production.get("deflator_index"),
            f"{path}.production.deflator_index",
        )
        if not math.isclose(
            deflator,
            100.0 * nominal_total / real_total,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            _fail(
                f"{path}.production.deflator_index",
                "does not match nominal and real GDP",
            )
        growth = production.get("real_growth_yoy_pct")
        previous_production = _previous_year_production(
            period_tuple[0], period_tuple[1], history, baseline
        )
        expected_growth = (
            None
            if previous_production is None
            else (
                real_total / previous_production["real_gdp_mvl"] - 1.0
            )
            * 100.0
        )
        if growth is None and expected_growth is not None:
            _fail(
                f"{path}.production.real_growth_yoy_pct",
                "missing year-on-year growth",
            )
        if growth is not None:
            converted_growth = _finite(
                growth, f"{path}.production.real_growth_yoy_pct"
            )
            if expected_growth is None or not math.isclose(
                converted_growth,
                expected_growth,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                _fail(
                    f"{path}.production.real_growth_yoy_pct",
                    "does not match the previous closed quarter",
                )

        expenditure = account.get("expenditure")
        if not isinstance(expenditure, dict) or set(expenditure) != EXPENDITURE_KEYS:
            _fail(f"{path}.expenditure", "unexpected expenditure keys")
        expenditure_values = {
            key: _finite(value, f"{path}.expenditure.{key}")
            for key, value in expenditure.items()
        }
        if not math.isclose(
            _expenditure_total(expenditure_values),
            nominal_total,
            rel_tol=0.0,
            abs_tol=0.01,
        ):
            _fail(
                f"{path}.expenditure",
                "expenditure identity does not match nominal GDP",
            )

        vintages = account.get("vintages")
        if not isinstance(vintages, list):
            _fail(f"{path}.vintages", "expected a list")
        expected_vintages = [
            vintage
            for vintage in VINTAGE_ORDER
            if expected_end
            + timedelta(days=baseline.release_lags_days[vintage])
            <= current_date
        ]
        actual_vintages = [
            item.get("vintage")
            for item in vintages
            if isinstance(item, dict)
        ]
        if actual_vintages != expected_vintages:
            _fail(
                f"{path}.vintages",
                "does not match vintages due under the release policy",
            )
        for vintage_index, vintage in enumerate(vintages):
            vintage_path = f"{path}.vintages[{vintage_index}]"
            if not isinstance(vintage, dict):
                _fail(vintage_path, "expected a dictionary")
            vintage_name = vintage.get("vintage")
            expected_release = expected_end + timedelta(
                days=baseline.release_lags_days[vintage_name]
            )
            if vintage.get("release_date") != expected_release.isoformat():
                _fail(
                    f"{vintage_path}.release_date",
                    "does not match the release policy",
                )
            if vintage.get("period") != period:
                _fail(f"{vintage_path}.period", "does not match the quarter")
            if vintage.get("status") != "official_release" or vintage.get(
                "is_model_nowcast"
            ) is not False:
                _fail(vintage_path, "expected an official release")
            for field, expected_value in (
                ("real_gdp_mvl", real_total),
                ("nominal_gdp_mvl", nominal_total),
                ("deflator_index", deflator),
                ("real_growth_yoy_pct", growth),
            ):
                if vintage.get(field) != expected_value:
                    _fail(
                        f"{vintage_path}.{field}",
                        "does not match the closed quarter",
                    )
            if vintage.get("expenditure") != expenditure:
                _fail(
                    f"{vintage_path}.expenditure",
                    "does not match the closed quarter",
                )
            shares = vintage.get("industry_shares_pct")
            if not isinstance(shares, dict) or set(shares) != set(
                baseline.industries
            ):
                _fail(
                    f"{vintage_path}.industry_shares_pct",
                    "industry keys do not match the baseline",
                )
            share_total = sum(
                _finite(
                    value,
                    f"{vintage_path}.industry_shares_pct.{key}",
                )
                for key, value in shares.items()
            )
            if not math.isclose(share_total, 100.0, abs_tol=1e-9):
                _fail(
                    f"{vintage_path}.industry_shares_pct",
                    "shares must sum to 100",
                )
            for key, value in shares.items():
                expected_share = nominal_by_industry[key] / nominal_total * 100.0
                if not math.isclose(
                    float(value),
                    expected_share,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    _fail(
                        f"{vintage_path}.industry_shares_pct.{key}",
                        "does not match the closed quarter",
                    )
            contributions = vintage.get("industry_contributions_pct")
            expected_contributions = {}
            if previous_production is not None:
                previous_total = previous_production["real_gdp_mvl"]
                expected_contributions = {
                    key: (
                        real_by_industry[key]
                        - previous_production[
                            "real_gva_mvl_by_industry"
                        ][key]
                    )
                    / previous_total
                    * 100.0
                    for key in baseline.industries
                }
            if contributions != expected_contributions:
                _fail(
                    f"{vintage_path}.industry_contributions_pct",
                    "does not match the previous closed quarter",
                )
            all_vintages.append(vintage)

    current_path = "state.model_state.gdp.current_quarter"
    expected_year, expected_quarter = _quarter_for_date(current_date)
    expected_period = f"{expected_year}-Q{expected_quarter}"
    if current.get("period") != expected_period:
        _fail(f"{current_path}.period", "does not match state date")
    current_start, current_end = _quarter_dates(
        expected_year, expected_quarter
    )
    if current.get("start_date") != current_start.isoformat():
        _fail(f"{current_path}.start_date", "does not match state date")
    if current.get("end_date") != current_end.isoformat():
        _fail(f"{current_path}.end_date", "does not match state date")
    expected_elapsed = (current_date - current_start).days + 1
    if current.get("days_elapsed") != expected_elapsed:
        _fail(
            f"{current_path}.days_elapsed",
            f"expected {expected_elapsed}",
        )
    for field in (
        "real_gva_mvl_by_industry",
        "nominal_gva_mvl_by_industry",
    ):
        values = current.get(field)
        if not isinstance(values, dict) or set(values) != set(
            baseline.industries
        ):
            _fail(f"{current_path}.{field}", "industry keys do not match")
        for key, value in values.items():
            if _finite(value, f"{current_path}.{field}.{key}") < 0.0:
                _fail(
                    f"{current_path}.{field}.{key}",
                    "expected a non-negative value",
                )
    if history and _next_period(previous_period) != (
        expected_year, expected_quarter
    ):
        _fail(
            f"{current_path}.period",
            "does not immediately follow the closed history",
        )
    expected_latest = max(
        all_vintages,
        key=lambda item: (item["period"], item["release_date"]),
        default=None,
    )
    if state.get("latest_release") != expected_latest:
        _fail(
            "state.model_state.gdp.latest_release",
            "does not match the latest published vintage",
        )


def gdp_step(
    current_date: date,
    previous_state: dict,
    weather: dict,
    cpi: dict,
    commodities: dict,
    exchange: dict,
    population: int,
    baseline: GdpBaseline,
) -> tuple[dict, dict, list[dict]]:
    """Advance the latent GDP ledger by one day."""
    previous_date = date.fromisoformat(previous_state["last_processed_date"])
    if current_date != previous_date + timedelta(days=1):
        _fail(
            "state.model_state.gdp.last_processed_date",
            "must be exactly one day before the GDP step date",
        )
    state = copy.deepcopy(previous_state)
    year, quarter = _quarter_for_date(current_date)
    period = f"{year}-Q{quarter}"
    accumulator = state["current_quarter"]
    if accumulator["period"] != period:
        closed = _account_from_accumulator(
            accumulator, baseline, state["quarterly_history"]
        )
        closed["vintages"] = []
        state["quarterly_history"].append(closed)
        state["quarterly_history"] = state["quarterly_history"][
            -MAX_CLOSED_QUARTERS:
        ]
        planned = _planned_quarter_account(year, quarter, baseline)
        accumulator = {
            "period": period,
            "start_date": planned["start_date"],
            "end_date": planned["end_date"],
            "days_elapsed": 0,
            "real_gva_mvl_by_industry": {
                key: 0.0 for key in baseline.industries
            },
            "nominal_gva_mvl_by_industry": {
                key: 0.0 for key in baseline.industries
            },
        }
        state["current_quarter"] = accumulator

    planned = _planned_quarter_account(year, quarter, baseline)
    driver_factors = _daily_driver_factors(
        weather, cpi, commodities, exchange, population, baseline
    )
    for key in baseline.industries:
        accumulator["real_gva_mvl_by_industry"][key] += (
            planned["production"]["real_gva_mvl_by_industry"][key]
            / planned["days_in_quarter"]
            * driver_factors.get(key, 1.0)
        )
        accumulator["nominal_gva_mvl_by_industry"][key] += (
            planned["production"]["nominal_gva_mvl_by_industry"][key]
            / planned["days_in_quarter"]
            * driver_factors.get(key, 1.0)
        )
    accumulator["days_elapsed"] += 1
    state["last_processed_date"] = current_date.isoformat()

    events = _release_due_vintages(state, current_date, baseline)
    public = _public_gdp_snapshot(
        current_date,
        state,
        population,
        exchange,
        baseline,
    )
    return public, state, events


def gdp_snapshot(
    current_date: date,
    state: dict,
    population: int,
    exchange: dict,
    baseline: GdpBaseline,
) -> dict:
    """Build the public GDP object without advancing its ledger."""
    return _public_gdp_snapshot(
        current_date, state, population, exchange, baseline
    )


def gdp_headline_growth(public: dict, baseline: GdpBaseline) -> float:
    """Return a numeric headline even while only benchmark vintages exist."""
    latest = public.get("latest_release")
    growth = (
        None if latest is None else latest.get("real_growth_yoy_pct")
    )
    return (
        baseline.real_growth_2026_pct
        if growth is None
        else _finite(growth, "gdp.latest_release.real_growth_yoy_pct")
    )


def _daily_driver_factors(
    weather: dict,
    cpi: dict,
    commodities: dict,
    exchange: dict,
    population: int,
    baseline: GdpBaseline,
) -> dict[str, float]:
    parameters = baseline.driver_parameters
    references = parameters["reference_values"]
    factors = {key: 1.0 for key in baseline.industries}
    for commodity, elasticities in parameters[
        "commodity_elasticities"
    ].items():
        value = _positive(
            commodities.get(commodity), f"commodities.{commodity}"
        )
        reference = _positive(
            references[commodity],
            f"baseline.driver_parameters.reference_values.{commodity}",
        )
        log_move = math.log(value / reference)
        for sector, elasticity in elasticities.items():
            factors[sector] *= math.exp(elasticity * log_move)
    exchange_rate = _positive(
        exchange.get("mvl_per_usd"), "exchange.mvl_per_usd"
    )
    exchange_move = math.log(
        exchange_rate / references["mvl_per_usd"]
    )
    for sector, elasticity in parameters["exchange_elasticities"].items():
        factors[sector] *= math.exp(elasticity * exchange_move)
    population_value = _positive(population, "population")
    population_move = math.log(
        population_value / references["population"]
    )
    for sector, elasticity in parameters[
        "population_elasticities"
    ].items():
        factors[sector] *= math.exp(elasticity * population_move)
    cpi_yoy = _finite(cpi.get("yoy_pct"), "cpi.yoy_pct")
    cpi_gap = cpi_yoy - references["cpi_yoy_pct"]
    for sector, elasticity in parameters[
        "cpi_elasticities_per_pct_point"
    ].items():
        factors[sector] *= math.exp(elasticity * cpi_gap)
    rainfall = _finite(weather.get("rainfall_mm"), "weather.rainfall_mm")
    if rainfall < 0.0:
        _fail("weather.rainfall_mm", "expected a non-negative number")
    for sector, elasticity in parameters[
        "rainfall_elasticities_per_mm"
    ].items():
        factors[sector] *= math.exp(elasticity * rainfall)
    lower, upper = parameters["ordinary_factor_bounds"]
    factors = {
        key: min(upper, max(lower, factor))
        for key, factor in factors.items()
    }
    cyclone_risk = weather.get("cyclone_risk", "none")
    if cyclone_risk != "high":
        return factors
    cyclone_factors = parameters["cyclone_high_factors"]
    for key, factor in cyclone_factors.items():
        factors[key] = factors.get(key, 1.0) * factor
    return factors


def _previous_year_production(
    year: int,
    quarter: int,
    history: list[dict],
    baseline: GdpBaseline,
) -> dict | None:
    if year <= baseline.base_year:
        return None
    target = f"{year - 1}-Q{quarter}"
    for account in reversed(history):
        if account.get("period") == target:
            return account["production"]
    return _planned_quarter_account(
        year - 1, quarter, baseline
    )["production"]


def _account_from_accumulator(
    accumulator: dict,
    baseline: GdpBaseline,
    history: list[dict] | None = None,
) -> dict:
    real_by_industry = copy.deepcopy(
        accumulator["real_gva_mvl_by_industry"]
    )
    nominal_by_industry = copy.deepcopy(
        accumulator["nominal_gva_mvl_by_industry"]
    )
    real_total = sum(real_by_industry.values())
    nominal_total = sum(nominal_by_industry.values())
    year, quarter = map(
        int,
        accumulator["period"].replace("-Q", "-").split("-"),
    )
    previous_production = _previous_year_production(
        year, quarter, history or [], baseline
    )
    previous_real = (
        None
        if previous_production is None
        else previous_production["real_gdp_mvl"]
    )
    expenditure_scale = nominal_total / baseline.base_nominal_gdp_mvl
    return {
        "period": accumulator["period"],
        "start_date": accumulator["start_date"],
        "end_date": accumulator["end_date"],
        "days_in_quarter": accumulator["days_elapsed"],
        "production": {
            "real_gva_mvl_by_industry": real_by_industry,
            "nominal_gva_mvl_by_industry": nominal_by_industry,
            "real_gdp_mvl": real_total,
            "nominal_gdp_mvl": nominal_total,
            "real_growth_yoy_pct": (
                None
                if previous_real is None
                else (real_total / previous_real - 1.0) * 100.0
            ),
            "deflator_index": 100.0 * nominal_total / real_total,
        },
        "expenditure": {
            key: value * expenditure_scale
            for key, value in baseline.expenditure.items()
        },
    }


def _release_due_vintages(
    state: dict,
    current_date: date,
    baseline: GdpBaseline,
) -> list[dict]:
    events = []
    for account in state["quarterly_history"]:
        existing = {item["vintage"] for item in account["vintages"]}
        due = _published_vintages(
            account,
            current_date,
            baseline,
            state["quarterly_history"],
        )
        for vintage in due:
            if vintage["vintage"] in existing:
                continue
            account["vintages"].append(vintage)
            growth = vintage["real_growth_yoy_pct"]
            release_detail = (
                f"名义GDP {vintage['nominal_gdp_mvl'] / 1_000_000:.1f} 百万MVL"
                if growth is None
                else f"实际同比 {growth:.1f}%"
            )
            events.append({
                "type": "gdp_release",
                "severity": "info",
                "text": (
                    f"国家统计局发布 {account['period']} GDP "
                    f"{vintage['vintage']} 数据：{release_detail}"
                ),
            })
    published = [
        vintage
        for account in state["quarterly_history"]
        for vintage in account["vintages"]
    ]
    state["latest_release"] = max(
        published,
        key=lambda item: (item["period"], item["release_date"]),
        default=None,
    )
    return events


def _public_gdp_snapshot(
    current_date: date,
    state: dict,
    population: int,
    exchange: dict,
    baseline: GdpBaseline,
) -> dict:
    accumulator = state["current_quarter"]
    start = date.fromisoformat(accumulator["start_date"])
    end = date.fromisoformat(accumulator["end_date"])
    quarter_days = (end - start).days + 1
    completion = accumulator["days_elapsed"] / quarter_days
    real_forecast_by_industry = {
        key: value / completion
        for key, value in accumulator["real_gva_mvl_by_industry"].items()
    }
    nominal_forecast_by_industry = {
        key: value / completion
        for key, value in accumulator["nominal_gva_mvl_by_industry"].items()
    }
    quarter_real = sum(real_forecast_by_industry.values())
    quarter_nominal = sum(nominal_forecast_by_industry.values())
    current_year = current_date.year
    _, current_quarter_number = _quarter_for_date(current_date)
    previous_quarter = _previous_year_production(
        current_year,
        current_quarter_number,
        state["quarterly_history"],
        baseline,
    )
    previous_quarter_real = (
        None
        if previous_quarter is None
        else previous_quarter["real_gdp_mvl"]
    )
    quarter_real_growth = (
        None
        if previous_quarter_real is None
        else (quarter_real / previous_quarter_real - 1.0) * 100.0
    )
    annual_real = 0.0
    annual_nominal = 0.0
    for account in state["quarterly_history"]:
        if account["period"].startswith(f"{current_year}-"):
            annual_real += account["production"]["real_gdp_mvl"]
            annual_nominal += account["production"]["nominal_gdp_mvl"]
    annual_real += quarter_real
    annual_nominal += quarter_nominal
    for future_quarter in range(current_quarter_number + 1, 5):
        future = _planned_quarter_account(
            current_year, future_quarter, baseline
        )["production"]
        annual_real += future["real_gdp_mvl"]
        annual_nominal += future["nominal_gdp_mvl"]
    mvl_per_usd = _finite(
        exchange.get("mvl_per_usd"), "exchange.mvl_per_usd"
    )
    if population <= 0:
        _fail("population", "expected a positive integer")
    next_release = _next_release_date(state, current_date, baseline)
    previous_real, previous_nominal = _year_totals(
        current_year - 1, state, baseline
    )
    annual_real_growth = (annual_real / previous_real - 1.0) * 100.0
    current_deflator = annual_nominal / annual_real
    previous_deflator = previous_nominal / previous_real
    annual_deflator_growth = (
        current_deflator / previous_deflator - 1.0
    ) * 100.0
    return {
        "as_of_date": current_date.isoformat(),
        "latest_release": copy.deepcopy(state["latest_release"]),
        "current_quarter_nowcast": {
            "period": accumulator["period"],
            "through_date": current_date.isoformat(),
            "completion_pct": completion * 100.0,
            "real_gdp_mvl": quarter_real,
            "nominal_gdp_mvl": quarter_nominal,
            "real_growth_yoy_pct": quarter_real_growth,
            "real_gva_mvl_by_industry": real_forecast_by_industry,
            "nominal_gva_mvl_by_industry": nominal_forecast_by_industry,
            "status": "model_nowcast",
        },
        "annual_nowcast": {
            "year": current_year,
            "real_gdp_mvl": annual_real,
            "nominal_gdp_mvl": annual_nominal,
            "real_growth_pct": annual_real_growth,
            "deflator_growth_pct": annual_deflator_growth,
            "real_growth_risk_pct": {
                "low": annual_real_growth - 1.0,
                "central": annual_real_growth,
                "high": annual_real_growth + 1.0,
            },
            "status": "model_nowcast",
        },
        "population": population,
        "exchange_rate_mvl_per_usd": mvl_per_usd,
        "gdp_per_capita_mvl": annual_nominal / population,
        "gdp_per_capita_usd": annual_nominal / population / mvl_per_usd,
        "next_release_date": next_release,
    }


def _year_totals(
    year: int,
    state: dict,
    baseline: GdpBaseline,
) -> tuple[float, float]:
    accounts = [
        account
        for account in state["quarterly_history"]
        if account["period"].startswith(f"{year}-")
    ]
    if len(accounts) != 4:
        accounts = [
            _planned_quarter_account(year, quarter, baseline)
            for quarter in range(1, 5)
        ]
    real = sum(account["production"]["real_gdp_mvl"] for account in accounts)
    nominal = sum(
        account["production"]["nominal_gdp_mvl"] for account in accounts
    )
    return real, nominal


def _next_release_date(
    state: dict,
    current_date: date,
    baseline: GdpBaseline,
) -> str | None:
    candidates = []
    for account in state["quarterly_history"]:
        existing = {item["vintage"] for item in account["vintages"]}
        end = date.fromisoformat(account["end_date"])
        for vintage, lag in baseline.release_lags_days.items():
            release = end + timedelta(days=lag)
            if vintage not in existing and release > current_date:
                candidates.append(release)
    current_end = date.fromisoformat(state["current_quarter"]["end_date"])
    candidates.append(
        current_end
        + timedelta(days=baseline.release_lags_days["provisional"])
    )
    return min(candidates).isoformat() if candidates else None


def _quarter_for_date(value: date) -> tuple[int, int]:
    return value.year, (value.month - 1) // 3 + 1


def _quarter_dates(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return (
        date(year, start_month, 1),
        date(year, end_month, monthrange(year, end_month)[1]),
    )


def _planned_quarter_account(
    year: int,
    quarter: int,
    baseline: GdpBaseline,
) -> dict:
    start, end = _quarter_dates(year, quarter)
    real_by_industry = {}
    nominal_by_industry = {}
    for key, industry in baseline.industries.items():
        if year <= baseline.base_year:
            real_growth_factor = 1.0
            deflator_factor = 1.0
        else:
            years_after_base = year - baseline.base_year
            real_growth_factor = (
                1.0 + industry.real_growth_2026_pct / 100.0
            ) ** years_after_base
            deflator_factor = (
                1.0 + baseline.deflator_growth_2026_pct / 100.0
            ) ** years_after_base
        real_value = (
            industry.nominal_mvl
            * industry.quarter_weights[quarter - 1]
            * real_growth_factor
        )
        real_by_industry[key] = real_value
        nominal_by_industry[key] = real_value * deflator_factor
    real_total = sum(real_by_industry.values())
    nominal_total = sum(nominal_by_industry.values())
    expenditure_scale = nominal_total / baseline.base_nominal_gdp_mvl
    expenditure = {
        key: value * expenditure_scale
        for key, value in baseline.expenditure.items()
    }
    previous_year = None
    if year > baseline.base_year:
        previous_year = _planned_quarter_account(
            year - 1, quarter, baseline
        )["production"]["real_gdp_mvl"]
    real_growth_yoy_pct = (
        None
        if previous_year is None
        else (real_total / previous_year - 1.0) * 100.0
    )
    return {
        "period": f"{year}-Q{quarter}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days_in_quarter": (end - start).days + 1,
        "production": {
            "real_gva_mvl_by_industry": real_by_industry,
            "nominal_gva_mvl_by_industry": nominal_by_industry,
            "real_gdp_mvl": real_total,
            "nominal_gdp_mvl": nominal_total,
            "real_growth_yoy_pct": real_growth_yoy_pct,
            "deflator_index": 100.0 * nominal_total / real_total,
        },
        "expenditure": expenditure,
    }


def _published_vintages(
    account: dict,
    as_of_date: date,
    baseline: GdpBaseline,
    history: list[dict] | None = None,
) -> list[dict]:
    end = date.fromisoformat(account["end_date"])
    year, quarter = map(
        int,
        account["period"].replace("-Q", "-").split("-"),
    )
    contributions = {}
    previous = _previous_year_production(
        year, quarter, history or [], baseline
    )
    if previous is not None:
        previous_total = previous["real_gdp_mvl"]
        contributions = {
            key: (
                account["production"]["real_gva_mvl_by_industry"][key]
                - previous["real_gva_mvl_by_industry"][key]
            )
            / previous_total
            * 100.0
            for key in baseline.industries
        }
    vintages = []
    for vintage in ("provisional", "revised", "final"):
        release_date = end + timedelta(
            days=baseline.release_lags_days[vintage]
        )
        if release_date <= as_of_date:
            production = account["production"]
            industry_shares = {
                key: value / production["nominal_gdp_mvl"] * 100.0
                for key, value in production[
                    "nominal_gva_mvl_by_industry"
                ].items()
            }
            vintages.append({
                "period": account["period"],
                "vintage": vintage,
                "release_date": release_date.isoformat(),
                "nominal_gdp_mvl": production["nominal_gdp_mvl"],
                "real_gdp_mvl": production["real_gdp_mvl"],
                "real_growth_yoy_pct": production["real_growth_yoy_pct"],
                "deflator_index": production["deflator_index"],
                "industry_shares_pct": industry_shares,
                "industry_contributions_pct": copy.deepcopy(contributions),
                "expenditure": copy.deepcopy(account["expenditure"]),
                "status": "official_release",
                "is_model_nowcast": False,
            })
    return vintages
