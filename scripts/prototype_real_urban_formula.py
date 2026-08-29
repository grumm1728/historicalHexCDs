"""PROTOTYPE — THROWAWAY. Wayfinder ticket #24 (map #12).

Real implementations of #16's urban-seat formula and #17's cluster identification,
built to validate #18/#19's city-seeded partitioning against real multi-anchor
states (NY, TX) instead of #18's crude hardcoded fractions.

Deliberately SKIPS composite-outline summing (#23) and the MAINE_IN_MA 0% rule
(#16 decision 7) — neither New York nor Texas is a PREDECESSOR_PARENT parent,
child, or touches Maine, so those rules never fire for this test. Everything
else (rounding, the census->Congress step function, cluster radius/allocation)
is the real decided mechanism.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = 35000.0  # hex circumradius, meters — must match tile_state_pentahexes.R
EARTH = 6378137.0


def lonlat_to_wm(lon: float, lat: float) -> tuple[float, float]:
    return (EARTH * math.radians(lon), EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


# ---------------------------------------------------------------- congress -> census year

def _build_congress_to_census_year() -> dict[int, int]:
    """Reuse the exact apportionment effective_year -> congress_number cutover already
    verified for seats (state_seats_by_apportionment.csv), rather than inventing a new
    timing rule. Verified against two independent real jumps: VA's 1st apportionment
    (effective 1793) lands at Congress 3; GA's 3rd (effective 1813) lands at Congress 13.
    Both match congress_number = (effective_year - 1789)//2 + 1 exactly.
    """
    rows = list(csv.DictReader(open(ROOT / "data_raw" / "seats" / "state_seats_by_apportionment.csv")))
    # one state's timeline is enough; apportionment cycles are national
    labels = {}
    for r in rows:
        if r["state_abbr"] != "NY":
            continue
        label = r["apportionment_label"]
        eff = int(r["effective_year"])
        labels[label] = eff
    # census year N apportionment -> congress at which it takes effect
    mapping: dict[int, int] = {}
    ordinal_re = re.compile(r"(\d+)(st|nd|rd|th)")
    census_by_label = {}
    for label, eff in labels.items():
        if label == "Const.":
            continue
        m = ordinal_re.match(label)
        k = int(m.group(1))
        census_year = 1780 + 10 * k
        congress_at_effect = (eff - 1789) // 2 + 1
        census_by_label[congress_at_effect] = census_year
    return census_by_label  # congress_number (first congress using this census) -> census_year


_CONGRESS_CENSUS_STARTS = _build_congress_to_census_year()  # sparse: congress -> census_year, only at cutover points
_SORTED_CUTOVERS = sorted(_CONGRESS_CENSUS_STARTS)


def congress_to_census_year(congress_number: int) -> int | None:
    """The most recent census whose apportionment is in effect for this Congress.
    Congresses 1-2 (before the 1790 apportionment takes effect at Congress 3) are the
    documented exception: backfilled with the 1790 census per #16 decision 5."""
    if congress_number < _SORTED_CUTOVERS[0]:
        return 1790  # decision 5: backfill C1-C2 with 1790 data
    year = None
    for c in _SORTED_CUTOVERS:
        if c <= congress_number:
            year = _CONGRESS_CENSUS_STARTS[c]
        else:
            break
    return year


assert congress_to_census_year(1) == 1790
assert congress_to_census_year(2) == 1790
assert congress_to_census_year(3) == 1790  # VA's verified jump congress
assert congress_to_census_year(13) == 1810  # GA's verified jump congress


# ---------------------------------------------------------------- urban_share sources

US_STATES = {
    "Alabama", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
    "Florida", "Georgia", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New York", "North Carolina",
    "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
}
STATE_ABBR_TO_NAME = {
    "NY": "New York", "TX": "Texas", "CA": "California",  # extend as needed
}


