#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    source = ROOT / "data_processed" / "polyhex_by_congress" / "118.geojson"
    if not source.exists():
        raise SystemExit("Bootstrap source missing: data_processed/polyhex_by_congress/118.geojson")

    obj = json.loads(source.read_text(encoding="utf-8"))
    by_state = defaultdict(list)
    for f in obj.get("features", []):
        p = f.get("properties", {})
        by_state[p.get("state_abbr", "")].append(f)

    state_fips_map = {
        "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
        "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20",
        "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
        "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
        "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
        "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
        "WI": "55", "WY": "56"
    }

    seats_lines = ["congress_number,state_fips,state_abbr,state_name,house_seats,admitted,source_seat_version"]
    boundary_features = []

    for abbr in sorted(by_state):
        features = by_state[abbr]
        if not abbr or abbr not in state_fips_map:
            continue
        state_name = features[0]["properties"].get("state_name", abbr)
        seats = len(features)
        state_fips = state_fips_map[abbr]
        seats_lines.append(f"118,{state_fips},{abbr},{state_name},{seats},true,bootstrap-118")
        seats_lines.append(f"119,{state_fips},{abbr},{state_name},{seats},true,bootstrap-118")

        multipoly = []
        for feat in features:
            g = feat.get("geometry", {})
            if g.get("type") == "Polygon":
                multipoly.append(g.get("coordinates", []))
            elif g.get("type") == "MultiPolygon":
                multipoly.extend(g.get("coordinates", []))

        boundary_features.append(
            {
                "type": "Feature",
                "properties": {
                    "from_congress": 118,
                    "to_congress": 119,
                    "state_fips": state_fips,
                    "state_abbr": abbr,
                    "state_name": state_name,
                    "source_boundary_id": "bootstrap-118",
                },
                "geometry": {"type": "MultiPolygon", "coordinates": multipoly},
            }
        )

    seats_path = ROOT / "data_raw" / "seats" / "congress_exact_seats.csv"
    seats_path.parent.mkdir(parents=True, exist_ok=True)
    seats_path.write_text("\n".join(seats_lines) + "\n", encoding="utf-8")

    boundary_path = ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"
    boundary_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_path.write_text(json.dumps({"type": "FeatureCollection", "features": boundary_features}, indent=2), encoding="utf-8")

    print("Wrote bootstrap raw inputs for Congress 118")


if __name__ == "__main__":
    main()
