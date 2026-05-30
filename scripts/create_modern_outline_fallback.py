#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import shapefile
from shapely.geometry import Polygon, MultiPolygon, shape, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent

STATE_FIPS_BY_ABBR = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20",
    "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
    "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def shape_to_polygons(s: shapefile.Shape) -> list[Polygon]:
    points = s.points
    parts = list(s.parts)
    if not parts:
        return []
    out: list[Polygon] = []
    for i, start in enumerate(parts):
        end = parts[i + 1] if i + 1 < len(parts) else len(points)
        ring = [(float(x), float(y)) for x, y in points[start:end]]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        try:
            poly = Polygon(ring)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            out.append(poly)
        except Exception:
            continue
    return out


def dissolve_state_hexes(template_shp: Path) -> dict[str, dict]:
    reader = shapefile.Reader(str(template_shp))
    fields = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
    state_idx = fields.index("STATEAB")
    name_idx = fields.index("STATENAME") if "STATENAME" in fields else None

    by_state: dict[str, dict] = defaultdict(lambda: {"name": "", "polygons": []})
    for sr in reader.iterShapeRecords():
        abbr = str(sr.record[state_idx]).strip().upper()
        if not abbr:
            continue
        if name_idx is not None and not by_state[abbr]["name"]:
            by_state[abbr]["name"] = str(sr.record[name_idx]).strip()
        by_state[abbr]["polygons"].extend(shape_to_polygons(sr.shape))

    dissolved: dict[str, dict] = {}
    for abbr, data in by_state.items():
        polys = data["polygons"]
        if not polys:
            continue
        merged = unary_union(polys)
        # Slight buffer to close hairline seams between hexes, then unbuffer
        # to keep the outer silhouette stable.
        sealed = merged.buffer(1.0).buffer(-1.0)
        if sealed.is_empty:
            sealed = merged
        if isinstance(sealed, Polygon):
            sealed = MultiPolygon([sealed])
        elif not isinstance(sealed, MultiPolygon):
            sealed = MultiPolygon([g for g in getattr(sealed, "geoms", []) if isinstance(g, Polygon)])
        dissolved[abbr] = {"name": data["name"] or abbr, "geometry": mapping(sealed)}
    return dissolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create modern-outline fallback boundaries (in Web Mercator) by dissolving the HexCDv31wm template per state."
    )
    parser.add_argument(
        "--template-shp",
        default=str(ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.shp"),
    )
    parser.add_argument("--out", default=str(ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"))
    parser.add_argument("--from-congress", type=int, default=1)
    parser.add_argument("--to-congress", type=int, default=119)
    args = parser.parse_args()

    template_shp = Path(args.template_shp)
    if not template_shp.exists():
        raise SystemExit(f"Template shapefile missing: {template_shp}")

    out = Path(args.out)
    dissolved = dissolve_state_hexes(template_shp)

    features = []
    for abbr in sorted(dissolved):
        fips = STATE_FIPS_BY_ABBR.get(abbr)
        if not fips:
            continue
        data = dissolved[abbr]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "from_congress": int(args.from_congress),
                    "to_congress": int(args.to_congress),
                    "state_fips": fips,
                    "state_abbr": abbr,
                    "state_name": data["name"],
                    "source_boundary_id": "modern-fallback-from-hexcdv31wm",
                },
                "geometry": data["geometry"],
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
    print(f"Wrote modern-outline fallback boundaries (WM) to {out}")


if __name__ == "__main__":
    main()
