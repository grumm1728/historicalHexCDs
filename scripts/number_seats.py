"""Numbering: assign each state's real districts to its seats, after the tiler (#53, #48).

A label-only pass (docs/adr/0001-numbering-is-a-post-tiler-label.md): it reads the
finished seats (`polyhex_cds_by_congress/<n>.geojson`) and each state's saved layout
record (`state_outlines_by_congress/<n>.geojson`), and never touches geometry.

Each real district is one point, its center of population
(`data_raw/congressional_districts/real_district_points_c113_c119.csv`), projected into
hex space the way the state's outline is drawn (`urban_clusters.to_hex_space`).

Methods
-------
`grouped` (the numbering written out):
  1. Group districts by metro: a district is a metro district of M when at least half its
     population lives in M (`real_districts_c113_c119.csv`, the #35 rule). Group seats by
     their 1.0x-tier metro label. Everything else is the non-metro group.
  2. When a group has more districts than seats, its most marginal districts (lowest
     share in the group's metro, or highest metro share for the non-metro group) move to
     the nearest group that has seats to spare. Each move is a **metro mismatch**.
  3. Within each group, centre and ZCA-whiten the district points and the seat centroids
     separately, then run the Hungarian on squared distance. This matches *relative
     arrangement* (who is north/east of whom), not absolute position, which matters where
     the cartogram blows a dense metro up far beyond its real extent.
`plain` (baseline only): the Hungarian on raw projected points over the whole state.

Metrics (per state, both methods)
---------------------------------
  metro_agreement    share of metro-labelled seats numbered with a district of the same metro
  metro_mismatches   seats whose metro label differs from their district's metro
  direction_agree    share of district pairs whose seat-to-seat bearing is within 45 deg of
                     the real bearing between the two districts
  neighbour_kept     share of real adjacent district pairs whose seats share an edge
  mean_disp_R, max_disp_R
                     seat centroid to projected district point, in hex radii R (report only)

Writes `data_processed/seat_numbering_by_congress/<n>.json` (the `grouped` numbering plus
both methods' metrics) and prints a gate table for the #53 gate states.

Run:  python scripts/number_seats.py [--congress 119 ...]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from urban_clusters import _min_cost_assignment, to_hex_space  # noqa: E402

R = 35000.0
PROC = ROOT / "data_processed"
CD_DIR = ROOT / "data_raw" / "congressional_districts"
OUT_DIR = PROC / "seat_numbering_by_congress"
REAL_CONGRESSES = range(113, 120)

GATE_STATES = ("NY", "CA", "IL", "TX", "PA")
GATE_METRO_AGREEMENT = 0.95
GATE_DIRECTION_AGREE = 0.70
DIRECTION_TOLERANCE_DEG = 45.0
SEAT_EDGE_MIN = 0.1 * R  # rendered seats sharing less boundary than this are not neighbours
NON_METRO = ""


# ----------------------------------------------------------------------------- inputs

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_seats(congress: int) -> dict[str, list[dict]]:
    fc = json.loads((PROC / "polyhex_cds_by_congress" / f"{congress}.geojson").read_text(encoding="utf-8"))
    by_state: dict[str, list[dict]] = defaultdict(list)
    for f in fc["features"]:
        p = f["properties"]
        geom = shape(f["geometry"])
        c = geom.centroid
        by_state[p["state_abbr"]].append({
            "cd_index": int(p["cd_index"]),
            "xy": (c.x, c.y),
            "geom": geom,
            "metro": (p.get("metro_name") or NON_METRO) if p.get("is_metro") else NON_METRO,
        })
    for seats in by_state.values():
        seats.sort(key=lambda s: s["cd_index"])
    return by_state


def load_layout(congress: int) -> dict[str, dict]:
    fc = json.loads((PROC / "state_outlines_by_congress" / f"{congress}.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in fc["features"]:
        p = f["properties"]
        out[p["state_abbr"]] = {"anchor": (p["anchor_x"], p["anchor_y"]), "scale": p["area_scale"],
                                "displacement": (p["displacement_x"], p["displacement_y"])}
    return out


def load_districts(congress: int, layout: dict[str, dict]) -> dict[str, list[dict]]:
    metro = {}
    with (CD_DIR / "real_districts_c113_c119.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["congress"]) == congress:
                metro[(r["state"], r["cd"])] = (r["metro_name"] if r["is_metro"] == "1" else NON_METRO,
                                                float(r["metro_pop_frac"]))
    by_state: dict[str, list[dict]] = defaultdict(list)
    with (CD_DIR / "real_district_points_c113_c119.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["congress"]) != congress:
                continue
            st, cd = r["state"], r["cd"]
            group, frac = metro[(st, cd)]
            by_state[st].append({
                "cd": cd,
                "xy": to_hex_space(st, float(r["lon"]), float(r["lat"]), layout[st]),
                "metro": group,
                "metro_frac": frac,
            })
    for ds in by_state.values():
        ds.sort(key=lambda d: d["cd"])
    return by_state


def load_adjacency(congress: int) -> dict[str, set[tuple[str, str]]]:
    out: dict[str, set[tuple[str, str]]] = defaultdict(set)
    with (CD_DIR / "real_district_adjacency_c113_c119.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["congress"]) == congress:
                out[r["state"]].add((r["cd_a"], r["cd_b"]))
    return out


# ------------------------------------------------------------------------- geometry

def _mean(pts):
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def whiten(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Centre and ZCA-whiten a 2-D point cloud: Sigma^(-1/2) (p - mean).

    ZCA (the symmetric inverse square root) keeps the axes as close to the original as any
    whitening can, so north stays north. Tiny or degenerate clouds get a ridge so a
    near-collinear seat row is not blown up sideways."""
    n = len(pts)
    if n == 1:
        return [(0.0, 0.0)]
    mx, my = _mean(pts)
    d = [(x - mx, y - my) for x, y in pts]
    a = sum(x * x for x, _ in d) / n
    b = sum(x * y for x, y in d) / n
    c = sum(y * y for _, y in d) / n
    ridge = 0.05 * (a + c) / 2 if n > 2 else (a + c) / 2  # n == 2: isotropic scale only
    a, c = a + ridge, c + ridge
    if n == 2:
        b = 0.0
    tr, det = a + c, a * c - b * b
    disc = math.sqrt(max(tr * tr / 4 - det, 0.0))
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    if abs(b) > 1e-12:
        v1 = (l1 - c, b)
    else:
        v1 = (1.0, 0.0) if a >= c else (0.0, 1.0)
    norm = math.hypot(*v1)
    v1 = (v1[0] / norm, v1[1] / norm)
    v2 = (-v1[1], v1[0])
    s1, s2 = 1 / math.sqrt(l1), 1 / math.sqrt(l2)
    # W = s1 v1 v1^T + s2 v2 v2^T
    w11 = s1 * v1[0] * v1[0] + s2 * v2[0] * v2[0]
    w12 = s1 * v1[0] * v1[1] + s2 * v2[0] * v2[1]
    w22 = s1 * v1[1] * v1[1] + s2 * v2[1] * v2[1]
    return [(w11 * x + w12 * y, w12 * x + w22 * y) for x, y in d]


