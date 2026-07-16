#!/usr/bin/env python3
"""Build the versioned Mariven 2026 population baseline.

The single-age prior is Fiji's 2026 medium-variant projection from UN WPP
2024, cross-checked against the official Fiji 2017 census age-sex table. The
resulting values are synthetic Mariven data calibrated to the project's
worldbuilding anchors; they are not Fiji population estimates.
"""

import argparse
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path


TARGET_POPULATION = 1_200_000
TARGET_MEDIAN_AGE = 27.8
ANCHOR_DATE = "2026-08-11"
BASELINE_VERSION = "mariven-population-2026-v1"
WPP_FIJI_2026_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sources"
    / "wpp2024_fiji_2026_single_age_sex.json"
)
WPP_SOURCE_SHA256 = (
    "a44c70cbf852c07fbe844bb45271ee5b533b62e6c2a6edcb3cf7f23bcbb13ab3"
)
WPP_EXTRACT_DATA_SHA256 = (
    "1162453270449aa7bdb2518e402d970807fbda6806502d7229a2fd01adc291bb"
)

FIJI_2017_MALE = (
    47_195, 45_243, 40_715, 38_032, 37_464, 35_253, 35_266, 33_382,
    27_697, 25_314, 24_649, 21_263, 14_891, 10_076, 6_367, 5_788,
)
FIJI_2017_FEMALE = (
    44_702, 43_052, 38_881, 36_056, 36_152, 34_055, 33_552, 31_768,
    25_817, 24_190, 23_961, 20_745, 15_724, 11_252, 7_781, 8_604,
)

MALE_MORTALITY_ANCHORS = {
    5: 0.00030, 10: 0.00025, 15: 0.00060, 20: 0.00120,
    25: 0.00180, 30: 0.00200, 35: 0.00240, 40: 0.00320,
    45: 0.00450, 50: 0.00650, 55: 0.00950, 60: 0.01400,
    65: 0.02200, 70: 0.03500, 75: 0.05500, 80: 0.09000,
    85: 0.15000, 90: 0.24000, 95: 0.36000, 100: 0.50000,
}
FEMALE_MORTALITY_ANCHORS = {
    5: 0.00025, 10: 0.00020, 15: 0.00035, 20: 0.00050,
    25: 0.00070, 30: 0.00090, 35: 0.00120, 40: 0.00180,
    45: 0.00280, 50: 0.00440, 55: 0.00680, 60: 0.01050,
    65: 0.01650, 70: 0.02700, 75: 0.04500, 80: 0.07500,
    85: 0.12500, 90: 0.21000, 95: 0.34000, 100: 0.48000,
}


def largest_remainder(values, total):
    scaled = [value * total / sum(values) for value in values]
    result = [math.floor(value) for value in scaled]
    order = sorted(
        range(len(values)),
        key=lambda index: (scaled[index] - result[index], -index),
        reverse=True,
    )
    for index in order[:total - sum(result)]:
        result[index] += 1
    return result


@lru_cache(maxsize=1)
def wpp_fiji_2026_prior():
    raw = json.loads(WPP_FIJI_2026_PATH.read_text(encoding="utf-8"))
    metadata = raw.get("_meta")
    if not isinstance(metadata, dict):
        raise ValueError("WPP Fiji extract is missing metadata")
    if metadata.get("source_file_sha256") != WPP_SOURCE_SHA256:
        raise ValueError("WPP Fiji extract source checksum is unexpected")
    extracted = {
        key: raw.get(key) for key in ("age_groups", "male", "female")
    }
    extracted_sha256 = hashlib.sha256(
        json.dumps(
            extracted,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        metadata.get("extract_data_sha256") != WPP_EXTRACT_DATA_SHA256
        or extracted_sha256 != WPP_EXTRACT_DATA_SHA256
    ):
        raise ValueError("WPP Fiji extracted arrays checksum is unexpected")
    if raw.get("age_groups") != [str(age) for age in range(100)] + ["100+"]:
        raise ValueError("WPP Fiji extract must cover ages 0 through 100+")
    priors = []
    for sex in ("male", "female"):
        values = raw.get(sex)
        if (
            not isinstance(values, list)
            or len(values) != 101
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                for value in values
            )
        ):
            raise ValueError(f"WPP Fiji extract {sex} values are invalid")
        priors.append(tuple(float(value) for value in values))
    return priors[0], priors[1], dict(metadata)


def interpolated_median(cohorts):
    totals = [
        cohorts["male"][age] + cohorts["female"][age]
        for age in range(101)
    ]
    halfway = sum(totals) / 2
    cumulative = 0
    for age, count in enumerate(totals):
        if cumulative + count >= halfway:
            return age + (halfway - cumulative) / count
        cumulative += count
    return 100.0


