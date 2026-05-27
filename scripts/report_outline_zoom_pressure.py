#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bounds_from_coords(coords, out):
    if isinstance(coords, list):
        if len(coords) == 2 and all(isinstance(v, (int, float)) for v in coords):
            x, y = coords
            out[0] = min(out[0], x)
            out[1] = min(out[1], y)
            out[2] = max(out[2], x)
            out[3] = max(out[3], y)
        else:
            for c in coords:
                bounds_from_coords(c, out)


def feature_bounds(feature):
    out = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    bounds_from_coords(feature["geometry"]["coordinates"], out)
    return tuple(out)


def intersects(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def main() -> None:
    idx = json.loads((ROOT / "data_processed" / "congress_index.json").read_text(encoding="utf-8"))
    rows = []
    for item in idx["timeline"]:
        congress = int(item["congress_number"])
        outline_rel = item.get("state_outline_path")
        if not outline_rel:
            continue
        p = ROOT / outline_rel
        if not p.exists():
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        feats = obj.get("features", [])
        if not feats:
            continue
        bb = [float("inf"), float("inf"), float("-inf"), float("-inf")]
        fbs = []
        for f in feats:
            b = feature_bounds(f)
            fbs.append((f["properties"].get("state_abbr", ""), b))
            bb[0] = min(bb[0], b[0]); bb[1] = min(bb[1], b[1]); bb[2] = max(bb[2], b[2]); bb[3] = max(bb[3], b[3])
        width = bb[2] - bb[0]
        height = bb[3] - bb[1]
        overlap_pairs = 0
        for i in range(len(fbs)):
            for j in range(i + 1, len(fbs)):
                if intersects(fbs[i][1], fbs[j][1]):
                    overlap_pairs += 1
        rows.append((congress, width, height, width * height, overlap_pairs, len(feats)))

    rows.sort(key=lambda r: r[0])
    out_csv = ROOT / "data_processed" / "outline_zoom_pressure.csv"
    lines = ["congress_number,bounds_width,bounds_height,bounds_area,overlap_pairs,feature_count"]
    lines.extend([f"{c},{w:.6f},{h:.6f},{a:.6f},{o},{n}" for c, w, h, a, o, n in rows])
    out_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()

