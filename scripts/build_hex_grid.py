#!/usr/bin/env python3
"""Build a national flat-top hex grid in Web Mercator covering CONUS + AK/HI inset buffer.

Outputs:
- data_processed/hex_grid/hex_grid.geojson  (one Polygon per hex)
- data_processed/hex_grid/hex_grid_meta.json (R, origin, count, bbox)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Flat-top hex neighbor offsets in axial (q, r) coords.
NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


def axial_to_xy(q: int, r: int, R: float, origin: tuple[float, float]) -> tuple[float, float]:
    """Flat-top hex axial to Cartesian center."""
    ox, oy = origin
    x = ox + R * 1.5 * q
    y = oy + R * math.sqrt(3.0) * (r + q / 2.0)
    return (x, y)


def hex_polygon(cx: float, cy: float, R: float) -> list[list[float]]:
    """Closed ring of 6 vertices, flat-top hex centered at (cx, cy).

    Vertex coordinates are rounded to millimetre precision so that shared
    vertices between axially-adjacent hexes compare exactly equal under
    floating-point. Without this rounding, two paths that mathematically
    converge on the same point (e.g. neighbor1.cy + R*sin(60°) vs
    neighbor2.cy + R*sin(-60°)) differ by ~1 ulp, which makes shapely treat
    edge-shared hexes as merely corner-touching MultiPolygons.
    """
    ring: list[list[float]] = []
    for k in range(6):
        a = math.radians(60.0 * k)
        x = round(cx + R * math.cos(a), 3)
        y = round(cy + R * math.sin(a), 3)
        ring.append([x, y])
    ring.append(ring[0])
    return ring


def main() -> None:
    parser = argparse.ArgumentParser(description="Build national hex grid in Web Mercator")
    # CONUS bbox + AK/HI inset buffer (AK & HI are inset into the SW quadrant).
    # Coverage chosen to give us a comfortable buffer past the lower-48 silhouette.
    parser.add_argument("--xmin", type=float, default=-14_500_000.0)
    parser.add_argument("--xmax", type=float, default=-6_900_000.0)
    parser.add_argument("--ymin", type=float, default=2_700_000.0)
    parser.add_argument("--ymax", type=float, default=8_400_000.0)
    parser.add_argument("--R", type=float, default=50_000.0, help="Hex circumradius in meters")
    parser.add_argument("--out-root", default=str(ROOT / "data_processed" / "hex_grid"))
    args = parser.parse_args()

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    R = float(args.R)
    origin = (args.xmin, args.ymin)
    xstep = R * 1.5
    ystep = R * math.sqrt(3.0)

    # Compute axial index ranges that cover the bbox.
    q_max = int(math.ceil((args.xmax - args.xmin) / xstep)) + 1
    r_max = int(math.ceil((args.ymax - args.ymin) / ystep)) + 1
    # r must extend negative as q grows (because y depends on r + q/2).
    r_min = -(q_max // 2) - 1

    features: list[dict] = []
    bbox = [math.inf, math.inf, -math.inf, -math.inf]
    for q in range(0, q_max + 1):
        for r in range(r_min, r_max + 1):
            cx, cy = axial_to_xy(q, r, R, origin)
            if cx < args.xmin - R or cx > args.xmax + R:
                continue
            if cy < args.ymin - R or cy > args.ymax + R:
                continue
            ring = hex_polygon(cx, cy, R)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "q": q,
                        "r": r,
                        "cx": cx,
                        "cy": cy,
                        "R": R,
                    },
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
            if cx < bbox[0]: bbox[0] = cx
            if cy < bbox[1]: bbox[1] = cy
            if cx > bbox[2]: bbox[2] = cx
            if cy > bbox[3]: bbox[3] = cy

    grid_path = out_root / "hex_grid.geojson"
    grid_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )

    meta = {
        "R": R,
        "origin": list(origin),
        "xstep": xstep,
        "ystep": ystep,
        "bbox": bbox,
        "count": len(features),
        "neighbor_offsets": NEIGHBOR_OFFSETS,
        "orientation": "flat-top",
        "crs": "EPSG:3857",
    }
    (out_root / "hex_grid_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {len(features)} hexes (R={R:.0f} m) to {grid_path}")


if __name__ == "__main__":
    main()
