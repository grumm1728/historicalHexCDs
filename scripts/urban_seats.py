"""Urban-seat counts per state per Congress (issue #26; decision record: wayfinder #16/#23).

    urban_seats = round(urban_share * seats), clamped to [0, seats]. No floor.

`urban_share` is the state's census urban population / total population, spliced raw
(no cross-era harmonization) across four source eras:

    1790-1890  NHGIS extract nhgis0001 (places 2,500+)   data_raw/urbanization/nhgis0001_csv/
    1900-1990  Census "Urban and Rural Population"       data_raw/urbanization/urpop0090.txt
    2000       Census 2000 SF1 P002                      data_raw/urbanization/sf1_p002_2000.json
    2010/2020  Census state urban/rural XLSX             data_raw/urbanization/State_Urban_Rural_Pop_2020_2010.xlsx

Census -> Congress is a step function on the existing seat-apportionment cutover
(`data_raw/seats/state_seats_by_apportionment.csv`), so a Congress's urban share and its
seat count always come from the same census. Congresses 1-2 (pre-census "Const." seats)
are backfilled with 1790.

Two historical-outline rules keep the number describing the population the map draws:

- Composite outlines (`PREDECESSOR_PARENT`): while a parent is drawn inclusive of a
  not-yet-seated child, and the census tabulates that child's territory as its own row,
  the parent's counts are summed with that row (curated in
  `data_raw/urbanization/composite_outline_predecessor_rows.csv`: NC+Southwest Territory
  1790, GA+Mississippi Territory 1800/1810).
- `MAINE_IN_MA` (Congresses 1-16): the tiler splits MA's delegation into an MA-proper block
  and a Maine block. Maine's block is unconditionally 0% urban; the MA-proper block uses
  the (fused MA+Maine) Massachusetts share.

Admitted between censuses: a state seated before the census in effect has its own row
(Ohio at C8 on the 1800 census, Maine at C17 on 1810, ...) uses the row of the territory
it was formed from, or 0% where the census has none (`TERRITORY_ROW`, exhaustive).

Public entry points:
    urban_share(state_fips, congress_number) -> float
    urban_seats(state_fips, congress_number, seats=None) -> int
    urban_seats_by_fips(congress_number) -> dict[str, int]   # tiler's post-Maine seat table
"""

from __future__ import annotations

import csv
import json
import math
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URB = ROOT / "data_raw" / "urbanization"
SEATS_BY_APPORTIONMENT = ROOT / "data_raw" / "seats" / "state_seats_by_apportionment.csv"
CONGRESS_SEATS = ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"

# (state FIPS, census_year) -> territory row, for every seated state whose census in effect
# predates its own row (admitted between censuses). None = no separate row exists (the land
# was counted inside another state's row), so the state is 0% urban. Exhaustive: a seated
# state missing from both the census and this table raises, so a data change can't
# silently zero a state. Every entry rounds to 0 urban seats either way (all 1-7 seat
# frontier delegations well under 50% urban); the table exists to make that explicit.
TERRITORY_ROW: dict[tuple[str, int], str | None] = {
    ("21", 1790): None,                     # Kentucky C2-C7: inside Virginia's 1790 row
    ("47", 1790): "Southwest Territory",    # Tennessee C4-C7
    ("23", 1790): None,                     # Maine (MAINE_IN_MA block): inside Massachusetts
    ("23", 1800): None,
    ("23", 1810): None,                     # Maine C17: first seated on the 1810 census
    ("39", 1800): "Northwest Territory",    # Ohio C8-C12
    ("22", 1810): "Orleans Territory",      # Louisiana C13-C17
    ("28", 1810): "Mississippi Territory",  # Mississippi C15-C17
    ("01", 1810): "Mississippi Territory",  # Alabama C16-C17
    ("29", 1820): "Missouri Territory",     # Missouri C18-C22
    ("20", 1860): "Kansas Territory",       # Kansas C38-C42
    ("54", 1860): None,                     # West Virginia C38-C42: inside Virginia's 1860 row
}


