"""Metro-based urban seats and anchors per state per Congress (issue #36).

Decision record: #33 (meaning, importance, seats), amended by #34 (option A': linking rule
and per-area anchors). Replaces `urban_seats` / `urban_clusters` as the source of the seat
counts and anchors the #28 labelling pass (`label_urban_tiles`) uses. The Census-urban
count (`urban_seats`, #26) is still exported alongside.

1. Metros before 1950: single-linkage chains of ALL CESTA places (`1790-2010_MASTER.csv`)
   within `CHAIN_KM` = 13 km (haversine), with that census's populations.
2. Metros from 1950 on: official urbanized areas (`data_raw/urbanized_areas/
   ua_state_portions.csv`). Only areas of `LARGE_POP` = 500,000+ link, and small areas never
   bridge a chain:
     1990-2020  boundary gap <= 5 km (precomputed: `ua_large_area_gaps.csv`)
     1950-1980  first-named cities <= 100 km apart (no digital boundaries exist)
3. Importance: the top N = floor(states in the census year / 2) metros nationally. The
   ranking spans the whole census (every place or area, seated state or not, DC and
   territories), so Civil War secessions don't promote smaller cities.
4. Seats: per qualifying metro portion in a drawn state,
   round-half-up(portion_pop / state_pop * seats), summed per state (clamped to seats).
5. Anchors: from 1950, one per in-state portion of each ORIGINAL urbanized area — linking
   decides only ranking and rounding; a merged portion's seats are split among its areas by
   population (largest remainder). Before 1950, one anchor per in-state chain portion at its
   population-weighted centre. A portion or area that rounds to 0 gets no anchor.
6. Timing: #16's census -> Congress step function (C1-C2 backfill 1790). Each place counts
   toward the state that draws it: an unseated child's places toward its composite-outline
   parent (`PREDECESSOR_PARENT`), Maine's toward MA through C16 (`MAINE_IN_MA`; the Maine
   block itself gets 0). `state_pop` is #26's per-outline census total, so composite rows
   are already included.

Public entry points:
    metro_seats(state, congress_number, seats=None) -> int
    metro_anchors(state, congress_number, seats=None) -> list[MetroAnchor]
    metro_clusters(state, congress_number, layout_rec, seats=None) -> list[UrbanCluster]
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from urban_clusters import UrbanCluster, _cesta_rows, _coords, _population, to_hex_space
from urban_seats import _lineage, _resolve_fips, _seats_table, _state_counts, _state_names, congress_to_census_year, seat_table

ROOT = Path(__file__).resolve().parent.parent
UA = ROOT / "data_raw" / "urbanized_areas"
STATE_META = ROOT / "data_raw" / "states" / "state_metadata.csv"

CHAIN_KM = 13.0         # pre-1950 CESTA place chain (#33 decision 2)
LARGE_POP = 500_000     # only areas this big link (#34 option A')
GAP_KM = 5.0            # 1990-2020 boundary gap
CITY_KM = 100.0         # 1950-1980 first-named-city distance
FIRST_UA_YEAR = 1950
FIRST_GAP_YEAR = 1990
FALLBACK_KM = 60.0      # portion without a published point: CESTA places in-state within this
EARTH_KM = 6371.0088

# Census day per year: decides which states existed (#33 decision 4 counts states "in the
# census year"). 1790 Aug 2 includes Rhode Island (May 1790) but not Vermont (1791) -> 13.
CENSUS_DAY = {1790: date(1790, 8, 2), 1800: date(1800, 8, 4), 1810: date(1810, 8, 6),
              1820: date(1820, 8, 7), 1910: date(1910, 4, 15), 1920: date(1920, 1, 1)}


def census_day(year: int) -> date:
    if year in CENSUS_DAY:
        return CENSUS_DAY[year]
    return date(year, 6, 1) if year < 1910 else date(year, 4, 1)


@dataclass(frozen=True)
class Place:
    name: str
    st: str                  # postal abbr of the real state/territory (CESTA ST / UA state)
    lon: float
    lat: float
    population: int


@dataclass(frozen=True)
class Portion:
    """One anchor-able piece of a metro in one real state."""
    name: str                # anchor label: urbanized area (stripped of its state suffix) or largest place
    st: str
    population: int
    points: tuple[tuple[float, float, int], ...]   # (lon, lat, weight); weighted centre = anchor


@dataclass(frozen=True)
class Metro:
    name: str
    population: int
    portions: tuple[Portion, ...]   # pre-1950: one per state; from 1950: one per (area, state)


@dataclass(frozen=True)
class MetroAnchor:
    name: str
    metro: str
    national_rank: int        # 1 = largest metro in the census
    population: int
    seats: int
    st: str
    points: tuple[tuple[float, float, int], ...]


# ---------------------------------------------------------------- shared helpers

def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _components(n: int, edges) -> list[list[int]]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def largest_remainder(populations: list[int], total: int) -> list[int]:
    """Split `total` seats by population; remainders broken by population, then order."""
    whole = sum(populations)
    if total <= 0 or whole <= 0:
        return [0] * len(populations)
    quotas = [p / whole * total for p in populations]
    seats = [math.floor(q) for q in quotas]
    order = sorted(range(len(populations)), key=lambda i: (-(quotas[i] - seats[i]), -populations[i], i))
    for i in order[: total - sum(seats)]:
        seats[i] += 1
    return seats


@lru_cache(maxsize=None)
def states_in_census(year: int) -> int:
    day = census_day(year)
    with STATE_META.open(encoding="utf-8", newline="") as f:
        return sum(date.fromisoformat(r["admission_date_iso"]) <= day for r in csv.DictReader(f))


def top_n(year: int) -> int:
    return states_in_census(year) // 2


@lru_cache(maxsize=None)
def _abbr_by_fips() -> dict[str, str]:
    out = {fips: abbr for fips, (abbr, _) in _state_names().items()}
    out.setdefault("11", "DC")
    out.setdefault("72", "PR")
    return out


# ---------------------------------------------------------------- pre-1950: CESTA place chains

@lru_cache(maxsize=None)
def cesta_places(year: int) -> tuple[Place, ...]:
    out = []
    for r in _cesta_rows():
        pop = _population(r, year)
        coords = _coords(r)
        if pop > 0 and coords is not None:
            out.append(Place(r["City"].strip(), r["ST"].strip(), coords[0], coords[1], pop))
    return tuple(out)


def chain_places(places: list[Place] | tuple[Place, ...], km: float = CHAIN_KM) -> list[list[int]]:
    """Single-linkage components of places within `km` (haversine), via a degree grid."""
    cell = 0.35  # degrees; > 13 km of longitude up to ~70 deg N
    grid: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(places):
        grid.setdefault((math.floor(p.lon / cell), math.floor(p.lat / cell)), []).append(i)
    edges = []
    for (gx, gy), members in grid.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    for i in members:
                        if i < j and haversine_km(places[i].lon, places[i].lat, places[j].lon, places[j].lat) <= km:
                            edges.append((i, j))
    return _components(len(places), edges)


def _chain_metros(year: int) -> list[Metro]:
    places = cesta_places(year)
    metros = []
    for comp in chain_places(places):
        members = sorted((places[i] for i in comp), key=lambda p: (-p.population, p.name))
        by_st: dict[str, list[Place]] = {}
        for p in members:
            by_st.setdefault(p.st, []).append(p)
        portions = tuple(
            Portion(ps[0].name, st, sum(p.population for p in ps), tuple((p.lon, p.lat, p.population) for p in ps))
            for st, ps in by_st.items()
        )
        metros.append(Metro(members[0].name, sum(p.population for p in members), portions))
    return metros


# ---------------------------------------------------------------- 1950+: official urbanized areas

@lru_cache(maxsize=None)
def _ua_rows(year: int) -> tuple[dict, ...]:
    with (UA / "ua_state_portions.csv").open(encoding="utf-8", newline="") as f:
        return tuple(r for r in csv.DictReader(f) if int(r["year"]) == year)


def _short_name(ua_name: str) -> str:
    """'San Francisco--Oakland, CA' -> 'San Francisco--Oakland'; 'Chicago, Ill.' -> 'Chicago'."""
    head, sep, _ = ua_name.rpartition(", ")
    return head if sep else ua_name


@lru_cache(maxsize=None)
def _large_gaps() -> dict[int, list[tuple[str, str, float]]]:
    out: dict[int, list[tuple[str, str, float]]] = {}
    with (UA / "ua_large_area_gaps.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(int(r["year"]), []).append((r["ua_code_a"], r["ua_code_b"], float(r["gap_km"])))
    return out


def _fallback_point(st: str, year: int, near: tuple[float, float] | None) -> tuple[tuple[float, float, int], ...]:
    """A portion with no published point (1950-1980 parts outside the first-named city's
    state, e.g. New York's NJ part): the CESTA places of that state near the area's point."""
    if near is None:
        return ()
    cesta_year = min(year, 2010)
    pts = [(p.lon, p.lat, p.population) for p in cesta_places(cesta_year)
           if p.st == st and haversine_km(p.lon, p.lat, *near) <= FALLBACK_KM]
    return tuple(pts)


def _ua_metros(year: int) -> list[Metro]:
    abbr = _abbr_by_fips()
    areas: dict[str, dict] = {}
    for r in _ua_rows(year):
        key = r["ua_code"] or r["ua_name"]   # 1950/1960 rows have no codes
        a = areas.setdefault(key, {"name": r["ua_name"], "pop": int(r["total_pop"]), "parts": [], "point": None})
        pt = (float(r["lon"]), float(r["lat"])) if r["lon"] else None
        if pt and r["loc_source"] == "cesta_first_named_city":
            a["point"] = pt
        a["parts"].append((abbr.get(r["state_fips"].zfill(2), r["state_fips"]), int(r["portion_pop"]), pt))
    keys = list(areas)
    for a in areas.values():
        if a["point"] is None:  # 1990+: the population-weighted mean of the part points
            pts = [(pt, pop) for _, pop, pt in a["parts"] if pt]
            if pts:
                w = sum(pop for _, pop in pts) or 1
                a["point"] = (sum(p[0] * pop for p, pop in pts) / w, sum(p[1] * pop for p, pop in pts) / w)

    large = [i for i, k in enumerate(keys) if areas[k]["pop"] >= LARGE_POP]
    edges = []
    if year >= FIRST_GAP_YEAR:
        index = {k: i for i, k in enumerate(keys)}
        for a, b, gap in _large_gaps()[year]:
            if gap <= GAP_KM and a in index and b in index:
                edges.append((index[a], index[b]))
    else:
        for x, i in enumerate(large):
            for j in large[x + 1:]:
                pi, pj = areas[keys[i]]["point"], areas[keys[j]]["point"]
                if pi is None or pj is None:
                    raise RuntimeError(f"{year}: large area without a first-named-city point: "
                                       f"{areas[keys[i if pi is None else j]]['name']}")
                if haversine_km(*pi, *pj) <= CITY_KM:
                    edges.append((i, j))

    metros = []
    for comp in _components(len(keys), edges):
        comp.sort(key=lambda i: (-areas[keys[i]]["pop"], areas[keys[i]]["name"]))
        portions = []
        for i in comp:
            a = areas[keys[i]]
            for st, pop, pt in a["parts"]:
                pts = ((pt[0], pt[1], 1),) if pt else _fallback_point(st, year, a["point"])
                portions.append(Portion(_short_name(a["name"]), st, pop, pts))
        name = "+".join(_short_name(areas[keys[i]]["name"]) for i in comp)
        metros.append(Metro(name, sum(areas[keys[i]]["pop"] for i in comp), tuple(portions)))
    return metros


# ---------------------------------------------------------------- national ranking

@lru_cache(maxsize=None)
def qualifying_metros(census_year: int) -> tuple[Metro, ...]:
    """The census's top-N metros nationally, largest first."""
    metros = _ua_metros(census_year) if census_year >= FIRST_UA_YEAR else _chain_metros(census_year)
    metros.sort(key=lambda m: (-m.population, m.name))
    return tuple(metros[: top_n(census_year)])


# ---------------------------------------------------------------- per state / Congress

def _drawing_fips(st: str, congress_number: int) -> str | None:
    """The seated state whose outline draws real state `st` this Congress, or None."""
    predecessor_parent, maine_in_ma, ma_fips, me_fips = _lineage()
    try:
        fips = _resolve_fips(st)
    except KeyError:
        return None  # DC, territories: ranked, never drawn
    if fips == me_fips and congress_number in maine_in_ma:
        return ma_fips
    seated = _seats_table().get(congress_number, {})
    while fips not in seated:
        fips = predecessor_parent.get(fips)
        if fips is None:
            return None
    return fips


def metro_anchors(state: str, congress_number: int, seats: int | None = None) -> list[MetroAnchor]:
    """A drawn state's metro anchors for one Congress, most seats first; seats sum to
    `metro_seats(...)`. `seats` defaults to the tiler's (post-Maine-split) seat count."""
    fips = _resolve_fips(state)
    _, maine_in_ma, _, me_fips = _lineage()
    if seats is None:
        seats = seat_table(congress_number).get(fips, 0)
    if seats <= 0 or (fips == me_fips and congress_number in maine_in_ma):
        return []
    state_pop = _state_counts(fips, congress_number)[0]
    if state_pop <= 0:
        return []
    census_year = congress_to_census_year(congress_number)

    anchors: list[MetroAnchor] = []
    for rank, metro in enumerate(qualifying_metros(census_year), start=1):
        mine = [p for p in metro.portions if _drawing_fips(p.st, congress_number) == fips]
        if not mine:
            continue
        in_state = sum(p.population for p in mine)
        n = round_half_up(in_state / state_pop * seats)
        if n <= 0:
            continue
        if census_year < FIRST_UA_YEAR:
            # one anchor per in-state chain portion (several only when places from an
            # unseated child or Maine are drawn by this state)
            pieces = [Portion(max(mine, key=lambda p: p.population).name, mine[0].st, in_state,
                              tuple(pt for p in mine for pt in p.points))]
        else:
            pieces = sorted(mine, key=lambda p: (-p.population, p.name))
        for piece, k in zip(pieces, largest_remainder([p.population for p in pieces], n)):
            if k > 0:
                if not piece.points:
                    raise RuntimeError(f"C{congress_number} {state}: no location for metro portion {piece.name}")
                anchors.append(MetroAnchor(piece.name, metro.name, rank, piece.population, k, piece.st, piece.points))

    over = sum(a.seats for a in anchors) - seats
    while over > 0:  # rounding up several portions overshot the delegation: trim the smallest
        i = min(range(len(anchors)), key=lambda i: (anchors[i].population, -i))
        a = anchors[i]
        anchors[i] = MetroAnchor(a.name, a.metro, a.national_rank, a.population, a.seats - 1, a.st, a.points)
        anchors = [x for x in anchors if x.seats > 0]
        over -= 1
    anchors.sort(key=lambda a: (-a.seats, -a.population, a.name))
    return _dedupe_names(anchors)


def _dedupe_names(anchors: list[MetroAnchor]) -> list[MetroAnchor]:
    seen: dict[str, int] = {}
    out = []
    for a in anchors:
        seen[a.name] = seen.get(a.name, 0) + 1
        if seen[a.name] > 1:
            a = MetroAnchor(f"{a.name} ({a.st})", a.metro, a.national_rank, a.population, a.seats, a.st, a.points)
        out.append(a)
    return out


def metro_seats(state: str, congress_number: int, seats: int | None = None) -> int:
    return sum(a.seats for a in metro_anchors(state, congress_number, seats))


def metro_clusters(state: str, congress_number: int, layout_rec: dict, seats: int | None = None) -> list[UrbanCluster]:
    """`metro_anchors` projected through the state's LIVE layout record (AK/HI inset
    included), as the `UrbanCluster`s `label_urban_tiles` consumes."""
    abbr = _state_names()[_resolve_fips(state)][0]
    out = []
    for a in metro_anchors(state, congress_number, seats):
        projected = [(to_hex_space(abbr, lon, lat, layout_rec), w) for lon, lat, w in a.points]
        w = sum(wt for _, wt in projected)
        x = sum(p[0] * wt for p, wt in projected) / w
        y = sum(p[1] * wt for p, wt in projected) / w
        out.append(UrbanCluster(a.name, (x, y), a.population, a.seats, (a.name,)))
    return out


if __name__ == "__main__":
    for c in range(1, 120):
        st = seat_table(c)
        total = sum(metro_seats(f, c, s) for f, s in st.items())
        print(f"C{c:<3} census {congress_to_census_year(c)}  top {top_n(congress_to_census_year(c)):>2}  "
              f"metro {total:>3} / {sum(st.values())} seats")
