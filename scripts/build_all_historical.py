#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SHP = ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.shp"
TEMPLATE_PRJ = ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.prj"


def run(script_name: str, *args: str) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / script_name), *args]
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def build_congress_index(max_congress: int) -> None:
    polyhex_index_path = ROOT / "data_processed" / "polyhex_states_by_congress" / "_index.json"
    if not polyhex_index_path.exists():
        raise SystemExit(f"Missing polyhex index: {polyhex_index_path}")

    polyhex_index = json.loads(polyhex_index_path.read_text(encoding="utf-8"))
    timeline = []

    for item in polyhex_index.get("timeline", []):
        congress_number = int(item["congress_number"])
        shapefile_path = Path("data_processed") / "shapefiles" / str(congress_number) / f"HexState_{congress_number}.shp"
        timeline.append(
            {
                "congress_number": congress_number,
                "start_date": item.get("start_date") or None,
                "end_date": item.get("end_date") or None,
                "state_feature_path": item["state_feature_path"],
                "shapefile_path": str(shapefile_path.as_posix()),
                "generator_version": item.get("generator_version", "unknown"),
                "coverage_flags": item.get("coverage_flags", {}),
                "state_feature_count": item.get("state_feature_count", 0),
            }
        )

    timeline.sort(key=lambda x: x["congress_number"])
    index = {
        "generated_on": date.today().isoformat(),
        "render_mode": "clipped_polyhex_only",
        "canonical_unit": "state",
        "max_congress_expected": max_congress,
        "timeline": timeline,
    }

    (ROOT / "data_processed" / "congress_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full historical polyhex pipeline")
    parser.add_argument("--max-congress", type=int, default=119)
    parser.add_argument(
        "--allow-modern-outline-fallback",
        action="store_true",
        help="If NHGIS boundary input is missing, derive modern outlines from the 118 sample and reuse for all Congresses.",
    )
    args = parser.parse_args()

    boundary_input = ROOT / "data_raw" / "nhgis" / "state_boundaries_by_congress.geojson"
    if args.allow_modern_outline_fallback and not boundary_input.exists():
        run(
            "create_modern_outline_fallback.py",
            "--from-congress",
            "1",
            "--to-congress",
            str(args.max_congress),
        )

    run("validate_raw_inputs.py")
    run("build_seat_table.py", "--max-congress", str(args.max_congress))
    run("build_boundary_timeline.py")
    run("generate_polyhex_states.py", "--template-shp", str(TEMPLATE_SHP))
    run("export_shapefiles.py", "--template-prj", str(TEMPLATE_PRJ))
    build_congress_index(args.max_congress)
    print("Historical pipeline complete.")


if __name__ == "__main__":
    main()
