#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_seat_expectations(path: Path) -> dict[int, set[str]]:
    expected: dict[int, set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c = int(row["congress_number"])
            admitted = str(row["admitted"]).strip().lower() in {"1", "true", "t", "yes", "y"}
            seats = int(row["house_seats"])
            if admitted and seats > 0:
                expected[c].add(str(row["state_fips"]).zfill(2))
    return expected


def normalize_boundaries(raw_geojson: dict) -> dict[int, list[dict]]:
    by_congress: dict[int, list[dict]] = defaultdict(list)

    for f in raw_geojson.get("features", []):
        props = dict(f.get("properties", {}))
        geom = f.get("geometry")
        if not geom:
            continue

        if "congress_number" in props:
            congresses = [int(props["congress_number"])]
        else:
            start = int(props["from_congress"])
            end = int(props["to_congress"])
            congresses = list(range(start, end + 1))

        for congress_number in congresses:
            by_congress[congress_number].append(
                {
                    "type": "Feature",
                    "properties": {
                        "congress_number": congress_number,
                        "state_fips": str(props["state_fips"]).zfill(2),
                        "state_abbr": str(props["state_abbr"]).strip().upper(),
                        "state_name": str(props["state_name"]).strip(),
                        "source_boundary_id": str(props.get("source_boundary_id", "unknown")).strip() or "unknown",
                    },
                    "geometry": geom,
                }
            )

    return by_congress


def write_outputs(by_congress: dict[int, list[dict]], out_root: Path, expected: dict[int, set[str]]) -> None:
    by_dir = out_root / "by_congress"
    by_dir.mkdir(parents=True, exist_ok=True)

    index = {"timeline": [], "missing_by_congress": {}}

    for congress_number in sorted(by_congress):
        features = by_congress[congress_number]

        seen: dict[str, dict] = {}
        for feature in features:
            state_fips = feature["properties"]["state_fips"]
            if state_fips in seen:
                raise SystemExit(f"Duplicate boundary for congress={congress_number}, state_fips={state_fips}")
            seen[state_fips] = feature

        missing = sorted(expected.get(congress_number, set()) - set(seen.keys()))
        if missing:
            index["missing_by_congress"][str(congress_number)] = missing

        collection = {"type": "FeatureCollection", "features": list(seen.values())}
        out_path = by_dir / f"{congress_number}.geojson"
        out_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")

        index["timeline"].append(
            {
                "congress_number": congress_number,
                "state_count": len(seen),
                "boundary_path": str((Path("data_processed") / "boundaries" / "by_congress" / f"{congress_number}.geojson").as_posix()),
            }
        )

    (out_root / "states_by_congress_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize NHGIS boundaries to congress-indexed files")
    parser.add_argument("--input", default=str(ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"))
    parser.add_argument("--seats", default=str(ROOT / "data_processed" / "seats" / "state_seats_by_congress.csv"))
    parser.add_argument("--out-root", default=str(ROOT / "data_processed" / "boundaries"))
    args = parser.parse_args()

    input_path = Path(args.input)
    seat_path = Path(args.seats)
    out_root = Path(args.out_root)

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if raw.get("type") != "FeatureCollection":
        raise SystemExit("Boundary input must be FeatureCollection")

    expected = load_seat_expectations(seat_path)
    by_congress = normalize_boundaries(raw)
    write_outputs(by_congress, out_root, expected)

    print(f"Wrote congress-indexed boundaries to {out_root}")


if __name__ == "__main__":
    main()