def calibrated_cohorts(senior_tilt=0.0):
    male_prior, female_prior, _ = wpp_fiji_2026_prior()
    fiji_total = sum(male_prior) + sum(female_prior)
    male_total = round(TARGET_POPULATION * sum(male_prior) / fiji_total)
    female_total = TARGET_POPULATION - male_total

    def at_tilt(tilt):
        male = largest_remainder(
            [
                value * math.exp(tilt * (age - TARGET_MEDIAN_AGE) / 50)
                * math.exp(senior_tilt * max(0, age - 60) / 40)
                for age, value in enumerate(male_prior)
            ],
            male_total,
        )
        female = largest_remainder(
            [
                value * math.exp(tilt * (age - TARGET_MEDIAN_AGE) / 50)
                * math.exp(senior_tilt * max(0, age - 60) / 40)
                for age, value in enumerate(female_prior)
            ],
            female_total,
        )
        return {"male": male, "female": female}

    low, high = -2.0, 2.0
    for _ in range(80):
        midpoint = (low + high) / 2
        if interpolated_median(at_tilt(midpoint)) < TARGET_MEDIAN_AGE:
            low = midpoint
        else:
            high = midpoint
    return at_tilt((low + high) / 2), (low + high) / 2


def birthday_buckets(cohorts):
    output = {"male": [], "female": []}
    for sex_offset, sex in enumerate(("male", "female")):
        for age, count in enumerate(cohorts[sex]):
            quotient, remainder = divmod(count, 12)
            buckets = [quotient] * 12
            start = (age * 5 + sex_offset * 7) % 12
            for offset in range(remainder):
                buckets[(start + offset) % 12] += 1
            output[sex].append(buckets)
    return output


def fertility_weights():
    five_year_shares = (0.06, 0.20, 0.30, 0.24, 0.14, 0.05, 0.01)
    weights = []
    for share in five_year_shares:
        weights.extend([share / 5] * 5)
    return weights


def log_interpolate(anchors, age):
    keys = sorted(anchors)
    if age <= keys[0]:
        return anchors[keys[0]]
    for lower, upper in zip(keys, keys[1:]):
        if age <= upper:
            fraction = (age - lower) / (upper - lower)
            return math.exp(
                math.log(anchors[lower]) * (1 - fraction)
                + math.log(anchors[upper]) * fraction
            )
    return anchors[keys[-1]]


def life_expectancy(rates):
    survivors = 1.0
    years = 0.0
    for probability in rates[:100]:
        years += survivors * (1 - probability / 2)
        survivors *= 1 - probability
    open_probability = rates[100]
    return years + survivors * (1 / open_probability - 0.5)


def mortality_rates(anchors, target_life_expectancy):
    infant_probability = 0.0162
    child_probability = 1 - (
        (1 - 0.0213) / (1 - infant_probability)
    ) ** 0.25

    def at_scale(scale):
        return [
            infant_probability
            if age == 0
            else child_probability
            if age <= 4
            else min(0.95, log_interpolate(anchors, age) * scale)
            for age in range(101)
        ]

    low, high = 0.1, 10.0
    for _ in range(100):
        midpoint = (low + high) / 2
        if life_expectancy(at_scale(midpoint)) > target_life_expectancy:
            low = midpoint
        else:
            high = midpoint
    return at_scale((low + high) / 2)


def calibrated_population_and_mortality(annual_deaths=6_600):
    mortality = {
        "male": mortality_rates(MALE_MORTALITY_ANCHORS, 67.0),
        "female": mortality_rates(FEMALE_MORTALITY_ANCHORS, 71.5),
    }

    def at_senior_tilt(senior_tilt):
        cohorts, age_tilt = calibrated_cohorts(senior_tilt)
        implied = sum(
            cohorts[sex][age] * mortality[sex][age]
            for sex in ("male", "female")
            for age in range(101)
        )
        return cohorts, age_tilt, implied

    low, high = -12.0, 0.0
    low_cohorts, low_age_tilt, low_deaths = at_senior_tilt(low)
    high_cohorts, high_age_tilt, high_deaths = at_senior_tilt(high)
    if not low_deaths <= annual_deaths <= high_deaths:
        raise ValueError(
            "population senior-tilt bounds do not bracket annual deaths"
        )
    for _ in range(80):
        midpoint = (low + high) / 2
        cohorts, age_tilt, implied = at_senior_tilt(midpoint)
        if implied < annual_deaths:
            low = midpoint
            low_cohorts = cohorts
            low_age_tilt = age_tilt
            low_deaths = implied
        else:
            high = midpoint
            high_cohorts = cohorts
            high_age_tilt = age_tilt
            high_deaths = implied
    senior_tilt = (low + high) / 2
    cohorts, age_tilt, implied = at_senior_tilt(senior_tilt)
    return cohorts, age_tilt, senior_tilt, mortality, implied


def normalized_age_sex_weights(age_function, male_share):
    male = [age_function(age) * male_share for age in range(101)]
    female = [age_function(age) * (1 - male_share) for age in range(101)]
    total = sum(male) + sum(female)
    return {
        "male": [value / total for value in male],
        "female": [value / total for value in female],
    }


def gaussian(age, mean, sigma):
    return math.exp(-0.5 * ((age - mean) / sigma) ** 2)


