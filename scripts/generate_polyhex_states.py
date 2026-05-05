#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "v2-template118"


@dataclass
class TemplateCell:
    centroid: tuple[float, float]
    polygons: list[list[list[list[float]]]]
    area: float


def congress_start_date(congress_number: int) -> date:
    year = 1789 + (congress_number - 1) * 2
    if congress_number >= 74:
        return date(year, 1, 3)
    return date(year, 3, 4)


def congress_end_date(congress_number: int) -> date:
    return congress_start_date(congress_number + 1) - timedelta(days=1)


def ring_area(ring: list[list[float]]) -> float:
    a = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        a += (x1 * y2) - (x2 * y1)
    return abs(a / 2.0)


def ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    if len(ring) <= 1:
        return (0.0, 0.0)
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    if not pts:
        return (0.0, 0.0)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    return (sx / len(pts), sy / len(pts))


def shape_to_polygons(shape: shapefile.Shape) -> list[list[list[list[float]]]]:
    points = shape.points
    parts = list(shape.parts)
    if not parts:
        return []

    polygons: list[list[list[list[float]]]] = []
    for i, start in enumerate(parts):
        end = parts[i + 1] if i + 1 < len(parts) else len(points)
        ring = [[float(x), float(y)] for x, y in points[start:end]]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        polygons.append([ring])
    return polygons


def load_template_cells(template_shp: Path) -> dict[str, list[TemplateCell]]:
    reader = shapefile.Reader(str(template_shp))
    fields = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
    state_idx = fields.index("STATEAB")

    by_state: dict[str, list[TemplateCell]] = defaultdict(list)
    for sr in reader.iterShapeRecords():
        state_abbr = str(sr.record[state_idx]).strip().upper()
        polygons = shape_to_polygons(sr.shape)
        if not polygons:
            continue

        first_ring = polygons[0][0]
        centroid = ring_centroid(first_ring)
        area = sum(ring_area(poly[0]) for poly in polygons)
        by_state[state_abbr].append(TemplateCell(centroid=centroid, polygons=polygons, area=area))

    for state_abbr in by_state:
        by_state[state_abbr].sort(key=lambda c: (c.centroid[1], c.centroid[0]))
    return by_state


