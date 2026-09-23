"""Normalize official Census urbanized-area files into one tidy CSV (issue #34).

Reads the raw files under data_raw/urbanized_areas/ (see its README.txt) and writes
data_raw/urbanized_areas/ua_state_portions.csv with one row per
(census year, urbanized area, state portion):

    year, ua_code, ua_name, state_fips, portion_pop, total_pop,
    portion_land_sqkm, total_land_sqkm, lon, lat, loc_source

Coverage per year (what the raw inputs allow):
  1950, 1960  UA totals transcribed from the published rank tables, state parts
              for the 17 principal multi-state areas transcribed from the state
              volumes (published_tables/); point = first-named central city
              (CESTA coordinates) for that city's own state portion only.
  1970, 1980  NHGIS extract (not yet acquired; see README) -- skipped if absent.
  1990        STF 1C summary levels 400 (UA) / 410 (UA--State part), with the
              Bureau's own internal points for both the UA and each state part.
  2000        ua2k.txt + st2kua.txt (as tabulated in SF1); location = representative
              point of (UA polygon ∩ state polygon).
  2010        ua_list_ua.txt + ua_st_list_ua.txt; UA internal point from the
              2010 gazetteer, part location from polygon ∩ state.
  2020        2020_Census_ua_list_all.xlsx + ..._st_list_all.xlsx, filtered to
              urban areas with total population >= 50,000 (the 2020 large-area
              tier; see README); UA internal point from the 2023 gazetteer.

Single-state areas use the UA's own internal point for their one portion.

Usage: python scripts/normalize_urbanized_areas.py
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw" / "urbanized_areas"
REF = RAW / "census_ua_reference"
BND = RAW / "boundaries"
OUT = RAW / "ua_state_portions.csv"

SQMI_TO_SQKM = 2.589988110336
LARGE_2020 = 50_000

COLUMNS = [
    "year", "ua_code", "ua_name", "state_fips", "portion_pop", "total_pop",
    "portion_land_sqkm", "total_land_sqkm", "lon", "lat", "loc_source", "part_note",
]


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="latin-1").splitlines()


# --------------------------------------------------------------------------- 1990
def load_1990() -> list[dict]:
    import pyogrio

    z = RAW / "stf1c_1990" / "stf1c0us.dbf.zip"
    df = pyogrio.read_dataframe(
        f"/vsizip/{z.as_posix()}/stf1c0us.dbf", read_geometry=False,
        columns=["SUMLEV", "GEOCOMP", "STATEFP", "URBAREA", "ANPSADPI",
                 "AREALAND", "INTPTLAT", "INTPTLNG", "P0010001"],
    )
    df = df[df.GEOCOMP == "00"]

    def ll(v: str) -> float:  # "+40746573" -> 40.746573 (6 implied decimals)
        return int(v) / 1e6

    ua = df[df.SUMLEV == "400"].set_index("URBAREA")
    parts = df[df.SUMLEV == "410"]
    rows = []
    for _, p in parts.iterrows():
        u = ua.loc[p.URBAREA]
        rows.append(dict(
            year=1990, ua_code=p.URBAREA, ua_name=u.ANPSADPI, state_fips=p.STATEFP,
            portion_pop=int(p.P0010001), total_pop=int(u.P0010001),
            # AREALAND is km^2 with 3 implied decimals (NY UA 7683.055 km^2 = 2,966 sq mi)
            portion_land_sqkm=int(p.AREALAND) / 1000, total_land_sqkm=int(u.AREALAND) / 1000,
            lon=ll(p.INTPTLNG), lat=ll(p.INTPTLAT), loc_source="stf1c_intpt_part",
        ))
    return rows


# --------------------------------------------------------------------------- 2000
# The Aug/Nov-2002 corrected lists (ua_natl_corr.txt, ua_state_corr.txt,
# ua_state_100302.txt) are NOT what Census 2000 SF1 tabulated ("official Census 2000
# urban/rural data do not contain these changes"), so the tabulated originals are used.
UA2000_NATL, UA2000_STATE = "ua2k.txt", "st2kua.txt"


def load_2000() -> list[dict]:
    natl = {}
    for ln in _lines(REF / UA2000_NATL):
        m = re.match(r"^(\d{5})\s+(.+?)\s{2,}(\d+)\s+(\d+)\s+[\d.]+\s*$", ln)
        if m:
            natl[m[1]] = (m[2].strip(), int(m[3]), int(m[4]) / 1e6)
    rows = []
    for ln in _lines(REF / UA2000_STATE):
        m = re.match(r"^(\d\d) (\d{5}) (.+?)\s{2,}(\d+)(\(PT\))?\s+(\d+)\s+[\d.]+\s*$", ln)
        if not m:
            continue
        name, tot, tot_area = natl[m[2]]
        rows.append(dict(
            year=2000, ua_code=m[2], ua_name=name, state_fips=m[1],
            portion_pop=int(m[4]), total_pop=tot,
            portion_land_sqkm=int(m[6]) / 1e6, total_land_sqkm=tot_area,
        ))
    return rows


# --------------------------------------------------------------------------- 2010
_NUM = r"\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)"


def load_2010() -> list[dict]:
    natl = {}
    for ln in _lines(REF / "ua_list_ua.txt"):
        m = re.match(r"^(\d{5})\s+(.+?)\s{2,}(\d+)" + _NUM[len(r"\s+(\d+)"):], ln)
        if m:
            natl[m[1]] = (m[2].strip(), int(m[3]), int(m[5]) / 1e6)
    rows = []
    for ln in _lines(REF / "ua_st_list_ua.txt"):
        m = re.match(r"^(\d{5})\s+(.+?)\s{2,}(\d\d)\s+(P?)" + _NUM, ln)
        if not m:
            continue
        name, tot, tot_area = natl[m[1]]
        rows.append(dict(
            year=2010, ua_code=m[1], ua_name=name, state_fips=m[3],
            portion_pop=int(m[5]), total_pop=tot,
            portion_land_sqkm=int(m[7]) / 1e6, total_land_sqkm=tot_area,
        ))
    return rows


# --------------------------------------------------------------------------- 2020
def load_2020() -> list[dict]:
    natl = pd.read_excel(REF / "2020_Census_ua_list_all.xlsx", dtype={"UACE": str})
    natl["UACE"] = natl.UACE.str.zfill(5)
    natl = natl.set_index("UACE")
    st = pd.read_excel(REF / "2020_Census_ua_st_list_all.xlsx", header=None, dtype=str)
    st = st[st[0].str.fullmatch(r"\d+", na=False)]
    rows = []
    for _, r in st.iterrows():
        code = r[0].zfill(5)
        u = natl.loc[code]
        if int(u.POP) < LARGE_2020:
            continue
        rows.append(dict(
            year=2020, ua_code=code, ua_name=u.NAME, state_fips=r[2].zfill(2),
            portion_pop=int(r[4]), total_pop=int(u.POP),
            portion_land_sqkm=int(r[6]) / 1e6, total_land_sqkm=int(u.AREALAND) / 1e6,
        ))
    return rows


# ------------------------------------------------------------------ transcribed
PUB = RAW / "published_tables"

# Old-style (1950/1960 publication) state abbreviations -> FIPS. Longest first so
# "W. Va." is not read as "Va." and "N. Mex." not as something shorter.
OLD_ABBR = {
    "N.Mex.": "35", "N.Dak.": "38", "S.Dak.": "46", "W.Va.": "54", "D.C.": "11",
    "N.H.": "33", "N.J.": "34", "N.Y.": "36", "N.C.": "37", "R.I.": "44", "S.C.": "45",
    "Ala.": "01", "Ariz.": "04", "Ark.": "05", "Calif.": "06", "Colo.": "08",
    "Conn.": "09", "Del.": "10", "Fla.": "12", "Ga.": "13", "Hawaii": "15", "Idaho": "16",
    "Ill.": "17", "Ind.": "18", "Iowa": "19", "Kans.": "20", "Ky.": "21", "La.": "22",
    "Maine": "23", "Md.": "24", "Mass.": "25", "Mich.": "26", "Minn.": "27", "Miss.": "28",
    "Mo.": "29", "Mont.": "30", "Nebr.": "31", "Nev.": "32", "Ohio": "39", "Okla.": "40",
    "Oreg.": "41", "Pa.": "42", "Tenn.": "47", "Texas": "48", "Utah": "49", "Vt.": "50",
    "Va.": "51", "Wash.": "53", "Wis.": "55", "Wyo.": "56",
}
POSTAL = {"NY": "36", "NJ": "34", "IL": "17", "IN": "18", "PA": "42", "DC": "11",
          "MD": "24", "VA": "51", "MO": "29", "KY": "21", "OH": "39", "KS": "20",
          "MA": "25", "RI": "44", "WA": "53", "OR": "41", "CT": "09", "DE": "10",
          "NH": "33", "WV": "54"}
SPECIAL_STATES = {  # names that spell the states out
    "New York-Northeastern New Jersey": ["36", "34"],
    "Chicago-Northwestern Indiana": ["17", "18"],
}


def name_states(name: str) -> list[str]:
    """States named in a 1950/1960 UA title, in order of appearance."""
    if name in SPECIAL_STATES:
        return SPECIAL_STATES[name]
    tail = name.split(", ", 1)[1] if ", " in name else name
    t = tail.replace(" ", "")
    found = []
    for ab in sorted(OLD_ABBR, key=len, reverse=True):
        key = ab.replace(" ", "")
        while key in t:
            i = t.index(key)
            found.append((i, OLD_ABBR[ab]))
            t = t[:i] + "#" * len(key) + t[i + len(key):]
    return [f for _, f in sorted(found)]


def load_transcribed(year: int) -> list[dict]:
    """1950/1960 published UA totals + transcribed state parts (see README).

    Parts come from published_tables/ua_state_parts_1950_1960.csv (keyed on the
    1960 title). A UA whose title names several states but has no transcribed
    parts is emitted as ONE row for its first-named state with
    part_note='multistate_unsplit'. 1950 titles often omit the second state
    (e.g. "Chicago, Ill."), so 1950 rows are matched to the 1960 parts table
    through PARTS_1950_ALIAS.
    """
    p = PUB / f"ua_{year}_published.csv"
    if not p.exists():
        return []
    parts = pd.read_csv(PUB / "ua_state_parts_1950_1960.csv")
    col = f"pop_{year}"
    by_name = {n: g for n, g in parts.groupby("ua_name_1960")}
    alias = PARTS_1950_ALIAS if year == 1950 else {}
    rows = []
    for r in csv.DictReader(p.open(encoding="utf-8")):
        name, tot = r["ua_name"], int(r["population"])
        key = alias.get(name, name)
        base = dict(year=year, ua_code="", ua_name=name, total_pop=tot,
                    portion_land_sqkm="", total_land_sqkm="", lon="", lat="", loc_source="")
        if key in by_name:
            for _, pr in by_name[key].iterrows():
                if int(pr[col]) == 0:
                    continue  # part not yet in the area this year
                rows.append(dict(base, state_fips=POSTAL[pr.state_abbr],
                                 portion_pop=int(pr[col]), part_note=pr.method))
            continue
        states = name_states(name)
        note = "multistate_unsplit" if len(states) > 1 else ""
        rows.append(dict(base, state_fips=states[0] if states else "",
                         portion_pop=tot, part_note=note))
    return rows


PARTS_1950_ALIAS = {
    "Chicago, Ill.": "Chicago-Northwestern Indiana",
    "Philadelphia, Pa.": "Philadelphia, Pa.-N.J.",
    "Washington, D. C.": "Washington, D.C.-Md.-Va.",
    "St. Louis, Mo.": "St. Louis, Mo.-Ill.",
    "Cincinnati, Ohio": "Cincinnati, Ohio-Ky.",
    "Kansas City, Mo.": "Kansas City, Mo.-Kans.",
    "Providence, R. I.": "Providence-Pawtucket, R.I.-Mass.",
    "Portland, Oreg.": "Portland, Oreg.-Wash.",
    "Louisville, Ky.": "Louisville, Ky.-Ind.",
    "Springfield-Holyoke, Mass.": "Springfield-Chicopee-Holyoke, Mass.-Conn.",
    "Wilmington, Del.": "Wilmington, Del.-N.J.",
    "Trenton, N. J.": "Trenton, N.J.-Pa.",
    "Lawrence, Mass.": "Lawrence-Haverhill, Mass.-N.H.",
    "Huntington, W. Va.-Ashland, Ky.": "Huntington-Ashland, W.Va.-Ky.-Ohio",
    "Fall River, Mass.": "Fall River, Mass.-R.I.",
    "St. Joseph, Mo.": "St. Joseph, Mo.-Kans.",
    "New York-Northeastern New Jersey": "New York-Northeastern New Jersey",
}


def add_transcribed_locations(rows: list[dict]) -> None:
    """1950/1960: first-named central city (CESTA coords) for the portion in
    that city's state; other portions are left without a point (see README)."""
    c = pd.read_csv(ROOT / "data_raw" / "cities" / "1790-2010_MASTER.csv", encoding="latin-1")
    look = {}
    for _, r in c.iterrows():
        lat = r.LAT if pd.notna(r.LAT) else r.LAT_BING
        lon = r.LON if pd.notna(r.LON) else r.LON_BING
        look[(str(r.City).strip(), str(r.ST).strip())] = (lon, lat)
    st_postal = {f: a for a, f in ABBR2FIPS.items()}
    for r in rows:
        if r["year"] not in (1950, 1960) or not r["state_fips"]:
            continue
        st = st_postal.get(r["state_fips"], "")
        head = r["ua_name"].split(",")[0].strip()  # "Wilkes-Barre" must stay whole
        pt = look.get((head, st)) or look.get((head.split("-")[0].strip(), st))
        if pt:
            r["lon"], r["lat"] = round(float(pt[0]), 6), round(float(pt[1]), 6)
            r["loc_source"] = "cesta_first_named_city"


