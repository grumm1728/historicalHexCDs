#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WIKI_URL = "https://en.wikipedia.org/wiki/United_States_congressional_apportionment"


def congress_start_year(congress_number: int) -> int:
    return 1789 + (congress_number - 1) * 2


@dataclass
class ApportionmentColumn:
    congress_label: str
    effected_year: int


def load_state_lookup(seed_csv: Path) -> dict[str, tuple[str, str]]:
    with seed_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    sample = [r for r in rows if int(r["congress_number"]) == 118]
    lookup = {r["state_abbr"].strip().upper(): (str(r["state_fips"]).zfill(2), r["state_name"].strip()) for r in sample}
    if len(lookup) != 50:
        raise SystemExit(f"Expected 50 states in seed lookup, found {len(lookup)}")
    return lookup


def fetch_past_apportionments_table() -> pd.DataFrame:
    req = Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        html_text = resp.read().decode("utf-8", errors="replace")
    tables = pd.read_html(StringIO(html_text))

    target = None
    for tbl in tables:
        cols = [str(c) for c in tbl.columns]
        if any("Const." in c for c in cols) and any("24th" in c for c in cols):
            target = tbl
            break
    if target is None:
        raise SystemExit("Could not find Wikipedia Past apportionments table")
    return target


def normalize_table(tbl: pd.DataFrame) -> tuple[list[ApportionmentColumn], pd.DataFrame]:
    # MultiIndex columns like ('Const.', '1789', '1789', '65', 'Unnamed...')
    ap_cols: list[ApportionmentColumn] = []
    value_cols: list[str] = []

    for col in tbl.columns[2:]:
        label = str(col[0]).strip()
        effected_raw = str(col[2]).strip() if isinstance(col, tuple) and len(col) > 2 else ""
        if effected_raw.isdigit():
            ap_cols.append(ApportionmentColumn(congress_label=label, effected_year=int(effected_raw)))
            value_cols.append(col)

    states = tbl.copy()
    states = states[[tbl.columns[1], *value_cols]]
    states.columns = ["state_abbr", *value_cols]

    # Normalize values
    states["state_abbr"] = states["state_abbr"].astype(str).str.strip().str.upper()
    for c in value_cols:
        states[c] = (
            states[c]
            .astype(str)
            .str.replace("\u2013", "0", regex=False)
            .str.replace("-", "0", regex=False)
            .str.replace("\u2014", "0", regex=False)
            .str.strip()
        )
        states[c] = pd.to_numeric(states[c], errors="coerce").fillna(0).astype(int)

    return ap_cols, states


def seats_for_congress(ap_cols: list[ApportionmentColumn], states: pd.DataFrame, congress_number: int) -> dict[str, int]:
    year = congress_start_year(congress_number)
    eligible = [c for c in ap_cols if c.effected_year <= year]
    if not eligible:
        raise SystemExit(f"No apportionment column for congress {congress_number} (start year {year})")
    chosen = max(eligible, key=lambda c: c.effected_year)

    col = None
    for candidate in states.columns[1:]:
        if str(candidate[0]).strip() == chosen.congress_label:
            col = candidate
            break
    if col is None:
        raise SystemExit(f"Could not map apportionment column {chosen.congress_label}")

    return {row["state_abbr"]: int(row[col]) for _, row in states.iterrows()}


def write_output(path: Path, lookup: dict[str, tuple[str, str]], ap_cols: list[ApportionmentColumn], states: pd.DataFrame, max_congress: int) -> None:
    fieldnames = [
        "congress_number",
        "state_fips",
        "state_abbr",
        "state_name",
        "house_seats",
        "admitted",
        "source_seat_version",
    ]
    version = f"wikipedia-past-apportionments-{date.today().isoformat()}"
    out_rows: list[dict[str, object]] = []

    for congress in range(1, max_congress + 1):
        seat_map = seats_for_congress(ap_cols, states, congress)
        for abbr in sorted(lookup):
            state_fips, state_name = lookup[abbr]
            seats = int(seat_map.get(abbr, 0))
            out_rows.append(
                {
                    "congress_number": congress,
                    "state_fips": state_fips,
                    "state_abbr": abbr,
                    "state_name": state_name,
                    "house_seats": seats,
                    "admitted": seats > 0,
                    "source_seat_version": version,
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)


def write_apportionment_output(
    path: Path,
    lookup: dict[str, tuple[str, str]],
    ap_cols: list[ApportionmentColumn],
    states: pd.DataFrame,
) -> None:
    fieldnames = [
        "apportionment_label",
        "effective_year",
        "state_fips",
        "state_abbr",
        "state_name",
        "house_seats",
        "admitted",
        "source_seat_version",
    ]
    version = f"wikipedia-past-apportionments-{date.today().isoformat()}"
    out_rows: list[dict[str, object]] = []

    for ap in sorted(ap_cols, key=lambda a: a.effected_year):
        col = None
        for candidate in states.columns[1:]:
            if str(candidate[0]).strip() == ap.congress_label:
                col = candidate
                break
        if col is None:
            continue

        for abbr in sorted(lookup):
            state_fips, state_name = lookup[abbr]
            row_match = states[states["state_abbr"] == abbr]
            if row_match.empty:
                seats = 0
            else:
                seats = int(row_match.iloc[0][col])
            out_rows.append(
                {
                    "apportionment_label": ap.congress_label,
                    "effective_year": ap.effected_year,
                    "state_fips": state_fips,
                    "state_abbr": abbr,
                    "state_name": state_name,
                    "house_seats": seats,
                    "admitted": seats > 0,
                    "source_seat_version": version,
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild congress-exact seat table from Wikipedia past apportionments")
    parser.add_argument("--seed-csv", default=str(ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"))
    parser.add_argument("--out", default=str(ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"))
    parser.add_argument(
        "--apportionment-out",
        default=str(ROOT / "data_raw" / "seats" / "state_seats_by_apportionment.csv"),
    )
    parser.add_argument("--max-congress", type=int, default=119)
    args = parser.parse_args()

    lookup = load_state_lookup(Path(args.seed_csv))
    tbl = fetch_past_apportionments_table()
    ap_cols, states = normalize_table(tbl)
    write_output(Path(args.out), lookup, ap_cols, states, args.max_congress)
    write_apportionment_output(Path(args.apportionment_out), lookup, ap_cols, states)
    print(f"Wrote seat table to {args.out}")
    print(f"Wrote apportionment table to {args.apportionment_out}")


if __name__ == "__main__":
    main()
