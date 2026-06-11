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

import numpy as np
from datetime import date, timedelta
from pathlib import Path

from shapely.affinity import scale as shapely_scale, translate as shapely_translate
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v6-pentahex-scaled-outlines"

NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

# Gentle global compaction: each state's first-appearance ("home") position is pulled
# this fraction of the way toward a fixed national center (computed once in main() from
# the union of all modern outlines). Because the web viewer fits one projection to the
# largest (C119) frame and reuses it for every Congress, pulling toward a FIXED center
# translates sparse/early clusters toward frame-center — using the empty western space to
# give the early eastern states a more central, legible footprint — while being ~invisible
# for the full modern map (a uniform scale-about-center that fitSize re-normalizes). The
# overlap resolver still restores min-gap spacing, so the dense core is not re-jammed. This
# replaces the old NE_EXPAND radial hack. 1.0 = no compaction; lower = stronger pull.
COMPACTION = 0.9

# Failure-recovery escalation ladder of (retention, spring_scale). Normally a Congress uses
# pure carried positions with full adjacency springs (retention 0.0, spring 1.0) — max temporal
# stability, stationary states have zero drift. Two failure modes are recovered by retrying the
# Congress down this ladder, adopting the first rung that reduces warnings:
#   - retention pulls carried seeds toward each state's fixed compacted "home" (fixes a state
#     that temporal drift boxed in: NY C53-57, MI C83-87);
#   - spring_scale weakens/disables the adjacency springs (fixes a many-neighbour hub the
#     springs over-constrain into an un-tileable shape: IL C63-72).
# The ladder ends at (1.0, 0.0) == fresh placement with no springs, i.e. the proven warning-free
# baseline, so recovery is guaranteed. Retention is applied only to carried states, never to
# split pop-off seeds.
ESCALATION_LADDER = ((0.0, 0.5), (0.0, 0.0), (0.3, 0.0), (0.6, 0.0), (1.0, 0.0))

# ---- Reference-anchored layout (primary mode) ------------------------------------------
# The hand-authored HexCDv31wm reference is the spacing target: every state is seeded at its
# reference-blob centroid (similarity-transformed into our hex space) EVERY Congress, and the
# polygon overlap resolver handles the eras where a state outgrows its reference hole (e.g.
# 1930s NY at 45 seats pushes NJ/CT a few R; they return to anchor as it shrinks). This is
# stateless: no temporal carry, no springs, no path dependence — identical seat tables give
# byte-identical layouts, C119 lands ~exactly on the reference arrangement (its seat counts
# match the reference apportionment), and earlier Congresses are the same arrangement with
# era-sized states. The carry+springs machinery below remains as the fallback when the
# anchors JSON is absent.
# Failure recovery: retry with all anchors spread radially about the reference map centre
# (relieves crowding-induced un-tileable shapes), ending with the legacy compacted-home fresh
# placement as the guaranteed final rung.
REFERENCE_ANCHORS_PATH = ROOT / "data_raw" / "reference" / "hexcdv31_anchors.json"
ANCHOR_SPREAD_LADDER = (1.04, 1.08, 1.15, 1.3)

# Directional adjacency springs. Before the exact polygon overlap resolver, a fast circle
# model positions states topologically: each pair of states whose REAL outlines share a
# border is pulled toward sitting just-adjacent (separation r_i + r_j + gap) in their REAL
# relative direction, while non-adjacent pairs only repel. This keeps neighbours nestled
# (Delaware in Maryland's corner) and stops a non-neighbour from wedging between two states
# that really border each other (Missouri between KY/TN). Adjacency-first: springs are strong
# relative to repulsion so the neighbour graph wins when area-proportional sizing conflicts.
# ADJ_TOL: max real gap (m) between outlines still counted as a shared border.
ADJ_TOL = 3000.0
SPRING_K = 0.5          # adjacency spring stiffness (fraction of position error per step)
SPRING_REPULSE = 0.5    # non-adjacent circle repulsion stiffness
SPRING_STEP = 0.08      # global damping per circle-model iteration (small => converges to a
                        # static equilibrium instead of oscillating, which keeps it idempotent)
SPRING_ITERS = 2000     # max circle-model iterations (stops early on the move threshold)
SPRING_MOVE_EPS = 0.01  # stop when the largest per-iteration move (in R) falls below this
# Deadband (in R): a spring exerts no force while its pair is within this distance of the
# ideal relative offset. Crucial for BOTH temporal stability and geometry: once settled the
# circle model is a true fixed point (re-seeding it produces zero movement, so stable
# Congresses keep zero drift), and the slack absorbs the mismatch between the circle estimate
# and exact polygon spacing so the spring and the polygon overlap resolver don't fight.
SPRING_DEADBAND = 0.75

# States whose land is split across open water by the Great Lakes clip and so must be
# allocated as multiple connected components (each a multiple of 5 hexes) rather than one
# blob. Scope today: Michigan ("26") = Upper + Lower Peninsula. Gated to this set so the
# multi-component path never perturbs island states (NY/MA/HI/AK/...) that tile fine today.
MULTI_COMPONENT_FIPS = frozenset({"26"})

