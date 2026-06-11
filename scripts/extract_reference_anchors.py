"""Extract per-state layout anchors from the HexCDv31wm reference cartogram.

The reference (hexmap_reference_files/HexCDv31wm/) is the hand-authored hex-CD map this
project replicates. This script distills it into the small JSON the tiler needs to aim its
layout at the reference arrangement (see "Reference-anchored layout" in CLAUDE.md):

  - per state: FIPS, abbr, blob centroid (reference Mercator coords), CD count, blob area
  - meta: the reference hex radius R_ref (derived from CD area) and the map centroid

(No adjacency is extracted: the reference packing is loose — real-neighbour gutters range
0.6-7.7 R_ref — so the tiler pins states at anchor positions rather than springing
neighbours to touching.)

The output (data_raw/reference/hexcdv31_anchors.json) is checked in so the tiler has no
shapefile/pyshp dependency. Re-run only if the reference shapefile changes.
"""
import json
import math
from pathlib import Path

import shapefile
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
SHP = ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.shp"
OUT = ROOT / "data_raw" / "reference" / "hexcdv31_anchors.json"

ABBR_TO_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def main() -> None:
    sf = shapefile.Reader(str(SHP))
    fields = [f[0] for f in sf.fields[1:]]
    by_state: dict[str, list] = {}
    n_cds = 0
    abbr_by_fips = {v: k for k, v in ABBR_TO_FIPS.items()}
    for sr in sf.shapeRecords():
        rec = dict(zip(fields, sr.record))
        # GEOID = state FIPS + CD number. Derive state from it: one reference record has
        # STATEAB='01' (a FIPS slipped into the abbr column), so GEOID is the robust key.
        fips = str(rec.get("GEOID", "")).strip()[:2]
        if fips not in abbr_by_fips:
            raise SystemExit(f"Unknown GEOID state prefix in reference: {rec!r}")
        geom = shape(sr.shape.__geo_interface__)
        if not geom.is_valid:
            geom = geom.buffer(0)
        by_state.setdefault(fips, []).append(geom)
        n_cds += 1

    unions = {f: unary_union(gs) for f, gs in by_state.items()}
    total_area = sum(g.area for g in unions.values())
    hex_area_ref = total_area / (n_cds * 5)
    # hex_area = 1.5 * sqrt(3) * R^2 (same formula as the tiler's hex_area_from_R)
    r_ref = math.sqrt(hex_area_ref / (1.5 * math.sqrt(3)))

    fips_list = sorted(unions)
    map_centroid = unary_union(list(unions.values())).centroid
    out = {
        "source": "hexmap_reference_files/HexCDv31wm (118th-Congress hand-authored hex-CD cartogram)",
        "crs": "sphere Mercator (Web-Mercator-compatible metres); only used via similarity transform",
        "n_cds": n_cds,
        "R_ref": r_ref,
        "hex_area_ref": hex_area_ref,
        "map_centroid": [map_centroid.x, map_centroid.y],
        "states": {
            f: {
                "abbr": abbr_by_fips[f],
                "centroid": [unions[f].centroid.x, unions[f].centroid.y],
                "cd_count": len(by_state[f]),
                "area": unions[f].area,
            }
            for f in fips_list
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(fips_list)} states, {n_cds} CDs, "
          f"R_ref={r_ref:.1f} m")


if __name__ == "__main__":
    main()
