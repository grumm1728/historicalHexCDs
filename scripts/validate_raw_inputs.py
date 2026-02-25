#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEATS_PATH = ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"
BOUNDARY_PATH = ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"

REQUIRED_SEAT_COLUMNS = {
    "congress_number",
    "state_fips",
    "state_abbr",
    "state_name",
    "house_seats",
    "admitted",
    "source_seat_version",
}

REQUIRED_BOUNDARY_BASE = {"state_fips", "state_abbr", "state_name", "source_boundary_id"}


def _fail(msg: str) -> None:
    raise SystemExit(msg)


def validate_seats() -> None:
    if not SEATS_PATH.exists():
        _fail(f"Missing seats file: {SEATS_PATH}")

    with SEATS_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            _fail("Seats CSV has no header")
        cols = set(reader.fieldnames)
        missing = REQUIRED_SEAT_COLUMNS - cols
        if missing:
            _fail(f"Seats CSV missing required columns: {sorted(missing)}")
        first = next(reader, None)
        if first is None:
            _fail("Seats CSV has no data rows")


def validate_boundaries() -> None:
    if not BOUNDARY_PATH.exists():
        _fail(f"Missing boundary file: {BOUNDARY_PATH}")

    obj = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    if obj.get("type") != "FeatureCollection":
        _fail("Boundary file must be a GeoJSON FeatureCollection")

    features = obj.get("features", [])
    if not features:
        _fail("Boundary FeatureCollection is empty")

    props = features[0].get("properties", {})
    missing_base = REQUIRED_BOUNDARY_BASE - set(props.keys())
    if missing_base:
        _fail(f"Boundary properties missing required keys: {sorted(missing_base)}")

    has_congress = "congress_number" in props
    has_window = "from_congress" in props and "to_congress" in props
    if not (has_congress or has_window):
        _fail("Boundary properties must include `congress_number` or both `from_congress` and `to_congress`")


def main() -> None:
    validate_seats()
    validate_boundaries()
    print("Raw input validation passed.")


if __name__ == "__main__":
    main()
