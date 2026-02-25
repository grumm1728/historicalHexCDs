#!/usr/bin/env python3
"""Build timeline-ready GeoJSON assets from per-Congress polyhex shapefiles.

Input convention:
  data_raw/congress/<congress_number>/HexCDv31.shp

Output:
  data_processed/congress_index.json
  data_processed/polyhex_by_congress/<congress_number>.geojson
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import shapefile  # pyshp


def congress_start_date(congress_number: int) -> date:
    year = 1789 + (congress_number - 1) * 2
    # 20th Amendment moved congressional terms from March 4 to January 3
    # starting with the 74th Congress (1935-01-03).
    if congress_number >= 74:
        return date(year, 1, 3)
    return date(year, 3, 4)


def congress_end_date(congress_number: int) -> date:
    return congress_start_date(congress_number + 1) - timedelta(days=1)


@dataclass
class CongressAsset:
    congress_number: int
    source_shp: Path


def discover_congress_assets(raw_root: Path) -> list[CongressAsset]:
    assets: list[CongressAsset] = []
    congress_root = raw_root / "congress"
    if not congress_root.exists():
        return assets

    for entry in sorted(congress_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        try:
            congress_number = int(entry.name)
        except ValueError:
            continue

        shp = entry / "HexCDv31.shp"
        if shp.exists():
            assets.append(CongressAsset(congress_number=congress_number, source_shp=shp))

    return assets


def ring_signed_area(ring: list[list[float]]) -> float:
    area = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        area += (x1 * y2) - (x2 * y1)
    return area / 2.0


def shape_to_geojson_geometry(shape: shapefile.Shape) -> dict[str, Any]:
    points = shape.points
    part_starts = list(shape.parts)
    if not part_starts:
        return {"type": "Polygon", "coordinates": []}

    part_ranges: list[tuple[int, int]] = []
    for i, start in enumerate(part_starts):
        end = part_starts[i + 1] if i + 1 < len(part_starts) else len(points)
        part_ranges.append((start, end))

    rings: list[list[list[float]]] = []
    for start, end in part_ranges:
        ring = [[float(x), float(y)] for x, y in points[start:end]]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings.append(ring)

    if not rings:
        return {"type": "Polygon", "coordinates": []}

    polygons: list[dict[str, Any]] = []
    for ring in rings:
        if ring_signed_area(ring) >= 0:
            polygons.append({"outer": ring, "holes": []})
        else:
            if polygons:
                polygons[-1]["holes"].append(ring)
            else:
                polygons.append({"outer": ring, "holes": []})

    if len(polygons) == 1:
        return {
            "type": "Polygon",
            "coordinates": [polygons[0]["outer"], *polygons[0]["holes"]],
        }

    return {
        "type": "MultiPolygon",
        "coordinates": [[poly["outer"], *poly["holes"]] for poly in polygons],
    }


def load_congress_geojson(asset: CongressAsset) -> tuple[dict[str, Any], dict[str, int]]:
    reader = shapefile.Reader(str(asset.source_shp))
    fields = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]

    features: list[dict[str, Any]] = []
    seats_by_state: dict[str, int] = defaultdict(int)

    for sr in reader.iterShapeRecords():
        record_dict = dict(zip(fields, sr.record))
        state_abbr = str(record_dict.get("STATEAB", "")).strip()
        state_name = str(record_dict.get("STATENAME", "")).strip()

        if state_abbr:
            seats_by_state[state_abbr] += 1

        feature = {
            "type": "Feature",
            "properties": {
                "congress_number": asset.congress_number,
                "geoid": str(record_dict.get("GEOID", "")).strip(),
                "state_abbr": state_abbr,
                "state_name": state_name,
                "district_label": str(record_dict.get("CDLABEL", "")).strip(),
            },
            "geometry": shape_to_geojson_geometry(sr.shape),
        }
        features.append(feature)

    start_date = congress_start_date(asset.congress_number)
    end_date = congress_end_date(asset.congress_number)
    collection = {
        "type": "FeatureCollection",
        "properties": {
            "congress_number": asset.congress_number,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source": str(asset.source_shp.as_posix()),
            "render_mode": "clipped_polyhex_only",
        },
        "features": features,
    }

    return collection, dict(seats_by_state)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build polyhex timeline assets")
    parser.add_argument("--raw-root", default="data_raw", help="Raw data root")
    parser.add_argument("--out-root", default="data_processed", help="Output root")
    args = parser.parse_args()

    raw_root = Path(args.raw_root)
    out_root = Path(args.out_root)

    assets = discover_congress_assets(raw_root)
    if not assets:
        raise SystemExit("No congress shapefiles found in data_raw/congress/<number>/HexCDv31.shp")

    index: dict[str, Any] = {
        "generated_on": date.today().isoformat(),
        "render_mode": "clipped_polyhex_only",
        "timeline": [],
    }

    for asset in assets:
        collection, seats_by_state = load_congress_geojson(asset)
        output_path = out_root / "polyhex_by_congress" / f"{asset.congress_number}.geojson"
        write_json(output_path, collection)

        start_date = congress_start_date(asset.congress_number)
        end_date = congress_end_date(asset.congress_number)
        index["timeline"].append(
            {
                "congress_number": asset.congress_number,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "feature_path": str(output_path.as_posix()),
                "state_seat_counts": seats_by_state,
                "total_district_features": len(collection["features"]),
            }
        )

    write_json(out_root / "congress_index.json", index)


if __name__ == "__main__":
    main()
