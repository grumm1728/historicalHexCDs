"""Real congressional districts C113-C119: which ones are "metro" (#35).

Reads the Census cartographic-boundary CD files and tract centers of population in
data_raw/congressional_districts/, plus the 2010/2020 urbanized-area boundaries in
data_raw/urbanized_areas/boundaries/, and writes two CSVs next to the CD files:

  real_districts_c113_c119.csv     one row per voting district (50 states; DC and the
                                   territories' delegates are dropped)
  real_metro_counts_c113_c119.csv  one row per (Congress, state): the real-district metro
                                   count under the chosen rule (`real_metro`), the
                                   sensitivity variants, and our model's `metro_seats`
                                   for #37's +/-1 comparison

Chosen rule: a district is metro when at least half its population (2010 or 2020 tract
centers of population, by the census in effect) lives inside an urbanized area of one of
the census's qualifying top-N metros (`metro_seats.qualifying_metros`). Density (state
population / seats / land area) and land share are kept as alternatives. Calibration and
sensitivity: docs/research_real_district_metro.md.

Run:  python scripts/build_real_district_metro.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import metro_seats as ms  # noqa: E402
import urban_seats as us  # noqa: E402

CD_DIR = ROOT / "data_raw" / "congressional_districts"
UA_DIR = ROOT / "data_raw" / "urbanized_areas" / "boundaries"
EQUAL_AREA = 5070  # CONUS Albers; only area *ratios* are taken, so AK/HI distortion cancels

# Congress -> Census CD file. C117 reuses the 116th file: the Census Bureau never published
# North Carolina's 2019 remedial plan (used for the 2020 election), so NC C117 is the 2016
# plan and is flagged `nc_c117_proxy` (every other state's 117th map equals its 116th).
CD_FILES = {
    113: "cb_2013_us_cd113_500k.zip",
    114: "cb_2014_us_cd114_500k.zip",
    115: "cb_2016_us_cd115_500k.zip",
    116: "cb_2018_us_cd116_500k.zip",
    117: "cb_2020_us_cd116_500k.zip",
    118: "cb_2022_us_cd118_500k.zip",
    119: "cb_2024_us_cd119_500k.zip",
}
TRACT_FILES = {2010: "CenPop2010_Mean_TR.txt", 2020: "CenPop2020_Mean_TR.txt"}
UA_FILES = {2010: ("cb_2013_us_ua10_500k.zip", "UACE10"),
            2020: ("cb_2020_us_ua20_corrected_500k.zip", "UACE20")}

METRO_POP_FRAC_MIN = 0.5                     # chosen rule
POP_FRAC_SWEEP = (0.3, 0.4, 0.6, 0.7)        # sensitivity of the chosen rule
LAND_FRAC_MIN = 0.5                          # alternative: half the district's land
DENSITY_SWEEP = (250, 500, 750, 1000, 1500)  # alternative: people per km^2 of land


def qualifying_ua_codes(census_year: int) -> dict[str, str]:
    """UA code -> metro name for every area in the census's top-N metros (metro_seats)."""
    code_of: dict[tuple[str, str], str] = {}
    abbr = ms._abbr_by_fips()
    for r in ms._ua_rows(census_year):
        st = abbr.get(r["state_fips"].zfill(2), r["state_fips"])
        code_of[(ms._short_name(r["ua_name"]), st)] = r["ua_code"].zfill(5)
    return {code_of[(p.name, p.st)]: metro.name
            for metro in ms.qualifying_metros(census_year) for p in metro.portions}


def metro_geometries(census_year: int) -> dict[str, object]:
    """Metro name -> union of its qualifying UA polygons (EPSG:5070)."""
    fname, code_col = UA_FILES[census_year]
    ua = gpd.read_file(UA_DIR / fname).to_crs(EQUAL_AREA)
    codes = qualifying_ua_codes(census_year)
    ua = ua[ua[code_col].isin(codes)]
    missing = set(codes) - set(ua[code_col])
    if missing:
        raise RuntimeError(f"{census_year}: qualifying UA codes missing from boundaries: {sorted(missing)}")
    ua = ua.assign(metro=ua[code_col].map(codes))
    return {name: unary_union(list(g.geometry)) for name, g in ua.groupby("metro")}