def _nhgis_urban_share(state_name: str, year: int) -> float | None:
    """1790-1890 via the NHGIS extract (ticket #21/#14). Returns None if the state
    has no recorded population that year (not yet a state / not yet admitted)."""
    import glob
    for f in glob.glob(str(ROOT / "data_raw" / "urbanization" / "nhgis0001_csv" / f"nhgis0001_ds*_{year}_state.csv")):
        cb_path = f.replace(".csv", "_codebook.txt")
        rows = list(csv.DictReader(open(f)))
        match = next((r for r in rows if r["STATE"] == state_name), None)
        if match is None:
            continue
        codebook = open(cb_path, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"Table \d+:\s+(.*?)\n.*?NHGIS code:\s+(\w+)", codebook, re.S):
            name, code = m.group(1).strip(), m.group(2).strip()
            col = code + "001"
            if col not in match:
                continue
            val = int(match[col]) if match[col].strip() not in ("", ".") else 0
            if "Urban" in name:
                urban = val
            elif "Total Population" in name:
                total = val
    try:
        if total <= 0:
            return None
        return urban / total
    except NameError:
        return None


_URPOP_CACHE: dict[int, dict[str, tuple[int, int]]] = {}


def _load_urpop0090() -> dict[int, dict[str, tuple[int, int]]]:
    """Parses urpop0090.txt's 4 blocks (1990/80/70, 1960/50/40, 1930/20/10, 1900),
    each carrying up to 3 decades of (total, urban, rural, %urb, %rur) per state line."""
    if _URPOP_CACHE:
        return _URPOP_CACHE
    text = open(ROOT / "data_raw" / "urbanization" / "urpop0090.txt", encoding="latin-1").read()
    blocks = re.split(r"\n(?=\s+Table 1\.)", text)
    year_header_re = re.compile(r"^\s+(\d{4})\s+(\d{4})", re.M)
    for block in blocks:
        # find the header line with bare 4-digit years separated by whitespace
        m = re.search(r"^(\s+\d{4}\s+\d{4}(?:\s+\d{4}\s+\d{4})*)\s*$", block, re.M)
        if not m:
            continue
        yrs = [int(y) for y in re.findall(r"\d{4}", m.group(1))]
        decade_years = sorted(set(yrs), reverse=True)
        n_decades = len(decade_years)
        for line in block.splitlines():
            lm = re.match(r"^\s{4,8}([A-Za-z][A-Za-z .]+?)\s{2,}([\d,.]+.*)$", line)
            if not lm:
                continue
            name = lm.group(1).strip()
            if name not in US_STATES:
                continue
            nums = re.findall(r"[\d,]+(?:\.\d+)?", lm.group(2))
            # each decade contributes 3 population numbers (total,urban,rural) then 2 percents
            # percents contain a decimal point; population numbers here do not (integers with commas)
            pop_nums = [n for n in nums if "." not in n]
            for i, yr in enumerate(decade_years):
                if i * 3 + 1 >= len(pop_nums):
                    continue
                total = int(pop_nums[i * 3].replace(",", ""))
                urban = int(pop_nums[i * 3 + 1].replace(",", ""))
                _URPOP_CACHE.setdefault(yr, {})[name] = (total, urban)
    return _URPOP_CACHE


_SF1_2000 = None


def _sf1_2000_share(state_name: str) -> float | None:
    global _SF1_2000
    if _SF1_2000 is None:
        d = json.load(open(ROOT / "data_raw" / "urbanization" / "sf1_p002_2000.json"))
        header, rows = d[0], d[1:]
        idx = {c: header.index(c) for c in ("NAME", "P002001", "P002002")}
        _SF1_2000 = {r[idx["NAME"]]: (int(r[idx["P002001"]]), int(r[idx["P002002"]])) for r in rows}
    rec = _SF1_2000.get(state_name)
    if not rec or rec[0] <= 0:
        return None
    return rec[1] / rec[0]


_XLSX_2010_2020 = None


def _xlsx_2010_2020_share(state_name: str, year: int) -> float | None:
    global _XLSX_2010_2020
    if _XLSX_2010_2020 is None:
        import openpyxl
        wb = openpyxl.load_workbook(
            ROOT / "data_raw" / "urbanization" / "State_Urban_Rural_Pop_2020_2010.xlsx", data_only=True
        )
        ws = wb["States"]
        rows = list(ws.iter_rows(values_only=True))
        header = rows[0]
        _XLSX_2010_2020 = {"header": header, "rows": rows[1:]}
    header, rows = _XLSX_2010_2020["header"], _XLSX_2010_2020["rows"]
    name_idx = header.index("STATE NAME")
    pct_idx = header.index(f"{year} PCT URBAN POP")
    for r in rows:
        if r[name_idx] == state_name:
            return float(r[pct_idx]) / 100.0
    return None