def assign(points: list[tuple[float, float]], targets: list[tuple[float, float]]) -> list[int]:
    cost = [[(p[0] - t[0]) ** 2 + (p[1] - t[1]) ** 2 for t in targets] for p in points]
    return _min_cost_assignment(cost)


# -------------------------------------------------------------------------- methods

def number_plain(seats: list[dict], districts: list[dict]) -> dict[int, str]:
    cols = assign([d["xy"] for d in districts], [s["xy"] for s in seats])
    return {seats[j]["cd_index"]: districts[i]["cd"] for i, j in enumerate(cols)}


def _rebalance(seats: list[dict], districts: list[dict]) -> dict[str, str]:
    """District cd -> group it is matched in. Surplus districts move to the nearest group
    with spare seats, most marginal first."""
    group_of = {d["cd"]: d["metro"] for d in districts}
    seat_groups = defaultdict(list)
    for s in seats:
        seat_groups[s["metro"]].append(s["xy"])
    seat_centre = {g: _mean(xy) for g, xy in seat_groups.items()}

    def counts():
        dc = defaultdict(int)
        for g in group_of.values():
            dc[g] += 1
        return {g: dc.get(g, 0) - len(seat_groups.get(g, [])) for g in set(dc) | set(seat_groups)}

    while True:
        surplus = counts()
        over = sorted(g for g, k in surplus.items() if k > 0)
        if not over:
            return group_of
        g = over[0]
        members = [d for d in districts if group_of[d["cd"]] == g]
        # most marginal: least in its metro; for non-metro, the one most in some metro
        key = (lambda d: -d["metro_frac"]) if g == NON_METRO else (lambda d: d["metro_frac"])
        mover = min(members, key=lambda d: (key(d), d["cd"]))
        spare = [h for h, k in surplus.items() if k < 0]
        dest = min(spare, key=lambda h: (math.dist(mover["xy"], seat_centre[h]), h))
        group_of[mover["cd"]] = dest


def number_grouped(seats: list[dict], districts: list[dict]) -> dict[int, str]:
    group_of = _rebalance(seats, districts)
    out = {}
    for g in sorted({s["metro"] for s in seats}):
        gs = [s for s in seats if s["metro"] == g]
        gd = [d for d in districts if group_of[d["cd"]] == g]
        cols = assign(whiten([d["xy"] for d in gd]), whiten([s["xy"] for s in gs]))
        out.update({gs[j]["cd_index"]: gd[i]["cd"] for i, j in enumerate(cols)})
    return out


# -------------------------------------------------------------------------- metrics

def _bearing(a, b) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def seat_adjacency(seats: list[dict]) -> set[tuple[int, int]]:
    out = set()
    for i, a in enumerate(seats):
        for b in seats[i + 1:]:
            if a["geom"].distance(b["geom"]) > 1.0:
                continue
            shared = a["geom"].boundary.intersection(b["geom"].boundary).length
            if shared >= SEAT_EDGE_MIN:
                out.add((a["cd_index"], b["cd_index"]))
                out.add((b["cd_index"], a["cd_index"]))
    return out