ABBR2FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56", "PR": "72",
}


# --------------------------------------------------------------------- locations
def _gaz_points(zip_name: str) -> dict[str, tuple[float, float]]:
    with zipfile.ZipFile(REF / zip_name) as z:
        txt = z.read(z.namelist()[0]).decode("latin-1")
    df = pd.read_csv(io.StringIO(txt), sep="\t", dtype={"GEOID": str})
    df.columns = [c.strip() for c in df.columns]
    return {g: (float(lo), float(la)) for g, lo, la in zip(df.GEOID, df.INTPTLONG, df.INTPTLAT)}


def _polygons(year: int):
    import geopandas as gpd

    if year == 2000:
        g = gpd.read_file(f"zip://{BND / 'ua99_d00_shp.zip'}").set_crs(4269)
        # No LSAD filter (keeps UCs too) so either the original or the corrected 2000
        # list resolves: the corrections promoted e.g. Hanford, CA from UC to UA.
        g = g.dissolve(by="UA").reset_index().rename(columns={"UA": "code"})
    elif year == 2010:
        g = gpd.read_file(f"zip://{BND / 'cb_2013_us_ua10_500k.zip'}").rename(columns={"UACE10": "code"})
    else:
        g = gpd.read_file(f"zip://{BND / 'cb_2020_us_ua20_corrected_500k.zip'}").rename(columns={"UACE20": "code"})
    return g[["code", "geometry"]].set_index("code")