# ---------------------------------------------------------------- state identity

@lru_cache(maxsize=None)
def _state_names() -> dict[str, tuple[str, str]]:
    """FIPS -> (abbr, name) for every state in the seat table."""
    out: dict[str, tuple[str, str]] = {}
    with CONGRESS_SEATS.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out[r["state_fips"].zfill(2)] = (r["state_abbr"], r["state_name"])
    return out


def _resolve_fips(state: str) -> str:
    """Accept a FIPS code ("36" / "6") or a postal abbreviation ("NY")."""
    names = _state_names()
    if state.isdigit():
        fips = state.zfill(2)
        if fips in names:
            return fips
    else:
        for fips, (abbr, _) in names.items():
            if abbr == state.upper():
                return fips
    raise KeyError(f"unknown state {state!r}")


@lru_cache(maxsize=None)
def _seats_table() -> dict[int, dict[str, int]]:
    """congress -> {fips: house_seats} for seated states (house_seats > 0)."""
    out: dict[int, dict[str, int]] = {}
    with CONGRESS_SEATS.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            seats = int(r["house_seats"])
            if seats > 0:
                out.setdefault(int(r["congress_number"]), {})[r["state_fips"].zfill(2)] = seats
    return out


# ---------------------------------------------------------------- census -> Congress

@lru_cache(maxsize=None)
def _census_cutovers() -> tuple[tuple[int, int], ...]:
    """Sorted (first congress using this census, census_year), from the apportionment
    table's effective_year. Cycles are national, so any one state's timeline suffices."""
    ordinal = re.compile(r"(\d+)(st|nd|rd|th)")
    cut: dict[int, int] = {}
    with SEATS_BY_APPORTIONMENT.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            m = ordinal.match(r["apportionment_label"])
            if not m:
                continue  # "Const." — pre-census allocation
            congress = (int(r["effective_year"]) - 1789) // 2 + 1
            cut[congress] = 1780 + 10 * int(m.group(1))
    return tuple(sorted(cut.items()))


def congress_to_census_year(congress_number: int) -> int:
    """The census whose apportionment is in effect for this Congress; C1-C2 backfill 1790."""
    year = 1790
    for congress, census_year in _census_cutovers():
        if congress > congress_number:
            break
        year = census_year
    return year


# ---------------------------------------------------------------- per-era (total, urban) counts

@lru_cache(maxsize=None)
def _nhgis_year(year: int) -> dict[str, tuple[int, int]]:
    """Row name -> (total, urban) for one NHGIS census year. 1840/1880/1890 split the two
    tables across datasets, so tables are collected across every file for the year.
    Total = the first "Total Population" table (1800 also carries a later NT8 recount;
    the original-report NT1 is the one #23's curated rows cite)."""
    totals: dict[str, int] = {}
    urbans: dict[str, int] = {}
    table_re = re.compile(r"^Table \d+:\s+(.+?)\s*$.*?^NHGIS code:\s+(\w+)", re.M | re.S)
    for path in sorted((URB / "nhgis0001_csv").glob(f"nhgis0001_ds*_{year}_state.csv")):
        codebook = path.with_name(path.stem + "_codebook.txt").read_text(encoding="utf-8", errors="replace")
        total_col = urban_col = None
        for name, code in table_re.findall(codebook):
            if name.startswith("Total Population") and total_col is None:
                total_col = code + "001"
            elif "Urban" in name and urban_col is None:
                urban_col = code + "001"
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if total_col:
                    totals[r["STATE"]] = int(r[total_col] or 0)
                if urban_col:
                    urbans[r["STATE"]] = int(r[urban_col] or 0)
    if not totals or not urbans:
        raise RuntimeError(f"NHGIS {year}: missing total or urban table")
    return {name: (totals[name], urbans.get(name, 0)) for name in totals}