def metrics(numbering: dict[int, str], seats: list[dict], districts: list[dict],
            real_adj: set[tuple[str, str]], seat_adj: set[tuple[int, int]]) -> dict:
    seat_by_cd = {cd: s for s in seats for cd in [numbering[s["cd_index"]]]}
    dist_by_cd = {d["cd"]: d for d in districts}
    metro_seats = [s for s in seats if s["metro"] != NON_METRO]
    agree = sum(dist_by_cd[numbering[s["cd_index"]]]["metro"] == s["metro"] for s in metro_seats)
    mismatches = sum(dist_by_cd[numbering[s["cd_index"]]]["metro"] != s["metro"] for s in seats)

    cds = sorted(dist_by_cd)
    pairs = ok = 0
    for i, a in enumerate(cds):
        for b in cds[i + 1:]:
            real = _bearing(dist_by_cd[a]["xy"], dist_by_cd[b]["xy"])
            drawn = _bearing(seat_by_cd[a]["xy"], seat_by_cd[b]["xy"])
            diff = abs((drawn - real + 180) % 360 - 180)
            pairs += 1
            ok += diff <= DIRECTION_TOLERANCE_DEG
    kept = sum((seat_by_cd[a]["cd_index"], seat_by_cd[b]["cd_index"]) in seat_adj for a, b in real_adj)
    disp = [math.dist(seat_by_cd[cd]["xy"], dist_by_cd[cd]["xy"]) / R for cd in cds]
    return {
        "metro_seats": len(metro_seats),
        "metro_agreement": round(agree / len(metro_seats), 4) if metro_seats else None,
        "metro_mismatches": mismatches,
        "direction_agree": round(ok / pairs, 4) if pairs else None,
        "neighbour_kept": round(kept / len(real_adj), 4) if real_adj else None,
        "mean_disp_R": round(sum(disp) / len(disp), 2),
        "max_disp_R": round(max(disp), 2),
    }


# ----------------------------------------------------------------------------- main

def number_congress(congress: int) -> dict:
    cds_path = PROC / "polyhex_cds_by_congress" / f"{congress}.geojson"
    seats_by_state = load_seats(congress)
    layout = load_layout(congress)
    districts_by_state = load_districts(congress, layout)
    adjacency = load_adjacency(congress)

    states = {}
    for st in sorted(seats_by_state):
        seats, districts = seats_by_state[st], districts_by_state.get(st, [])
        if len(seats) != len(districts):
            raise SystemExit(f"C{congress} {st}: {len(seats)} seats but {len(districts)} real districts")
        if len(seats) == 1:
            states[st] = {"seats": {str(seats[0]["cd_index"]): districts[0]["cd"]}, "at_large": True}
            continue
        sadj = seat_adjacency(seats)
        grouped = number_grouped(seats, districts)
        plain = number_plain(seats, districts)
        states[st] = {
            "seats": {str(k): grouped[k] for k in sorted(grouped)},
            "metrics": {"grouped": metrics(grouped, seats, districts, adjacency[st], sadj),
                        "plain": metrics(plain, seats, districts, adjacency[st], sadj)},
        }
    return {
        "congress": congress,
        "method": "grouped-whitened-hungarian",
        "district_point": "center of population (Census tract centers)",
        "metro_tier": 1.0,
        "source": {"polyhex_cds": cds_path.relative_to(ROOT).as_posix(), "sha256": sha256(cds_path)},
        "states": states,
    }


def gate_report(result: dict) -> bool:
    print(f"C{result['congress']} gate (metro agreement >= {GATE_METRO_AGREEMENT:.0%}, "
          f"direction >= {GATE_DIRECTION_AGREE:.0%})")
    print(f"  {'state':5} {'method':8} {'metroAg':>8} {'mism':>5} {'dirAg':>6} {'nbrKept':>8} {'meanR':>6} {'maxR':>6}")
    passed = True
    for st in GATE_STATES:
        for method in ("plain", "grouped"):
            m = result["states"][st]["metrics"][method]
            print(f"  {st:5} {method:8} {m['metro_agreement']:>8.1%} {m['metro_mismatches']:>5} "
                  f"{m['direction_agree']:>6.1%} {m['neighbour_kept']:>8.1%} {m['mean_disp_R']:>6.2f} {m['max_disp_R']:>6.2f}")
        g = result["states"][st]["metrics"]["grouped"]
        passed &= (g["metro_agreement"] or 1.0) >= GATE_METRO_AGREEMENT and g["direction_agree"] >= GATE_DIRECTION_AGREE
    print(f"  gate: {'PASS' if passed else 'FAIL'} (grouped)")
    return passed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congress", type=int, nargs="*", default=[119])
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for congress in args.congress:
        if congress not in REAL_CONGRESSES:
            raise SystemExit(f"C{congress}: no real district data yet (C113-C119 only)")
        result = number_congress(congress)
        (OUT_DIR / f"{congress}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        gate_report(result)


if __name__ == "__main__":
    main()