# Historical composite outlines: curated child FIPS -> parent FIPS lineage. Before a child
# is first seated (house_seats > 0), its modern outline is unioned into the parent's so the
# parent is drawn at the extent it actually governed (e.g. early Virginia includes Kentucky
# and West Virginia). The CUTOVER TIMING is data-driven — a child detaches the first Congress
# it holds seats — so no Congress numbers are hardcoded. Only the lineage is curated, because
# `formed_from` metadata routes through territories (Southwest Territory, etc.), not parents.
PREDECESSOR_PARENT = {
    "21": "51",  # Kentucky      -> Virginia        (admitted 1792, first seated C2)
    "54": "51",  # West Virginia -> Virginia        (admitted 1863, first seated C38)
    "47": "37",  # Tennessee     -> North Carolina  (admitted 1796, first seated C4)
    "01": "13",  # Alabama       -> Georgia         (admitted 1819, first seated C16)
    "28": "13",  # Mississippi   -> Georgia         (admitted 1817, first seated C15)
}
# Maine (FIPS 23) is the one child geographically SEPARATED from its parent (NH lies between
# Maine and Massachusetts), so unioning it into MA's outline made the allocator seed/size the
# Maine lobe arbitrarily. Instead we allocate Maine in its OWN modern outline, sized to the
# number of MA districts that historically sat in the Maine territory, then relabel those
# tiles as Massachusetts (Maine was not yet a state) at render time.
#   congress -> (maine_total_districts, me_labeled_districts)
# `me_labeled` tiles stay Maine (FIPS 23); the rest become Massachusetts. C16 is the
# admission-year wrinkle: 7 Maine-territory seats were still MA, plus Maine's 1 at-large
# (7 of 8 -> MA, 1 -> ME); the full 7-seat reassignment to Maine lands in C17.
MAINE_IN_MA = {
    1: (1, 0), 2: (1, 0),
    3: (3, 0), 4: (3, 0), 5: (3, 0), 6: (3, 0), 7: (3, 0),
    8: (4, 0), 9: (4, 0), 10: (4, 0), 11: (4, 0), 12: (4, 0),
    13: (7, 0), 14: (7, 0), 15: (7, 0),
    16: (8, 1),
}
MA_FIPS = "25"
ME_FIPS = "23"


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


def build_effective_outlines(outlines: dict[str, dict], seated_fips: set[str]) -> dict[str, dict]:
    """Per-Congress outline view: each parent absorbs the modern outline of every
    `PREDECESSOR_PARENT` child that is not yet seated this Congress, so the parent is drawn
    at its historical silhouette (early VA = VA∪KY∪WV, MA = MA∪ME, NC = NC∪TN, GA = GA∪AL∪MS).

    Returns a dict that overrides only the affected parents; every other state passes through
    unchanged. Does NOT mutate `outlines` (the module-level cache reused across Congresses).
    Area is still normalized to the parent's own seat count downstream — the union supplies
    only *shape*, not extra hexes.
    """
    additions: dict[str, list[str]] = defaultdict(list)
    for child, parent in PREDECESSOR_PARENT.items():
        if child in seated_fips:
            continue  # child stands on its own this Congress
        if child in outlines and parent in outlines:
            additions[parent].append(child)
    if not additions:
        return outlines
    eff = dict(outlines)
    for parent, children in additions.items():
        merged = unary_union([outlines[parent]["_geom"], *(outlines[c]["_geom"] for c in children)])
        if not merged.is_valid:
            merged = merged.buffer(0)
        rep = merged.representative_point()
        eff[parent] = {
            **outlines[parent],
            "_geom": merged,
            "_centroid": (rep.x, rep.y),
            "geometry": mapping(merged),
            "_composite_children": sorted(children),
        }
    return eff


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


def build_adjacency(
    outlines: dict[str, dict], tol: float = ADJ_TOL
) -> list[tuple[str, str, float, float]]:
    """Real-geography adjacency graph: one edge per pair of states whose outlines share a
    border (within `tol` metres). Each edge carries the unit direction from a's real centroid
    to b's, so the spring can preserve not just *that* they touch but their real relative
    orientation (DE north-east of MD, TN south of KY, MO west of both). Computed once from the
    modern outlines; per-Congress callers use the subset whose endpoints are both seated.
    """
    items = [(f, feat["_geom"], feat["_centroid"]) for f, feat in outlines.items()]
    geoms = [g for _, g, _ in items]
    tree = STRtree(geoms)
    buffered = [g.buffer(tol) for g in geoms]
    edges: list[tuple[str, str, float, float]] = []
    for i, (fa, _, ca) in enumerate(items):
        for j in tree.query(buffered[i]):
            if j <= i:
                continue
            fb, gb, cb = items[j]
            if not buffered[i].intersects(gb):
                continue
            dx, dy = cb[0] - ca[0], cb[1] - ca[1]
            d = math.hypot(dx, dy) or 1.0
            edges.append((fa, fb, dx / d, dy / d))
    return edges


