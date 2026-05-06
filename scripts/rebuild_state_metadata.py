#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_U.S._states_by_date_of_admission_to_the_Union"


@dataclass
class StateMeta:
    admission_order: int
    state_name: str
    admission_date_raw: str
    admission_type: str
    admission_date_iso: str
    formed_from: str


def load_state_lookup(seed_csv: Path) -> dict[str, tuple[str, str]]:
    with seed_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    sample = [r for r in rows if int(r["congress_number"]) == 118]
    by_name = {
        r["state_name"].strip(): (str(r["state_fips"]).zfill(2), r["state_abbr"].strip().upper())
        for r in sample
    }
    if len(by_name) != 50:
        raise SystemExit(f"Expected 50 modern states in seed lookup, found {len(by_name)}")
    return by_name


def normalize_date(raw: str) -> tuple[str, str]:
    txt = re.sub(r"\[[^\]]+\]", "", str(raw)).strip()
    admission_type = "admitted"
    m = re.search(r"\(([^)]+)\)", txt)
    if m:
        admission_type = m.group(1).strip().lower()
        txt = re.sub(r"\s*\([^)]+\)\s*$", "", txt).strip()
    dt = pd.to_datetime(txt, errors="coerce")
    if pd.isna(dt):
        raise SystemExit(f"Could not parse admission date: {raw}")
    return dt.date().isoformat(), admission_type


def fetch_wiki_table() -> list[StateMeta]:
    req = Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    tables = pd.read_html(StringIO(html))
    if not tables:
        raise SystemExit("No tables found at admission-date source")
    df = tables[0].copy()

    out: list[StateMeta] = []
    for _, row in df.iterrows():
        order = int(row.iloc[0])
        state_name = str(row.iloc[1]).strip()
        raw_date = str(row.iloc[2]).strip()
        formed_from = str(row.iloc[3]).strip()
        iso, admission_type = normalize_date(raw_date)
        out.append(
            StateMeta(
                admission_order=order,
                state_name=state_name,
                admission_date_raw=raw_date,
                admission_type=admission_type,
                admission_date_iso=iso,
                formed_from=formed_from,
            )
        )
    if len(out) != 50:
        raise SystemExit(f"Expected 50 states in admission table, found {len(out)}")
    return out


def write_output(path: Path, lookup: dict[str, tuple[str, str]], states: list[StateMeta]) -> None:
    fieldnames = [
        "state_fips",
        "state_abbr",
        "state_name",
        "admission_order",
        "admission_date_iso",
        "admission_date_raw",
        "admission_type",
        "formed_from",
        "source_admission_version",
    ]
    version = f"wikipedia-admission-dates-{date.today().isoformat()}"
    rows: list[dict[str, object]] = []

    for s in states:
        if s.state_name not in lookup:
            raise SystemExit(f"State name mismatch against local lookup: {s.state_name}")
        state_fips, state_abbr = lookup[s.state_name]
        rows.append(
            {
                "state_fips": state_fips,
                "state_abbr": state_abbr,
                "state_name": s.state_name,
                "admission_order": s.admission_order,
                "admission_date_iso": s.admission_date_iso,
                "admission_date_raw": s.admission_date_raw,
                "admission_type": s.admission_type,
                "formed_from": s.formed_from,
                "source_admission_version": version,
            }
        )

    rows.sort(key=lambda r: int(r["admission_order"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build state admission metadata from Wikipedia")
    parser.add_argument("--seed-csv", default=str(ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"))
    parser.add_argument("--out", default=str(ROOT / "data_raw" / "states" / "state_metadata.csv"))
    args = parser.parse_args()

    lookup = load_state_lookup(Path(args.seed_csv))
    states = fetch_wiki_table()
    write_output(Path(args.out), lookup, states)
    print(f"Wrote state metadata to {args.out}")


if __name__ == "__main__":
    main()

