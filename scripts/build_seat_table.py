#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def congress_start_date(congress_number: int) -> date:
    year = 1789 + (congress_number - 1) * 2
    if congress_number >= 74:
        return date(year, 1, 3)
    return date(year, 3, 4)


def congress_end_date(congress_number: int) -> date:
    return congress_start_date(congress_number + 1) - timedelta(days=1)


def parse_bool(raw: str) -> bool:
    v = str(raw).strip().lower()
    return v in {"1", "true", "t", "yes", "y"}


@dataclass
class SeatRow:
    congress_number: int
    state_fips: str
    state_abbr: str
    state_name: str
    house_seats: int
    admitted: bool
    source_seat_version: str


def load_rows(path: Path) -> list[SeatRow]:
    rows: list[SeatRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for src in reader:
            rows.append(
                SeatRow(
                    congress_number=int(src["congress_number"]),
                    state_fips=str(src["state_fips"]).zfill(2),
                    state_abbr=str(src["state_abbr"]).strip().upper(),
                    state_name=str(src["state_name"]).strip(),
                    house_seats=int(src["house_seats"]),
                    admitted=parse_bool(src["admitted"]),
                    source_seat_version=str(src.get("source_seat_version", "unknown")).strip() or "unknown",
                )
            )
    if not rows:
        raise SystemExit("Seat input is empty")
    return rows


def build_matrix(rows: list[SeatRow], max_congress: int) -> list[dict[str, object]]:
    by_key: dict[tuple[int, str], SeatRow] = {}
    state_meta: dict[str, tuple[str, str]] = {}
    state_versions: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        by_key[(row.congress_number, row.state_fips)] = row
        state_meta[row.state_fips] = (row.state_abbr, row.state_name)
        state_versions[row.state_fips].add(row.source_seat_version)

    admission_by_state: dict[str, int] = {}
    for state_fips in state_meta:
        admitted_points = [
            r.congress_number
            for r in rows
            if r.state_fips == state_fips and (r.admitted or r.house_seats > 0)
        ]
        if not admitted_points:
            raise SystemExit(f"No admission signal found for state_fips={state_fips}")
        admission_by_state[state_fips] = min(admitted_points)

    out: list[dict[str, object]] = []
    missing_post_admission: list[tuple[int, str]] = []

    for congress_number in range(1, max_congress + 1):
        for state_fips in sorted(state_meta):
            state_abbr, state_name = state_meta[state_fips]
            admission = admission_by_state[state_fips]
            row = by_key.get((congress_number, state_fips))

            if row is not None:
                admitted = row.admitted
                house_seats = row.house_seats
                source_seat_version = row.source_seat_version
            elif congress_number < admission:
                admitted = False
                house_seats = 0
                source_seat_version = "derived-pre-admission"
            else:
                missing_post_admission.append((congress_number, state_fips))
                admitted = True
                house_seats = -1
                source_seat_version = "missing"

            out.append(
                {
                    "congress_number": congress_number,
                    "start_date": congress_start_date(congress_number).isoformat(),
                    "end_date": congress_end_date(congress_number).isoformat(),
                    "state_fips": state_fips,
                    "state_abbr": state_abbr,
                    "state_name": state_name,
                    "house_seats": house_seats,
                    "admitted": admitted,
                    "source_seat_version": source_seat_version,
                }
            )

    if missing_post_admission:
        sample = ", ".join([f"(C{c}, {s})" for c, s in missing_post_admission[:8]])
        raise SystemExit(
            "Congress-exact seat table has gaps after state admission; add rows for all post-admission Congresses. "
            f"Sample gaps: {sample}"
        )

    return out


def write_outputs(rows: list[dict[str, object]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "state_seats_by_congress.csv"
    json_path = out_dir / "state_seats_index.json"

    fieldnames = [
        "congress_number",
        "start_date",
        "end_date",
        "state_fips",
        "state_abbr",
        "state_name",
        "house_seats",
        "admitted",
        "source_seat_version",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    congresses = sorted({int(r["congress_number"]) for r in rows})
    states = sorted({str(r["state_fips"]) for r in rows})
    versions = sorted({str(r["source_seat_version"]) for r in rows})

    summary = {
        "row_count": len(rows),
        "state_count": len(states),
        "congress_min": min(congresses),
        "congress_max": max(congresses),
        "source_versions": versions,
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize congress-exact seat table")
    parser.add_argument("--input", default=str(ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"))
    parser.add_argument("--out-dir", default=str(ROOT / "data_processed" / "seats"))
    parser.add_argument("--max-congress", type=int, default=119)
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    rows = load_rows(input_path)
    matrix = build_matrix(rows, max_congress=args.max_congress)
    write_outputs(matrix, out_dir)
    print(f"Wrote normalized seat table to {out_dir}")


if __name__ == "__main__":
    main()
