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
5. Render tiles as the union of their 5 hexes. (Phase 2 will clip border tiles
   to the scaled state outline to reproduce HexCDv31wm's snap-to-edge styling.)
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
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v6-pentahex-scaled-outlines"

NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


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


def write_geojson_with_retry(path: Path, common_props: dict, features: list, attempts: int = 5) -> None:
    """Write a GeoJSON FeatureCollection, retrying on transient Windows OSError 22.

    The pentahex regen writes 357 files in a tight loop; Windows occasionally
    returns EINVAL on the very next open() if antivirus or the file indexer is
    still holding a handle from a recent write. A tiny sleep-and-retry clears it.
    """
    import time as _time
    payload = json.dumps({"type": "FeatureCollection", "properties": common_props, "features": features})
    last_err: OSError | None = None
    for i in range(attempts):
        try:
            path.write_text(payload, encoding="utf-8")
            return
        except OSError as e:
            last_err = e
            _time.sleep(0.2 * (i + 1))
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
) -> dict[str, dict]:
    """Scale each state's outline to delegation size, then resolve overlaps.

    For each admitted state:
      - target_area = seats * 5 * hex_area
      - area_scale  = sqrt(target_area / real_area)
      - geom is scaled around the state's real centroid

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


def allocate_territories(
    need: dict[str, int],
    centroid_by_fips: dict[str, tuple[float, float]],
    cell_outline_fips: dict[tuple[int, int], str],
    hex_by_qr: dict[tuple[int, int], dict],
) -> dict[str, set[tuple[int, int]]]:
    """Grow a contiguous territory of exactly `need[fips]` cells for each state.

    Process states smallest-need-first so tiny dense states (e.g. Delaware) lock
    in a compact, connected territory before bigger neighbors inflate around them.
    Each state is seeded with the unclaimed cell nearest its centroid (preferring
    cells inside its own outline) and then grown to its full `need` by repeatedly
    claiming the frontier cell that lies inside the state's own outline if
    possible, then is closest to its centroid. Growth only ever takes cells
    adjacent to the existing territory, so each territory stays connected; if a
    state is fully boxed in before reaching `need` it stops (leaving a smaller,
    still-connected territory) rather than grabbing a disconnected far cell.
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

        # Seed: nearest unclaimed cell inside the state's own outline, else the
        # globally nearest unclaimed cell.
        own_unclaimed = [qr for qr in own_inside if qr in unclaimed]
        pool = own_unclaimed if own_unclaimed else list(unclaimed)
        seed = min(pool, key=lambda qr: squared_dist(hex_by_qr[qr]["_xy"], center))
        cells.add(seed)
        unclaimed.discard(seed)

        # Grow to full need via connected frontier expansion.
        while len(cells) < need[fips]:
            frontier: set[tuple[int, int]] = set()
            for c in cells:
                for nb in neighbors(c):
                    if nb in unclaimed:
                        frontier.add(nb)
            if not frontier:
                break  # boxed in; leave a smaller connected territory
            chosen = min(
                frontier,
                key=lambda qr: (
                    0 if qr in own_inside else 1,
                    squared_dist(hex_by_qr[qr]["_xy"], center),
                ),
            )
            cells.add(chosen)
            unclaimed.discard(chosen)

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

    cells_by_state = allocate_territories(need, centroid_by_fips, cell_outline_fips, hex_by_qr)

    for fips in need:
        cells = cells_by_state[fips]
        if not cells:
            continue
        boundary = {c for c in cells if any(nb not in cells for nb in neighbors(c))}
        tiles_by_state[fips] = partition_into_pentahexes(cells, boundary)

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
) -> list[list[tuple[int, int]]]:
    """Partition `cells` into connected groups of 5. Returns [] on failure."""
    if not cells or len(cells) % 5 != 0:
        return []

    def external_degree(c: tuple[int, int], avail: set[tuple[int, int]]) -> int:
        return sum(1 for nb in neighbors(c) if nb not in avail)

    def grow_one(avail: set[tuple[int, int]], seed: tuple[int, int]) -> list[tuple[int, int]] | None:
        tile = [seed]
        used = {seed}
        while len(tile) < 5:
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


def render_tile(tile: list[tuple[int, int]], hex_by_qr: dict[tuple[int, int], dict]):
    polys = [hex_by_qr[qr]["_geom"] for qr in tile]
    union = unary_union(polys)
    if not union.is_valid:
        union = union.buffer(0)
    if isinstance(union, Polygon):
        return MultiPolygon([union])
    if isinstance(union, MultiPolygon):
        return union
    flat: list[Polygon] = []
    for g in getattr(union, "geoms", []):
        if isinstance(g, Polygon):
            flat.append(g)
        elif isinstance(g, MultiPolygon):
            flat.extend(list(g.geoms))
    return MultiPolygon(flat) if flat else union


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
            cd_feats_for_state: list[dict] = []
            for idx, tile in enumerate(tiles, start=1):
                touches_boundary = any(qr in boundary_cells for qr in tile)
                geom = render_tile(tile, hex_by_qr)
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

            layout_rec = layout.get(fips)
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
                        "real_geometry": mapping(outline_geom),
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
