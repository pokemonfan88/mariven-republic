#!/usr/bin/env python3
"""Extract the Fiji 2026 single-age prior from the official WPP 2024 CSV."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


SOURCE_URL = (
    "https://population.un.org/wpp/assets/Excel%20Files/"
    "1_Indicator%20(Standard)/CSV_FILES/"
    "WPP2024_Population1JanuaryBySingleAgeSex_Medium_2024-2100.csv.gz"
)
EXPECTED_CONTENT_LENGTH = 67_882_675
EXPECTED_CONTENT_MD5_BASE64 = "TH0BA8QFM5lieXMP4V0nwQ=="
EXPECTED_ETAG = "0x8DD1BA9FCD4B6BC"
EXPECTED_LAST_MODIFIED = "2024-12-13T19:11:46Z"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(source_path):
    records = []
    with gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if (
                row["ISO3_code"] == "FJI"
                and row["Variant"] == "Medium"
                and row["Time"] == "2026"
            ):
                records.append(row)
    records.sort(key=lambda row: int(row["AgeGrpStart"]))
    if len(records) != 101:
        raise ValueError(f"expected 101 Fiji age rows, found {len(records)}")
    if [int(row["AgeGrpStart"]) for row in records] != list(range(101)):
        raise ValueError("Fiji age rows must cover 0 through 100+")
    extracted = {
        "age_groups": [row["AgeGrp"] for row in records],
        "male": [
            round(float(row["PopMale"]) * 1000, 3) for row in records
        ],
        "female": [
            round(float(row["PopFemale"]) * 1000, 3) for row in records
        ],
    }
    extract_data_sha256 = hashlib.sha256(
        json.dumps(
            extracted,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "_meta": {
            "description": "Fiji 2026 single-age population prior by sex",
            "source": "United Nations World Population Prospects 2024",
            "source_url": SOURCE_URL,
            "source_file": Path(source_path).name,
            "source_file_sha256": sha256_file(source_path),
            "extract_data_sha256": extract_data_sha256,
            "source_content_length": EXPECTED_CONTENT_LENGTH,
            "source_content_md5_base64": EXPECTED_CONTENT_MD5_BASE64,
            "source_etag": EXPECTED_ETAG,
            "source_last_modified": EXPECTED_LAST_MODIFIED,
            "accessed_on": "2026-07-16",
            "revision": "2024",
            "variant": "Medium",
            "reference_date": "2026-01-01",
            "location": "Fiji",
            "iso3": "FJI",
            "units": "persons",
            "license": "Creative Commons Attribution 3.0 IGO",
            "license_url": "https://creativecommons.org/licenses/by/3.0/igo/",
            "transformation": "PopMale and PopFemale multiplied by 1000; no smoothing or interpolation",
        },
        **extracted,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "sources"
        / "wpp2024_fiji_2026_single_age_sex.json",
    )
    args = parser.parse_args()
    if args.source.stat().st_size != EXPECTED_CONTENT_LENGTH:
        raise ValueError("WPP source content length does not match expected file")
    value = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
