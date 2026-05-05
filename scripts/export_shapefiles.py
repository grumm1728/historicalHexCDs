#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parent.parent
WGS84_PRJ = "GEOGCS[\"GCS_WGS_1984\",DATUM[\"D_WGS_1984\",SPHEROID[\"WGS_1984\",6378137.0,298.257223563]],PRIMEM[\"Greenwich\",0.0],UNIT[\"Degree\",0.0174532925199433]]"


def geometry_to_parts(geom: dict) -> list[list[list[float]]]:
    gtype = geom.get("type")
    if gtype == "Polygon":
        return [ring for ring in geom.get("coordinates", []) if ring]
    if gtype == "MultiPolygon":
        parts: list[list[list[float]]] = []
        for poly in geom.get("coordinates", []):
            parts.extend([ring for ring in poly if ring])
        return parts
    raise ValueError(f"Unsupported geometry type: {gtype}")


def export_congress_file(path: Path, out_dir: Path, prj_text: str) -> None:
    congress_number = int(path.stem)
    obj = json.loads(path.read_text(encoding="utf-8"))
    features = obj.get("features", [])

    out_dir.mkdir(parents=True, exist_ok=True)
    shp_base = out_dir / f"HexState_{congress_number}"

    writer = shapefile.Writer(str(shp_base), shapeType=shapefile.POLYGON)
    writer.field("CONGRESS", "N", 4, 0)
    writer.field("STFIPS", "C", 2)
    writer.field("STUSPS", "C", 2)
    writer.field("STATENAME", "C", 40)
    writer.field("SEATS", "N", 4, 0)
    writer.field("ADMIT", "L")
    writer.field("CELLS", "N", 4, 0)
    writer.field("SRCBOUND", "C", 50)
    writer.field("SRCSEAT", "C", 50)
    writer.field("GENVER", "C", 20)

    for feature in features:
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        parts = geometry_to_parts(geom)
        writer.poly(parts)
        writer.record(
            int(props.get("congress_number", congress_number)),
            str(props.get("state_fips", ""))[:2],
            str(props.get("state_abbr", ""))[:2],
            str(props.get("state_name", ""))[:40],
            int(props.get("house_seats", 0)),
            bool(props.get("admitted", True)),
            int(props.get("cell_count", 0)),
            str(props.get("source_boundary_id", ""))[:50],
            str(props.get("source_seat_version", ""))[:50],
            str(props.get("generator_version", ""))[:20],
        )

    writer.close()
    (shp_base.with_suffix(".prj")).write_text(prj_text, encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export state-level polyhex GeoJSON to shapefiles")
    parser.add_argument("--input-root", default=str(ROOT / "data_processed" / "polyhex_states_by_congress"))
    parser.add_argument("--out-root", default=str(ROOT / "data_processed" / "shapefiles"))
    parser.add_argument("--template-prj", default="")
    args = parser.parse_args()

    input_root = Path(args.input_root)
    out_root = Path(args.out_root)

    files = sorted([p for p in input_root.glob("*.geojson") if p.stem.isdigit()], key=lambda p: int(p.stem))
    if not files:
        raise SystemExit(f"No GeoJSON congress files found at {input_root}")

    prj_text = WGS84_PRJ
    if args.template_prj:
        tp = Path(args.template_prj)
        if tp.exists():
            prj_text = tp.read_text(encoding="utf-8").strip() or WGS84_PRJ

    for file in files:
        congress_number = int(file.stem)
        export_congress_file(file, out_root / str(congress_number), prj_text)

    print(f"Exported shapefiles to {out_root}")


if __name__ == "__main__":
    main()
