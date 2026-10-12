"""Boundary gaps between large urbanized areas, 1990-2020 (#36, linking rule A' from #34).

The metro module links two official urbanized areas from 1990 on when both have at least
500,000 people and their boundaries are within 5 km. Polygon distances need geopandas and
the zipped boundary files (~2 min), so they are computed once here and checked in as

    data_raw/urbanized_areas/ua_large_area_gaps.csv   (year, ua_code_a, ua_code_b, gap_km)

for every pair of >= 500,000 areas within CANDIDATE_KM of each other. The wider window
keeps the "stay apart" pairs (Chicago+Milwaukee ~38 km) visible for tests and audits.

Usage: python scripts/build_ua_large_area_gaps.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from diag_ua_linking import load_polygons

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw" / "urbanized_areas"
OUT = RAW / "ua_large_area_gaps.csv"
LARGE_POP = 500_000
CANDIDATE_KM = 60.0


def main() -> None:
    portions = pd.read_csv(RAW / "ua_state_portions.csv", dtype={"ua_code": str, "state_fips": str})
    rows = []
    for year in (1990, 2000, 2010, 2020):
        p = portions[portions.year == year]
        big = sorted(p.loc[p.total_pop >= LARGE_POP, "ua_code"].unique())
        polys = load_polygons(year).set_index("code")
        missing = [c for c in big if c not in polys.index]
        if missing:
            raise RuntimeError(f"{year}: no boundary for large areas {missing}")
        geoms = {c: polys.loc[c, "geometry"] for c in big}
        for i, a in enumerate(big):
            for b in big[i + 1:]:
                gap = geoms[a].distance(geoms[b]) / 1000.0
                if gap <= CANDIDATE_KM:
                    rows.append((year, a, b, round(gap, 3)))
        print(f"{year}: {len(big)} large areas, {sum(r[0] == year for r in rows)} pairs within {CANDIDATE_KM:g} km")
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "ua_code_a", "ua_code_b", "gap_km"])
        w.writerows(rows)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
