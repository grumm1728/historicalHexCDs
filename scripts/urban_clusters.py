"""Urban clusters per state per Congress (issue #27; decision record: wayfinder #17).

Given a state's urban seat count (`urban_seats`, #26) and its LIVE layout record for the
Congress, returns the city-centred clusters its urban seats are anchored to:

1. Candidates: the top `N = min(5, urban_seats)` cities by population for the census in
   effect, from CESTA (`data_raw/cities/1790-2010_MASTER.csv`). 2020 has no CESTA column,
   so CESTA's coordinates are joined to `sub-est2024.csv`'s April-2020 base on place FIPS.
   `urban_seats == 0` means no lookup at all.
2. Each city is projected into hex space exactly like the state's outline: AK/HI inset
   (shared `inset_lonlat`), Web Mercator, then `anchor + scale * (p - anchor) + displacement`.
3. Single-linkage clustering with a 2.9R cutoff in that hex space, so cluster resolution
   tracks the state's own drawn scale. A cluster's anchor is its population-weighted
   centroid; its name joins its cities, largest first.
4. Seats: `round-half-up(population_share * urban_seats)` per cluster; the largest cluster
   absorbs the rounding remainder so the total is exactly `urban_seats`. A cluster that
   rounds to 0 gets no anchor.

The layout record MUST be the tiler's own `compute_scaled_layout` result for this Congress
(keys `anchor`, `scale`, `displacement`) — recomputing the layout standalone gives the wrong
position (the #20 lesson).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fetch_modern_state_outlines import inset_lonlat
from urban_seats import _resolve_fips, _state_names, congress_to_census_year, urban_seats

ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "data_raw" / "cities"
R = 35000.0  # hex circumradius (m); must match tile_state_pentahexes.R
MERGE_RADIUS = 2.9 * R
MAX_CANDIDATES = 5
EARTH = 6378137.0


@dataclass(frozen=True)
class City:
    name: str
    lon: float
    lat: float
    population: int


@dataclass(frozen=True)
class UrbanCluster:
    name: str                 # e.g. "Dallas+Fort Worth"
    xy: tuple[float, float]   # population-weighted anchor, hex-space (layout) coordinates
    population: int
    seats: int
    cities: tuple[str, ...]


# ---------------------------------------------------------------- city candidates

@lru_cache(maxsize=None)
def _cesta_rows() -> tuple[dict, ...]:
    with (CITIES / "1790-2010_MASTER.csv").open(encoding="utf-8", errors="replace", newline="") as f:
        return tuple(csv.DictReader(f))


@lru_cache(maxsize=None)
def _pop2020_by_place() -> dict[str, int]:
    """7-digit place FIPS -> April 2020 base population (incorporated places only)."""
    out = {}
    with (CITIES / "sub-est2024.csv").open(encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            if r["SUMLEV"] == "162":
                out[r["STATE"] + r["PLACE"]] = int(r["ESTIMATESBASE2020"])
    return out


def _coords(r: dict) -> tuple[float, float] | None:
    for lat_col, lon_col in (("LAT", "LON"), ("LAT_BING", "LON_BING")):
        lat, lon = r.get(lat_col, "").strip(), r.get(lon_col, "").strip()
        try:
            return float(lon), float(lat)
        except ValueError:
            continue  # blank or malformed (one CESTA LAT reads "36.36.960974") -> Bing pair
    return None


def _population(r: dict, census_year: int) -> int:
    if census_year == 2020:
        return _pop2020_by_place().get(r.get("STPLFIPS_2010", "").strip(), 0)
    v = r.get(str(census_year), "").strip().replace(",", "")
    try:
        return int(float(v)) if v else 0
    except ValueError:
        return 0


@lru_cache(maxsize=None)
def _ranked_cities(state_abbr: str, census_year: int) -> tuple[City, ...]:
    cities = []
    for r in _cesta_rows():
        if r.get("ST") != state_abbr:
            continue
        pop = _population(r, census_year)
        coords = _coords(r)
        if pop > 0 and coords is not None:
            cities.append(City(r["City"], coords[0], coords[1], pop))
    cities.sort(key=lambda c: (-c.population, c.name))
    return tuple(cities)


def top_cities(state_abbr: str, census_year: int, n: int) -> list[City]:
    """The state's `n` most populous CESTA places for a census year, largest first."""
    return list(_ranked_cities(state_abbr, census_year)[:n]) if n > 0 else []


# ---------------------------------------------------------------- hex-space projection

def to_hex_space(state_abbr: str, lon: float, lat: float, layout_rec: dict) -> tuple[float, float]:
    """Project a real WGS84 point the same way the state's outline is drawn."""
    lon, lat = inset_lonlat(state_abbr, lon, lat)
    x = EARTH * math.radians(lon)
    y = EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    ax, ay = layout_rec["anchor"]
    s = layout_rec["scale"]
    dx, dy = layout_rec["displacement"]
    return ax + s * (x - ax) + dx, ay + s * (y - ay) + dy


# ---------------------------------------------------------------- clustering + seats

def _single_linkage(points: list[tuple[City, tuple[float, float]]]) -> list[list[int]]:
    """Connected components of the graph joining points within MERGE_RADIUS."""
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            (xi, yi), (xj, yj) = points[i][1], points[j][1]
            if math.hypot(xi - xj, yi - yj) <= MERGE_RADIUS:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(points)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def allocate_seats(populations: list[int], total_seats: int) -> list[int]:
    """Split `total_seats` by population share (populations sorted largest first).
    Each non-largest cluster gets round-half-up(share * total); the largest takes the
    remainder. If rounding up overshoots so the largest would drop below 1, seats are
    taken back from the smallest clusters first — the largest always keeps an anchor."""
    if total_seats <= 0 or not populations:
        return [0] * len(populations)
    whole = sum(populations)
    seats = [0] + [math.floor(p / whole * total_seats + 0.5) for p in populations[1:]]
    for i in range(len(seats) - 1, 0, -1):
        if total_seats - sum(seats[1:]) >= 1:
            break
        seats[i] -= min(seats[i], sum(seats[1:]) - (total_seats - 1))
    seats[0] = total_seats - sum(seats[1:])
    return seats


def urban_clusters(
    state: str, congress_number: int, layout_rec: dict, n_urban: int | None = None
) -> list[UrbanCluster]:
    """A state's urban clusters for one Congress, largest first; seats sum to `n_urban`
    (default: `urban_seats(state, congress_number)`). Empty when there are no urban seats
    or no tabulated cities."""
    fips = _resolve_fips(state)
    abbr = _state_names()[fips][0]
    if n_urban is None:
        n_urban = urban_seats(fips, congress_number)
    if n_urban <= 0:
        return []

    cities = top_cities(abbr, congress_to_census_year(congress_number), min(MAX_CANDIDATES, n_urban))
    points = [(c, to_hex_space(abbr, c.lon, c.lat, layout_rec)) for c in cities]

    groups = []
    for members in _single_linkage(points):
        members.sort(key=lambda i: -points[i][0].population)
        pop = sum(points[i][0].population for i in members)
        x = sum(points[i][1][0] * points[i][0].population for i in members) / pop
        y = sum(points[i][1][1] * points[i][0].population for i in members) / pop
        groups.append((pop, (x, y), tuple(points[i][0].name for i in members)))
    groups.sort(key=lambda g: (-g[0], g[2]))

    out = []
    for (pop, xy, names), seats in zip(groups, allocate_seats([g[0] for g in groups], n_urban)):
        if seats > 0:
            out.append(UrbanCluster("+".join(names), xy, pop, seats, names))
    return out
