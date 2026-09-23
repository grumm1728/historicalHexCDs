"""Measure the 13 km urbanized-area linking rule and a boundary-free substitute (#34).

Decision 3 (#33) links urbanized areas whose *boundaries* are within 13 km
(single linkage). Digital UA boundaries exist only from 1990 on, so for
1950-1980 we need a substitute computable from published attributes. This
script compares, for every census with boundaries (1990/2000/2010/2020):

  boundary gap  = min distance between the two UA polygons (EPSG:5070, km)
  substitute    = center distance - (r_a + r_b),  r = sqrt(land_area / pi)

with two choices of "center":
  intpt  = the Census internal point of the UA (1990 STF1C / gazetteers /
           polygon representative point for 2000)
  city   = the first-named central city's coordinates from the CESTA
           city file (data_raw/cities/1790-2010_MASTER.csv) -- the only
           center available for 1950-1980 without an NHGIS extract.

It reports the four decision-3 test cases under each rule, the pair-level
agreement (links that the boundary rule makes vs the substitute) at 13 km,
the substitute threshold that best reproduces the boundary links, and the
merges produced by candidate large-area rules (both ends >= 500,000):
boundary gap <= 5 km, sub_intpt <= 25 km, first-named-city distance <= 100 km.
Runtime ~2 min (polygon distances).

Usage: python scripts/diag_ua_linking.py
"""
from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw" / "urbanized_areas"
BND = RAW / "boundaries"
LINK_KM = 13.0
CANDIDATE_KM = 60.0  # only pairs with boundary gap below this are examined

TESTS = [  # (label, first-named city of A, of B, must_link)
    ("Bay Area: San Francisco + San Jose", "San Francisco", "San Jose", True),
    ("LA + Riverside", "Los Angeles", "Riverside", True),
    ("Chicago + Milwaukee", "Chicago", "Milwaukee", False),
    ("New York + Philadelphia", "New York", "Philadelphia", False),
]



def load_polygons(year: int) -> gpd.GeoDataFrame:
    if year == 1990:
        g = gpd.read_file(f"zip://{BND / 'ua99_d90_shp.zip'}").set_crs(4269)
        g = g.rename(columns={"UA": "code"})
    elif year == 2000:
        g = gpd.read_file(f"zip://{BND / 'ua99_d00_shp.zip'}").set_crs(4269)
        g = g.rename(columns={"UA": "code"})
    elif year == 2010:
        g = gpd.read_file(f"zip://{BND / 'cb_2013_us_ua10_500k.zip'}").rename(columns={"UACE10": "code"})
    else:
        g = gpd.read_file(f"zip://{BND / 'cb_2020_us_ua20_corrected_500k.zip'}").rename(columns={"UACE20": "code"})
    g = g[["code", "geometry"]].dissolve(by="code").reset_index()
    return g.to_crs(5070)


def first_city(name: str) -> tuple[str, str]:
    """'San Francisco--Oakland, CA' -> ('San Francisco', 'CA')."""
    city_part, _, st_part = name.rpartition(", ")
    city = city_part.split("--")[0].strip()
    st = st_part.split("--")[0].strip()[:2]
    return city, st


def city_lookup() -> dict[tuple[str, str], tuple[float, float]]:
    c = pd.read_csv(ROOT / "data_raw" / "cities" / "1790-2010_MASTER.csv", encoding="latin-1")
    out = {}
    for _, r in c.iterrows():
        lat = r.LAT if pd.notna(r.LAT) else r.LAT_BING
        lon = r.LON if pd.notna(r.LON) else r.LON_BING
        out[(str(r.City).strip(), str(r.ST).strip())] = (lon, lat)
    return out


def project(lon, lat):
    s = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4269).to_crs(5070)
    return s.x.values, s.y.values


def year_table(year: int, portions: pd.DataFrame, cities) -> pd.DataFrame:
    p = portions[portions.year == year]
    ua = p.groupby("ua_code").agg(ua_name=("ua_name", "first"), pop=("total_pop", "first"),
                                  land=("total_land_sqkm", "first")).reset_index()
    # UA-level internal point: population-weighted mean of the portion points
    # (== the UA point for single-state areas; 1990 uses the part internal points).
    w = p.assign(wx=p.lon * p.portion_pop, wy=p.lat * p.portion_pop).groupby("ua_code")
    pts = (w.wx.sum() / w.portion_pop.sum()).rename("lon").to_frame().join(
        (w.wy.sum() / w.portion_pop.sum()).rename("lat"))
    ua = ua.merge(pts, left_on="ua_code", right_index=True)
    ua["ix"], ua["iy"] = project(ua.lon.values, ua.lat.values)
    cc = [cities.get(first_city(n)) for n in ua.ua_name]
    ua["city_ok"] = [c is not None for c in cc]
    cx, cy = project([c[0] if c else 0 for c in cc], [c[1] if c else 0 for c in cc])
    ua["cx"], ua["cy"] = np.where(ua.city_ok, cx, ua.ix), np.where(ua.city_ok, cy, ua.iy)
    ua["r"] = np.sqrt(ua.land / math.pi)  # km
    ua["city"] = [first_city(n)[0] for n in ua.ua_name]
    return ua


