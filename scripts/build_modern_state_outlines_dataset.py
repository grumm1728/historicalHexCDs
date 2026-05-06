#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract 50 modern MVP state outlines into a standalone dataset")
    parser.add_argument("--input", default=str(ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"))
    parser.add_argument("--out", default=str(ROOT / "data_raw" / "states" / "state_outlines_modern.geojson"))
    args = parser.parse_args()

    input_path = Path(args.input)
    out_path = Path(args.out)

    src = json.loads(input_path.read_text(encoding="utf-8"))
    features = src.get("features", [])
    by_fips: dict[str, dict] = {}
    for f in features:
        props = f.get("properties", {})
        fips = str(props.get("state_fips", "")).zfill(2)
        if not fips:
            continue
        by_fips[fips] = {
            "type": "Feature",
            "properties": {
                "state_fips": fips,
                "state_abbr": str(props.get("state_abbr", "")).strip().upper(),
                "state_name": str(props.get("state_name", "")).strip(),
                "source_outline_id": str(props.get("source_boundary_id", "unknown")).strip() or "unknown",
            },
            "geometry": f.get("geometry"),
        }

    if len(by_fips) != 50:
        raise SystemExit(f"Expected 50 state outlines, found {len(by_fips)}")

    out = {
        "type": "FeatureCollection",
        "properties": {
            "outline_version": "modern-mvp-2026",
            "source": str(input_path.as_posix()),
            "state_count": 50,
        },
        "features": [by_fips[k] for k in sorted(by_fips)],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote modern outlines dataset to {out_path}")


if __name__ == "__main__":
    main()

