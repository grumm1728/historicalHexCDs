#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v1"


def congress_start_date(congress_number: int) -> date:
    year = 1789 + (congress_number - 1) * 2
    if congress_number >= 74:
        return date(year, 1, 3)
    return date(year, 3, 4)


def congress_end_date(congress_number: int) -> date:
    return congress_start_date(congress_number + 1) - timedelta(days=1)


def ring_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def geometry_bbox(geom: dict) -> tuple[float, float, float, float]:
    gtype = geom.get("type")
    if gtype == "Polygon":
        boxes = [ring_bbox(r) for r in geom.get("coordinates", []) if r]
    elif gtype == "MultiPolygon":
        boxes = [ring_bbox(r) for poly in geom.get("coordinates", []) for r in poly if r]
    else:
        raise ValueError(f"Unsupported geometry type {gtype}")

    if not boxes:
        return (0.0, 0.0, 1.0, 1.0)

    xmin = min(b[0] for b in boxes)
    ymin = min(b[1] for b in boxes)
    xmax = max(b[2] for b in boxes)
    ymax = max(b[3] for b in boxes)
    return xmin, ymin, xmax, ymax


def pointy_hex(cx: float, cy: float, size: float) -> list[list[float]]:
    pts: list[list[float]] = []
    for i in range(6):
        ang = math.radians(60 * i - 30)
        pts.append([cx + size * math.cos(ang), cy + size * math.sin(ang)])
    pts.append(pts[0])
    return pts


def axial_to_xy(q: int, r: int, size: float) -> tuple[float, float]:
    x = size * math.sqrt(3) * (q + r / 2)
    y = size * 1.5 * r
    return x, y


def axial_neighbors(q: int, r: int) -> list[tuple[int, int]]:
    return [
        (q + 1, r),
        (q - 1, r),
        (q, r + 1),
        (q, r - 1),
        (q + 1, r - 1),
        (q - 1, r + 1),
    ]


def connected_cluster(n: int) -> list[tuple[int, int]]:
    cluster = [(0, 0)]
    frontier = [(0, 0)]
    seen = {(0, 0)}

    while len(cluster) < n:
        q, r = frontier.pop(0)
        for nq, nr in axial_neighbors(q, r):
            if (nq, nr) in seen:
                continue
            seen.add((nq, nr))
            cluster.append((nq, nr))
            frontier.append((nq, nr))
            if len(cluster) >= n:
                break
    return cluster


def fit_cluster_to_bbox(n: int, bbox: tuple[float, float, float, float]) -> tuple[list[list[list[float]]], int]:
    xmin, ymin, xmax, ymax = bbox
    w = max(1e-6, xmax - xmin)
    h = max(1e-6, ymax - ymin)
    margin = 0.08

    if n <= 1:
        cx = xmin + (w * 0.5)
        cy = ymin + (h * 0.5)
        size = min(w, h) * 0.28
        ring = pointy_hex(cx, cy, size=max(size, 1e-6))
        return [ring], 1

    cluster = connected_cluster(max(1, n))
    base_size = 1.0
    centers = [axial_to_xy(q, r, base_size) for q, r in cluster]
    cxs = [c[0] for c in centers]
    cys = [c[1] for c in centers]
    cxmin, cxmax = min(cxs), max(cxs)
    cymin, cymax = min(cys), max(cys)

    cw = max(1e-6, cxmax - cxmin)
    ch = max(1e-6, cymax - cymin)

    scale = min((w * (1 - 2 * margin)) / cw if cw else w, (h * (1 - 2 * margin)) / ch if ch else h)
    if not math.isfinite(scale) or scale <= 0:
        scale = min(w, h) * 0.5

    target_xmin = xmin + w * margin
    target_ymin = ymin + h * margin

    rings: list[list[list[float]]] = []
    for x, y in centers:
        tx = target_xmin + (x - cxmin) * scale
        ty = target_ymin + (y - cymin) * scale
        ring = pointy_hex(tx, ty, size=max(scale * 0.45, 1e-6))
        rings.append(ring)

    return rings, len(rings)


