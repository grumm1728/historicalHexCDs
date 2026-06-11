"""Read-only: how closely does a generated Congress match the HexCDv31wm reference layout?

Compares each state's rendered centroid (data_processed/polyhex_states_by_congress/<n>.geojson)
against its reference anchor (data_raw/reference/hexcdv31_anchors.json) transformed exactly the
way the tiler transforms it (same scale + same fixed national centre). Distances in R units.

For C119 (same apportionment as the reference) this is the headline target metric; for earlier
Congresses larger offsets are expected only where the overlap resolver had to displace a state
whose era delegation outgrew its reference hole.
"""
import argparse
import json
import math
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
R = 35000.0
HEX_AREA = 1.5 * math.sqrt(3) * R * R


def anchor_positions() -> dict[str, tuple[float, float]]:
    ref = json.loads((ROOT / "data_raw" / "reference" / "hexcdv31_anchors.json").read_text(encoding="utf-8"))
    outlines = json.loads(
        (ROOT / "data_processed" / "states" / "state_outlines_modern_wm.geojson").read_text(encoding="utf-8")
    )
    union = unary_union([shape(f["geometry"]) for f in outlines["features"]])
    cc = union.centroid  # == the tiler's compaction_center (same outlines, same union)
    s = math.sqrt(HEX_AREA / ref["hex_area_ref"])
    rcx, rcy = ref["map_centroid"]
    return {
        f: (cc.x + s * (st["centroid"][0] - rcx), cc.y + s * (st["centroid"][1] - rcy))
        for f, st in ref["states"].items()
    }


def rendered_centroids(n: int) -> dict[str, tuple[float, float]]:
    fc = json.loads(
        (ROOT / "data_processed" / "polyhex_states_by_congress" / f"{n}.geojson").read_text(encoding="utf-8")
    )
    return {
        ft["properties"]["state_fips"]: (lambda g: (g.centroid.x, g.centroid.y))(shape(ft["geometry"]))
        for ft in fc["features"]
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--congress", type=int, default=119)
    ap.add_argument("--top", type=int, default=10, help="How many worst-fitting states to list")
    args = ap.parse_args()

    anchors = anchor_positions()
    cents = rendered_centroids(args.congress)
    ds = {
        f: math.hypot(cents[f][0] - anchors[f][0], cents[f][1] - anchors[f][1]) / R
        for f in cents
        if f in anchors
    }
    vals = sorted(ds.values())
    mean = sum(vals) / len(vals)
    print(f"C{args.congress}: {len(ds)} states vs reference anchors  "
          f"mean={mean:.2f}R  median={vals[len(vals) // 2]:.2f}R  max={max(vals):.2f}R")
    print(f"worst {args.top}:")
    for f, d in sorted(ds.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  {f}: {d:6.2f}R")


if __name__ == "__main__":
    main()