def compute_scaled_layout(
    seat_by_fips: dict[str, int],
    outlines: dict[str, dict],
    hex_area: float,
    R: float,
    max_iter: int = 1000,
    seed_centroids: dict[str, tuple[float, float]] | None = None,
    compaction_center: tuple[float, float] | None = None,
    compaction: float = COMPACTION,
    adjacency: list[tuple[str, str, float, float]] | None = None,
    spring_scale: float = 1.0,
) -> dict[str, dict]:
    """Scale each state's outline to delegation size, place it, then resolve overlaps.

    For each admitted state:
      - target_area = seats * 5 * hex_area
      - area_scale  = sqrt(target_area / real_area)
      - geom is scaled around the state's real centroid

    Initial placement (the state's starting centroid):
      - If `seed_centroids[fips]` is given (the previous Congress's resolved position,
        or a split child's pop-off seed), the state starts there. This carries position
        forward across Congresses so states move only gradually (temporal stability).
      - Otherwise the state starts at its "home" anchor: its real centroid pulled
        `compaction` of the way toward `compaction_center` (a fixed national center).
        This gently translates sparse/early clusters toward frame-center to use empty
        space, and is ~invisible for the full modern map. Replaces the old NE_EXPAND.

    Then a fast circle-model phase positions states topologically (directional adjacency
    springs + non-adjacent repulsion, see `adjacency` / `build_adjacency`), so neighbours sit
    nestled in their real relative direction. Finally the exact polygon resolver iteratively
    pushes the most-overlapping pair apart along their centroid vector until separation reaches
    `target_gap = 0.5 * R`, guaranteeing a non-overlapping layout.

    Returns fips -> dict with:
      geom (Shapely scaled+displaced),
      centroid (post-displacement, used as the state's pull-anchor),
      anchor   (original real centroid, the scale center),
      scale    (area_scale used),
      displacement (dx, dy applied after scaling).
    """
    target_gap = 0.5 * R
    seed_centroids = seed_centroids or {}
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
        # Initial centroid: carry forward the previous position if we have one, else
        # the compacted "home" anchor. The scaled geom is centered on the real centroid,
        # so translate it onto the chosen start position.
        if fips in seed_centroids:
            tx, ty = seed_centroids[fips]
        elif compaction_center is not None and compaction != 1.0:
            ccx, ccy = compaction_center
            tx = ccx + compaction * (cx - ccx)
            ty = ccy + compaction * (cy - ccy)
        else:
            tx, ty = cx, cy
        dx0, dy0 = tx - cx, ty - cy
        if dx0 or dy0:
            scaled = shapely_translate(scaled, xoff=dx0, yoff=dy0)
        layout[fips] = {
            "geom": scaled,
            "centroid": (tx, ty),
            "anchor": (cx, cy),
            "scale": scale,
            "displacement": (dx0, dy0),
        }

    fips_list = list(layout)

    def displace(fips: str, dx: float, dy: float) -> None:
        rec = layout[fips]
        rec["geom"] = shapely_translate(rec["geom"], xoff=dx, yoff=dy)
        cx, cy = rec["centroid"]
        rec["centroid"] = (cx + dx, cy + dy)
        ddx, ddy = rec["displacement"]
        rec["displacement"] = (ddx + dx, ddy + dy)

    # ---- Adjacency relaxation: directional springs + repulsion to a joint fixed point ----
    # A lightweight circle model (radius sqrt(area/pi)) positions states topologically: an
    # adjacent pair is sprung toward separation r_a+r_b+gap in its REAL relative direction
    # (but only beyond a deadband), and non-adjacent pairs repel when closer than that. With
    # the deadband the converged configuration is a true fixed point, so re-seeding it next
    # Congress produces no movement (temporal stability). The converged circle centroids are
    # stored as `seed_centroid` and carried forward by main(); the polygon overlap resolver
    # below still runs on the geometry for exact non-overlap in the rendered output.
    cap = 0.5 * target_gap
    present = set(fips_list)
    edges = [(a, b, ux, uy) for (a, b, ux, uy) in (adjacency or []) if a in present and b in present]
    if edges and len(fips_list) > 1 and spring_scale > 0.0:
        # Vectorized circle-model relaxation (springs + repulsion) to a static, idempotent
        # equilibrium. State count is small (~50) so the full N*N repulsion is cheap in numpy.
        idx = {f: i for i, f in enumerate(fips_list)}
        N = len(fips_list)
        P = np.array([layout[f]["centroid"] for f in fips_list], dtype=float)
        rad = np.array([math.sqrt(max(seat_by_fips.get(f, 1), 1) * 5 * hex_area / math.pi) for f in fips_list])
        ea = np.array([idx[a] for a, b, _, _ in edges], dtype=int)
        eb = np.array([idx[b] for a, b, _, _ in edges], dtype=int)
        edir = np.array([(ux, uy) for _, _, ux, uy in edges], dtype=float)
        eL = rad[ea] + rad[eb] + target_gap
        adjM = np.zeros((N, N), dtype=bool)
        adjM[ea, eb] = True
        adjM[eb, ea] = True
        trigger = (rad[:, None] + rad[None, :] + target_gap) - SPRING_DEADBAND * R  # repel threshold
        deadband = SPRING_DEADBAND * R
        move_eps = SPRING_MOVE_EPS * R
        for _ in range(SPRING_ITERS):
            disp = np.zeros((N, 2))
            # Directional adjacency springs: pull b toward a + dir*(r_a+r_b+gap), silent inside
            # the deadband (that silence is what makes the equilibrium a true fixed point).
            evec = (P[ea] + edir * eL[:, None]) - P[eb]
            errn = np.hypot(evec[:, 0], evec[:, 1])
            smask = errn > deadband
            if smask.any():
                k = (SPRING_K * 0.5 * spring_scale) * np.where(smask, (errn - deadband) / np.maximum(errn, 1e-9), 0.0)
                f = evec * k[:, None]
                np.add.at(disp, eb, f)
                np.add.at(disp, ea, -f)
            # Non-adjacent repulsion: push apart only the overlap beyond the deadband.
            diff = P[:, None, :] - P[None, :, :]
            dist = np.hypot(diff[:, :, 0], diff[:, :, 1])
            np.fill_diagonal(dist, np.inf)
            rmask = (dist < trigger) & (~adjM)
            if rmask.any():
                unit = diff / np.maximum(dist, 1e-9)[:, :, None]
                mag = np.where(rmask, SPRING_REPULSE * 0.5 * (trigger - dist), 0.0)
                disp += (mag[:, :, None] * unit).sum(axis=1)
            step = np.clip(disp * SPRING_STEP, -cap, cap)
            P += step
            if np.abs(step).max() < move_eps:
                break
        for f in fips_list:
            cx0, cy0 = layout[f]["centroid"]
            nx, ny = float(P[idx[f]][0]), float(P[idx[f]][1])
            layout[f]["seed_centroid"] = (nx, ny)
            displace(f, nx - cx0, ny - cy0)
    else:
        for f in fips_list:
            layout[f]["seed_centroid"] = layout[f]["centroid"]

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