def load_boundaries(path: Path) -> dict[int, dict[str, dict]]:
    by_congress: dict[int, dict[str, dict]] = defaultdict(dict)
    for geojson_path in sorted((path / "by_congress").glob("*.geojson"), key=lambda p: int(p.stem)):
        congress_number = int(geojson_path.stem)
        obj = json.loads(geojson_path.read_text(encoding="utf-8"))
        for f in obj.get("features", []):
            props = f.get("properties", {})
            state_fips = str(props.get("state_fips", "")).zfill(2)
            by_congress[congress_number][state_fips] = f
    return by_congress


def load_seats(path: Path) -> dict[int, list[dict]]:
    by_congress: dict[int, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            by_congress[int(row["congress_number"])].append(row)
    return by_congress


def build_state_features(
    congress_number: int,
    seat_rows: list[dict],
    boundary_by_state: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    features: list[dict] = []
    missing_states: list[str] = []

    for row in sorted(seat_rows, key=lambda r: r["state_fips"]):
        state_fips = str(row["state_fips"]).zfill(2)
        seats = int(row["house_seats"])
        admitted = str(row["admitted"]).strip().lower() in {"1", "true", "t", "yes", "y"}

        if not admitted or seats <= 0:
            continue

        boundary_feature = boundary_by_state.get(state_fips)
        if not boundary_feature:
            missing_states.append(state_fips)
            continue

        boundary_geom = boundary_feature.get("geometry", {})
        bbox = geometry_bbox(boundary_geom)
        rings, cell_count = fit_cluster_to_bbox(seats, bbox)

        polyhex_geom = {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}
        bprops = boundary_feature.get("properties", {})

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "congress_number": congress_number,
                    "start_date": congress_start_date(congress_number).isoformat(),
                    "end_date": congress_end_date(congress_number).isoformat(),
                    "state_fips": state_fips,
                    "state_abbr": str(row["state_abbr"]).upper(),
                    "state_name": str(row["state_name"]),
                    "house_seats": seats,
                    "admitted": True,
                    "cell_count": cell_count,
                    "source_boundary_id": str(bprops.get("source_boundary_id", "unknown")),
                    "source_seat_version": str(row.get("source_seat_version", "unknown")),
                    "generator_version": GENERATOR_VERSION,
                },
                "geometry": polyhex_geom,
            }
        )

    return features, missing_states


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate state-level polyhex geometries per Congress")
    parser.add_argument("--seats", default=str(ROOT / "data_processed" / "seats" / "state_seats_by_congress.csv"))
    parser.add_argument("--boundaries", default=str(ROOT / "data_processed" / "boundaries"))
    parser.add_argument("--out-root", default=str(ROOT / "data_processed" / "polyhex_states_by_congress"))
    args = parser.parse_args()

    seats_path = Path(args.seats)
    boundaries_root = Path(args.boundaries)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    by_congress_seats = load_seats(seats_path)
    by_congress_boundaries = load_boundaries(boundaries_root)

    summary = {"generator_version": GENERATOR_VERSION, "timeline": []}

    for congress_number in sorted(by_congress_seats):
        seat_rows = by_congress_seats[congress_number]
        boundary_by_state = by_congress_boundaries.get(congress_number, {})

        features, missing_states = build_state_features(congress_number, seat_rows, boundary_by_state)
        collection = {
            "type": "FeatureCollection",
            "properties": {
                "congress_number": congress_number,
                "start_date": congress_start_date(congress_number).isoformat(),
                "end_date": congress_end_date(congress_number).isoformat(),
                "generator_version": GENERATOR_VERSION,
            },
            "features": features,
        }

        out_path = out_root / f"{congress_number}.geojson"
        out_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")

        summary["timeline"].append(
            {
                "congress_number": congress_number,
                "start_date": congress_start_date(congress_number).isoformat(),
                "end_date": congress_end_date(congress_number).isoformat(),
                "state_feature_path": str((Path("data_processed") / "polyhex_states_by_congress" / f"{congress_number}.geojson").as_posix()),
                "state_feature_count": len(features),
                "coverage_flags": {
                    "missing_boundary_states": missing_states,
                    "used_overrides": False,
                },
                "generator_version": GENERATOR_VERSION,
            }
        )

    (out_root / "_index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote polyhex state files to {out_root}")


if __name__ == "__main__":
    main()