@lru_cache(maxsize=None)
def _urpop0090() -> dict[int, dict[str, tuple[int, int]]]:
    """urpop0090.txt: four blocks (1990/80/70, 1960/50/40, 1930/20/10, 1900), each state
    line carrying (total, urban, rural, %urban, %rural) per decade.

    Total is taken as urban + rural, not the printed total: the printed column has typos
    (Nevada 1940 "0", Delaware 1930 230,380 for 238,380) and "r"-flagged 1970/1980 totals
    were revised without re-splitting urban/rural. Footnote markers ("*1", "*2", "r") are
    stripped before tokenizing, and each decade's share is checked against the printed
    %urban so a column shift cannot pass silently."""
    names = {name for _, name in _state_names().values()}
    text = (URB / "urpop0090.txt").read_text(encoding="latin-1")
    out: dict[int, dict[str, tuple[int, int]]] = {}
    for block in re.split(r"\n(?=\s+Table 1\.)", text):
        header = re.search(r"^\s+(\d{4})(?:\s+\d{4})*\s*$", block, re.M)
        if not header:
            continue
        years = list(dict.fromkeys(int(y) for y in re.findall(r"\d{4}", header.group(0))))
        for line in block.splitlines():
            m = re.match(r"^\s+([A-Z][A-Za-z .]+?)\s{2,}(.*)$", line)
            if not m or m.group(1) not in names:
                continue
            body = re.sub(r"\*\d+|\br\b", " ", m.group(2))
            tokens = re.findall(r"[\d,]+(?:\.\d+)?%?", body)
            if len(tokens) != 5 * len(years):
                raise RuntimeError(f"urpop0090: {m.group(1)} has {len(tokens)} fields for {years}")
            for i, year in enumerate(years):
                _, urban, rural, pct_urban, _ = tokens[5 * i: 5 * i + 5]
                urban, rural = int(urban.replace(",", "")), int(rural.replace(",", ""))
                if abs(100 * urban / (urban + rural) - float(pct_urban.rstrip("%"))) > 0.06:
                    raise RuntimeError(f"urpop0090: {m.group(1)} {year} share disagrees with printed %urban")
                out.setdefault(year, {})[m.group(1)] = (urban + rural, urban)
    return out


@lru_cache(maxsize=None)
def _sf1_2000() -> dict[str, tuple[int, int]]:
    rows = json.loads((URB / "sf1_p002_2000.json").read_text(encoding="utf-8"))
    header = rows[0]
    i_name, i_total, i_urban = (header.index(c) for c in ("NAME", "P002001", "P002002"))
    return {r[i_name]: (int(r[i_total]), int(r[i_urban])) for r in rows[1:]}


@lru_cache(maxsize=None)
def _xlsx_2010_2020(year: int) -> dict[str, tuple[int, int]]:
    import openpyxl

    wb = openpyxl.load_workbook(URB / "State_Urban_Rural_Pop_2020_2010.xlsx", read_only=True, data_only=True)
    rows = list(wb["States"].iter_rows(values_only=True))
    # headers carry embedded newlines ("2020 \nURBAN POP"); normalize whitespace
    header = [" ".join(str(h).split()) if h is not None else None for h in rows[0]]
    i_name = header.index("STATE NAME")
    i_total = header.index(f"{year} TOTAL POP")
    i_urban = header.index(f"{year} URBAN POP")
    return {r[i_name]: (int(r[i_total]), int(r[i_urban])) for r in rows[1:] if r[i_name]}


def census_counts(census_year: int) -> dict[str, tuple[int, int]]:
    """Row name -> (total population, urban population) for one census year."""
    if 1790 <= census_year <= 1890:
        return _nhgis_year(census_year)
    if 1900 <= census_year <= 1990:
        return _urpop0090()[census_year]
    if census_year == 2000:
        return _sf1_2000()
    if census_year in (2010, 2020):
        return _xlsx_2010_2020(census_year)
    raise ValueError(f"no urbanization source for census year {census_year}")


# ---------------------------------------------------------------- composite outlines / Maine

