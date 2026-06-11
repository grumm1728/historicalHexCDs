"""Read-only: how closely does a generated Congress match the HexCDv31wm reference layout?

Primary metric: per-state IoU between the rendered geometry
(data_processed/polyhex_states_by_congress/<n>.geojson) and the state's reference blob,
both in hex space (the blob is similarity-transformed exactly the way the tiler transforms
anchors). Edge alignment is the goal, so footprint overlap is the honest score — centroid
distance alone can look perfect while coastlines misalign.

For C119 (same apportionment as the reference) IoU is the headline target; for earlier
Congresses states are smaller than their blobs, so IoU is bounded by the area ratio and only
the relative ranking is meaningful.
"""
import argparse
import json
import math
from pathlib import Path

from shapely.affinity import affine_transform
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
R = 35000.0
HEX_AREA = 1.5 * math.sqrt(3) * R * R


def reference_blobs_hexspace() -> tuple[dict[str, object], dict[str, str]]:
    ref = json.loads((ROOT / "data_raw" / "reference" / "hexcdv31_anchors.json").read_text(encoding="utf-8"))
    outlines = json.loads(
        (ROOT / "data_processed" / "states" / "state_outlines_modern_wm.geojson").read_text(encoding="utf-8")
    )
    union = unary_union([shape(f["geometry"]) for f in outlines["features"]])
    cc = union.centroid  # == the tiler's compaction_center (same outlines, same union)
    s = math.sqrt(HEX_AREA / ref["hex_area_ref"])
    rcx, rcy = ref["map_centroid"]
    mat = [s, 0, 0, s, cc.x - s * rcx, cc.y - s * rcy]
    blobs = {f: affine_transform(shape(st["blob"]), mat) for f, st in ref["states"].items()}
    abbrs = {f: st["abbr"] for f, st in ref["states"].items()}
    return blobs, abbrs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--congress", type=int, default=119)
    ap.add_argument("--top", type=int, default=10, help="How many worst-fitting states to list")
    args = ap.parse_args()

    blobs, abbrs = reference_blobs_hexspace()
    fc = json.loads(
        (ROOT / "data_processed" / "polyhex_states_by_congress" / f"{args.congress}.geojson").read_text(encoding="utf-8")
    )
    ious: dict[str, float] = {}
    for ft in fc["features"]:
        f = ft["properties"]["state_fips"]
        blob = blobs.get(f)
        if blob is None:
            continue
        g = shape(ft["geometry"])
        inter = g.intersection(blob).area
        ious[f] = inter / (g.area + blob.area - inter)
    vals = sorted(ious.values())
    mean = sum(vals) / len(vals)
    print(f"C{args.congress}: {len(ious)} states, rendered-vs-reference-blob IoU  "
          f"mean={mean:.3f}  median={vals[len(vals) // 2]:.3f}  min={vals[0]:.3f}")
    print(f"worst {args.top}:")
    for f, v in sorted(ious.items(), key=lambda kv: kv[1])[: args.top]:
        print(f"  {abbrs.get(f, f)}: {v:.3f}")


if __name__ == "__main__":
    main()