def add_locations(rows: list[dict]) -> None:
    import geopandas as gpd

    states = gpd.read_file(f"zip://{BND / 'cb_2020_us_state_500k.zip'}").set_index("STATEFP")
    gaz = {2010: _gaz_points("Gaz_ua.zip"), 2020: _gaz_points("2023_Gaz_ua_national.zip")}
    multi = {}
    for r in rows:
        multi.setdefault((r["year"], r["ua_code"]), []).append(r)
    polys = {}
    for (year, code), rs in multi.items():
        if year not in (2000, 2010, 2020):
            continue
        if len(rs) == 1 and year in gaz and code in gaz[year]:
            rs[0]["lon"], rs[0]["lat"] = gaz[year][code]
            rs[0]["loc_source"] = "gazetteer_intpt"
            continue
        if year not in polys:
            polys[year] = _polygons(year)
        ua_geom = polys[year].loc[code].geometry
        if hasattr(ua_geom, "iloc"):
            ua_geom = ua_geom.iloc[0]
        for r in rs:
            part = ua_geom.intersection(states.loc[r["state_fips"]].geometry) if len(rs) > 1 else ua_geom
            if part.is_empty:  # boundary-generalization slop; fall back to whole UA
                part = ua_geom
            pt = part.representative_point()
            r["lon"], r["lat"] = round(pt.x, 6), round(pt.y, 6)
            r["loc_source"] = "polygon_x_state_reppoint" if len(rs) > 1 else "polygon_reppoint"


def main() -> None:
    rows = []
    rows += load_transcribed(1950)
    rows += load_transcribed(1960)
    rows += load_1990()
    rows += load_2000()
    rows += load_2010()
    rows += load_2020()
    add_locations(rows)
    add_transcribed_locations(rows)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    by_year = {}
    for r in rows:
        y = by_year.setdefault(r["year"], [set(), 0, 0])
        y[0].add(r["ua_code"] or r["ua_name"])
        y[1] += 1
        y[2] += r["portion_pop"]
    for y, (uas, n, pop) in sorted(by_year.items()):
        print(f"{y}: {len(uas)} areas, {n} state portions, portion-pop sum {pop:,}")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