# ---- Read-only layout diagnostic (--diagnose) ------------------------------------------
# Coarse regional buckets (continental FIPS) for measuring east-west spread of the layout.
# AK(02)/HI(15)/DC(11) are excluded everywhere in the diagnostic (insets / non-state). EAST
# is computed as "every laid-out state not in WEST/MIDWEST/excluded", so it auto-covers the
# original 13, the South, and the south-central states without an explicit list.
DIAG_WEST_FIPS = frozenset({"04", "06", "08", "16", "30", "32", "35", "41", "49", "53", "56"})
DIAG_MIDWEST_FIPS = frozenset({"17", "18", "19", "20", "26", "27", "29", "31", "38", "39", "46", "55"})
DIAG_EXCLUDE_FIPS = frozenset({"02", "15", "11"})


def _region_stats(layout: dict, fips_set: frozenset[str]) -> dict | None:
    """Mean centroid + east-west spread of the laid-out members of a region. Uses each
    record's resolved (post-overlap) `centroid`. Returns None if no member is present."""
    xs: list[float] = []
    ys: list[float] = []
    for f in fips_set:
        rec = layout.get(f)
        if rec is None:
            continue
        cx, cy = rec["centroid"]
        xs.append(cx)
        ys.append(cy)
    if not xs:
        return None
    return {
        "n": len(xs),
        "mean": (sum(xs) / len(xs), sum(ys) / len(ys)),
        "xspread": max(xs) - min(xs),
        "x_min": min(xs),
        "x_max": max(xs),
    }


def _collect_layout_metrics(congress_number: int, layout: dict) -> dict:
    """Capture raw (frame-independent) layout numbers for one Congress. Frame-relative
    fractions are derived later in _diagnose_format once the C119 frame is known."""
    geoms = [rec["geom"] for rec in layout.values() if rec.get("geom") is not None]
    union = unary_union(geoms) if geoms else None
    bbox = union.bounds if (union is not None and not union.is_empty) else None
    east_fips = frozenset(
        f for f in layout
        if f not in DIAG_WEST_FIPS and f not in DIAG_MIDWEST_FIPS and f not in DIAG_EXCLUDE_FIPS
    )
    ca = layout.get("06")
    return {
        "congress": congress_number,
        "n_states": len(layout),
        "bbox": bbox,
        "union_area": (union.area if union is not None else 0.0),
        "ca_xmin": (ca["geom"].bounds[0] if ca is not None else None),
        "ca_centroid_x": (ca["centroid"][0] if ca is not None else None),
        "regions": {
            "EAST": _region_stats(layout, east_fips),
            "MIDWEST": _region_stats(layout, DIAG_MIDWEST_FIPS),
            "WEST": _region_stats(layout, DIAG_WEST_FIPS),
        },
    }


def _diagnose_frame(cds_root: Path, records: list[dict], pad_frac: float = 0.02) -> tuple[float, float, float, float]:
    """The fixed viewer frame = bounds of the committed C119 CD output (what web/app.js fits
    its single projection to), padded `pad_frac` per axis. Falls back to the union bbox of the
    collected records if 119.geojson is absent (e.g. a partial diagnose walk before any regen)."""
    bbox = None
    f119 = cds_root / "119.geojson"
    if f119.exists():
        try:
            fc = json.loads(f119.read_text(encoding="utf-8"))
            u = unary_union([shape(ft["geometry"]) for ft in fc.get("features", [])])
            if not u.is_empty:
                bbox = u.bounds
        except Exception:
            bbox = None
    if bbox is None:
        bxs = [r["bbox"] for r in records if r["bbox"] is not None]
        if not bxs:
            return (0.0, 0.0, 1.0, 1.0)
        bbox = (min(b[0] for b in bxs), min(b[1] for b in bxs),
                max(b[2] for b in bxs), max(b[3] for b in bxs))
    minx, miny, maxx, maxy = bbox
    w, h = (maxx - minx) or 1.0, (maxy - miny) or 1.0
    return (minx - pad_frac * w, miny - pad_frac * h, maxx + pad_frac * w, maxy + pad_frac * h)