def urban_share(state_abbr: str, census_year: int) -> float | None:
    """Real urban_share for a state at a given census year, spliced across all four
    source eras per #16's decision (no cross-era harmonization — raw era-native share)."""
    name = STATE_ABBR_TO_NAME[state_abbr]
    if 1790 <= census_year <= 1890:
        return _nhgis_urban_share(name, census_year)
    if 1900 <= census_year <= 1990:
        table = _load_urpop0090()
        rec = table.get(census_year, {}).get(name)
        if not rec or rec[0] <= 0:
            return None
        return rec[1] / rec[0]
    if census_year == 2000:
        return _sf1_2000_share(name)
    if census_year in (2010, 2020):
        return _xlsx_2010_2020_share(name, census_year)
    raise ValueError(f"no source for census year {census_year}")


def urban_seats(state_abbr: str, congress_number: int, house_seats: int) -> int:
    """#16 decision 1: round(share * seats), clamped [0, seats]."""
    year = congress_to_census_year(congress_number)
    share = urban_share(state_abbr, year)
    if share is None:
        return 0
    n = round(share * house_seats)
    return max(0, min(house_seats, n))


# ---------------------------------------------------------------- #17: real cluster identification

_CESTA_ROWS = None
_STATE_FIPS = {"NY": "36", "TX": "48", "CA": "06"}
_SUBEST2024 = None


def _load_subest2024() -> dict[str, int]:
    """place FIPS (state+place, 7 digits) -> 2020 census-equivalent population
    (ESTIMATESBASE2020, the vintage's April 2020 count per the cities/README note)."""
    global _SUBEST2024
    if _SUBEST2024 is None:
        _SUBEST2024 = {}
        for r in csv.DictReader(open(ROOT / "data_raw" / "cities" / "sub-est2024.csv")):
            if r["SUMLEV"] != "162":  # incorporated place only, avoid county-subdivision dupes
                continue
            key = r["STATE"] + r["PLACE"]
            _SUBEST2024[key] = int(r["ESTIMATESBASE2020"])
    return _SUBEST2024


def _cesta_top_n(state_abbr: str, census_year: int, n: int) -> list[tuple[str, float, float, int]]:
    """Top-N cities by population for a state/census year, per #17 decision 4:
    N = min(5, urban_seats). CESTA (#15) covers 1790-2010; 2020 is extended by joining
    CESTA's coordinates to the real sub-est2024 (#15's own recommended extension) via
    each place's FIPS code, since CESTA has no 2020 population column at all."""
    global _CESTA_ROWS
    if _CESTA_ROWS is None:
        _CESTA_ROWS = list(csv.DictReader(open(ROOT / "data_raw" / "cities" / "1790-2010_MASTER.csv")))

    def coords(r):
        lat, lon = r.get("LAT", "").strip(), r.get("LON", "").strip()
        if not lat or not lon:
            lat, lon = r.get("LAT_BING", "").strip(), r.get("LON_BING", "").strip()
        return (float(lat), float(lon)) if lat and lon else None

    if census_year == 2020:
        pop2020 = _load_subest2024()
        cands = []
        for r in _CESTA_ROWS:
            if r.get("ST") != state_abbr:
                continue
            fips = r.get("STPLFIPS_2010", "").strip()
            if not fips or fips not in pop2020:
                continue
            c = coords(r)
            if c is None:
                continue
            lat, lon = c
            cands.append((r["City"], lon, lat, pop2020[fips]))
        cands.sort(key=lambda c: -c[3])
        return cands[:n]

    year_col = str(census_year)
    cands = []
    for r in _CESTA_ROWS:
        if r.get("ST") != state_abbr:
            continue
        v = r.get(year_col, "").strip().replace(",", "")
        if not v or v in ("0", "0.0"):
            continue
        try:
            pop = int(float(v))
        except ValueError:
            continue
        c = coords(r)
        if c is None:
            continue
        lat, lon = c
        cands.append((r["City"], lon, lat, pop))
    cands.sort(key=lambda c: -c[3])
    return cands[:n]


