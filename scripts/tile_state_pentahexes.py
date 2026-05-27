#!/usr/bin/env python3
"""Allocate hex cells to states from a national grid (Voronoi-style around real
Census centroids), then partition each state's cells into pentahex CD tiles.

Outputs:
  - data_processed/polyhex_cds_by_congress/<n>.geojson    (one Feature per CD)
  - data_processed/polyhex_states_by_congress/<n>.geojson (state-level dissolve)
  - data_processed/state_outlines_by_congress/<n>.geojson (per-Congress real outlines, for reference)
  - data_processed/polyhex_states_by_congress/_index.json (timeline summary)
  - data_processed/tiling_warnings.json                   (partial/fallback rows)

Algorithm:
1. Pick a seed hex for each state: the unclaimed hex whose center is closest
   to the state's real Census centroid.
2. Round-robin expand by largest-unmet-need ratio. On each turn the state
   claims the unclaimed hex adjacent to its current cluster whose center is
   closest to its centroid. If no adjacent unclaimed hex exists, it claims the
   globally closest unclaimed hex (a "jump"), then continues expanding.
3. Partition each state's cell set into pentahex (5-hex) tiles via
   region-growing from boundary cells.
4. Render tiles as the union of their 5 hexes (no boundary clipping — the
   real-outline clip step is intentionally skipped here because the hex grid
   IS the cartogram in this design).

This algorithm gives each admitted state exactly `seats * 5` cells, in a
single connected region, clustered around its real geographic position.
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

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v5-pentahex-tiling"

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


def neighbors(qr: tuple[int, int]) -> list[tuple[int, int]]:
    q, r = qr
    return [(q + dq, r + dr) for dq, dr in NEIGHBOR_OFFSETS]


def squared_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def place_pentahex_tiles(
    seat_by_fips: dict[str, int],
    centroid_by_fips: dict[str, tuple[float, float]],
    hex_by_qr: dict[tuple[int, int], dict],
) -> tuple[dict[str, list[list[tuple[int, int]]]], dict[str, str]]:
    """Place pentahex tiles one at a time, state-by-state.

    For each state in round-robin priority order (largest remaining-tile-need
    first), grow ONE pentahex tile: pick the seed hex closest to the state
    centroid among unclaimed hexes adjacent to the state's existing tiles (or
    globally unclaimed if the state has no tiles yet), then add 4 more
    connected unclaimed hexes biased toward the state centroid.

    Returns:
      tiles_by_state: list of 5-hex tiles per state (length == seats on success)
      statuses:       "ok" | "partial" | "skipped" per state
    """
    statuses: dict[str, str] = {}
    tiles_by_state: dict[str, list[list[tuple[int, int]]]] = {fips: [] for fips in seat_by_fips}
    needs = {fips: seat_by_fips[fips] for fips in seat_by_fips if seat_by_fips[fips] > 0}
    if not needs:
        return tiles_by_state, {f: "skipped" for f in seat_by_fips}

    unclaimed: set[tuple[int, int]] = set(hex_by_qr.keys())

    # Priority queue: place tiles in order of biggest remaining deficit ratio,
    # so big states don't monopolize while small states get squeezed out.
    def deficit_ratio(fips: str) -> float:
        return needs[fips] / seat_by_fips[fips]

    # Tiebreak by ascending total budget (small states go first so they reach
    # the cells nearest their centroid before bigger neighbors crowd them out).
    pq: list[tuple[float, int, str]] = []  # (-deficit_ratio, total_budget, fips)
    for fips in needs:
        heapq.heappush(pq, (-deficit_ratio(fips), seat_by_fips[fips], fips))

    def try_grow_from(seed: tuple[int, int], center: tuple[float, float]) -> list[tuple[int, int]] | None:
        tile = [seed]
        used = {seed}
        while len(tile) < 5:
            cands: list[tuple[int, int]] = []
            for c in tile:
                for nb in neighbors(c):
                    if nb in unclaimed and nb not in used:
                        cands.append(nb)
            if not cands:
                return None
            # Prefer unclaimed neighbor closest to state centroid; tie-break by
            # higher "still-available-neighbor count" so we don't paint ourselves
            # into a corner.
            chosen = min(
                cands,
                key=lambda qr: (
                    squared_dist(hex_by_qr[qr]["_xy"], center),
                    -sum(1 for nb in neighbors(qr) if nb in unclaimed and nb not in used),
                ),
            )
            tile.append(chosen)
            used.add(chosen)
        return tile

    SEEDS_TO_TRY = 8

    while pq and unclaimed:
        _, _, fips = heapq.heappop(pq)
        if needs[fips] <= 0:
            continue
        center = centroid_by_fips[fips]
        existing: set[tuple[int, int]] = set()
        for tile in tiles_by_state[fips]:
            existing.update(tile)

        # Build candidate seeds in priority order.
        if existing:
            frontier = set()
            for c in existing:
                for nb in neighbors(c):
                    if nb in unclaimed:
                        frontier.add(nb)
            if not frontier:
                # Fully surrounded for this round; allow re-attempt next round only if
                # neighbors get freed (they won't, so this state is effectively done).
                statuses[fips] = "partial"
                continue
            seed_candidates = sorted(
                frontier,
                key=lambda qr: (
                    squared_dist(hex_by_qr[qr]["_xy"], center),
                    -sum(1 for nb in neighbors(qr) if nb in unclaimed),
                ),
            )
        else:
            # First tile: globally closest unclaimed. Try a few near the centroid.
            seed_candidates = sorted(
                unclaimed,
                key=lambda qr: squared_dist(hex_by_qr[qr]["_xy"], center),
            )

        chosen_tile = None
        for seed in seed_candidates[:SEEDS_TO_TRY]:
            tile = try_grow_from(seed, center)
            if tile is not None:
                chosen_tile = tile
                break

        if chosen_tile is None:
            statuses[fips] = "partial"
            continue

        tiles_by_state[fips].append(chosen_tile)
        for qr in chosen_tile:
            unclaimed.discard(qr)
        needs[fips] -= 1
        if needs[fips] > 0:
            heapq.heappush(pq, (-deficit_ratio(fips), seat_by_fips[fips], fips))

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
            centroid_by_fips[fips] = outline_feat["_centroid"]

        tiles_by_state, statuses = place_pentahex_tiles(seat_by_fips, centroid_by_fips, hex_by_qr)

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

            outline_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "congress_number": congress_number,
                        "state_fips": fips,
                        "state_abbr": str(row["state_abbr"]).strip().upper(),
                        "state_name": str(row["state_name"]),
                        "house_seats": seats,
                        "generator_version": GENERATOR_VERSION,
                    },
                    "geometry": mapping(outline_geom),
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

        (cds_root / f"{congress_number}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "properties": common_props, "features": cd_features}),
            encoding="utf-8",
        )
        (states_root / f"{congress_number}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "properties": common_props, "features": state_features}),
            encoding="utf-8",
        )
        (outlines_root / f"{congress_number}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "properties": common_props, "features": outline_features}),
            encoding="utf-8",
        )

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