def _diagnose_format(
    records: list[dict],
    frame: tuple[float, float, float, float],
    compaction_center: tuple[float, float],
    conus_center: tuple[float, float],
) -> tuple[str, dict]:
    """Render the per-Congress table (frame-relative %) + a JSON payload. All `*_frac` values
    are fractions of frame width (x) so 0%=west edge, 100%=east edge."""
    fminx, fminy, fmaxx, fmaxy = frame
    fw = (fmaxx - fminx) or 1.0
    fh = (fmaxy - fminy) or 1.0
    farea = fw * fh

    def xf(v: float | None) -> float | None:
        return None if v is None else (v - fminx) / fw

    lines: list[str] = []
    lines.append(
        f"Layout diagnostic - frame bbox=({fminx:.0f},{fminy:.0f},{fmaxx:.0f},{fmaxy:.0f}) "
        f"w={fw:.0f} h={fh:.0f}"
    )
    lines.append(
        f"compaction_center x-frac={xf(compaction_center[0]):.3f} (incl AK/HI insets)   "
        f"CONUS-center x-frac={xf(conus_center[0]):.3f}   "
        f"skew dx={compaction_center[0]-conus_center[0]:+.0f}m dy={compaction_center[1]-conus_center[1]:+.0f}m"
    )
    lines.append("(x-fracs: 0%=west frame edge, 100%=east frame edge)")
    lines.append("")
    lines.append(
        f"{'C':>4} {'states':>6} {'cover%':>7} {'bboxW%':>7} {'CAxmin%':>8} "
        f"{'EASTx%':>7} {'WESTx%':>7} {'E-Wgap%':>8} {'WESTspr%':>8}"
    )

    def pct(v: float | None, width: int = 7) -> str:
        return (f"{v*100:.1f}".rjust(width)) if v is not None else "n/a".rjust(width)

    payload: dict = {
        "frame": list(frame),
        "compaction_center": list(compaction_center),
        "conus_center": list(conus_center),
        "congresses": [],
    }
    for r in records:
        cover = r["union_area"] / farea if farea else 0.0
        bboxw = ((r["bbox"][2] - r["bbox"][0]) / fw) if r["bbox"] else None
        ca = xf(r["ca_xmin"])
        east = r["regions"]["EAST"]
        west = r["regions"]["WEST"]
        eastx = xf(east["mean"][0]) if east else None
        westx = xf(west["mean"][0]) if west else None
        ewgap = (eastx - westx) if (eastx is not None and westx is not None) else None
        westspr = (west["xspread"] / fw) if west else None
        lines.append(
            f"{r['congress']:>4} {r['n_states']:>6} {pct(cover)} {pct(bboxw)} {pct(ca, 8)} "
            f"{pct(eastx)} {pct(westx)} {pct(ewgap, 8)} {pct(westspr, 8)}"
        )
        payload["congresses"].append({
            "congress": r["congress"],
            "n_states": r["n_states"],
            "cover_frac": cover,
            "bbox_w_frac": bboxw,
            "ca_xmin_frac": ca,
            "east_x_frac": eastx,
            "west_x_frac": westx,
            "ew_gap_frac": ewgap,
            "west_xspread_frac": westspr,
        })
    return "\n".join(lines), payload


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
    parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Exit 0 even if some states failed to tile. By default a clean regen MUST end "
        "with warnings: 0 (the project invariant), so any warning makes the run exit non-zero "
        "to make a layout regression loud. Use this only for debugging/partial runs.",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Read-only layout diagnostic: walk the per-Congress layout (honest carried "
        "history) and print east-west spread / frame-coverage metrics for the requested "
        "Congresses, then exit WITHOUT writing any GeoJSON / index / warnings. Used to ground "
        "layout tuning (e.g. the 'condensed West') in real numbers before changing anything.",
    )
    parser.add_argument(
        "--diagnose-congresses",
        default="1,53,54,55,56,57,58,59,60,61,62,63,68,119",
        help="Comma-separated Congress numbers to report under --diagnose. The walk stops "
        "after the largest one (so a small set is fast). The fixed C119 frame is read from the "
        "committed 119.geojson regardless.",
    )
    parser.add_argument("--diagnose-out", default=None, help="Optional path to also write the --diagnose report as JSON.")
    parser.add_argument(
        "--reference-anchors",
        default=str(REFERENCE_ANCHORS_PATH),
        help="Path to the HexCDv31wm anchor JSON (scripts/extract_reference_anchors.py). "
        "Pass an empty string or a missing path to fall back to the legacy carried-seed layout.",
    )
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

    # Fixed national center for gentle compaction (computed once from all modern
    # outlines, including the AK/HI insets so it matches the drawn frame). The same
    # center every Congress keeps framing stable as western states fill in.
    _center_geom = unary_union([o["_geom"] for o in outlines.values()]).centroid
    compaction_center = (_center_geom.x, _center_geom.y)

    # Real-geography adjacency graph (computed once from modern outlines). Each Congress uses
    # the subset whose endpoints are both seated, to spring neighbouring states into their real
    # relative positions during layout. See build_adjacency / the circle-model phase.
    # (Unused in the reference-anchored mode below, where springs are off.)
    adjacency = build_adjacency(outlines)

    # Reference anchors: each state's blob centroid in the HexCDv31wm reference, similarity-
    # transformed into our hex space (uniform scale matching hex sizes, recentred on the fixed
    # national centre so the map stays where the grid already is). See the constant's comment.
    anchor_pos: dict[str, tuple[float, float]] = {}
    anchors_path = Path(args.reference_anchors) if args.reference_anchors else None
    if anchors_path is not None and anchors_path.exists():
        ref = json.loads(anchors_path.read_text(encoding="utf-8"))
        s_ref = math.sqrt(hex_area / ref["hex_area_ref"])
        rcx, rcy = ref["map_centroid"]
        anchor_pos = {
            f: (
                compaction_center[0] + s_ref * (st["centroid"][0] - rcx),
                compaction_center[1] + s_ref * (st["centroid"][1] - rcy),
            )
            for f, st in ref["states"].items()
        }
        print(f"Reference-anchored layout: {len(anchor_pos)} state anchors from {anchors_path.name} "
              f"(scale {s_ref:.4f})")
    else:
        print(
            "Reference anchors disabled or not found "
            f"({anchors_path}); using legacy carried-seed + adjacency-spring layout"
        )

    # Resolved state centroids carried across Congresses for temporal stability. Persisted
    # (not reset per Congress) so a state that briefly drops out keeps its position on return.
    prev_centroids: dict[str, tuple[float, float]] = {}

    # Identical-input fast path: when a Congress's effective inputs (post-Maine seat table +
    # MAINE_IN_MA entry) match the previous Congress's exactly, reuse the previous layout/
    # tiles/statuses verbatim instead of recomputing. Recomputing from carried seeds is only
    # *approximately* a fixed point — the polygon overlap resolver re-runs from the circle
    # equilibrium and lands sub-hex differently each Congress — so without reuse even
    # seat-identical transitions wobble (measured: 90/118 transitions are seat-identical but
    # only 1 rendered frozen). Reuse makes "nothing changed => nothing moves" exact and skips
    # the dominant layout/allocation/tiling cost (~most Congresses within a decade). Gated on
    # the previous Congress having tiled fully ok so a failing Congress is never frozen in —
    # recomputation keeps its self-healing chance. Rendering still runs per Congress (it is
    # deterministic on identical inputs) so dates/metadata stay correct.
    reuse_sig: tuple | None = None
    reuse_state: tuple | None = None  # (layout, tiles_by_state, statuses)
    reused_count = 0

    # --diagnose: collect layout metrics for the requested Congresses, then exit before any
    # writes. The walk still runs from C1 so carried history is honest, but stops after the
    # largest requested Congress and skips per-state rendering.
    diag_set: set[int] = set()
    diag_max: int | None = None
    diag_records: list[dict] = []
    if args.diagnose:
        diag_set = {int(x) for x in args.diagnose_congresses.split(",") if x.strip()}
        diag_max = max(diag_set) if diag_set else None

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

        # Maine-as-part-of-Massachusetts: while Maine was MA territory, split MA's delegation
        # into MA-proper (allocated in MA's outline) and a Maine block (allocated in Maine's
        # own outline, sized to the historical district count). Maine's tiles are relabeled to
        # Massachusetts after rendering (see the relabel pass below), except `me_labeled` of
        # them at C16. This sizes the Maine lobe correctly without unioning the two outlines.
        if congress_number in MAINE_IN_MA and MA_FIPS in seat_by_fips:
            maine_total, me_labeled = MAINE_IN_MA[congress_number]
            ma_proper = seat_by_fips[MA_FIPS] - (maine_total - me_labeled)
            seat_by_fips[MA_FIPS] = ma_proper
            seat_by_fips[ME_FIPS] = maine_total
            me_row = next((r for r in seat_rows if str(r["state_fips"]).zfill(2) == ME_FIPS), None)
            if me_row is not None:
                meta_by_fips[ME_FIPS] = me_row

        # Historical composite outlines: before a child state is first seated, fold its
        # modern outline into its parent so the parent is drawn at its true historical
        # extent (early VA includes KY+WV, MA includes ME, etc.). `eff_outlines` overrides
        # only those parents; everything else is the modern outline. Used for layout,
        # anchors and clipping in this Congress.
        eff_outlines = build_effective_outlines(outlines, set(seat_by_fips))

        # Temporal seeding: carry each state's resolved position from the previous Congress
        # so the layout moves only gradually. `retention` optionally pulls each carried state
        # toward its fixed compacted "home" (used only by the failure-recovery ladder below;
        # 0.0 = pure carry). A split child first appearing (KY/WV from VA, TN from NC, AL/MS
        # from GA) has no prior position, so it is always seeded adjacent to its parent's
        # current position — offset by the real centroid gap — so it "pops off" the parent
        # rather than teleporting to its own raw centroid (retention never applies to it).
        ccx0, ccy0 = compaction_center

        def build_seeds(retention: float) -> dict[str, tuple[float, float]]:
            seeds: dict[str, tuple[float, float]] = {}
            for fips in seat_by_fips:
                if fips in prev_centroids:
                    sx, sy = prev_centroids[fips]
                    feat = eff_outlines.get(fips) or outlines.get(fips)
                    if feat is not None and retention:
                        rx, ry = feat["_centroid"]
                        hx = ccx0 + COMPACTION * (rx - ccx0)
                        hy = ccy0 + COMPACTION * (ry - ccy0)
                        sx += retention * (hx - sx)
                        sy += retention * (hy - sy)
                    seeds[fips] = (sx, sy)
                    continue
                parent = PREDECESSOR_PARENT.get(fips)
                if parent and parent in prev_centroids and parent in outlines and fips in outlines:
                    pcx, pcy = outlines[parent]["_centroid"]
                    ccx, ccy = outlines[fips]["_centroid"]
                    ppx, ppy = prev_centroids[parent]
                    seeds[fips] = (ppx + (ccx - pcx), ppy + (ccy - pcy))
            return seeds

        def build_anchor_seeds(spread: float) -> dict[str, tuple[float, float]]:
            # Reference-anchored seeds: every state at its HexCDv31wm anchor, every Congress.
            # spread > 1 scales the whole configuration radially about the fixed national
            # centre (failure recovery: relieves crowding when a mid-era giant outgrows its
            # reference hole and boxes a neighbour in). A state without an anchor falls
            # through to compute_scaled_layout's compacted-home placement.
            seeds: dict[str, tuple[float, float]] = {}
            for fips in seat_by_fips:
                a = anchor_pos.get(fips)
                if a is not None:
                    seeds[fips] = (ccx0 + spread * (a[0] - ccx0), ccy0 + spread * (a[1] - ccy0))
            return seeds

        def _layout_and_tile(seeds: dict[str, tuple[float, float]] | None, spring_scale: float = 1.0):
            # HexCDv31-style scaled outlines: scale each state to its delegation-size area
            # around its real centroid, place it at its carried/seeded/compacted-home
            # position, run the adjacency springs, then push overlapping pairs apart to a
            # non-overlapping layout. The pre-allocator then sees outlines that already have
            # ~the right cell count inside.
            lay = compute_scaled_layout(
                seat_by_fips, eff_outlines, hex_area, R,
                seed_centroids=seeds, compaction_center=compaction_center,
                adjacency=adjacency, spring_scale=spring_scale,
            )
            # Expand the hex grid (in place) if the layout reaches past the current bbox;
            # keeps tile size constant across Congresses. Additive, so safe to call twice.
            if lay:
                xs_min = min(rec["geom"].bounds[0] for rec in lay.values())
                ys_min = min(rec["geom"].bounds[1] for rec in lay.values())
                xs_max = max(rec["geom"].bounds[2] for rec in lay.values())
                ys_max = max(rec["geom"].bounds[3] for rec in lay.values())
                expand_grid_if_needed(hex_by_qr, R, origin, (xs_min, ys_min, xs_max, ys_max), margin=2 * R)
            # Build cell -> fips from scaled outlines; displaced centroids are pull-anchors.
            cof = build_cell_outline_map(hex_by_qr, lay, geom_key="geom")
            cby = {fips: rec["centroid"] for fips, rec in lay.items()}
            for f in seat_by_fips:  # states with no layout entry still get a pull-anchor
                if f not in cby and f in eff_outlines:
                    cby[f] = eff_outlines[f]["_centroid"]
            tbs, st = place_pentahex_tiles(seat_by_fips, cby, cof, hex_by_qr)
            return lay, cof, cby, tbs, st

        # Identical-input fast path (see the reuse_sig comment above the loop): the signature
        # is the post-Maine-adjustment seat table plus the MAINE_IN_MA entry (which also
        # drives the render-time relabel). Same signature => same eff_outlines (a function of
        # the seated set) and same carried seeds (the previous Congress's no-op update), so
        # the previous layout/tiles are reused verbatim and this transition is exactly frozen.
        input_sig = (tuple(sorted(seat_by_fips.items())), MAINE_IN_MA.get(congress_number))
        if (
            input_sig == reuse_sig
            and reuse_state is not None
            and all(s == "ok" for s in reuse_state[2].values())
        ):
            layout, tiles_by_state, statuses = reuse_state
            reused_count += 1
        elif anchor_pos:
            # Reference-anchored layout (stateless, springs off): seed at the anchors and let
            # the polygon overlap resolver absorb eras whose delegations outgrow their
            # reference holes. Failure recovery = retry at progressively spread-out anchors,
            # then the legacy compacted-home fresh placement as the guaranteed final rung.
            layout, cell_outline_fips, centroid_by_fips, tiles_by_state, statuses = _layout_and_tile(
                build_anchor_seeds(1.0), spring_scale=0.0
            )
            best_bad = sum(1 for s in statuses.values() if s != "ok")
            if best_bad:
                for spread in (*ANCHOR_SPREAD_LADDER, None):
                    seeds = build_anchor_seeds(spread) if spread is not None else build_seeds(1.0)
                    cand = _layout_and_tile(seeds, spring_scale=0.0)
                    cand_bad = sum(1 for s in cand[4].values() if s != "ok")
                    if cand_bad < best_bad:
                        rung = f"anchor spread={spread}" if spread is not None else "legacy fresh placement"
                        print(
                            f"C{congress_number}: escalation adopted {rung}; "
                            f"non-ok states {best_bad} -> {cand_bad}",
                            flush=True,
                        )
                        layout, cell_outline_fips, centroid_by_fips, tiles_by_state, statuses = cand
                        best_bad = cand_bad
                        if best_bad == 0:
                            break
        else:
            # Legacy fallback (no anchors JSON): pure carry first (retention 0.0) —
            # stationary states stay exactly put.
            layout, cell_outline_fips, centroid_by_fips, tiles_by_state, statuses = _layout_and_tile(build_seeds(0.0))

            # Failure recovery: a Congress can be left un-tileable either by temporal drift boxing
            # a growing state in, or by the springs over-constraining a many-neighbour hub. Retry
            # down ESCALATION_LADDER (relax toward home and/or weaken springs), adopting the first
            # rung that reduces warnings. The ladder ends at the proven no-spring baseline, so this
            # localizes any disruption to the few failing Congresses while guaranteeing recovery.
            best_bad = sum(1 for s in statuses.values() if s != "ok")
            if best_bad:
                for retention, spring_scale in ESCALATION_LADDER:
                    cand = _layout_and_tile(build_seeds(retention), spring_scale)
                    cand_bad = sum(1 for s in cand[4].values() if s != "ok")
                    if cand_bad < best_bad:
                        print(
                            f"C{congress_number}: escalation adopted rung (retention={retention}, "
                            f"spring_scale={spring_scale}); non-ok states {best_bad} -> {cand_bad}",
                            flush=True,
                        )
                        layout, cell_outline_fips, centroid_by_fips, tiles_by_state, statuses = cand
                        best_bad = cand_bad
                        if best_bad == 0:
                            break
        reuse_sig = input_sig
        reuse_state = (layout, tiles_by_state, statuses)

        # Carry forward the adopted layout's circle-equilibrium positions (idempotent, so a
        # stable Congress re-seeds to itself with zero drift). Merge to keep history.
        prev_centroids.update({f: rec.get("seed_centroid", rec["centroid"]) for f, rec in layout.items()})

        # --diagnose: capture metrics for requested Congresses and skip rendering. Carry is
        # already updated above, so the walk stays honest; stop once past the largest request.
        if args.diagnose:
            if congress_number in diag_set:
                diag_records.append(_collect_layout_metrics(congress_number, layout))
            if diag_max is not None and congress_number >= diag_max:
                break
            continue

        cd_features: list[dict] = []
        state_features: list[dict] = []
        outline_features: list[dict] = []
        cells_used_total = 0

        for fips, seats in seat_by_fips.items():
            outline_feat = eff_outlines[fips]
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

        # Maine relabel pass: the Maine block was rendered as its own state (FIPS 23); now
        # relabel those tiles back to Massachusetts (Maine was not yet a state), keeping
        # `me_labeled` of them as Maine (the C16 at-large district). Then renumber cd indices,
        # fix house_seats, and rebuild the MA/ME state dissolves from the relabeled districts.
        if congress_number in MAINE_IN_MA:
            _, me_labeled = MAINE_IN_MA[congress_number]
            me_cds = [f for f in cd_features if f["properties"]["state_fips"] == ME_FIPS]
            # Keep the northernmost `me_labeled` tiles as Maine; relabel the rest to MA.
            me_cds.sort(key=lambda f: shape(f["geometry"]).representative_point().y, reverse=True)
            keep_me = {id(f) for f in me_cds[:me_labeled]}
            for f in me_cds:
                if id(f) not in keep_me:
                    p = f["properties"]
                    p["state_fips"], p["state_abbr"], p["state_name"] = MA_FIPS, "MA", "Massachusetts"
            counts: dict[str, int] = {}
            for f in cd_features:
                fp = f["properties"]["state_fips"]
                counts[fp] = counts.get(fp, 0) + 1
            seen: dict[str, int] = {}
            for f in cd_features:
                fp = f["properties"]["state_fips"]
                if fp in (MA_FIPS, ME_FIPS):
                    seen[fp] = seen.get(fp, 0) + 1
                    f["properties"]["cd_index"] = seen[fp]
                    f["properties"]["house_seats"] = counts[fp]
            # Rebuild MA/ME state dissolves; relabel the Maine scaled-outline feature to MA
            # when no Maine district remains (C1-C15).
            state_features = [sf for sf in state_features if sf["properties"]["state_fips"] not in (MA_FIPS, ME_FIPS)]
            for fp, abbr, name in ((MA_FIPS, "MA", "Massachusetts"), (ME_FIPS, "ME", "Maine")):
                grp = [f for f in cd_features if f["properties"]["state_fips"] == fp]
                if not grp:
                    continue
                sg = unary_union([shape(f["geometry"]) for f in grp])
                if isinstance(sg, Polygon):
                    sg = MultiPolygon([sg])
                cells = sum(f["properties"]["hex_count"] for f in grp)
                state_features.append({
                    "type": "Feature",
                    "properties": {
                        "congress_number": congress_number,
                        "start_date": congress_start_date(congress_number).isoformat(),
                        "end_date": congress_end_date(congress_number).isoformat(),
                        "state_fips": fp, "state_abbr": abbr, "state_name": name,
                        "house_seats": counts[fp], "admitted": True,
                        "cell_count": cells, "cells_used": cells, "tiling_status": "ok",
                        "source_seat_version": "maine-as-massachusetts",
                        "source_boundary_id": "natural-earth-10m",
                        "generator_version": GENERATOR_VERSION,
                    },
                    "geometry": mapping(sg),
                })
            if counts.get(ME_FIPS, 0) == 0:
                for of in outline_features:
                    if of["properties"]["state_fips"] == ME_FIPS:
                        of["properties"]["state_fips"], of["properties"]["state_abbr"], of["properties"]["state_name"] = MA_FIPS, "MA", "Massachusetts"

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

    if args.diagnose:
        # CONUS centroid (AK/HI insets + DC excluded) — the un-skewed reference Part B will use.
        _conus = unary_union([o["_geom"] for f, o in outlines.items() if f not in DIAG_EXCLUDE_FIPS]).centroid
        conus_center = (_conus.x, _conus.y)
        frame = _diagnose_frame(cds_root, diag_records)
        text, payload = _diagnose_format(diag_records, frame, compaction_center, conus_center)
        print(text)
        if args.diagnose_out:
            Path(args.diagnose_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return

    (states_root / "_index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.warnings_out).write_text(json.dumps({"warnings": warnings}, indent=2), encoding="utf-8")
    print(
        f"Done. Wrote tiling outputs for {len(summary['timeline'])} Congresses; "
        f"warnings: {len(warnings)} (layout reused for {reused_count} identical-input Congresses)"
    )

    # Enforce the project invariant in code, not just in the sweep: a clean regen MUST end with
    # warnings: 0. The escalation ladder is only empirically guaranteed to reach 0 (its final
    # rung is the proven baseline), so a future seat-table / outline / layout change could
    # silently ship a partial Congress. Exit non-zero so that regression is loud and fails CI
    # / the web build pipeline instead of producing a quietly-broken map. (--allow-warnings opts
    # out for debugging/partial runs.)
    if warnings and not args.allow_warnings:
        congresses = sorted({w["congress"] for w in warnings if "congress" in w})
        raise SystemExit(
            f"FAILED: {len(warnings)} tiling warning(s) across Congress(es) {congresses}. "
            f"A clean regen must end with warnings: 0; see {args.warnings_out}. "
            f"Pass --allow-warnings to override for debugging."
        )


if __name__ == "__main__":
    main()
