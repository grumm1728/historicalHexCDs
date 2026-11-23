"""Real congressional districts C113-C119: one point per district, plus real adjacency (#53).

Numbering (scripts/number_seats.py) projects each real district to a single point and
matches those points to seats. The point is the district's **center of population** (the
population-weighted mean of the Census tract centers of population inside it), not its
geometric centroid. A big rural district's population sits in its towns, and a center
of population is where the district "is" for a reader.

Writes, next to the CD files in data_raw/congressional_districts/:

  real_district_points_c113_c119.csv     congress, state_fips, state, cd, lon, lat, tract_pop
  real_district_adjacency_c113_c119.csv  congress, state, cd_a, cd_b, shared_km
                                         (same-state pairs whose boundaries share a line;
                                         used only for the neighbour-preservation metric)

Reuses the CD file table and filters of build_real_district_metro.py (DC, territories and
the "ZZ" water parts are dropped). Needs geopandas, unlike the tiler.

Run:  python scripts/build_real_district_points.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import urban_seats as us  # noqa: E402
from build_real_district_metro import CD_DIR, CD_FILES, EQUAL_AREA, TRACT_FILES  # noqa: E402

MIN_SHARED_KM = 0.5  # boundaries touching at a point (or a sliver) are not neighbours


def tracts(census_year: int) -> gpd.GeoDataFrame:
    df = pd.read_csv(CD_DIR / TRACT_FILES[census_year], dtype={"STATEFP": str}, encoding="utf-8-sig")
    df = df[df.POPULATION > 0]
    return gpd.GeoDataFrame(df[["POPULATION"]], crs=4326,
                            geometry=gpd.points_from_xy(df.LONGITUDE, df.LATITUDE)).to_crs(EQUAL_AREA)


def build() -> tuple[list[dict], list[dict]]:
    names = us._state_names()
    tracts_by_year = {y: tracts(y) for y in TRACT_FILES}
    points, adjacency = [], []
    for congress, fname in CD_FILES.items():
        cds = gpd.read_file(CD_DIR / fname)
        cd_col = next(c for c in cds.columns if c.startswith("CD") and c.endswith("FP"))
        cds = cds[cds.STATEFP.isin(names) & (cds.STATEFP != "11") & (cds[cd_col] != "ZZ")]
        cds = cds.to_crs(EQUAL_AREA).reset_index(drop=True)

        t = gpd.sjoin(tracts_by_year[us.congress_to_census_year(congress)],
                      cds[["GEOID", "geometry"]], how="inner", predicate="within")
        t["wx"] = t.geometry.x * t.POPULATION
        t["wy"] = t.geometry.y * t.POPULATION
        agg = t.groupby("GEOID")[["POPULATION", "wx", "wy"]].sum()

        xs, ys, pops = [], [], []
        for _, d in cds.iterrows():
            if d.GEOID in agg.index and agg.at[d.GEOID, "POPULATION"] > 0:
                a = agg.loc[d.GEOID]
                xs.append(a.wx / a.POPULATION)
                ys.append(a.wy / a.POPULATION)
                pops.append(int(a.POPULATION))
            else:  # no tract center inside (never expected): fall back to a point on the shape
                p = d.geometry.representative_point()
                xs.append(p.x)
                ys.append(p.y)
                pops.append(0)
        ll = gpd.GeoSeries(gpd.points_from_xy(xs, ys), crs=EQUAL_AREA).to_crs(4326)
        for i, d in cds.iterrows():
            points.append({"congress": congress, "state_fips": d.STATEFP, "state": names[d.STATEFP][0],
                           "cd": d[cd_col], "lon": round(ll.iloc[i].x, 6), "lat": round(ll.iloc[i].y, 6),
                           "tract_pop": pops[i]})

        for fips, grp in cds.groupby("STATEFP"):
            grp = grp.sort_values(cd_col)
            rows = list(grp.itertuples())
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    if not a.geometry.intersects(b.geometry):
                        continue
                    shared = a.geometry.boundary.intersection(b.geometry.boundary).length / 1000
                    if shared >= MIN_SHARED_KM:
                        adjacency.append({"congress": congress, "state": names[fips][0],
                                          "cd_a": getattr(a, cd_col), "cd_b": getattr(b, cd_col),
                                          "shared_km": round(shared, 2)})
    return points, adjacency


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    points, adjacency = build()
    write_csv(CD_DIR / "real_district_points_c113_c119.csv", points)
    write_csv(CD_DIR / "real_district_adjacency_c113_c119.csv", adjacency)
    print(f"{len(points)} district points, {len(adjacency)} adjacent pairs")


if __name__ == "__main__":
    main()