def euclid(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def adjacency(cells: list[TemplateCell]) -> dict[int, set[int]]:
    if len(cells) <= 1:
        return {0: set()} if cells else {}

    centroids = [c.centroid for c in cells]
    nearest = []
    for i, c in enumerate(centroids):
        d = min(euclid(c, centroids[j]) for j in range(len(centroids)) if j != i)
        nearest.append(d)

    d0 = statistics.median(nearest) if nearest else 0.0
    thresh = d0 * 1.35 if d0 > 0 else 0.0

    adj: dict[int, set[int]] = {i: set() for i in range(len(cells))}
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            d = euclid(centroids[i], centroids[j])
            if d <= thresh:
                adj[i].add(j)
                adj[j].add(i)

    return adj


def connected(indices: set[int], adj: dict[int, set[int]]) -> bool:
    if not indices:
        return True
    start = next(iter(indices))
    q = deque([start])
    seen = {start}
    while q:
        i = q.popleft()
        for n in adj.get(i, set()):
            if n in indices and n not in seen:
                seen.add(n)
                q.append(n)
    return seen == indices


def choose_template_subset(cells: list[TemplateCell], target_n: int) -> list[int]:
    n = len(cells)
    if target_n >= n:
        return list(range(n))
    if target_n <= 0:
        return []
    if target_n == 1:
        cx = sum(c.centroid[0] for c in cells) / n
        cy = sum(c.centroid[1] for c in cells) / n
        best = min(range(n), key=lambda i: euclid(cells[i].centroid, (cx, cy)))
        return [best]

    adj = adjacency(cells)
    selected = set(range(n))

    while len(selected) > target_n:
        cx = sum(cells[i].centroid[0] for i in selected) / len(selected)
        cy = sum(cells[i].centroid[1] for i in selected) / len(selected)
        center = (cx, cy)
        maxd = max(euclid(cells[i].centroid, center) for i in selected) or 1.0

        candidates: list[tuple[float, int]] = []
        for i in selected:
            if len(selected) == 1:
                continue
            trial = set(selected)
            trial.remove(i)
            if not connected(trial, adj):
                continue
            deg = sum(1 for j in adj.get(i, set()) if j in selected)
            dnorm = euclid(cells[i].centroid, center) / maxd
            score = (deg * 2.0) - dnorm
            candidates.append((score, i))

        if not candidates:
            break

        _, drop_i = max(candidates, key=lambda t: t[0])
        selected.remove(drop_i)

    if len(selected) > target_n:
        cx = sum(cells[i].centroid[0] for i in selected) / len(selected)
        cy = sum(cells[i].centroid[1] for i in selected) / len(selected)
        selected = set(sorted(selected, key=lambda i: euclid(cells[i].centroid, (cx, cy)))[:target_n])

    return sorted(selected)


def mean_xy(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def prototype_ring(cells: list[TemplateCell], indices: list[int]) -> list[list[float]]:
    source = cells[indices[0]] if indices else cells[0]
    ring = source.polygons[0][0]
    c = ring_centroid(ring)
    rel = [[p[0] - c[0], p[1] - c[1]] for p in ring]
    return rel


def estimate_spacing(cells: list[TemplateCell], indices: list[int]) -> float:
    if len(indices) < 2:
        return 0.3
    pts = [cells[i].centroid for i in indices]
    nearest = []
    for i, p in enumerate(pts):
        d = min(euclid(p, pts[j]) for j in range(len(pts)) if j != i)
        nearest.append(d)
    d = statistics.median(nearest)
    return d if d > 1e-6 else 0.3


def add_extra_cells(
    cells: list[TemplateCell],
    indices: list[int],
    target_n: int,
) -> list[list[list[list[float]]]]:
    polygons: list[list[list[list[float]]]] = []
    for i in indices:
        polygons.extend(cells[i].polygons)

    if len(polygons) >= target_n:
        return polygons[:target_n]

    centroids = [cells[i].centroid for i in indices] if indices else [c.centroid for c in cells]
    if not centroids:
        return polygons

    spacing = estimate_spacing(cells, indices if indices else list(range(len(cells))))
    proto = prototype_ring(cells, indices if indices else [0])

    current = list(centroids)
    while len(polygons) < target_n:
        center = mean_xy(current)
        cands: list[tuple[float, tuple[float, float]]] = []
        for p in current:
            vx = p[0] - center[0]
            vy = p[1] - center[1]
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                continue
            cand = (p[0] + (vx / mag) * spacing, p[1] + (vy / mag) * spacing)
            min_d = min(euclid(cand, q) for q in current)
            if min_d < spacing * 0.55:
                continue
            cands.append((euclid(cand, center), cand))

        if cands:
            _, chosen = max(cands, key=lambda t: t[0])
        else:
            k = len(polygons) - len(centroids)
            ang = (2 * math.pi * k) / 6.0
            chosen = (center[0] + math.cos(ang) * spacing, center[1] + math.sin(ang) * spacing)

        translated = [[chosen[0] + p[0], chosen[1] + p[1]] for p in proto]
        polygons.append([translated])
        current.append(chosen)

    return polygons


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
    template_by_state: dict[str, list[TemplateCell]],
) -> tuple[list[dict], list[str], list[str]]:
    features: list[dict] = []
    missing_boundary_states: list[str] = []
    missing_template_states: list[str] = []

    for row in sorted(seat_rows, key=lambda r: r["state_fips"]):
        state_fips = str(row["state_fips"]).zfill(2)
        state_abbr = str(row["state_abbr"]).strip().upper()
        seats = int(row["house_seats"])
        admitted = str(row["admitted"]).strip().lower() in {"1", "true", "t", "yes", "y"}

        if not admitted or seats <= 0:
            continue

        template_cells = template_by_state.get(state_abbr)
        if not template_cells:
            missing_template_states.append(state_fips)
            continue

        subset = choose_template_subset(template_cells, seats)
        polygons = add_extra_cells(template_cells, subset, seats)
        cell_count = len(polygons)

        boundary_feature = boundary_by_state.get(state_fips)
        if boundary_feature is None:
            missing_boundary_states.append(state_fips)
            source_boundary_id = "template-118"
        else:
            source_boundary_id = str(boundary_feature.get("properties", {}).get("source_boundary_id", "unknown"))

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "congress_number": congress_number,
                    "start_date": congress_start_date(congress_number).isoformat(),
                    "end_date": congress_end_date(congress_number).isoformat(),
                    "state_fips": state_fips,
                    "state_abbr": state_abbr,
                    "state_name": str(row["state_name"]),
                    "house_seats": seats,
                    "admitted": True,
                    "cell_count": cell_count,
                    "source_boundary_id": source_boundary_id,
                    "source_seat_version": str(row.get("source_seat_version", "unknown")),
                    "generator_version": GENERATOR_VERSION,
                },
                "geometry": {"type": "MultiPolygon", "coordinates": polygons},
            }
        )

    return features, missing_boundary_states, missing_template_states


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate state-level polyhex geometries per Congress from 118 templates")
    parser.add_argument("--seats", default=str(ROOT / "data_processed" / "seats" / "state_seats_by_congress.csv"))
    parser.add_argument("--boundaries", default=str(ROOT / "data_processed" / "boundaries"))
    parser.add_argument(
        "--template-shp",
        default=str(ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.shp"),
    )
    parser.add_argument("--out-root", default=str(ROOT / "data_processed" / "polyhex_states_by_congress"))
    args = parser.parse_args()

    seats_path = Path(args.seats)
    boundaries_root = Path(args.boundaries)
    template_shp = Path(args.template_shp)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if not template_shp.exists():
        raise SystemExit(f"Template shapefile missing: {template_shp}")

    by_congress_seats = load_seats(seats_path)
    by_congress_boundaries = load_boundaries(boundaries_root)
    template_by_state = load_template_cells(template_shp)

    summary = {"generator_version": GENERATOR_VERSION, "timeline": []}

    for congress_number in sorted(by_congress_seats):
        seat_rows = by_congress_seats[congress_number]
        boundary_by_state = by_congress_boundaries.get(congress_number, {})

        features, missing_boundary_states, missing_template_states = build_state_features(
            congress_number,
            seat_rows,
            boundary_by_state,
            template_by_state,
        )

        collection = {
            "type": "FeatureCollection",
            "properties": {
                "congress_number": congress_number,
                "start_date": congress_start_date(congress_number).isoformat(),
                "end_date": congress_end_date(congress_number).isoformat(),
                "generator_version": GENERATOR_VERSION,
                "template_source": str(template_shp.as_posix()),
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
                    "missing_boundary_states": missing_boundary_states,
                    "missing_template_states": missing_template_states,
                    "used_overrides": False,
                },
                "generator_version": GENERATOR_VERSION,
            }
        )

    (out_root / "_index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote polyhex state files to {out_root}")


if __name__ == "__main__":
    main()
