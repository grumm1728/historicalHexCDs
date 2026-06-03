#!/usr/bin/env python3
"""Allocate hex cells to states from a national grid (Voronoi-style around real
Census centroids), then partition each state's cells into pentahex CD tiles.

Outputs:
  - data_processed/polyhex_cds_by_congress/<n>.geojson         (one Feature per CD)
  - data_processed/polyhex_states_by_congress/<n>.geojson      (state-level dissolve)
  - data_processed/state_outlines_by_congress/<n>.geojson      (per-Congress real + scaled outlines)
  - data_processed/polyhex_states_by_congress/_index.json      (timeline summary)
  - data_processed/tiling_warnings.json                        (partial/fallback rows)

Algorithm (HexCDv31-style cartogram via scaled outlines):
1. For each Congress, scale each state's real outline so its area equals
   `seats * 5 * hex_area`, around the state's real centroid (compute_scaled_layout).
   Then iteratively push apart any overlapping pairs so the final layout is
   non-overlapping while preserving roughly real-world relative positions.
2. If the resulting layout extends beyond the base hex grid bbox, in-memory
   expand the grid (same R/origin, more axial cells) so every state has room.
3. Allocate a contiguous territory of exactly `seats * 5` cells per state by
   point-in-polygon against the scaled+displaced outlines (build_cell_outline_map +
   allocate_territories). Because each scaled outline holds approximately the
   right number of cells, territories almost always fit inside their own state's
   region — minimal outward inflation, no boxing.
4. Partition each territory into pentahex (5-hex) tiles via region-growing from
   boundary cells (partition_into_pentahexes).
5. Render tiles as the union of their 5 hexes. Border tiles (those touching the
   territory edge) are additionally clipped to the scaled state outline so the
   outline snaps to tile edges, reproducing HexCDv31wm's look. Interior tiles are
   left as plain hex unions (render_tile).
"""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

from shapely.affinity import scale as shapely_scale, translate as shapely_translate
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v6-pentahex-scaled-outlines"

NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

# Northeast cluster: small, seat-dense states that jam together once scaled to
# delegation size. compute_scaled_layout gives this cluster a local radial
# expansion so the crammed states get room to breathe, without warping the rest
# of the (geographic) layout. FIPS: CT DE DC ME MD MA NH NJ NY PA RI VT.
NE_FIPS = frozenset({"09", "10", "11", "23", "24", "25", "33", "34", "36", "42", "44", "50"})
# 1.25 is the strongest local expansion that stays warning-free across all 119
# Congresses; 1.3 reshapes early Massachusetts (14 seats) into an un-tileable blob.
NE_EXPAND = 1.25

# States whose land is split across open water by the Great Lakes clip and so must be
# allocated as multiple connected components (each a multiple of 5 hexes) rather than one
# blob. Scope today: Michigan ("26") = Upper + Lower Peninsula. Gated to this set so the
# multi-component path never perturbs island states (NY/MA/HI/AK/...) that tile fine today.
MULTI_COMPONENT_FIPS = frozenset({"26"})


def congress_start_date(congress_number: int) -> date:
    year = 1789 + (congress_number - 1) * 2
    if congress_number >= 74:
        return date(year, 1, 3)
    return date(year, 3, 4)


def congress_end_date(congress_number: int) -> date:
    return congress_start_date(congress_number + 1) - timedelta(days=1)