@lru_cache(maxsize=None)
def _predecessor_rows() -> dict[tuple[str, int], tuple[str, frozenset[str]]]:
    """(parent FIPS, census_year) -> (extra row name, covered child abbrs), from #23."""
    out = {}
    with (URB / "composite_outline_predecessor_rows.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = (r["parent_state_fips"].zfill(2), int(r["census_year"]))
            out[key] = (r["extra_row_name"], frozenset(r["covers_children"].split("+")))
    return out


def _lineage():
    # Lazy: the tiler will import this module, so importing it back at load time would cycle.
    from tile_state_pentahexes import MA_FIPS, MAINE_IN_MA, ME_FIPS, PREDECESSOR_PARENT

    return PREDECESSOR_PARENT, MAINE_IN_MA, MA_FIPS, ME_FIPS


def _state_counts(fips: str, congress_number: int) -> tuple[int, int]:
    """(total, urban) describing the population this state's outline draws this Congress."""
    census_year = congress_to_census_year(congress_number)
    counts = census_counts(census_year)
    _, name = _state_names()[fips]
    rec = counts.get(name)
    if rec is None:
        if (fips, census_year) not in TERRITORY_ROW:
            raise KeyError(f"no {census_year} census row for {name} and no TERRITORY_ROW entry")
        territory = TERRITORY_ROW[(fips, census_year)]
        return counts[territory] if territory else (0, 0)
    total, urban = rec

    predecessor_parent = _lineage()[0]
    extra = _predecessor_rows().get((fips, census_year))
    if extra is not None:
        row_name, covered = extra
        seated = _seats_table().get(congress_number, {})
        unseated_children = {
            _state_names()[child][0]
            for child, parent in predecessor_parent.items()
            if parent == fips and child not in seated
        }
        # one shared row covers several children (GA: MS+AL); add it once while ANY
        # covered child is still drawn inside the parent's outline
        if covered & unseated_children:
            t, u = counts[row_name]
            total, urban = total + t, urban + u
    return total, urban


def urban_share(state: str, congress_number: int) -> float:
    fips = _resolve_fips(state)
    total, urban = _state_counts(fips, congress_number)
    return urban / total if total > 0 else 0.0


def urban_seats(state: str, congress_number: int, seats: int | None = None) -> int:
    """Urban seats for a state in a Congress. `seats` defaults to the tiler's seat count
    for that state (post-`MAINE_IN_MA` split: MA-proper block for MA, the Maine block for
    ME during C1-C16)."""
    fips = _resolve_fips(state)
    _, maine_in_ma, _, me_fips = _lineage()
    if seats is None:
        seats = seat_table(congress_number).get(fips, 0)
    if seats <= 0:
        return 0
    if fips == me_fips and congress_number in maine_in_ma:
        return 0  # #16 decision 7: the Maine block is 0% urban while Maine is MA territory
    # the MA-proper block uses Massachusetts's own (fused MA+Maine) census row unchanged
    # round half up, not Python's banker's round: #16 says a 1-seat state at share >= 0.5 is urban
    return max(0, min(seats, math.floor(urban_share(fips, congress_number) * seats + 0.5)))


def seat_table(congress_number: int) -> dict[str, int]:
    """Seats per FIPS as the tiler allocates them: MA's delegation split into MA-proper and
    a Maine block during `MAINE_IN_MA` (mirrors `tile_state_pentahexes.main`)."""
    _, maine_in_ma, ma_fips, me_fips = _lineage()
    seats = dict(_seats_table().get(congress_number, {}))
    if congress_number in maine_in_ma and ma_fips in seats:
        maine_total, me_labeled = maine_in_ma[congress_number]
        seats[ma_fips] -= maine_total - me_labeled
        seats[me_fips] = maine_total
    return seats


def urban_seats_by_fips(congress_number: int) -> dict[str, int]:
    return {fips: urban_seats(fips, congress_number, seats) for fips, seats in seat_table(congress_number).items()}


if __name__ == "__main__":
    for c in range(1, 120):
        by_fips = urban_seats_by_fips(c)
        print(f"C{c:<3} census {congress_to_census_year(c)}  urban {sum(by_fips.values()):>3} / {sum(seat_table(c).values())} seats")
