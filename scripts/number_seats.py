"""Numbering: assign each state's real districts to its seats, after the tiler (#53, #48).

A label-only pass (docs/adr/0001-numbering-is-a-post-tiler-label.md): it reads the
finished seats (`polyhex_cds_by_congress/<n>.geojson`) and each state's saved layout
record (`state_outlines_by_congress/<n>.geojson`), and never touches geometry.

Each real district is one point, its center of population
(`data_raw/congressional_districts/real_district_points_c113_c119.csv`), projected into
hex space the way the state's outline is drawn (`urban_clusters.to_hex_space`).

Methods
-------
`plain` (the numbering written out): one Hungarian over the whole state on squared
  distance between seat centroids and projected district points. Pure geography: the
  seat view's metro labels play no part.
`lexicographic` (comparison only): the same, plus MISMATCH_COST * [district metro !=
  seat metro label], large enough that the fewest metro mismatches come first.

Why plain (#53): numbering feeds the **district view** (political modes), where the
urban/rural outline is drawn from each seat's real district, so it can't disagree with
the district. The **seat view** keeps the labeller's metro labels. The two views may
disagree about which seats are metro; `metro_mismatches` measures by how much. Forcing
agreement (lexicographic) put real districts in absurd places, e.g. C119 TX-01 (Tyler,
East Texas) in the Panhandle and rural CA-23 on the Nevada border, because the labeller
had already given those regions' seats to Dallas/Houston and LA.

Measured on C119 (all states with 2+ seats):
  plain                 71 mismatches, direction 89.5%
  grouped + ZCA-whiten  11 mismatches, direction 77.8%  (#48 option (a), rejected)
  lexicographic         11 mismatches, direction 81.0%  (rejected, see above)
Centring / isotropic scaling of either cloud cannot change a full Hungarian matching
(the argmin is invariant to translation and uniform scale), so "relative arrangement"
normalisation only acts through anisotropy, and whitening slightly hurt.

Metrics (per state, both methods)
---------------------------------
  metro_agreement    share of metro-labelled seats numbered with a district of the same metro
  metro_mismatches   seats whose metro label differs from their district's metro
  mismatch_floor     the fewest mismatches any numbering can reach (count differences)
  direction_agree    share of district pairs whose seat-to-seat bearing is within 45 deg of
                     the real bearing between the two districts
  neighbour_kept     share of real adjacent district pairs whose seats share an edge
  mean_disp_R, max_disp_R
                     seat centroid to projected district point, in hex radii R (report only)

Gate (#53): direction_agree >= 70% in each gate state. Metro mismatches are reported,
not gated. Below the gate the political modes stay behind ?dev.

Writes `data_processed/seat_numbering_by_congress/<n>.json`: per state, `seats`
(cd_index -> district), `district_metro` (district -> its metro, "" if not metro; the
district view's urban/rural outline) and both methods' metrics. Prints a gate table for
the #53 gate states.

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
GATE_DIRECTION_AGREE = 0.70
DIRECTION_TOLERANCE_DEG = 45.0
SEAT_EDGE_MIN = 0.1 * R  # rendered seats sharing less boundary than this are not neighbours
NON_METRO = ""
MISMATCH_COST = 1e6  # in R^2: larger than any squared distance within a state


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

def _assign(cost: list[list[float]], seats: list[dict], districts: list[dict]) -> dict[int, str]:
    cols = _min_cost_assignment(cost)
    return {seats[j]["cd_index"]: districts[i]["cd"] for i, j in enumerate(cols)}


def _sqdist(d: dict, s: dict) -> float:
    return ((d["xy"][0] - s["xy"][0]) ** 2 + (d["xy"][1] - s["xy"][1]) ** 2) / (R * R)


def number_plain(seats: list[dict], districts: list[dict]) -> dict[int, str]:
    return _assign([[_sqdist(d, s) for s in seats] for d in districts], seats, districts)


def number_lexicographic(seats: list[dict], districts: list[dict]) -> dict[int, str]:
    cost = [[_sqdist(d, s) + MISMATCH_COST * (d["metro"] != s["metro"]) for s in seats] for d in districts]
    return _assign(cost, seats, districts)


def mismatch_floor(seats: list[dict], districts: list[dict]) -> int:
    seat_n, dist_n = defaultdict(int), defaultdict(int)
    for s in seats:
        seat_n[s["metro"]] += 1
    for d in districts:
        dist_n[d["metro"]] += 1
    return sum(max(0, dist_n[g] - seat_n[g]) for g in set(seat_n) | set(dist_n))


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
        "mismatch_floor": mismatch_floor(seats, districts),
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
        district_metro = {d["cd"]: d["metro"] for d in districts}
        if len(seats) == 1:
            states[st] = {"seats": {str(seats[0]["cd_index"]): districts[0]["cd"]},
                          "district_metro": district_metro, "at_large": True}
            continue
        sadj = seat_adjacency(seats)
        plain = number_plain(seats, districts)
        lex = number_lexicographic(seats, districts)
        states[st] = {
            "seats": {str(k): plain[k] for k in sorted(plain)},
            "district_metro": district_metro,
            "metrics": {"plain": metrics(plain, seats, districts, adjacency[st], sadj),
                        "lexicographic": metrics(lex, seats, districts, adjacency[st], sadj)},
        }
    return {
        "congress": congress,
        "method": "plain-hungarian",
        "district_point": "center of population (Census tract centers)",
        "metro_tier": 1.0,
        "source": {"polyhex_cds": cds_path.relative_to(ROOT).as_posix(), "sha256": sha256(cds_path)},
        "states": states,
    }


def gate_report(result: dict) -> bool:
    print(f"C{result['congress']} gate (direction >= {GATE_DIRECTION_AGREE:.0%}; mismatches reported only)")
    print(f"  {'state':5} {'method':13} {'metroAg':>8} {'mism':>5} {'floor':>5} {'dirAg':>6} {'nbrKept':>8} {'meanR':>6} {'maxR':>6}")
    passed = True
    for st in GATE_STATES:
        for method in ("plain", "lexicographic"):
            m = result["states"][st]["metrics"][method]
            print(f"  {st:5} {method:13} {m['metro_agreement']:>8.1%} {m['metro_mismatches']:>5} {m['mismatch_floor']:>5} "
                  f"{m['direction_agree']:>6.1%} {m['neighbour_kept']:>8.1%} {m['mean_disp_R']:>6.2f} {m['max_disp_R']:>6.2f}")
        passed &= result["states"][st]["metrics"]["plain"]["direction_agree"] >= GATE_DIRECTION_AGREE
    print(f"  gate: {'PASS' if passed else 'FAIL'} (plain)")
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