def load_seats(path: Path) -> dict[int, list[dict]]:
    by_congress: dict[int, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            by_congress[int(row["congress_number"])].append(row)
    return by_congress


def load_outlines(path: Path) -> dict[str, dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for f in obj["features"]:
        fips = str(f["properties"]["state_fips"]).zfill(2)
        geom = shape(f["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        rep = geom.representative_point()
        f["_geom"] = geom
        f["_centroid"] = (rep.x, rep.y)
        out[fips] = f
    return out


def load_hex_grid(geojson_path: Path, meta_path: Path) -> tuple[dict, dict, dict]:
    grid = json.loads(geojson_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    hex_by_qr: dict[tuple[int, int], dict] = {}
    for f in grid["features"]:
        q = int(f["properties"]["q"])
        r = int(f["properties"]["r"])
        cx = float(f["properties"]["cx"])
        cy = float(f["properties"]["cy"])
        f["_geom"] = shape(f["geometry"])
        f["_qr"] = (q, r)
        f["_xy"] = (cx, cy)
        hex_by_qr[(q, r)] = f
    return grid, meta, hex_by_qr


def hex_area_from_R(R: float) -> float:
    return 1.5 * math.sqrt(3.0) * (R ** 2)


def _round_geojson_coords(obj: object, precision: int = 1) -> object:
    """Recursively round all coordinate values in a GeoJSON geometry or feature list.

    Shapely's mapping() emits full float64 precision (~15 sig figs).  Web Mercator
    coordinates at 960 px wide only need 1 decimal place (0.1 m ≈ 0.00002 px).
    Rounding here cuts per-file sizes by ~35% with no visible effect.
    """
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)) and not isinstance(obj[0], bool):
            return [round(v, precision) for v in obj]
        return [_round_geojson_coords(item, precision) for item in obj]
    if isinstance(obj, dict):
        if "coordinates" in obj:
            return {**obj, "coordinates": _round_geojson_coords(obj["coordinates"], precision)}
        return {k: _round_geojson_coords(v, precision) for k, v in obj.items()}
    return obj


def write_geojson_with_retry(path: Path, common_props: dict, features: list, attempts: int = 12) -> None:
    """Write a GeoJSON FeatureCollection, retrying on transient Windows OSError 22.

    The pentahex regen writes 357 files in a tight loop; Windows occasionally
    returns EINVAL on the very next open() if antivirus or the file indexer is
    still holding a handle from a recently written file. To dodge that race we
    write to a temp sibling (a fresh handle nothing is scanning) and atomically
    os.replace() it onto the target, with an escalating sleep-and-retry.
    """
    import os as _os
    import time as _time
    rounded = _round_geojson_coords(features, precision=1)
    payload = json.dumps({"type": "FeatureCollection", "properties": common_props, "features": rounded})
    tmp = path.with_name(path.name + ".tmp")
    last_err: OSError | None = None
    for i in range(attempts):
        try:
            tmp.write_text(payload, encoding="utf-8")
            _os.replace(tmp, path)
            return
        except OSError as e:
            last_err = e
            _time.sleep(min(0.25 * (i + 1), 2.0))
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    if last_err is not None:
        raise last_err


def neighbors(qr: tuple[int, int]) -> list[tuple[int, int]]:
    q, r = qr
    return [(q + dq, r + dr) for dq, dr in NEIGHBOR_OFFSETS]


def squared_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def compute_scaled_layout(
    seat_by_fips: dict[str, int],
    outlines: dict[str, dict],
    hex_area: float,
    R: float,
    max_iter: int = 1000,
    ne_expand: float = NE_EXPAND,
) -> dict[str, dict]:
    """Scale each state's outline to delegation size, then resolve overlaps.

    For each admitted state:
      - target_area = seats * 5 * hex_area
      - area_scale  = sqrt(target_area / real_area)
      - geom is scaled around the state's real centroid

    The Northeast cluster (NE_FIPS) is then given a local radial expansion by
    `ne_expand` (positions pushed out from the seat-weighted NE centroid) so those
    crammed small states get maneuvering room. This is a placement-only nudge local
    to the NE; the rest of the map stays geographic and the overlap-resolver below
    absorbs the push where the cluster meets its inland neighbours.

    Then iteratively pick the most-overlapping pair of states and push both
    halfway apart along their centroid-to-centroid vector until separation
    reaches `target_gap = 0.5 * R`. Iterative pairwise displacement: simple,
    deterministic, and converges fast for these dozens of polygons.

    Returns fips -> dict with:
      geom (Shapely scaled+displaced),
      centroid (post-displacement, used as the state's pull-anchor),
      anchor   (original real centroid, the scale center),
      scale    (area_scale used),
      displacement (dx, dy applied after scaling).
    """
    target_gap = 0.5 * R
    layout: dict[str, dict] = {}
    for fips, seats in seat_by_fips.items():
        outline_feat = outlines.get(fips)
        if outline_feat is None or seats <= 0:
            continue
        real_geom = outline_feat["_geom"]
        real_area = real_geom.area
        if real_area <= 0:
            continue
        cx, cy = outline_feat["_centroid"]
        target_area = seats * 5 * hex_area
        scale = math.sqrt(target_area / real_area)
        scaled = shapely_scale(real_geom, xfact=scale, yfact=scale, origin=(cx, cy))
        if not scaled.is_valid:
            scaled = scaled.buffer(0)
        layout[fips] = {
            "geom": scaled,
            "centroid": (cx, cy),
            "anchor": (cx, cy),
            "scale": scale,
            "displacement": (0.0, 0.0),
        }

    fips_list = list(layout)

    def displace(fips: str, dx: float, dy: float) -> None:
        rec = layout[fips]
        rec["geom"] = shapely_translate(rec["geom"], xoff=dx, yoff=dy)
        cx, cy = rec["centroid"]
        rec["centroid"] = (cx + dx, cy + dy)
        ddx, ddy = rec["displacement"]
        rec["displacement"] = (ddx + dx, ddy + dy)

    # Targeted Northeast de-jam: spread the NE cluster outward from its seat-weighted
    # centroid before overlap resolution, so its small dense states (RI, CT, DE, NJ…)
    # start with room instead of being relaxed into a tight jam.
    ne_members = [f for f in fips_list if f in NE_FIPS]
    if ne_expand != 1.0 and ne_members:
        sw = sum(seat_by_fips[f] for f in ne_members)
        ncx = sum(layout[f]["centroid"][0] * seat_by_fips[f] for f in ne_members) / sw
        ncy = sum(layout[f]["centroid"][1] * seat_by_fips[f] for f in ne_members) / sw
        for f in ne_members:
            cx, cy = layout[f]["centroid"]
            displace(f, (ne_expand - 1.0) * (cx - ncx), (ne_expand - 1.0) * (cy - ncy))

    for _ in range(max_iter):
        # Find the most-overlapping pair (largest intersection area).
        worst: tuple[str, str] | None = None
        worst_area = 0.0
        # STRtree against current geoms for O(N log N) candidate filtering.
        geoms = [layout[f]["geom"] for f in fips_list]
        tree = STRtree(geoms)
        for i, a in enumerate(fips_list):
            ga = geoms[i]
            for j in tree.query(ga):
                if j <= i:
                    continue
                b = fips_list[j]
                gb = geoms[j]
                if not ga.intersects(gb):
                    continue
                inter_area = ga.intersection(gb).area
                if inter_area > worst_area:
                    worst_area = inter_area
                    worst = (a, b)
        if worst is None:
            break
        a, b = worst
        ax, ay = layout[a]["centroid"]
        bx, by = layout[b]["centroid"]
        dx, dy = ax - bx, ay - by
        dist_sq = dx * dx + dy * dy
        if dist_sq < 1e-9:
            # Coincident centroids — pick an arbitrary axis to break symmetry.
            dx, dy = 1.0, 0.0
            dist = 1.0
        else:
            dist = math.sqrt(dist_sq)
            dx /= dist
            dy /= dist
        # Small symmetric nudge per iteration. Large per-iter pushes overshoot
        # and cascade — small nudges relax the layout smoothly. Step adapts to
        # overlap magnitude: bigger overlaps get bigger nudges but capped so a
        # single iteration never displaces a state by more than target_gap.
        overlap_diameter = 2.0 * math.sqrt(worst_area / math.pi)
        step = min(0.5 * target_gap, 0.25 * overlap_diameter + 0.25 * target_gap)
        half = step * 0.5
        displace(a, dx * half, dy * half)
        displace(b, -dx * half, -dy * half)

    return layout


def expand_grid_if_needed(
    hex_by_qr: dict[tuple[int, int], dict],
    R: float,
    origin: tuple[float, float],
    target_bbox: tuple[float, float, float, float],
    margin: float = 0.0,
) -> None:
    """Add hex cells to `hex_by_qr` in-place to cover `target_bbox` (xmin,ymin,xmax,ymax).

    Uses the same axial-coord scheme as scripts/build_hex_grid.py so existing cell
    (q, r) indices remain valid. New cells get full _geom / _qr / _xy attrs.
    """
    xmin, ymin, xmax, ymax = target_bbox
    xmin -= margin
    ymin -= margin
    xmax += margin
    ymax += margin
    ox, oy = origin
    xstep = R * 1.5
    ystep = R * math.sqrt(3.0)

    # Axial index ranges to cover the expanded bbox; mirrors build_hex_grid.main().
    q_lo = int(math.floor((xmin - ox) / xstep)) - 1
    q_hi = int(math.ceil((xmax - ox) / xstep)) + 1

    for q in range(q_lo, q_hi + 1):
        # y depends on r + q/2; reconstruct r-range from the y bbox.
        y_offset = oy + R * math.sqrt(3.0) * (q / 2.0)
        r_lo = int(math.floor((ymin - y_offset) / ystep)) - 1
        r_hi = int(math.ceil((ymax - y_offset) / ystep)) + 1
        for r in range(r_lo, r_hi + 1):
            qr = (q, r)
            if qr in hex_by_qr:
                continue
            cx = ox + R * 1.5 * q
            cy = oy + R * math.sqrt(3.0) * (r + q / 2.0)
            if cx < xmin - R or cx > xmax + R:
                continue
            if cy < ymin - R or cy > ymax + R:
                continue
            # Build a flat-top hex polygon (matches build_hex_grid.hex_polygon).
            ring: list[list[float]] = []
            for k in range(6):
                a = math.radians(60.0 * k)
                ring.append([round(cx + R * math.cos(a), 3), round(cy + R * math.sin(a), 3)])
            ring.append(ring[0])
            poly = Polygon(ring)
            feat = {
                "type": "Feature",
                "properties": {"q": q, "r": r, "cx": cx, "cy": cy, "R": R},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "_geom": poly,
                "_qr": qr,
                "_xy": (cx, cy),
            }
            hex_by_qr[qr] = feat


def build_cell_outline_map(
    hex_by_qr: dict[tuple[int, int], dict],
    outlines: dict[str, dict],
    geom_key: str = "_geom",
) -> dict[tuple[int, int], str]:
    """Map each hex cell to the FIPS of the state outline its center falls in.

    `outlines` is fips -> feature-or-record dict; the polygon is read from
    `record[geom_key]`. Cells whose center lies in no outline (ocean / foreign
    land / between displaced states) are omitted.
    """
    items = [(fips, feat[geom_key]) for fips, feat in outlines.items()]
    fips_list = [fips for fips, _ in items]
    geoms = [g for _, g in items]
    tree = STRtree(geoms)
    out: dict[tuple[int, int], str] = {}
    for qr, feat in hex_by_qr.items():
        pt = Point(feat["_xy"])
        for i in tree.query(pt):
            if geoms[i].contains(pt):
                out[qr] = fips_list[i]
                break
    return out


def _connected_components(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """Split a cell set into connected components (hex adjacency)."""
    remaining = set(cells)
    comps: list[set[tuple[int, int]]] = []
    while remaining:
        start = next(iter(remaining))
        comp = {start}
        queue = deque([start])
        remaining.discard(start)
        while queue:
            cur = queue.popleft()
            for nb in neighbors(cur):
                if nb in remaining:
                    remaining.discard(nb)
                    comp.add(nb)
                    queue.append(nb)
        comps.append(comp)
    return comps


def _split_targets_multiple_of_5(sizes: list[int], total: int) -> list[int]:
    """Distribute `total` cells (a multiple of 5) across components as multiples of 5,
    proportional to each component's own-cell count. Used for states whose land splits
    across water (e.g. Michigan's Upper/Lower Peninsula) so each side gets a whole number
    of pentahexes and no tile straddles the gap."""
    units = total // 5
    span = sum(sizes) or 1
    base = [int(round(s / span * units)) for s in sizes]
    diff = units - sum(base)
    order = sorted(range(len(sizes)), key=lambda i: sizes[i], reverse=True)
    k = 0
    while diff != 0 and order:
        i = order[k % len(order)]
        if diff > 0:
            base[i] += 1
            diff -= 1
        elif base[i] > 0:
            base[i] -= 1
            diff += 1
        k += 1
    return [b * 5 for b in base]


def allocate_territories(
    need: dict[str, int],
    centroid_by_fips: dict[str, tuple[float, float]],
    cell_outline_fips: dict[tuple[int, int], str],
    hex_by_qr: dict[tuple[int, int], dict],
    steal_exempt: frozenset[str] = frozenset(),
) -> dict[str, set[tuple[int, int]]]:
    """Grow a contiguous territory of exactly `need[fips]` cells for each state.

    Process states smallest-need-first so tiny dense states (e.g. Delaware) lock
    in a compact, connected territory before bigger neighbors inflate around them.
    Each state is seeded with the unclaimed cell nearest its centroid (preferring
    cells inside its own outline) and then grown to its full `need` by repeatedly
    claiming the frontier cell with the best preference tier, then closest to its
    centroid. Frontier cells are ranked in three tiers:
      0. inside this state's own scaled outline,
      1. inside no state's outline (ocean / foreign land / gaps between states),
      2. inside ANOTHER admitted state's outline — taken only as a last resort.

    Tier 2 keeps a state from cannibalising a neighbour's cells just because they
    sit nearer its centroid: without it, a small state allocated early inflates
    straight through a big neighbour's region (e.g. VA/OH/WV eating PA's southern
    cells), leaving the big state to undershoot its own outline. Growth only ever
    takes cells adjacent to the existing territory, so each territory stays
    connected; if a state is fully boxed in before reaching `need` it stops
    (leaving a smaller, still-connected territory) rather than grabbing a far cell.

    States in `steal_exempt` skip the tier-2 penalty (free and another-state cells
    rank equally, tier 1). The caller exempts states whose strict-tier territory
    is an un-tileable shape: forbidding theft can force a small, fragmented coastal
    state (e.g. MD across the Chesapeake) onto scattered, spurred cells that no set
    of connected pentahexes can cover. Letting such a state reclaim nearby cells
    restores a compact, tileable blob.
    """
    cells_by_state: dict[str, set[tuple[int, int]]] = {fips: set() for fips in need}
    inside: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for qr, fips in cell_outline_fips.items():
        if fips in need:
            inside[fips].add(qr)

    unclaimed: set[tuple[int, int]] = set(hex_by_qr.keys())

    # Smallest-need states first so tiny dense states lock in compact, connected
    # territory before bigger neighbors inflate around them.
    order = sorted(need, key=lambda f: (need[f], f))

    for fips in order:
        if not unclaimed:
            break
        center = centroid_by_fips[fips]
        own_inside = inside.get(fips, frozenset())
        cells = cells_by_state[fips]

        exempt = fips in steal_exempt

        def cell_tier(qr: tuple[int, int]) -> int:
            owner = cell_outline_fips.get(qr)
            if owner == fips:
                return 0  # this state's own outline
            if owner is None or exempt:
                return 1  # free to take (or this state is exempt from the anti-steal rule)
            return 2  # inside another admitted state's outline — last resort

        def grow_region(count: int, seed_pool: list[tuple[int, int]]) -> None:
            """Seed at the nearest cell in `seed_pool`, then add `count` connected cells
            via frontier expansion (tiered preference). Growth is confined to the region
            grown from this seed, so a later call for a separate component never re-grows
            an earlier one."""
            if not seed_pool or count <= 0:
                return
            seed = min(seed_pool, key=lambda qr: squared_dist(hex_by_qr[qr]["_xy"], center))
            region = {seed}
            cells.add(seed)
            unclaimed.discard(seed)
            while len(region) < count:
                frontier: set[tuple[int, int]] = set()
                for c in region:
                    for nb in neighbors(c):
                        if nb in unclaimed:
                            frontier.add(nb)
                if not frontier:
                    break  # boxed in; leave a smaller connected territory
                chosen = min(
                    frontier,
                    key=lambda qr: (cell_tier(qr), squared_dist(hex_by_qr[qr]["_xy"], center)),
                )
                region.add(chosen)
                cells.add(chosen)
                unclaimed.discard(chosen)

        # States whose land splits across water (Michigan's Upper/Lower Peninsula, once
        # the Great Lakes are clipped out of the outline) have own-outline cells in two+
        # disconnected components. A single connected growth can only fill one; worse, it
        # would spill into the lake gap (tier-1 water) to reach `need`. Instead, give each
        # component a multiple-of-5 share and grow it independently. Because the components
        # are not hex-adjacent, no pentahex can straddle the gap and each side tiles cleanly.
        own_components = (
            _connected_components(set(own_inside))
            if own_inside and fips in MULTI_COMPONENT_FIPS
            else []
        )
        if len(own_components) > 1:
            own_components.sort(key=len, reverse=True)
            targets = _split_targets_multiple_of_5([len(c) for c in own_components], need[fips])
            for comp, target in zip(own_components, targets):
                if target <= 0:
                    continue
                comp_unclaimed = [qr for qr in comp if qr in unclaimed]
                grow_region(target, comp_unclaimed)
        else:
            # Single-component (the common case): nearest own cell, else nearest free
            # cell, else the globally nearest unclaimed cell; grow to full need.
            own_unclaimed = [qr for qr in own_inside if qr in unclaimed]
            if own_unclaimed:
                pool = own_unclaimed
            else:
                free_unclaimed = [qr for qr in unclaimed if qr not in cell_outline_fips]
                pool = free_unclaimed if free_unclaimed else list(unclaimed)
            grow_region(need[fips], pool)

    return cells_by_state


def place_pentahex_tiles(
    seat_by_fips: dict[str, int],
    centroid_by_fips: dict[str, tuple[float, float]],
    cell_outline_fips: dict[tuple[int, int], str],
    hex_by_qr: dict[tuple[int, int], dict],
) -> tuple[dict[str, list[list[tuple[int, int]]]], dict[str, str]]:
    """Allocate an outline-guided territory per state, then tile each as pentahexes.

    Returns:
      tiles_by_state: list of 5-hex tiles per state (length == seats on success)
      statuses:       "ok" | "partial" | "skipped" | "no-tiles" per state
    """
    statuses: dict[str, str] = {}
    tiles_by_state: dict[str, list[list[tuple[int, int]]]] = {fips: [] for fips in seat_by_fips}
    need = {fips: seat_by_fips[fips] * 5 for fips in seat_by_fips if seat_by_fips[fips] > 0}
    if not need:
        return tiles_by_state, {f: "skipped" for f in seat_by_fips}

    # Allocate, then tile. The anti-steal rule (see allocate_territories) can hand a
    # small fragmented state an un-tileable shape; when that happens we exempt the
    # offending state(s) and re-allocate, since the theft-allowed growth yields a
    # compact, tileable blob. This converges: in the worst case every state is
    # exempt, which reproduces the original theft-allowed allocation. The exempt
    # set only grows, so each pass strictly reduces the failure set or stops.
    steal_exempt: frozenset[str] = frozenset()
    max_passes = len(need) + 1
    for _ in range(max_passes):
        cells_by_state = allocate_territories(
            need, centroid_by_fips, cell_outline_fips, hex_by_qr, steal_exempt=steal_exempt
        )
        tiles_by_state = {fips: [] for fips in seat_by_fips}
        for fips in need:
            cells = cells_by_state[fips]
            if not cells:
                continue
            boundary = {c for c in cells if any(nb not in cells for nb in neighbors(c))}
            tiles = partition_into_pentahexes(cells, boundary, use_compact=True)
            if len(tiles) * 5 != len(cells):
                # Compact growth dead-ended on a tileable shape; retry with the proven
                # original heuristic so this state still tiles (keeps warnings at 0).
                tiles = partition_into_pentahexes(cells, boundary, use_compact=False)
            tiles_by_state[fips] = tiles

        # A state "fails" when its assigned cells were not fully tiled (and it isn't
        # already exempt). Exempt those and re-run; a state boxed in below `need`
        # (genuinely partial) can't be helped by exemption, so don't loop on it.
        newly_failing = {
            fips
            for fips in need
            if fips not in steal_exempt
            and len(cells_by_state[fips]) == need[fips]
            and len(tiles_by_state[fips]) * 5 != len(cells_by_state[fips])
        }
        if not newly_failing:
            break
        steal_exempt = steal_exempt | newly_failing

    # Cosmetic post-pass: de-stick non-compact pentahexes via border-cell swaps. Safe by
    # construction (preserves the size-5/connected partition), so it never affects status.
    for fips in need:
        if len(tiles_by_state[fips]) > 1:
            tiles_by_state[fips] = refine_tiles_compactness(tiles_by_state[fips])

    for fips, seats in seat_by_fips.items():
        if seats <= 0:
            statuses[fips] = "skipped"
        elif len(tiles_by_state[fips]) == seats:
            statuses[fips] = "ok"
        elif len(tiles_by_state[fips]) == 0:
            statuses[fips] = "no-tiles"
        else:
            statuses[fips] = "partial"

    return tiles_by_state, statuses


def is_partition_feasible(avail: set[tuple[int, int]]) -> bool:
    """Each connected component of `avail` must have a multiple-of-5 size."""
    if not avail:
        return True
    seen: set[tuple[int, int]] = set()
    for start in avail:
        if start in seen:
            continue
        comp_size = 0
        queue = deque([start])
        seen.add(start)
        while queue:
            cur = queue.popleft()
            comp_size += 1
            for nb in neighbors(cur):
                if nb in avail and nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        if comp_size % 5 != 0:
            return False
    return True


def partition_into_pentahexes(
    cells: set[tuple[int, int]],
    boundary_cells: set[tuple[int, int]],
    use_compact: bool = True,
) -> list[list[tuple[int, int]]]:
    """Partition `cells` into connected groups of 5. Returns [] on failure.

    With `use_compact`, the greedy growth prefers candidates that touch more of the current
    tile (rounder pentahexes). That heuristic occasionally dead-ends on a tileable shape;
    callers retry with `use_compact=False` (the original anti-stranding-only growth, which
    is the proven, more permissive heuristic) before treating a state as un-tileable.
    """
    if not cells or len(cells) % 5 != 0:
        return []

    def external_degree(c: tuple[int, int], avail: set[tuple[int, int]]) -> int:
        return sum(1 for nb in neighbors(c) if nb not in avail)

    def grow_one(avail: set[tuple[int, int]], seed: tuple[int, int]) -> list[tuple[int, int]] | None:
        tile = [seed]
        used = {seed}
        while len(tile) < 5:
            if not use_compact:
                # Original, proven growth: lowest available-degree neighbour (ties broken by
                # iteration order via stable sort). This is the warning-free fallback.
                cands: list[tuple[int, tuple[int, int]]] = []
                for c in tile:
                    for nb in neighbors(c):
                        if nb in avail and nb not in used:
                            deg = sum(1 for n2 in neighbors(nb) if n2 in avail and n2 not in used)
                            cands.append((deg, nb))
                if not cands:
                    return None
                cands.sort(key=lambda t: t[0])
                chosen = cands[0][1]
            else:
                # Compact growth: among equal-degree candidates, prefer the one touching the
                # most current-tile cells, pulling the tile into a blob instead of a stick.
                cand_deg: dict[tuple[int, int], int] = {}
                cand_internal: dict[tuple[int, int], int] = {}
                for c in tile:
                    for nb in neighbors(c):
                        if nb in avail and nb not in used and nb not in cand_deg:
                            cand_deg[nb] = sum(1 for n2 in neighbors(nb) if n2 in avail and n2 not in used)
                            cand_internal[nb] = sum(1 for n2 in neighbors(nb) if n2 in used)
                if not cand_deg:
                    return None
                chosen = min(cand_deg, key=lambda nb: (cand_deg[nb], -cand_internal[nb], nb))
            tile.append(chosen)
            used.add(chosen)
        return tile

    avail = set(cells)
    tiles: list[list[tuple[int, int]]] = []
    while avail:
        seed_candidates = sorted(
            avail,
            key=lambda c: (
                -1 if c in boundary_cells else 0,
                -external_degree(c, avail),
            ),
        )
        chosen_tile = None
        for cand_seed in seed_candidates[:12]:
            tile = grow_one(avail, cand_seed)
            if tile is None:
                continue
            if is_partition_feasible(avail - set(tile)):
                chosen_tile = tile
                break
        if chosen_tile is None:
            return tiles  # partial
        tiles.append(chosen_tile)
        avail -= set(chosen_tile)
    return tiles


def _tile_internal_edges(tile: set[tuple[int, int]]) -> int:
    """Number of shared hex edges among the cells of one tile (compactness score).

    A straight line of 5 has 4 internal edges; a compact blob has 6-7. Higher = rounder.
    """
    edges = 0
    for c in tile:
        for nb in neighbors(c):
            if nb in tile:
                edges += 1
    return edges // 2


def _cells_connected(cells: set[tuple[int, int]]) -> bool:
    if not cells:
        return True
    start = next(iter(cells))
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nb in neighbors(cur):
            if nb in cells and nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return len(seen) == len(cells)


def refine_tiles_compactness(
    tiles: list[list[tuple[int, int]]],
    max_rounds: int = 8,
) -> list[list[tuple[int, int]]]:
    """Improve tile compactness by swapping border cells between adjacent tiles.

    Starts from a valid partition and only performs A<->B single-cell exchanges that keep
    BOTH tiles size-5 and connected while raising total internal-adjacency. Because every
    move preserves "size-5 + connected" for both tiles, the result is always still a valid
    pentahex partition: this pass can never make a state un-tileable (warnings stay 0).
    """
    if len(tiles) < 2:
        return tiles
    tile_sets = [set(t) for t in tiles]
    # Territory-edge cells are clipped to the state outline at render time, so moving them
    # between tiles can shove a tile's hexes into clipped-away overshoot and leave a sliver
    # district. Only swap interior cells: the state's outer silhouette (the clipped union)
    # is then identical, so no slivers, while interior sticks still get rounded out.
    all_cells = set().union(*tile_sets)
    edge_cells = {c for c in all_cells if any(nb not in all_cells for nb in neighbors(c))}
    for _ in range(max_rounds):
        # Owner map -> only the tile pairs that actually touch are worth examining
        # (all-pairs is O(tiles^2) and dominates runtime; adjacent pairs are ~linear).
        owner: dict[tuple[int, int], int] = {}
        for idx, ts in enumerate(tile_sets):
            for c in ts:
                owner[c] = idx
        adjacent_pairs: set[tuple[int, int]] = set()
        for c, idx in owner.items():
            for nb in neighbors(c):
                j = owner.get(nb)
                if j is not None and j != idx:
                    adjacent_pairs.add((idx, j) if idx < j else (j, idx))

        improved = False
        for i, j in adjacent_pairs:
            a_set, b_set = tile_sets[i], tile_sets[j]
            a_cands = [a for a in a_set if a not in edge_cells and any(nb in b_set for nb in neighbors(a))]
            b_cands = [b for b in b_set if b not in edge_cells and any(nb in a_set for nb in neighbors(b))]
            base = _tile_internal_edges(a_set) + _tile_internal_edges(b_set)
            best = None
            for a in a_cands:
                for b in b_cands:
                    new_a = (a_set - {a}) | {b}
                    new_b = (b_set - {b}) | {a}
                    if not _cells_connected(new_a) or not _cells_connected(new_b):
                        continue
                    score = _tile_internal_edges(new_a) + _tile_internal_edges(new_b)
                    if score > base and (best is None or score > best[0]):
                        best = (score, new_a, new_b)
            if best is not None:
                tile_sets[i] = best[1]
                tile_sets[j] = best[2]
                improved = True
        if not improved:
            break
    return [list(s) for s in tile_sets]


def _as_multipolygon(geom):
    """Normalize a Shapely geometry to a MultiPolygon, dropping non-areal parts."""
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    flat: list[Polygon] = []
    for g in getattr(geom, "geoms", []):
        if isinstance(g, Polygon):
            flat.append(g)
        elif isinstance(g, MultiPolygon):
            flat.extend(list(g.geoms))
    return MultiPolygon(flat) if flat else geom


def render_tile(
    tile: list[tuple[int, int]],
    hex_by_qr: dict[tuple[int, int], dict],
    clip_geom=None,
):
    """Render a 5-hex tile as a MultiPolygon.

    Interior tiles (clip_geom is None) are the plain union of their hexes.
    Boundary tiles pass the scaled state outline as `clip_geom`; the union is
    intersected with it so the outline snaps to tile edges (HexCDv31wm's look).
    The clip may yield a MultiPolygon for complex coasts (Long Island, the SF
    peninsula, NJ islands) — that's expected. If a boundary tile lies (almost)
    entirely outside the outline — possible when the allocator inflated past the
    state's region — the clip would erase the CD, so we keep the plain union to
    preserve tile integrity.
    """
    polys = [hex_by_qr[qr]["_geom"] for qr in tile]
    union = unary_union(polys)
    if not union.is_valid:
        union = union.buffer(0)
    if clip_geom is not None:
        clipped = union.intersection(clip_geom)
        if not clipped.is_valid:
            clipped = clipped.buffer(0)
        if not clipped.is_empty and clipped.area > 0:
            union = clipped
    return _as_multipolygon(union)


def _nearest_tile_split(comp, adj, geoms, R):
    """Split one residual component `comp` among adjacent tiles `adj` (indices into
    `geoms`) by nearest tile. Returns {tile_index: geometry}.

    Implemented as a Voronoi diagram over points sampled along the adjacent tiles'
    boundaries, labelled by tile; each Voronoi cell (the region nearest its seed)
    is intersected with `comp` and accumulated onto that seed's tile. This spreads
    a wide undershoot strip across every tile that faces it instead of dumping it
    on one — keeping per-CD areas closer to five hexes.
    """
    seeds: list[Point] = []
    label: list[int] = []
    for i in adj:
        g = geoms[i]
        for poly in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
            bdry = poly.exterior
            steps = max(6, int(bdry.length / (0.3 * R)))
            for k in range(steps):
                seeds.append(bdry.interpolate(k / steps, normalized=True))
                label.append(i)
    if len(seeds) < 2:
        return {adj[0]: comp}
    try:
        vor = voronoi_diagram(MultiPoint(seeds), envelope=comp.buffer(R).envelope)
    except Exception:
        return {adj[0]: comp}
    seed_tree = STRtree(seeds)
    shares: dict[int, object] = {}
    for cell in vor.geoms:
        piece = cell.intersection(comp)
        if piece.is_empty or piece.area <= 0:
            continue
        owner = None
        for si in seed_tree.query(cell):
            if cell.contains(seeds[int(si)]):
                owner = label[int(si)]
                break
        if owner is None:
            q = seed_tree.query(cell)
            owner = label[int(q[0])] if len(q) else adj[0]
        shares[owner] = piece if owner not in shares else unary_union([shares[owner], piece])
    return shares or {adj[0]: comp}


def render_state_tiles(
    tiles: list[list[tuple[int, int]]],
    hex_by_qr: dict[tuple[int, int], dict],
    scaled_outline,
    boundary_cells: set[tuple[int, int]],
    R: float,
    hex_area: float,
):
    """Render every tile of one state, snapping the state to its scaled outline.

    Each tile starts as its (boundary-clipped) hex geometry via render_tile. The
    union of those clipped tiles undershoots the outline by a thin perimeter strip
    plus the odd larger lobe (cells never reach a straight edge; the allocator may
    fall a few cells short of the outline's exact area). That residual gap is split
    back onto the tiles so the per-state union equals the outline (option-3 snap):
      - tiny slivers (the vast majority) merge into the adjacent tile with the
        longest shared edge;
      - rarer large components split across all adjacent tiles by nearest tile, so
        a wide undershoot strip is shared rather than dumped on one CD.
    Returns one MultiPolygon per input tile (parallel to `tiles`).
    """
    geoms = []
    for tile in tiles:
        touches = any(qr in boundary_cells for qr in tile)
        clip = scaled_outline if (touches and scaled_outline is not None) else None
        geoms.append(render_tile(tile, hex_by_qr, clip))
    if scaled_outline is None or not geoms:
        return geoms

    union = unary_union(geoms)
    residual = scaled_outline.difference(union)
    if not residual.is_valid:
        residual = residual.buffer(0)
    if residual.is_empty or residual.area <= 0:
        return geoms

    big_thresh = 0.4 * (5.0 * hex_area)
    small_buf = [g.buffer(0.1 * R) for g in geoms]
    tree = STRtree(small_buf)
    extra: list[list[object]] = [[] for _ in geoms]

    comps = (
        list(residual.geoms)
        if residual.geom_type.startswith("Multi") or residual.geom_type == "GeometryCollection"
        else [residual]
    )
    for comp in comps:
        if comp.is_empty or comp.area <= 0:
            continue
        adj = [int(i) for i in tree.query(comp) if small_buf[int(i)].intersects(comp)]
        if not adj:
            nearest = min(range(len(geoms)), key=lambda i: geoms[i].distance(comp))
            extra[nearest].append(comp)
        elif comp.area < big_thresh or len(adj) == 1:
            best = max(adj, key=lambda i: small_buf[i].intersection(comp).area)
            extra[best].append(comp)
        else:
            for i, piece in _nearest_tile_split(comp, adj, geoms, R).items():
                if piece is not None and not piece.is_empty and piece.area > 0:
                    extra[i].append(piece)

    out = []
    for g, ex in zip(geoms, extra):
        if not ex:
            out.append(g)
            continue
        merged = unary_union([g, *ex])
        if not merged.is_valid:
            merged = merged.buffer(0)
        out.append(_as_multipolygon(merged))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Allocate hex cells to states and tile each as pentahexes")
    parser.add_argument("--seats", default=str(ROOT / "data_processed" / "seats" / "state_seats_by_congress.csv"))
    parser.add_argument("--outlines", default=str(ROOT / "data_processed" / "states" / "state_outlines_modern_wm.geojson"))
    parser.add_argument("--hex-grid", default=str(ROOT / "data_processed" / "hex_grid" / "hex_grid.geojson"))
    parser.add_argument("--hex-grid-meta", default=str(ROOT / "data_processed" / "hex_grid" / "hex_grid_meta.json"))
    parser.add_argument("--cds-out-root", default=str(ROOT / "data_processed" / "polyhex_cds_by_congress"))
    parser.add_argument("--states-out-root", default=str(ROOT / "data_processed" / "polyhex_states_by_congress"))
    parser.add_argument("--outlines-out-root", default=str(ROOT / "data_processed" / "state_outlines_by_congress"))
    parser.add_argument("--warnings-out", default=str(ROOT / "data_processed" / "tiling_warnings.json"))
    args = parser.parse_args()

    seats_by_congress = load_seats(Path(args.seats))
    outlines = load_outlines(Path(args.outlines))
    grid, meta, hex_by_qr = load_hex_grid(Path(args.hex_grid), Path(args.hex_grid_meta))
    R = float(meta["R"])
    hex_area = hex_area_from_R(R)
    origin = tuple(meta["origin"])  # type: ignore[arg-type]

    cds_root = Path(args.cds_out_root)
    states_root = Path(args.states_out_root)
    outlines_root = Path(args.outlines_out_root)
    cds_root.mkdir(parents=True, exist_ok=True)
    states_root.mkdir(parents=True, exist_ok=True)
    outlines_root.mkdir(parents=True, exist_ok=True)

    warnings: list[dict] = []
    summary = {"generator_version": GENERATOR_VERSION, "timeline": []}

    for congress_number in sorted(seats_by_congress):
        seat_rows = seats_by_congress[congress_number]
        seat_by_fips: dict[str, int] = {}
        meta_by_fips: dict[str, dict] = {}
        centroid_by_fips: dict[str, tuple[float, float]] = {}
        for row in seat_rows:
            fips = str(row["state_fips"]).zfill(2)
            admitted = str(row["admitted"]).strip().lower() in {"1", "true", "t", "yes", "y"}
            seats = int(row["house_seats"])
            if not admitted or seats <= 0:
                continue
            outline_feat = outlines.get(fips)
            if outline_feat is None:
                warnings.append({"congress": congress_number, "state_fips": fips, "issue": "no-outline"})
                continue
            seat_by_fips[fips] = seats
            meta_by_fips[fips] = row

        # HexCDv31-style scaled outlines: scale each state to its delegation-size
        # area around its real centroid, then iteratively push overlapping pairs
        # apart so the layout is non-overlapping. The pre-allocator then sees a
        # set of outlines that already have ~the right cell count inside.
        layout = compute_scaled_layout(seat_by_fips, outlines, hex_area, R)

        # Expand the hex grid (in place) if the scaled+displaced layout reaches
        # past the current grid bbox; keeps tile size constant across Congresses.
        if layout:
            xs_min = min(rec["geom"].bounds[0] for rec in layout.values())
            ys_min = min(rec["geom"].bounds[1] for rec in layout.values())
            xs_max = max(rec["geom"].bounds[2] for rec in layout.values())
            ys_max = max(rec["geom"].bounds[3] for rec in layout.values())
            expand_grid_if_needed(hex_by_qr, R, origin, (xs_min, ys_min, xs_max, ys_max), margin=2 * R)

        # Build cell -> fips from scaled outlines, and use displaced centroids
        # as each state's pull-anchor inside the allocator.
        cell_outline_fips = build_cell_outline_map(hex_by_qr, layout, geom_key="geom")
        centroid_by_fips = {fips: rec["centroid"] for fips, rec in layout.items()}
        # States with no layout entry (missing/invalid outline) get no chance to tile.
        for f in seat_by_fips:
            if f not in centroid_by_fips and f in outlines:
                centroid_by_fips[f] = outlines[f]["_centroid"]

        tiles_by_state, statuses = place_pentahex_tiles(seat_by_fips, centroid_by_fips, cell_outline_fips, hex_by_qr)

        cd_features: list[dict] = []
        state_features: list[dict] = []
        outline_features: list[dict] = []
        cells_used_total = 0

        for fips, seats in seat_by_fips.items():
            outline_feat = outlines[fips]
            outline_geom = outline_feat["_geom"]
            layout_rec = layout.get(fips)
            # Scaled+displaced outline this state's border tiles get clipped to.
            scaled_outline = layout_rec["geom"] if layout_rec is not None else None
            tiles = tiles_by_state.get(fips, [])
            all_cells: set[tuple[int, int]] = set()
            for t in tiles:
                all_cells.update(t)
            cells_used_total += len(all_cells)

            boundary_cells: set[tuple[int, int]] = set()
            for c in all_cells:
                for nb in neighbors(c):
                    if nb not in all_cells:
                        boundary_cells.add(c)
                        break

            row = meta_by_fips[fips]
            # Render the whole state at once: clip boundary tiles to the scaled
            # outline, then redistribute the leftover gap so the state snaps to its
            # outline (option-3 snap-to-edge).
            tile_geoms = render_state_tiles(tiles, hex_by_qr, scaled_outline, boundary_cells, R, hex_area)
            cd_feats_for_state: list[dict] = []
            for idx, (tile, geom) in enumerate(zip(tiles, tile_geoms), start=1):
                touches_boundary = any(qr in boundary_cells for qr in tile)
                ratio = geom.area / (5.0 * hex_area) if hex_area > 0 else 0.0
                cd_feats_for_state.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "congress_number": congress_number,
                            "start_date": congress_start_date(congress_number).isoformat(),
                            "end_date": congress_end_date(congress_number).isoformat(),
                            "state_fips": fips,
                            "state_abbr": str(row["state_abbr"]).strip().upper(),
                            "state_name": str(row["state_name"]),
                            "house_seats": seats,
                            "cd_index": idx,
                            "hex_count": len(tile),
                            "is_boundary_tile": bool(touches_boundary),
                            "tile_area_ratio": ratio,
                            "source_seat_version": str(row.get("source_seat_version", "unknown")),
                            "generator_version": GENERATOR_VERSION,
                        },
                        "geometry": mapping(geom),
                    }
                )
            cd_features.extend(cd_feats_for_state)

            if cd_feats_for_state:
                state_geom = unary_union([shape(cd["geometry"]) for cd in cd_feats_for_state])
                if isinstance(state_geom, Polygon):
                    state_geom = MultiPolygon([state_geom])
                tiling_status = statuses.get(fips, "ok")
            else:
                state_geom = None
                tiling_status = "fallback-silhouette"

            if state_geom is not None and not state_geom.is_empty:
                state_features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "congress_number": congress_number,
                            "start_date": congress_start_date(congress_number).isoformat(),
                            "end_date": congress_end_date(congress_number).isoformat(),
                            "state_fips": fips,
                            "state_abbr": str(row["state_abbr"]).strip().upper(),
                            "state_name": str(row["state_name"]),
                            "house_seats": seats,
                            "admitted": True,
                            "cell_count": sum(cd["properties"]["hex_count"] for cd in cd_feats_for_state),
                            "cells_used": len(all_cells),
                            "tiling_status": tiling_status,
                            "source_seat_version": str(row.get("source_seat_version", "unknown")),
                            "source_boundary_id": str(outline_feat["properties"].get("source_outline_id", "natural-earth-10m")),
                            "generator_version": GENERATOR_VERSION,
                        },
                        "geometry": mapping(state_geom),
                    }
                )

            if layout_rec is not None:
                scaled_geom = layout_rec["geom"]
                area_scale = layout_rec["scale"]
                disp_x, disp_y = layout_rec["displacement"]
                anchor_x, anchor_y = layout_rec["anchor"]
                centroid_x, centroid_y = layout_rec["centroid"]
            else:
                scaled_geom = outline_geom
                area_scale = 1.0
                disp_x = disp_y = 0.0
                anchor_x, anchor_y = outline_feat["_centroid"]
                centroid_x, centroid_y = outline_feat["_centroid"]
            outline_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "congress_number": congress_number,
                        "state_fips": fips,
                        "state_abbr": str(row["state_abbr"]).strip().upper(),
                        "state_name": str(row["state_name"]),
                        "house_seats": seats,
                        "area_scale": area_scale,
                        "displacement_x": disp_x,
                        "displacement_y": disp_y,
                        "anchor_x": anchor_x,
                        "anchor_y": anchor_y,
                        "centroid_x": centroid_x,
                        "centroid_y": centroid_y,
                        "generator_version": GENERATOR_VERSION,
                    },
                    "geometry": mapping(scaled_geom),
                }
            )

            if tiling_status != "ok":
                warnings.append(
                    {
                        "congress": congress_number,
                        "state_fips": fips,
                        "state_abbr": str(row["state_abbr"]),
                        "tiling_status": tiling_status,
                        "seats": seats,
                        "cells_assigned": len(all_cells),
                        "tiles_produced": len(cd_feats_for_state),
                    }
                )

        common_props = {
            "congress_number": congress_number,
            "start_date": congress_start_date(congress_number).isoformat(),
            "end_date": congress_end_date(congress_number).isoformat(),
            "generator_version": GENERATOR_VERSION,
            "hex_grid_R": R,
        }

        write_geojson_with_retry(cds_root / f"{congress_number}.geojson", common_props, cd_features)
        write_geojson_with_retry(states_root / f"{congress_number}.geojson", common_props, state_features)
        write_geojson_with_retry(outlines_root / f"{congress_number}.geojson", common_props, outline_features)

        summary["timeline"].append(
            {
                "congress_number": congress_number,
                "start_date": congress_start_date(congress_number).isoformat(),
                "end_date": congress_end_date(congress_number).isoformat(),
                "state_feature_path": str((Path("data_processed") / "polyhex_states_by_congress" / f"{congress_number}.geojson").as_posix()),
                "state_outline_path": str((Path("data_processed") / "state_outlines_by_congress" / f"{congress_number}.geojson").as_posix()),
                "cd_feature_path": str((Path("data_processed") / "polyhex_cds_by_congress" / f"{congress_number}.geojson").as_posix()),
                "state_feature_count": len(state_features),
                "cd_feature_count": len(cd_features),
                "state_outline_count": len(outline_features),
                "cells_used_total": cells_used_total,
                "generator_version": GENERATOR_VERSION,
                "coverage_flags": {
                    "missing_boundary_states": [],
                    "missing_template_states": [],
                    "used_overrides": False,
                },
            }
        )

    (states_root / "_index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.warnings_out).write_text(json.dumps({"warnings": warnings}, indent=2), encoding="utf-8")
    print(f"Done. Wrote tiling outputs for {len(summary['timeline'])} Congresses; warnings: {len(warnings)}")


if __name__ == "__main__":
    main()