def tract_points(census_year: int, metros: dict[str, object]) -> gpd.GeoDataFrame:
    """Tract centers of population (EPSG:5070) with the qualifying metro each falls in."""
    df = pd.read_csv(CD_DIR / TRACT_FILES[census_year], dtype={"STATEFP": str}, encoding="utf-8-sig")
    pts = gpd.GeoDataFrame(df[["POPULATION"]], crs=4326,
                           geometry=gpd.points_from_xy(df.LONGITUDE, df.LATITUDE)).to_crs(EQUAL_AREA)
    zones = gpd.GeoDataFrame({"metro": list(metros)}, geometry=list(metros.values()), crs=EQUAL_AREA)
    hit = gpd.sjoin(pts, zones, how="left", predicate="within")
    return hit[~hit.index.duplicated()][["POPULATION", "metro", "geometry"]]


def district_rows() -> list[dict]:
    names = us._state_names()
    metros_by_year = {y: metro_geometries(y) for y in UA_FILES}
    tracts_by_year = {y: tract_points(y, metros_by_year[y]) for y in UA_FILES}
    rows = []
    for congress, fname in CD_FILES.items():
        census_year = us.congress_to_census_year(congress)
        metros = metros_by_year[census_year]
        cds = gpd.read_file(CD_DIR / fname)
        cd_col = next(c for c in cds.columns if c.startswith("CD") and c.endswith("FP"))
        cds = cds[cds.STATEFP.isin(names) & (cds.STATEFP != "11") & (cds[cd_col] != "ZZ")].to_crs(EQUAL_AREA)
        seats = cds.groupby("STATEFP").size()

        t = gpd.sjoin(tracts_by_year[census_year], cds[["GEOID", "geometry"]], how="inner", predicate="within")
        tract_pop = t.groupby("GEOID").POPULATION.sum()
        metro_pop = t[t.metro.notna()].groupby(["GEOID", "metro"]).POPULATION.sum()

        for _, d in cds.sort_values(["STATEFP", cd_col]).iterrows():
            fips = d.STATEFP
            ideal = us._state_counts(fips, congress)[0] / seats[fips]
            aland = d.ALAND / 1e6
            land_frac = sum(d.geometry.intersection(g).area for g in metros.values()
                            if g.intersects(d.geometry)) / d.geometry.area
            tp = int(tract_pop.get(d.GEOID, 0))
            mine = metro_pop[d.GEOID] if d.GEOID in metro_pop.index.get_level_values(0) else pd.Series(dtype=int)
            pop_frac = mine.sum() / tp if tp else 0.0
            rows.append({
                "congress": congress,
                "state_fips": fips,
                "state": names[fips][0],
                "cd": d[cd_col],
                "seats": int(seats[fips]),
                "aland_km2": round(aland, 2),
                "ideal_pop": round(ideal),
                "tract_pop": tp,
                "density_per_km2": round(ideal / aland, 1),
                "metro_land_frac": round(min(land_frac, 1.0), 4),
                "metro_pop_frac": round(pop_frac, 4),
                "metro_name": mine.idxmax() if len(mine) else "",
                "is_metro": int(pop_frac >= METRO_POP_FRAC_MIN),
                "nc_c117_proxy": int(congress == 117 and fips == "37"),
            })
    return rows


def count_rows(rows: list[dict]) -> list[dict]:
    out: dict[tuple[int, str], dict] = {}
    for r in rows:
        c = out.setdefault((r["congress"], r["state_fips"]), {
            "congress": r["congress"], "state_fips": r["state_fips"], "state": r["state"],
            "seats": r["seats"],
            "model_metro_seats": ms.metro_seats(r["state_fips"], r["congress"]),
            "real_metro": 0,
            **{f"real_metro_pop{round(f * 100)}": 0 for f in POP_FRAC_SWEEP},
            "real_metro_land50": 0,
            **{f"real_metro_d{t}": 0 for t in DENSITY_SWEEP},
            "nc_c117_proxy": r["nc_c117_proxy"],
        })
        c["real_metro"] += r["is_metro"]
        for f in POP_FRAC_SWEEP:
            c[f"real_metro_pop{round(f * 100)}"] += int(r["metro_pop_frac"] >= f)
        c["real_metro_land50"] += int(r["metro_land_frac"] >= LAND_FRAC_MIN)
        for t in DENSITY_SWEEP:
            c[f"real_metro_d{t}"] += int(r["density_per_km2"] >= t)
    return list(out.values())


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = district_rows()
    write_csv(CD_DIR / "real_districts_c113_c119.csv", rows)
    counts = count_rows(rows)
    write_csv(CD_DIR / "real_metro_counts_c113_c119.csv", counts)
    print(f"{len(rows)} districts, {len(counts)} state-Congress rows")


if __name__ == "__main__":
    main()
