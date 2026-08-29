#!/usr/bin/env python3
"""PROTOTYPE — THROWAWAY. Wayfinder ticket #24 (map #12).

Validates city-seeded compact-first partitioning (#18) against the real
multi-anchor stress cases #17's grilling revealed: New York (up to 5 anchors)
and Texas (up to 4-5 anchors) — using the ACTUAL decided formulas (#16, #17),
not #18's crude hardcoded fractions.

Reuses #18's proven monkeypatch harness (scripts/prototype_city_seeded_partition.py)
verbatim for the growth/bail mechanism, replacing only its static CITY_ANCHORS
lookup with a live call into prototype_real_urban_formula.real_anchors_for,
which computes real urban_seats (#16) and real 2.9R-clustered anchors (#17)
per state per Congress from the actual source data.

Run: python scripts/prototype_multi_anchor_validation.py [--congresses 119]
Outputs land in prototype_out_city_seeded/ (shared with #18's output dir).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import prototype_city_seeded_partition as P  # noqa: E402
import prototype_real_urban_formula as F  # noqa: E402
import tile_state_pentahexes as T  # noqa: E402

TARGET_FIPS = {"36": "NY", "48": "TX"}  # the real multi-anchor stress cases from #17


def real_anchors_in_hex_space(fips: str, seats: int):
    """Drop-in replacement for P.anchors_in_hex_space: real #16 urban_seats + real
    #17 clustering, instead of a static CITY_ANCHORS fraction table. Congress number
    and the live layout record both come from P's own capture of this run's actual
    compute_scaled_layout call (see prototype_real_urban_formula.real_anchors_for's
    docstring on why that matters, not a re-read of a possibly-stale file)."""
    if fips not in TARGET_FIPS:
        return []
    congress_number = P._current_congress[0]
    abbr = TARGET_FIPS[fips]
    layout_rec = P._latest_layout.get(fips)
    if layout_rec is None:
        return []
    try:
        return F.real_anchors_for(abbr, congress_number, seats, layout_rec)
    except Exception as e:  # noqa: BLE001 — a prototype; log and treat as no-anchor rather than crash the sweep
        P.RESULTS.append({"congress": congress_number, "fips": fips, "seats": seats,
                           "outcome": "formula-error", "error": str(e)})
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congresses", default="", help="comma list for a quick look; empty = full sweep")
    args = ap.parse_args()

    if args.congresses:
        P.CONGRESS_FILTER = {int(x) for x in args.congresses.split(",")}

    # patched_place iterates `for fips in CITY_ANCHORS` to decide which states to even
    # consider — keep NY/TX as keys (with dummy values; our anchors_in_hex_space override
    # ignores the list contents and routes through the real formula instead).
    P.CITY_ANCHORS.clear()
    for fips in TARGET_FIPS:
        P.CITY_ANCHORS[fips] = []
    P.SCRATCH.mkdir(exist_ok=True)
    print(f"PROTOTYPE outputs -> {P.SCRATCH}")

    # anchors_in_hex_space is called from inside P.patched_place / P.patched_place_with_capture;
    # patch it at the module level so those call sites pick up the real-formula version.
    P.anchors_in_hex_space = real_anchors_in_hex_space
    P.PLOT_CONGRESSES = {30, 68, 90, 119}

    T.compute_scaled_layout = P.patched_layout
    T.place_pentahex_tiles = P.patched_place_with_capture
    T.load_seats = P.patched_load_seats
    T.build_effective_outlines = P.patched_beo

    out = P.SCRATCH / "tiler_out_multi_anchor"
    sys.argv = [
        "tile_state_pentahexes.py",
        "--cds-out-root", str(out / "cds"),
        "--states-out-root", str(out / "states"),
        "--outlines-out-root", str(out / "outlines"),
        "--warnings-out", str(out / "tiling_warnings.json"),
    ]
    try:
        T.main()
    except SystemExit as e:
        print("tiler exit:", e.code)

    results_path = P.SCRATCH / "multi_anchor_results.json"
    results_path.write_text(json.dumps(P.RESULTS, indent=1), encoding="utf-8")
    ok = [r for r in P.RESULTS if r["outcome"] == "ok"]
    bail = [r for r in P.RESULTS if r["outcome"] == "bail"]
    errors = [r for r in P.RESULTS if r["outcome"] == "formula-error"]
    no_share = [r for r in P.RESULTS if r["outcome"] == "no-anchor-share"]
    print(f"\n=== multi-anchor validation (NY, TX): {len(ok)} ok, {len(bail)} bail, "
          f"{len(no_share)} no-anchor-share, {len(errors)} formula-error "
          f"(of {len(P.RESULTS)} attempts) ===")
    for fips, abbr in TARGET_FIPS.items():
        sub = [r for r in P.RESULTS if r["fips"] == fips]
        sub_ok = [r for r in sub if r["outcome"] == "ok"]
        sub_bail = [r for r in sub if r["outcome"] == "bail"]
        max_anchors = max((len(r.get("anchors", [])) for r in sub), default=0)
        print(f"  {abbr}: {len(sub_ok)} ok / {len(sub_bail)} bail (of {len(sub)}), "
              f"max simultaneous anchors seen: {max_anchors}")
    if bail:
        print("  bail congresses:", sorted(set((r['fips'], r['congress']) for r in bail)))
    if errors:
        print("  formula errors (first 5):", errors[:5])

    for (cong, fips) in sorted(P._PLOT_TILES):
        png = P.SCRATCH / f"multi_anchor_c{cong}_{fips}.png"
        if P.plot_state(cong, fips, png):
            print("wrote", png)


if __name__ == "__main__":
    main()