def real_anchors_for(
    state_abbr: str, congress_number: int, house_seats: int, layout_rec: dict
) -> list[tuple[str, tuple[float, float], int]]:
    """The full #16+#17 pipeline for one state/Congress: real urban_seats, real top-N
    candidates, real 2.9R hex-space clustering, real per-cluster seat allocation.

    `layout_rec` must be the state's LIVE layout dict from this run's own
    compute_scaled_layout call (anchor/scale/displacement) — per the #20 lesson,
    recomputing compute_scaled_layout standalone (or trusting a separately-read file
    that could go stale) gives the wrong position; capturing it live during the actual
    run, exactly as #18's own anchors_in_hex_space did, is the reliable source.

    Returns (name, hexspace_xy, cluster_seats) tuples, largest cluster first.
    """
    n_urban = urban_seats(state_abbr, congress_number, house_seats)
    if n_urban <= 0:
        return []
    census_year = congress_to_census_year(congress_number)

    ax, ay = layout_rec["anchor"]
    s = layout_rec["scale"]
    dx, dy = layout_rec["displacement"]

    def to_hexspace(lon, lat):
        x, y = lonlat_to_wm(lon, lat)
        return (ax + s * (x - ax) + dx, ay + s * (y - ay) + dy)

    n_candidates = min(5, n_urban)
    cities = _cesta_top_n(state_abbr, census_year, n_candidates)
    if not cities:
        return []
    points = [(name, to_hexspace(lon, lat), pop) for name, lon, lat, pop in cities]

    # single-linkage clustering with a 2.9R cutoff (#17 decision 3)
    RADIUS = 2.9 * R
    clusters: list[dict] = [{"names": [nm], "pop": pop, "xy": xy} for nm, xy, pop in points]
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d2 = (clusters[i]["xy"][0] - clusters[j]["xy"][0]) ** 2 + (clusters[i]["xy"][1] - clusters[j]["xy"][1]) ** 2
                if d2 <= RADIUS * RADIUS:
                    a, b = clusters[i], clusters[j]
                    total = a["pop"] + b["pop"]
                    wx = (a["xy"][0] * a["pop"] + b["xy"][0] * b["pop"]) / total
                    wy = (a["xy"][1] * a["pop"] + b["xy"][1] * b["pop"]) / total
                    new = {"names": a["names"] + b["names"], "pop": total, "xy": (wx, wy)}
                    clusters = [c for k, c in enumerate(clusters) if k not in (i, j)] + [new]
                    merged = True
                    break
            if merged:
                break

    clusters.sort(key=lambda c: -c["pop"])
    total_pop = sum(c["pop"] for c in clusters)
    out = []
    remaining = n_urban
    for i, c in enumerate(clusters):
        if i == len(clusters) - 1:
            n = remaining  # last cluster takes the remainder (avoids rounding drift)
        else:
            n = round(c["pop"] / total_pop * n_urban)
        n = max(0, min(remaining, n))
        remaining -= n
        if n > 0:
            out.append(("+".join(c["names"]), c["xy"], n))
    return out


if __name__ == "__main__":
    # sanity spot-checks against known real-world figures
    print("NY urban_share 1900:", urban_share("NY", 1900), "(expect ~0.73, Bureau's 1900 NY figure)")
    print("NY urban_share 2000:", urban_share("NY", 2000))
    print("TX urban_share 2000:", urban_share("TX", 2000))
    print("NY urban_share 1790:", urban_share("NY", 1790))
    for c in [1, 2, 3, 60, 90, 119]:
        yr = congress_to_census_year(c)
        print(f"Congress {c} -> census {yr}, NY urban_seats (assume 26 seats): "
              f"{urban_seats('NY', c, 26)}")

    print("\n=== real anchors, C119 (reading layout from state_outlines_by_congress, standalone-only) ===")
    for abbr, fips, seats in [("NY", "36", 26), ("TX", "48", 38)]:
        d = json.load(open(ROOT / "data_processed" / "state_outlines_by_congress" / "119.geojson"))
        props = next(f["properties"] for f in d["features"] if f["properties"]["state_fips"] == fips)
        rec = {
            "anchor": (props["anchor_x"], props["anchor_y"]),
            "scale": props["area_scale"],
            "displacement": (props["displacement_x"], props["displacement_y"]),
        }
        print(f"{abbr} ({seats} seats):", real_anchors_for(abbr, 119, seats, rec))

