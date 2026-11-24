"""Split each seat into its 5 waffle cells for the vote-share display (#59).

The vote-share waffle draws a seat as 5 cells, each standing for a 20-point band of the
two-party Democratic share. The tiler records each seat's 5 hex-cell centres
(`cell_centers`), but the rendered tile is not 5 clean hexes: boundary tiles are clipped
to the state outline and absorb the outline-snap slivers. So the rendered tile is split
among its cell centres by Voronoi. The 5 pieces always add up exactly to the drawn tile,
and a merged sliver goes to its nearest cell.

Cells are ranked north to south (`cell_rank` 0 = northmost, ties west first). The viewer
fills blue from rank 0: rank k covers the share band [20k, 20k+20)%.

Writes `data_processed/seat_cells_by_congress/<n>.geojson` (state_abbr, cd_index,
cell_rank), same coordinates as the seat file. Label-only: never changes seat geometry.

Run:  python scripts/build_waffle_cells.py [--congress 119 ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import shapely
from shapely.geometry import MultiPoint, Point, mapping, shape

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data_processed"
OUT_DIR = PROC / "seat_cells_by_congress"


def split_seat(geom, centers: list[tuple[float, float]]) -> list[tuple[int, object]]:
    """(cell_rank, piece) for each cell centre; pieces partition `geom`."""
    order = sorted(range(len(centers)), key=lambda i: (-centers[i][1], centers[i][0]))
    rank = {i: k for k, i in enumerate(order)}
    cells = shapely.voronoi_polygons(MultiPoint(centers), extend_to=geom.envelope.buffer(1.0))
    pieces = []
    for cell in cells.geoms:
        owner = next(i for i, c in enumerate(centers) if cell.contains(Point(c)))
        piece = cell.intersection(geom)
        if not piece.is_empty and piece.area > 0:
            pieces.append((rank[owner], piece))
    return sorted(pieces, key=lambda t: t[0])


def build(congress: int) -> dict:
    fc = json.loads((PROC / "polyhex_cds_by_congress" / f"{congress}.geojson").read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        p = f["properties"]
        centers = [tuple(c) for c in p.get("cell_centers") or []]
        if len(centers) != 5:
            raise SystemExit(f"C{congress} {p['state_abbr']}-{p['cd_index']}: no cell_centers; "
                             "re-run scripts/tile_state_pentahexes.py")
        for rank, piece in split_seat(shape(f["geometry"]), centers):
            out.append({"type": "Feature",
                        "properties": {"state_abbr": p["state_abbr"], "cd_index": p["cd_index"], "cell_rank": rank},
                        "geometry": mapping(piece)})
    return {"type": "FeatureCollection", "features": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congress", type=int, nargs="*", default=[119])
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for congress in args.congress:
        fc = build(congress)
        (OUT_DIR / f"{congress}.geojson").write_text(json.dumps(fc), encoding="utf-8")
        print(f"C{congress}: {len(fc['features'])} waffle cells")


if __name__ == "__main__":
    main()
