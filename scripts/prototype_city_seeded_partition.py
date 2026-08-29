#!/usr/bin/env python3
"""PROTOTYPE — THROWAWAY. Wayfinder ticket #18 (map #12).

Question: does city-seeded compact-first partitioning tile reliably, and what do
the urban clusters look like?

Mechanism: monkeypatch two seams of tile_state_pentahexes (no production edits):
  * compute_scaled_layout — stash each state's (anchor, scale, displacement) so a
    real web-mercator city point can be mapped into hex space.
  * place_pentahex_tiles — after the proven pipeline tiles a state, re-partition
    the SAME allocated cells city-seeded for anchor states. On success the tiles
    are replaced (urban tiles tagged for viz); on any dead-end the state keeps
    its original tiles and a "bail" is recorded. warnings: 0 therefore holds by
    construction; the measured outcomes are bail rate and cluster shape.

Urban seat counts are CRUDE (fixed modern-ish fraction of the delegation, all
eras) — this prototypes partition mechanics, not the count formula (ticket #16).

Run (quick look, plots 3 states):   python scripts/prototype_city_seeded_partition.py --congresses 119
Run (full 119 sweep, ~20-35 min):   python scripts/prototype_city_seeded_partition.py
Outputs land in the scratch dir printed at start; nothing under data_processed/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import tile_state_pentahexes as T  # noqa: E402

SCRATCH = ROOT / "prototype_out_city_seeded"  # PROTOTYPE — wipe me

# fips -> [(name, lon, lat, frac_of_state_seats_urban)]
CITY_ANCHORS: dict[str, list[tuple[str, float, float, float]]] = {
    "06": [("San Francisco", -122.42, 37.77, 0.20), ("Los Angeles", -118.24, 34.05, 0.35)],
    "17": [("Chicago", -87.63, 41.88, 0.50)],
    "36": [("New York", -74.01, 40.71, 0.60)],
}

_EARTH = 6378137.0


def lonlat_to_wm(lon: float, lat: float) -> tuple[float, float]:
    return (
        _EARTH * math.radians(lon),
        _EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


# ---------------------------------------------------------------- city-seeded partition

def grow_urban_tile(avail, seed, xy_of, anchor_xy, relaxed: bool):
    """Grow one pentahex from `seed` toward the anchor.

    relaxed=False: pure compactness (hug the tile, then nearest anchor) — no
    anti-stranding term; the caller's feasibility check is the only guard.
    relaxed=True: production-style anti-stranding ordering (degree, -internal)
    with nearest-anchor tiebreak — tried when the pure-compact tile strands cells.
    """
    tile = [seed]
    used = {seed}
    while len(tile) < 5:
        cands = {}
        for c in tile:
            for nb in T.neighbors(c):
                if nb in avail and nb not in used and nb not in cands:
                    internal = sum(1 for n2 in T.neighbors(nb) if n2 in used)
                    dist = T.squared_dist(xy_of(nb), anchor_xy)
                    if relaxed:
                        deg = sum(1 for n2 in T.neighbors(nb) if n2 in avail and n2 not in used)
                        cands[nb] = (deg, -internal, dist)
                    else:
                        cands[nb] = (-internal, dist)
        if not cands:
            return None
        chosen = min(cands, key=lambda nb: cands[nb])
        tile.append(chosen)
        used.add(chosen)
    return tile


def partition_city_seeded(cells, anchors, xy_of):
    """anchors: [(name, (x, y) hex-space, n_tiles)]. Returns (tiles, urban_names)
    aligned lists, or None on bail. Rural remainder uses the proven partitioner."""
    avail = set(cells)
    tiles: list[list[tuple[int, int]]] = []
    urban_names: list[str | None] = []
    relaxed_tiles = 0
    for name, axy, n_tiles in anchors:
        for _ in range(n_tiles):
            seeds = sorted(avail, key=lambda c: T.squared_dist(xy_of(c), axy))[:12]
            chosen = None
            for relaxed in (False, True):
                for s in seeds:
                    t = grow_urban_tile(avail, s, xy_of, axy, relaxed)
                    if t is not None and T.is_partition_feasible(avail - set(t)):
                        chosen = t
                        break
                if chosen is not None:
                    relaxed_tiles += int(relaxed)
                    break
            if chosen is None:
                return None  # bail — caller keeps the proven tiles
            tiles.append(chosen)
            urban_names.append(name)
            avail -= set(chosen)
    if avail:
        boundary = {c for c in avail if any(nb not in avail for nb in T.neighbors(c))}
        rest = T.partition_into_pentahexes(avail, boundary, use_compact=True)
        if len(rest) * 5 != len(avail):
            rest = T.partition_into_pentahexes(avail, boundary, use_compact=False)
        if len(rest) * 5 != len(avail):
            return None
        tiles.extend(rest)
        urban_names.extend([None] * len(rest))
    return tiles, urban_names, relaxed_tiles


# ---------------------------------------------------------------- monkeypatched seams

_latest_layout: dict = {}
RESULTS: list[dict] = []  # one record per (congress, state) attempt
_current_congress: list[int] = [0]
URBAN_TAGS: dict[tuple[int, str], list[str | None]] = {}
_HEX_BY_QR: dict = {}

_orig_layout = T.compute_scaled_layout
_orig_place = T.place_pentahex_tiles
_orig_load_seats = T.load_seats


def patched_layout(*a, **kw):
    lay = _orig_layout(*a, **kw)
    _latest_layout.clear()
    _latest_layout.update(lay)
    return lay


def anchors_in_hex_space(fips: str, seats: int):
    rec = _latest_layout.get(fips)
    if rec is None:
        return []
    ax, ay = rec["anchor"]
    s = rec["scale"]
    dx, dy = rec["displacement"]
    out = []
    for name, lon, lat, frac in CITY_ANCHORS[fips]:
        n = round(frac * seats)
        if n < 1:
            continue
        x, y = lonlat_to_wm(lon, lat)
        out.append((name, (ax + s * (x - ax) + dx, ay + s * (y - ay) + dy), n))
    total = sum(n for _, _, n in out)
    if total > seats:  # tiny-delegation edge: never ask for more tiles than exist
        out = [(nm, xy, max(1, n * seats // total)) for nm, xy, n in out][:seats]
    return out


def patched_place(seat_by_fips, centroid_by_fips, cell_outline_fips, hex_by_qr):
    tiles_by_state, statuses = _orig_place(seat_by_fips, centroid_by_fips, cell_outline_fips, hex_by_qr)
    _HEX_BY_QR.update(hex_by_qr)
    xy_of = lambda qr: hex_by_qr[qr]["_xy"]  # noqa: E731
    cong = _current_congress[0]
    for fips in CITY_ANCHORS:
        seats = seat_by_fips.get(fips, 0)
        if seats <= 0 or statuses.get(fips) != "ok":
            continue
        cells = {qr for t in tiles_by_state[fips] for qr in t}
        anchors = anchors_in_hex_space(fips, seats)
        if not anchors:
            RESULTS.append({"congress": cong, "fips": fips, "seats": seats, "outcome": "no-anchor-share"})
            continue
        res = partition_city_seeded(cells, anchors, xy_of)
        rec = {
            "congress": cong, "fips": fips, "seats": seats,
            "urban_tiles": sum(n for _, _, n in anchors),
            "anchors": [nm for nm, _, _ in anchors],
        }
        if res is None:
            rec["outcome"] = "bail"
        else:
            tiles, urban_names, relaxed_tiles = res
            rec["outcome"] = "ok"
            rec["relaxed_tiles"] = relaxed_tiles
            base = tiles_by_state[fips]
            rec["internal_edges_base"] = sum(T._tile_internal_edges(set(t)) for t in base) / len(base)
            rec["internal_edges_proto"] = sum(T._tile_internal_edges(set(t)) for t in tiles) / len(tiles)
            tiles_by_state[fips] = tiles
            URBAN_TAGS[(cong, fips)] = urban_names
        RESULTS.append(rec)
    return tiles_by_state, statuses


CONGRESS_FILTER: set[int] | None = None
_congress_sequence: list[int] = []


def patched_load_seats(path):
    seats = _orig_load_seats(path)
    if CONGRESS_FILTER:
        seats = {k: v for k, v in seats.items() if k in CONGRESS_FILTER}
    _congress_sequence.extend(sorted(seats))
    return seats


# Track the current congress: main's loop calls build_effective_outlines exactly
# once per congress, in ascending order (single call site inside the loop), so
# advancing through the sorted congress list on each call tracks it reliably —
# unlike place_pentahex_tiles, which the escalation ladder can call several times.
_orig_beo = T.build_effective_outlines


def patched_beo(outlines, seated_fips):
    _current_congress[0] = _congress_sequence[_current_congress[1]]
    _current_congress[1] += 1
    return _orig_beo(outlines, seated_fips)


_current_congress.append(0)  # index into _congress_sequence


# ---------------------------------------------------------------- viz

def plot_state(cong: int, fips: str, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import RegularPolygon

    tags = URBAN_TAGS.get((cong, fips))
    tiles = _PLOT_TILES.get((cong, fips))
    if tags is None or tiles is None:
        return False
    names = [nm for nm, _, _ in _PLOT_ANCHORS.get((cong, fips), [])]
    colors = {None: "#d9d2b8"}
    palette = ["#7a1f1f", "#1f4e7a", "#3a6b35", "#7a5c1f"]
    for i, nm in enumerate(names):
        colors[nm] = palette[i % len(palette)]
    from matplotlib.colors import to_rgb
    from shapely.ops import unary_union

    def shade(base_hex: str, k: int):
        # cycle 4 lightness steps per tile so neighbouring districts of one
        # cluster stay distinguishable
        r, g, b = to_rgb(base_hex)
        f = (k % 4) * 0.13
        return (r + (1 - r) * f, g + (1 - g) * f, b + (1 - b) * f)

    fig, ax = plt.subplots(figsize=(9, 9))
    R = None
    for i, (tile, tag) in enumerate(zip(tiles, tags)):
        face = shade(colors[tag], i)
        for qr in tile:
            f = _HEX_BY_QR[qr]
            x, y = f["_xy"]
            R = f["properties"]["R"]
            ax.add_patch(RegularPolygon((x, y), 6, radius=R, orientation=0,
                                        facecolor=face, edgecolor="none"))
        # heavy outline around each pentahex so district boundaries are visible
        merged = unary_union([_HEX_BY_QR[qr]["_geom"] for qr in tile])
        for poly in getattr(merged, "geoms", [merged]):
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, color="white", linewidth=1.8, solid_capstyle="round")
    for nm, (x, y), n in _PLOT_ANCHORS.get((cong, fips), []):
        ax.plot(x, y, marker="*", ms=22, color="black", mec="white")
        ax.annotate(f"{nm} ({n} CDs)", (x, y), textcoords="offset points", xytext=(10, 10), fontsize=11)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_axis_off()
    ax.set_title(f"C{cong} {fips} — city-seeded partition (urban colored, rural sand)")
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return True


_PLOT_TILES: dict = {}
_PLOT_ANCHORS: dict = {}


PLOT_CONGRESSES = {30, 68, 90, 119}  # keep the full sweep from hoarding all 119


def patched_place_with_capture(seat_by_fips, centroid_by_fips, cell_outline_fips, hex_by_qr):
    tbs, st = patched_place(seat_by_fips, centroid_by_fips, cell_outline_fips, hex_by_qr)
    cong = _current_congress[0]
    if cong not in PLOT_CONGRESSES and not (CONGRESS_FILTER and cong in CONGRESS_FILTER):
        return tbs, st
    for fips in CITY_ANCHORS:
        if (cong, fips) in URBAN_TAGS:
            _PLOT_TILES[(cong, fips)] = [list(t) for t in tbs[fips]]
            _PLOT_ANCHORS[(cong, fips)] = anchors_in_hex_space(fips, seat_by_fips.get(fips, 0))
    return tbs, st


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congresses", default="", help="comma list for a quick look; empty = full sweep")
    args = ap.parse_args()

    global CONGRESS_FILTER
    if args.congresses:
        CONGRESS_FILTER = {int(x) for x in args.congresses.split(",")}

    SCRATCH.mkdir(exist_ok=True)
    print(f"PROTOTYPE outputs -> {SCRATCH}")

    T.compute_scaled_layout = patched_layout
    T.place_pentahex_tiles = patched_place_with_capture
    T.load_seats = patched_load_seats
    T.build_effective_outlines = patched_beo

    out = SCRATCH / "tiler_out"
    sys.argv = [
        "tile_state_pentahexes.py",
        "--cds-out-root", str(out / "cds"),
        "--states-out-root", str(out / "states"),
        "--outlines-out-root", str(out / "outlines"),
        "--warnings-out", str(out / "tiling_warnings.json"),
    ]
    try:
        T.main()
    except SystemExit as e:
        print("tiler exit:", e.code)

    (SCRATCH / "results.json").write_text(json.dumps(RESULTS, indent=1), encoding="utf-8")
    ok = [r for r in RESULTS if r["outcome"] == "ok"]
    bail = [r for r in RESULTS if r["outcome"] == "bail"]
    print(f"\n=== city-seeded partition: {len(ok)} ok, {len(bail)} bail, "
          f"{len(RESULTS) - len(ok) - len(bail)} no-anchor-share ===")
    if bail:
        print("bails:", [(r['congress'], r['fips']) for r in bail])
    if ok:
        db = sum(r["internal_edges_base"] for r in ok) / len(ok)
        dp = sum(r["internal_edges_proto"] for r in ok) / len(ok)
        print(f"mean internal edges/tile (compactness, higher=blobbier): base {db:.2f} -> proto {dp:.2f}")
    for (cong, fips) in sorted(_PLOT_TILES):
        png = SCRATCH / f"c{cong}_{fips}.png"
        if plot_state(cong, fips, png):
            print("wrote", png)


if __name__ == "__main__":
    main()
