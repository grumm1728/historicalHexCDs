#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from tile_state_pentahexes import MAINE_IN_MA, ME_FIPS

ROOT = Path(__file__).resolve().parent.parent
HEXES_PER_CD = 5


def load_seat_rows(path: Path) -> dict[tuple[int, str], dict]:
    out = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out[(int(row["congress_number"]), str(row["state_fips"]).zfill(2))] = row
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated historical outputs")
    parser.add_argument("--index", default=str(ROOT / "data_processed" / "congress_index.json"))
    parser.add_argument("--seats", default=str(ROOT / "data_processed" / "seats" / "state_seats_by_congress.csv"))
    args = parser.parse_args()

    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    seat_rows = load_seat_rows(Path(args.seats))

    failures: list[str] = []

    for frame in index.get("timeline", []):
        congress_number = int(frame["congress_number"])
        state_feature_path = ROOT / frame["state_feature_path"]
        shapefile_path = ROOT / frame["shapefile_path"]

        if not state_feature_path.exists():
            failures.append(f"Missing state feature file: {state_feature_path}")
            continue
        if not shapefile_path.exists():
            failures.append(f"Missing shapefile: {shapefile_path}")

        geo = json.loads(state_feature_path.read_text(encoding="utf-8"))
        # While Maine was part of Massachusetts the tiler draws its districts as MA, except
        # the C16 at-large seat it keeps as Maine (`me_labeled`; see MAINE_IN_MA).
        maine_seats = MAINE_IN_MA.get(congress_number, (0, 0))[1]
        seen = set()
        for feature in geo.get("features", []):
            p = feature.get("properties", {})
            state_fips = str(p.get("state_fips", "")).zfill(2)
            seen.add(state_fips)
            seats = int(p.get("house_seats", 0))
            cells = int(p.get("cell_count", 0))
            if cells != HEXES_PER_CD * seats:
                failures.append(f"Seats/cells mismatch C{congress_number} {state_fips}: seats={seats}, cells={cells}")

            seat_row = seat_rows.get((congress_number, state_fips))
            expected = maine_seats if state_fips == ME_FIPS and maine_seats else (
                int(seat_row["house_seats"]) if seat_row is not None else None
            )
            if expected is None:
                failures.append(f"Missing processed seat row for C{congress_number} {state_fips}")
            elif expected != seats:
                failures.append(f"Seat mismatch C{congress_number} {state_fips}: expected {expected} got {seats}")

        expected_admitted = {
            s
            for (c, s), r in seat_rows.items()
            if c == congress_number and str(r["admitted"]).strip().lower() in {"1", "true", "t", "yes", "y"} and int(r["house_seats"]) > 0
        }
        if maine_seats:
            expected_admitted.add(ME_FIPS)
        if expected_admitted != seen:
            missing = sorted(expected_admitted - seen)
            extra = sorted(seen - expected_admitted)
            if missing:
                failures.append(f"Missing states in C{congress_number}: {missing}")
            if extra:
                failures.append(f"Unexpected states in C{congress_number}: {extra}")

    if failures:
        msg = "\n".join(failures[:50])
        raise SystemExit(f"Validation failed:\n{msg}")

    print("Output validation passed.")


if __name__ == "__main__":
    main()
