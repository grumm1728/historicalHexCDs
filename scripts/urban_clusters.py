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
    metro: str = ""           # national metro this anchor belongs to (metro_seats only)
    national_rank: int = 0    # 1 = largest metro in the census; 0 = not ranked


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


# ---------------------------------------------------------------- label-only mechanism (#19/#28)

@dataclass(frozen=True)
class UrbanLabel:
    cluster: str   # UrbanCluster.name
    rank: int      # BFS claim order within the cluster: 0 = the tile nearest the anchor
    seats: int     # tiles the cluster finally holds (rank / (seats - 1) drives #29's gradient)


@dataclass(frozen=True)
class UrbanSpill:
    """A cluster walled in by larger clusters' regions before reaching its seat count;
    its leftover seats went to clusters that could still grow (kept for map footnotes)."""
    cluster: str
    allocated: int
    placed: int
    recipients: tuple[tuple[str, int], ...]  # (cluster name, extra seats taken)
    detached: int = 0  # seats no region could reach, placed as a detached piece of the largest


def _min_cost_assignment(cost: list[list[float]]) -> list[int]:
    """Hungarian algorithm (shortest augmenting paths) for a rows <= cols cost matrix:
    returns, per row, the column it is assigned to, minimising the total cost. Pure Python
    — matrices here are at most ~40 seats x ~53 tiles."""
    n, m = len(cost), len(cost[0]) if cost else 0
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)  # p[j] = row (1-based) holding column j
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [math.inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            row = cost[i0 - 1]
            for j in range(1, m + 1):
                if not used[j]:
                    cur = row[j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def _components(tiles: list[int], adjacency: list[set[int]]) -> list[list[int]]:
    """Connected components of `tiles` under `adjacency`, in first-seen order."""
    left, comps = set(tiles), []
    for t in tiles:
        if t not in left:
            continue
        left.discard(t)
        comp, stack = [t], [t]
        while stack:
            for nb in adjacency[stack.pop()]:
                if nb in left:
                    left.discard(nb)
                    comp.append(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def label_urban_tiles(
    centers: list[tuple[float, float]],
    adjacency: list[set[int]],
    clusters: list[UrbanCluster],
) -> tuple[list[UrbanLabel | None], list[UrbanSpill]]:
    """Post-hoc urban labels for a state's final tiles (never touches geometry).

    Seeds, then a joint assignment (docs/metro_joint_assignment.md):

    0. Seeds: each national metro (`UrbanCluster.metro`, largest first) takes the free tile
       nearest its principal area's anchor, preferring that anchor's Voronoi cell — every
       metro sits on its own city. Without this a big metro takes a small one's city tile
       (1850s-1900s New York swallowed Albany's). Seeding every *area* instead was measured
       too: near-coincident anchors (SF / San Jose / Concord) then flip seeds on tiny input
       changes and California got less stable.
    1. The remaining seats of each metro (SF-Oakland + San Jose + Concord, LA + Riverside
       + ...) are placed at once by a min-cost assignment of tiles (pure Python Hungarian;
       unassigned tiles stay rural) minimising total SQUARED distance to the metro's seat-weighted anchor centroid. Squared distance makes
       the optimum a capacitated (power-diagram) Voronoi partition: compact blobs meeting
       along straight-ish lines whose positions are set by seat counts, independent of any
       growth order.
    2. Each metro's footprint is split among its own anchors with cost squared distance /
       seats, so satellite areas (San Jose, McKinney) stay round blobs on their own city and
       the principal area takes the rest. (A one-level assignment pushed satellites to the
       far side of the state: C118 Temecula on the Arizona line, McKinney in the corner.)

    It replaces the greedy round-robin BFS (#19/#28), whose growth order decided which way a
    crowded cluster spread. Measured over all 119 Congresses it cuts the worst tile-to-anchor
    distance from 31R to 24R and spilled seats from 25 to 10, but cross-Congress stability
    is only slightly better: most label change between Congresses comes from the inputs
    (re-partitioned tiles, new census anchors and seats), not the labeller.

    Contiguity repair: the assignment ignores adjacency, so a cluster can come out in
    pieces (a tile across water, or a neighbour's blob cutting through). The piece holding
    its metro's seed (else its largest) is kept, the strays are released, and the cluster
    regrows from that piece by nearest-first BFS over unclaimed tiles (clusters with more
    seats first).

    Spill-over: a cluster walled in during repair stops short; its leftover seats go,
    largest cluster first, to clusters that can still grow, so the state's urban total stays
    exact. Each event is returned as an `UrbanSpill` for map footnotes.

    Detached last resort: if every region is walled in and seats remain (e.g. Michigan,
    when the Lower Peninsula fills and the rest of the state is the separate Upper
    Peninsula), the largest cluster reseeds at the unclaimed tile nearest its anchor;
    recorded as `UrbanSpill.detached`.

    `rank` orders a cluster's tiles by distance from its anchor (0 = nearest).
    """
    n = len(centers)
    owner: list[int | None] = [None] * n
    regions: list[list[int]] = [[] for _ in clusters]

    def dist2(k: int, i: int) -> float:
        ax, ay = clusters[k].xy
        return (centers[i][0] - ax) ** 2 + (centers[i][1] - ay) ** 2

    # one assignment row per seat; on a partial tiling (fewer tiles than seats) the smallest
    # clusters' last seats are dropped so every tile is still claimed
    slots = [k for k, cl in enumerate(clusters) for _ in range(cl.seats)][:n]
    target = [0] * len(clusters)
    for k in slots:
        target[k] += 1

    def assign(tiles: list[int], groups: list[tuple[tuple[float, float], int]], weighted: bool) -> dict[int, int]:
        """Min-cost assignment of `tiles` to `groups` [(anchor, seats)] -> {tile: group}.
        Cost = squared distance to the group's anchor, divided by the group's seats when
        `weighted` (so a small group stays a round blob around its own anchor)."""
        rows = [g for g, (_, s) in enumerate(groups) for _ in range(s)]
        if not rows:
            return {}
        cost = []
        for g in rows:
            (ax, ay), s = groups[g]
            w = s if weighted else 1
            cost.append([((centers[i][0] - ax) ** 2 + (centers[i][1] - ay) ** 2) / w for i in tiles])
        return {tiles[j]: g for g, j in zip(rows, _min_cost_assignment(cost))}

    metros = list(dict.fromkeys(cl.metro or cl.name for cl in clusters))
    members = [[k for k, cl in enumerate(clusters) if (cl.metro or cl.name) == m and target[k]] for m in metros]
    members = [ks for ks in members if ks]

    # seeds: each metro (largest first) owns the free tile nearest its principal (largest)
    # area's anchor, preferring tiles in that anchor's Voronoi cell among the metros'
    heads = [ks[0] for ks in members]
    nearest = [min(range(len(heads)), key=lambda g: (dist2(heads[g], i), g)) for i in range(n)]
    seeds: list[int] = []
    for g, k in enumerate(heads):
        free = [i for i in range(n) if i not in seeds]
        seeds.append(min([i for i in free if nearest[i] == g] or free, key=lambda i: (dist2(k, i), i)))
    pool_tiles = [i for i in range(n) if i not in seeds]

    # level 1: national metros as wholes, anchored at their seat-weighted anchor centroid
    groups = []
    for ks in members:
        s = sum(target[k] for k in ks)
        x = sum(clusters[k].xy[0] * target[k] for k in ks) / s
        y = sum(clusters[k].xy[1] * target[k] for k in ks) / s
        groups.append(((x, y), s - 1))
    top = assign(pool_tiles, groups, weighted=False)
    for g, i in enumerate(seeds):
        top[i] = g
    # level 2: split each metro's footprint among its own anchors
    for g, ks in enumerate(members):
        tiles = sorted(i for i, gg in top.items() if gg == g)
        for i, kk in assign(tiles, [(clusters[k].xy, target[k]) for k in ks], weighted=True).items():
            owner[i] = ks[kk]
            regions[ks[kk]].append(i)

    # contiguity repair: keep the piece holding the metro seed (else the largest; ties ->
    # nearest the anchor), release the strays
    seed = dict(zip(heads, seeds))
    for k in range(len(clusters)):
        comps = _components(regions[k], adjacency)
        if len(comps) > 1:
            keep = min(comps, key=lambda c: (seed.get(k) not in c, -len(c), min(dist2(k, i) for i in c), min(c)))
            for c in comps:
                if c is not keep:
                    for i in c:
                        owner[i] = None
            regions[k] = keep

    def claim_next(k: int, detach: bool = False) -> bool:
        frontier = {j for i in regions[k] for j in adjacency[i] if owner[j] is None}
        if not frontier:
            if regions[k] and not detach:
                return False  # walled in
            frontier = {i for i in range(n) if owner[i] is None}
            if not frontier:
                return False  # state has fewer tiles than urban seats (partial tiling)
        pick = min(frontier, key=lambda i: (dist2(k, i), i))
        owner[pick] = k
        regions[k].append(pick)
        return True

    short = []
    for k in range(len(clusters)):
        while len(regions[k]) < target[k] and claim_next(k):
            pass
        if len(regions[k]) < clusters[k].seats:
            short.append((k, clusters[k].seats - len(regions[k])))

    extra = [0] * len(clusters)
    pool = sum(s for _, s in short)
    for k in range(len(clusters)):
        while pool and claim_next(k):
            extra[k] += 1
            pool -= 1
    detached = 0
    while pool and clusters and claim_next(0, detach=True):
        extra[0] += 1
        detached += 1
        pool -= 1
    recipients = tuple((clusters[k].name, s) for k, s in enumerate(extra) if s)
    # only regions that ended short report a spill (a partial tiling has no room to spill into)
    spills = [
        UrbanSpill(clusters[k].name, clusters[k].seats, clusters[k].seats - s, recipients, detached)
        for k, s in short if recipients
    ]

    labels: list[UrbanLabel | None] = [None] * n
    for k, region in enumerate(regions):
        for rank, i in enumerate(sorted(region, key=lambda i: (dist2(k, i), i))):
            labels[i] = UrbanLabel(clusters[k].name, rank, len(region))
    return labels, spills