def pair_table(ua: pd.DataFrame, polys: gpd.GeoDataFrame) -> pd.DataFrame:
    g = polys.set_index("code").reindex(ua.ua_code)
    geoms = g.geometry.values
    sidx = gpd.GeoSeries(geoms).sindex
    rows = []
    for i, geom in enumerate(geoms):
        if geom is None:
            continue
        for j in sidx.query(geom.buffer(CANDIDATE_KM * 1000)):
            if j <= i or geoms[j] is None:
                continue
            gap = geom.distance(geoms[j]) / 1000
            a, b = ua.iloc[i], ua.iloc[j]
            di = math.hypot(a.ix - b.ix, a.iy - b.iy) / 1000
            dc = math.hypot(a.cx - b.cx, a.cy - b.cy) / 1000
            rows.append(dict(a=a.ua_name, b=b.ua_name, ia=i, ib=j, gap=gap,
                             sub_intpt=di - a.r - b.r, sub_city=dc - a.r - b.r))
    return pd.DataFrame(rows)


def clusters(n: int, edges) -> list[int]:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    return [find(i) for i in range(n)]


def main() -> None:
    portions = pd.read_csv(RAW / "ua_state_portions.csv", dtype={"ua_code": str, "state_fips": str})
    cities = city_lookup()
    for year in (1990, 2000, 2010, 2020):
        ua = year_table(year, portions, cities)
        polys = load_polygons(year)
        pairs = pair_table(ua, polys)
        print(f"\n=== {year}: {len(ua)} areas, {len(pairs)} candidate pairs "
              f"(city coords found for {ua.city_ok.sum()}/{len(ua)})")
        truth = pairs.gap <= LINK_KM
        for col in ("sub_intpt", "sub_city"):
            best = None
            for t in np.arange(-40, 40.5, 0.5):
                pred = pairs[col] <= t
                err = int((pred != truth).sum())
                if best is None or err < best[1]:
                    best = (t, err)
            pred13 = pairs[col] <= LINK_KM
            print(f"  {col}: at 13 km -> {int((pred13 & truth).sum())} agree-link, "
                  f"{int((pred13 & ~truth).sum())} extra, {int((~pred13 & truth).sum())} missed "
                  f"(boundary links: {int(truth.sum())}); best threshold {best[0]:+.1f} km "
                  f"with {best[1]} pair disagreements")
        for label, ca, cb, must in TESTS:
            ia = ua.index[ua.city == ca].tolist()
            ib = ua.index[ua.city == cb].tolist()
            if not ia or not ib:
                print(f"  {label}: area not found")
                continue
            ia, ib = ia[0], ib[0]
            res = []
            for col, thr in (("gap", LINK_KM), ("sub_intpt", LINK_KM), ("sub_city", LINK_KM)):
                cl = clusters(len(ua), pairs.loc[pairs[col] <= thr, ["ia", "ib"]].values)
                res.append("LINK" if cl[ia] == cl[ib] else "sep")
            direct = pairs[((pairs.ia == min(ia, ib)) & (pairs.ib == max(ia, ib)))]
            d = (f"direct gap {direct.gap.iloc[0]:.1f} km, sub_intpt {direct.sub_intpt.iloc[0]:.1f}, "
                 f"sub_city {direct.sub_city.iloc[0]:.1f}") if len(direct) else "direct gap > 60 km"
            ok = "OK" if (res[0] == "LINK") == must else "FAIL"
            print(f"  {label}: boundary={res[0]} ({ok} vs decision 3), substitute intpt={res[1]}, "
                  f"city={res[2]}; {d}")
        # Candidate rules restricted to large areas (both ends >= min_pop; smaller
        # areas neither link nor relay a chain). "city" = first-named-city distance.
        pairs["city_dist"] = [math.hypot(ua.cx[a] - ua.cx[b], ua.cy[a] - ua.cy[b]) / 1000
                              for a, b in zip(pairs.ia, pairs.ib)]
        for col, thr, min_pop in (("gap", 13, 50_000), ("gap", 5, 500_000),
                                  ("sub_intpt", 25, 500_000), ("city_dist", 100, 500_000)):
            big = (ua["pop"] >= min_pop).values
            e = pairs[(pairs[col] <= thr) & big[pairs.ia] & big[pairs.ib]]
            cl = clusters(len(ua), e[["ia", "ib"]].values)
            verdict = []
            for label, ca, cb, must in TESTS:
                ia, ib = ua.index[ua.city == ca][0], ua.index[ua.city == cb][0]
                verdict.append("ok" if (cl[ia] == cl[ib]) == must else "FAIL")
            groups = ua.assign(cl=cl).groupby("cl").filter(lambda x: len(x) > 1)
            merged = groups.groupby("cl").city.apply(lambda s: "+".join(sorted(s))).tolist()
            print(f"  rule {col}<={thr} among >= {min_pop:,}: tests {'/'.join(verdict)}; "
                  f"merges: {'; '.join(sorted(merged))}")
        # Largest boundary-linked chains, for the research note.
        cl = clusters(len(ua), pairs.loc[pairs.gap <= LINK_KM, ["ia", "ib"]].values)
        ua["cl"] = cl
        top = ua.groupby("cl").agg(pop=("pop", "sum"), n=("ua_code", "size"),
                                   names=("city", lambda s: " + ".join(s[:6]))).nlargest(8, "pop")
        for _, r in top.iterrows():
            print(f"    chain {r['pop']:>11,} ({r.n} areas): {r.names}")
        worst = pairs[(pairs.gap <= LINK_KM) != (pairs.sub_city <= LINK_KM)].copy()
        worst["delta"] = worst.sub_city - worst.gap
        for _, r in worst.reindex(worst.delta.abs().sort_values(ascending=False).index).head(6).iterrows():
            print(f"    disagree (city): {r.a} | {r.b}: gap {r.gap:.1f}, sub_city {r.sub_city:.1f}")


if __name__ == "__main__":
    main()
