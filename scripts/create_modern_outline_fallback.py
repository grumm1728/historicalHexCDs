#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

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


def to_multipolygon(geometry: dict) -> list:
    gtype = geometry.get("type")
    if gtype == "Polygon":
        return [geometry.get("coordinates", [])]
    if gtype == "MultiPolygon":
        return geometry.get("coordinates", [])
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Create modern-outline fallback boundaries for all Congresses")
    parser.add_argument("--source", default=str(ROOT / "data_processed" / "polyhex_by_congress" / "118.geojson"))
    parser.add_argument("--out", default=str(ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"))
    parser.add_argument("--from-congress", type=int, default=1)
    parser.add_argument("--to-congress", type=int, default=119)
    args = parser.parse_args()

    src = Path(args.source)
    out = Path(args.out)

    if not src.exists():
        raise SystemExit(
            f"Fallback source missing: {src}. Generate it with scripts/build_timeline.py or provide NHGIS boundaries."
        )

    raw = json.loads(src.read_text(encoding="utf-8"))
    by_state = defaultdict(lambda: {"state_name": "", "multipoly": []})

    for feature in raw.get("features", []):
        props = feature.get("properties", {})
        abbr = str(props.get("state_abbr", "")).strip().upper()
        if not abbr:
            continue
        by_state[abbr]["state_name"] = str(props.get("state_name", abbr)).strip() or abbr
        by_state[abbr]["multipoly"].extend(to_multipolygon(feature.get("geometry", {})))

    features = []
    for abbr, data in sorted(by_state.items()):
        state_fips = STATE_FIPS_BY_ABBR.get(abbr)
        if not state_fips:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "from_congress": int(args.from_congress),
                    "to_congress": int(args.to_congress),
                    "state_fips": state_fips,
                    "state_abbr": abbr,
                    "state_name": data["state_name"],
                    "source_boundary_id": "modern-fallback-from-118",
                },
                "geometry": {"type": "MultiPolygon", "coordinates": data["multipoly"]},
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
    print(f"Wrote modern-outline fallback boundaries to {out}")


if __name__ == "__main__":
    main()
