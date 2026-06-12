"""Read-only temporal-stability diagnostic over the COMMITTED per-Congress state outputs.

For every consecutive Congress pair, measures per-state centroid displacement (in units of
R = 35000 m) from data_processed/polyhex_states_by_congress/<n>.geojson. Prints a summary of
how stable the timeline actually is and which transitions / states move most. No writes.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATES = ROOT / "data_processed" / "polyhex_states_by_congress"
R = 35000.0


def centroids(n: int) -> dict[str, tuple[float, float]]:
    fc = json.loads((STATES / f"{n}.geojson").read_text(encoding="utf-8"))
    out = {}
    for ft in fc["features"]:
        g = ft["geometry"]
        # centroid of all ring vertices is plenty for a movement metric
        xs, ys, k = 0.0, 0.0, 0
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for x, y in poly[0]:
                xs += x; ys += y; k += 1
        out[ft["properties"]["state_fips"]] = (xs / k, ys / k)
    return out


def main() -> None:
    nums = sorted(int(p.stem) for p in STATES.glob("[0-9]*.geojson"))
    prev = None
    rows = []  # (n, n_common, mean_dR, max_dR, worst_fips, n_new)
    per_state_total: dict[str, float] = {}
    for n in nums:
        cur = centroids(n)
        if prev is not None:
            common = set(cur) & set(prev)
            ds = {f: math.hypot(cur[f][0] - prev[f][0], cur[f][1] - prev[f][1]) / R for f in common}
            worst = max(ds, key=ds.get) if ds else None
            rows.append((n, len(common), sum(ds.values()) / max(len(ds), 1),
                         ds[worst] if worst else 0.0, worst, len(set(cur) - set(prev))))
            for f, d in ds.items():
                per_state_total[f] = per_state_total.get(f, 0.0) + d
        prev = cur

    zero = [r for r in rows if r[3] < 0.05]
    small = [r for r in rows if 0.05 <= r[3] < 1.0]
    med = [r for r in rows if 1.0 <= r[3] < 5.0]
    big = [r for r in rows if r[3] >= 5.0]
    print(f"transitions: {len(rows)}  |  max-move <0.05R (frozen): {len(zero)}  "
          f"0.05-1R: {len(small)}  1-5R: {len(med)}  >=5R: {len(big)}")
    print("\nTransitions with max state move >= 1R (n: meanR maxR worst-state, +new states):")
    for n, nc, mean_d, max_d, worst, new in rows:
        if max_d >= 1.0:
            print(f"  C{n - 1:>3}->C{n:<3} mean={mean_d:6.2f}R max={max_d:7.2f}R worst={worst} new={new}")
    print("\nTop 12 states by total path length across all transitions (R units):")
    for f, tot in sorted(per_state_total.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {f}: {tot:8.1f}R")


if __name__ == "__main__":
    main()