def migration_weights():
    return {
        "returning_diaspora": normalized_age_sex_weights(
            lambda age: 0.22 * gaussian(age, 8, 6)
            + 0.78 * gaussian(age, 36, 11),
            0.50,
        ),
        "foreign_immigrants": normalized_age_sex_weights(
            lambda age: gaussian(age, 31, 9),
            0.55,
        ),
        "emigrants": normalized_age_sex_weights(
            lambda age: gaussian(age, 27, 8),
            0.50,
        ),
    }


def notable_death_weights(mortality):
    return {
        "traffic": normalized_age_sex_weights(
            lambda age: gaussian(age, 31, 15), 0.75
        ),
        "drowning": normalized_age_sex_weights(
            lambda age: 0.30 * gaussian(age, 10, 7)
            + 0.70 * gaussian(age, 30, 15),
            0.80,
        ),
        "suicide": normalized_age_sex_weights(
            lambda age: gaussian(age, 27, 10), 0.76
        ),
        "murder": normalized_age_sex_weights(
            lambda age: gaussian(age, 30, 12), 0.80
        ),
        "workplace": normalized_age_sex_weights(
            lambda age: gaussian(age, 38, 13), 0.90
        ),
        "lightning": normalized_age_sex_weights(
            lambda age: gaussian(age, 39, 16), 0.75
        ),
        "other": normalized_age_sex_weights(
            lambda age: (
                mortality["male"][age] + mortality["female"][age]
            ),
            0.50,
        ),
    }


def build_baseline():
    (
        cohorts,
        age_tilt,
        senior_tilt,
        mortality,
        implied_deaths,
    ) = calibrated_population_and_mortality()
    totals = [
        cohorts["male"][age] + cohorts["female"][age]
        for age in range(101)
    ]
    _, _, prior_metadata = wpp_fiji_2026_prior()
    return {
        "_meta": {
            "description": "Synthetic Mariven single-age population baseline",
            "generated_by": "scripts/build_population_baseline.py",
            "generated_on": "2026-07-16",
            "runtime_network_required": False,
            "sources": [
                {
                    "name": "UN World Population Prospects 2024",
                    "url": prior_metadata["source_url"],
                    "use": "Fiji 2026 single-age, sex-specific prior shape",
                    "accessed_on": prior_metadata["accessed_on"],
                    "license": prior_metadata["license"],
                    "license_url": prior_metadata["license_url"],
                },
                {
                    "name": "Fiji Bureau of Statistics, 2017 age-sex population table",
                    "url": "https://www.statsfiji.gov.fj/statistics/social-statistics/population-and-demographic-indicators/",
                    "use": "Official census cross-check for Fiji age-sex structure",
                    "accessed_on": "2026-07-16",
                    "reuse_note": "Official public statistics; source attribution retained.",
                },
                {
                    "name": "Mariven worldbuilding demographic anchors",
                    "url": "../worldbuilding/04-demographics.md",
                    "use": "Population, fertility, age and life-expectancy calibration",
                },
            ],
            "single_age_prior": prior_metadata,
            "fiji_2017_five_year_prior": {
                "age_groups": [
                    "0-4", "5-9", "10-14", "15-19", "20-24", "25-29",
                    "30-34", "35-39", "40-44", "45-49", "50-54",
                    "55-59", "60-64", "65-69", "70-74", "75+",
                ],
                "male": list(FIJI_2017_MALE),
                "female": list(FIJI_2017_FEMALE),
            },
            "transformation": {
                "single_age_source": "WPP 2024 Fiji medium variant, 2026",
                "age_tilt": age_tilt,
                "senior_tilt": senior_tilt,
                "integer_allocation": "largest_remainder",
            },
        },
        "version": BASELINE_VERSION,
        "anchor_date": ANCHOR_DATE,
        "cohorts": cohorts,
        "birthday_buckets": birthday_buckets(cohorts),
        "fertility_weights": fertility_weights(),
        "mortality_rates": mortality,
        "migration_weights": migration_weights(),
        "notable_death_weights": notable_death_weights(mortality),
        "first_cycle_targets": {
            "births": 27_500,
            "baseline_deaths": 6_600,
            "returning_diaspora": 2_500,
            "foreign_immigrants": 2_200,
            "emigrants": 2_800,
        },
        "calibration": {
            "total_population": sum(totals),
            "male_population": sum(cohorts["male"]),
            "female_population": sum(cohorts["female"]),
            "median_age": interpolated_median(cohorts),
            "children_0_14": sum(totals[:15]),
            "working_age_15_64": sum(totals[15:65]),
            "elderly_65_plus": sum(totals[65:]),
            "women_15_49": sum(cohorts["female"][15:50]),
            "tfr": 2.3,
            "annual_births": 27_500,
            "annual_all_cause_deaths": round(implied_deaths),
            "implied_annual_all_cause_deaths": implied_deaths,
            "life_expectancy_male": round(life_expectancy(mortality["male"]), 6),
            "life_expectancy_female": round(life_expectancy(mortality["female"]), 6),
            "infant_mortality_per_1000": 16.2,
            "under_five_mortality_per_1000": 21.3,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "population_baseline_2026.json",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
