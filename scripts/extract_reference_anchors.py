"""Extract per-state layout anchors from the HexCDv31wm reference cartogram.

The reference (hexmap_reference_files/HexCDv31wm/) is the hand-authored hex-CD map this
project replicates. This script distills it into the small JSON the tiler needs to aim its
layout at the reference arrangement (see "Reference-anchored layout" in CLAUDE.md):

  - per state: FIPS, abbr, blob centroid, CD count, blob area, a simplified blob polygon
    (for diagnostics), and — the value the tiler actually seeds with — a **fitted anchor**:
    the position for the state's outline representative point that minimizes the symmetric
    difference between our C119-scaled geographic silhouette and the reference blob.
    Footprint fit beats centroid fit because the shapes differ (our states are real
    silhouettes, the reference's are hand-drawn blobs): matching centroids still lets edges
    land wrong (WA/OR drifting east off CA's coast diagonal), while matching footprints puts
    our *edges* on the reference's edges, preserving its coastlines and gutter lines.
  - meta: the reference hex radius R_ref (derived from CD area) and the map centroid

All stored coordinates are in reference space; the tiler similarity-transforms them. The fit
itself runs in our hex space (R = 35000) against the modern outlines, so re-run this script
if the outlines or R change materially. The output (data_raw/reference/hexcdv31_anchors.json)
is checked in so the tiler has no shapefile/pyshp dependency.

(No adjacency is extracted: the reference packing is loose — real-neighbour gutters range
0.6-7.7 R_ref — so the tiler pins states at anchor positions rather than springing
neighbours to touching.)
"""
import json
import math
from pathlib import Path

import shapefile
from shapely.affinity import affine_transform, scale as shapely_scale, translate as shapely_translate
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
SHP = ROOT / "hexmap_reference_files" / "HexCDv31wm" / "HexCDv31wm.shp"
OUTLINES = ROOT / "data_processed" / "states" / "state_outlines_modern_wm.geojson"
OUT = ROOT / "data_raw" / "reference" / "hexcdv31_anchors.json"

R = 35000.0  # must match the tiler's hex radius
HEX_AREA = 1.5 * math.sqrt(3) * R * R

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


def fit_translation(scaled, blob, coarse: float, fine: float, reach: float) -> tuple[float, float]:
    """Grid-search the (dx, dy) that maximizes intersection area between `scaled` translated
    and `blob` (areas are equal by construction, so max intersection == min symmetric
    difference). Coarse pass over +-reach, then a fine pass around the best cell."""
    def inter(dx: float, dy: float) -> float:
        return blob.intersection(shapely_translate(scaled, dx, dy)).area

    best = (0.0, 0.0)
    best_v = inter(0.0, 0.0)
    steps = int(reach / coarse)
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            if i == 0 and j == 0:
                continue
            v = inter(i * coarse, j * coarse)
            if v > best_v:
                best_v, best = v, (i * coarse, j * coarse)
    cx, cy = best
    steps = int(coarse / fine)
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            v = inter(cx + i * fine, cy + j * fine)
            if v > best_v:
                best_v, best = v, (cx + i * fine, cy + j * fine)
    return best


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
    map_centroid = unary_union(list(unions.values())).centroid

    # Our modern outlines + the tiler's fixed national centre (same union centroid), so the
    # footprint fit happens in exactly the space the tiler lays out in.
    outlines_fc = json.loads(OUTLINES.read_text(encoding="utf-8"))
    outline_by_fips: dict[str, dict] = {}
    for ft in outlines_fc["features"]:
        g = shape(ft["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        outline_by_fips[str(ft["properties"]["state_fips"]).zfill(2)] = {
            "geom": g,
            "rep": g.representative_point(),
        }
    cc = unary_union([o["geom"] for o in outline_by_fips.values()]).centroid
    s = math.sqrt(HEX_AREA / hex_area_ref)
    # reference -> hex space: uniform scale about the reference map centroid, recentred on cc
    ref_to_hex = [s, 0, 0, s, cc.x - s * map_centroid.x, cc.y - s * map_centroid.y]

    states_out: dict[str, dict] = {}
    for f in sorted(unions):
        blob_hex = affine_transform(unions[f], ref_to_hex)
        rec = {
            "abbr": abbr_by_fips[f],
            "centroid": [unions[f].centroid.x, unions[f].centroid.y],
            "cd_count": len(by_state[f]),
            "area": unions[f].area,
            "blob": mapping(unions[f].simplify(r_ref / 4)),
        }
        ol = outline_by_fips.get(f)
        if ol is not None:
            scale_f = math.sqrt(len(by_state[f]) * 5 * HEX_AREA / ol["geom"].area)
            scaled = shapely_scale(ol["geom"], xfact=scale_f, yfact=scale_f,
                                   origin=(ol["rep"].x, ol["rep"].y))
            # Start with centroids matched, then refine. Simplify both for speed; the fit
            # surface is smooth so coarse/fine grid search is plenty.
            base_dx = blob_hex.centroid.x - scaled.centroid.x
            base_dy = blob_hex.centroid.y - scaled.centroid.y
            scaled0 = shapely_translate(scaled, base_dx, base_dy).simplify(R / 4)
            ddx, ddy = fit_translation(scaled0, blob_hex.simplify(R / 4),
                                       coarse=0.75 * R, fine=0.2 * R, reach=4.0 * R)
            # Fitted anchor = where the outline's representative point (the tiler's scale
            # origin and seed target) lands, converted back to reference coordinates.
            ax = ol["rep"].x + base_dx + ddx
            ay = ol["rep"].y + base_dy + ddy
            rec["fitted_anchor"] = [(ax - cc.x) / s + map_centroid.x,
                                    (ay - cc.y) / s + map_centroid.y]
            iou_den = scaled.area + blob_hex.area
            inter = blob_hex.intersection(shapely_translate(scaled, base_dx + ddx, base_dy + ddy)).area
            rec["fit_iou"] = inter / (iou_den - inter)
        states_out[f] = rec

    out = {
        "source": "hexmap_reference_files/HexCDv31wm (118th-Congress hand-authored hex-CD cartogram)",
        "crs": "sphere Mercator (Web-Mercator-compatible metres); only used via similarity transform",
        "n_cds": n_cds,
        "R_ref": r_ref,
        "hex_area_ref": hex_area_ref,
        "map_centroid": [map_centroid.x, map_centroid.y],
        "fit_R": R,
        "states": states_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    fitted = [st for st in states_out.values() if "fit_iou" in st]
    mean_iou = sum(st["fit_iou"] for st in fitted) / max(len(fitted), 1)
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(states_out)} states, {n_cds} CDs, "
          f"R_ref={r_ref:.1f} m, fitted anchors for {len(fitted)} states (mean IoU {mean_iou:.3f})")


if __name__ == "__main__":
    main()
