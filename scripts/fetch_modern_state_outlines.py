#!/usr/bin/env python3
"""Fetch / process real modern US state outlines and reproject to Web Mercator.

Source: Natural Earth `ne_10m_admin_1_states_provinces` (public domain).
Downloads the shapefile from naciscdn.org on first run, extracts US states,
applies a small AK/HI inset transform, and writes:

- data_raw/states/state_outlines_natural_earth.geojson     (WGS84, US subset)
- data_processed/states/state_outlines_modern_wm.geojson   (EPSG:3857)
- data_raw/states/state_outlines_modern.geojson            (WGS84, contract path)
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
import zipfile
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent

NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"

STATE_FIPS_BY_ABBR = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20",
    "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
    "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}

US_STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def download_natural_earth(cache_dir: Path) -> Path:
    """Download and unzip Natural Earth admin-1 shapefile (idempotent)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    shp_path = cache_dir / "ne_10m_admin_1_states_provinces.shp"
    if shp_path.exists():
        return shp_path
    print(f"Downloading {NE_URL} ...")
    with urllib.request.urlopen(NE_URL) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(cache_dir)
    if not shp_path.exists():
        raise SystemExit(f"Natural Earth extract did not produce {shp_path}")
    return shp_path


def shape_to_geometry(s: shapefile.Shape) -> dict:
    return s.__geo_interface__


def to_multipolygon(geom_obj):
    if isinstance(geom_obj, Polygon):
        return MultiPolygon([geom_obj])
    if isinstance(geom_obj, MultiPolygon):
        return geom_obj
    raise ValueError(f"Unexpected geometry: {type(geom_obj)}")


def apply_alaska_hawaii_inset(abbr: str, geom):
    """Lower-48 inset placement for AK and HI (in WGS84 degrees, applied pre-WM).

    Aleutians/Midway that wrap the dateline are clipped first so the inset
    transform doesn't produce nonsense coordinates.
    """
    if abbr == "AK":
        clipped = geom.intersection(box(-180.0, 50.0, -129.0, 72.0))
        if clipped.is_empty:
            clipped = geom
        def t(x, y, z=None):
            x2 = (x + 152.0) * 0.35 - 118.0
            y2 = (y - 64.0) * 0.35 + 27.0
            return (x2, y2) if z is None else (x2, y2, z)
        return shapely_transform(t, clipped)
    if abbr == "HI":
        clipped = geom.intersection(box(-160.5, 18.5, -154.0, 22.5))
        if clipped.is_empty:
            clipped = geom
        def t(x, y, z=None):
            x2 = x + 49.0
            y2 = y + 5.0
            return (x2, y2) if z is None else (x2, y2, z)
        return shapely_transform(t, clipped)
    return geom


def reproject_geom_to_wm(geom):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    def t(x, y, z=None):
        nx, ny = transformer.transform(x, y)
        return (nx, ny) if z is None else (nx, ny, z)
    return shapely_transform(t, geom)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch + process real US state outlines")
    parser.add_argument("--cache-dir", default=str(ROOT / "data_raw" / "_cache" / "natural_earth"))
    parser.add_argument("--out-degrees", default=str(ROOT / "data_raw" / "states" / "state_outlines_modern.geojson"))
    parser.add_argument("--out-natural-earth", default=str(ROOT / "data_raw" / "states" / "state_outlines_natural_earth.geojson"))
    parser.add_argument("--out-wm", default=str(ROOT / "data_processed" / "states" / "state_outlines_modern_wm.geojson"))
    args = parser.parse_args()

    shp_path = download_natural_earth(Path(args.cache_dir))
    reader = shapefile.Reader(str(shp_path))
    fields = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
    name_idx = fields.index("name")
    admin_idx = fields.index("admin")

    by_state: dict[str, list] = {}
    for sr in reader.iterShapeRecords():
        if sr.record[admin_idx] != "United States of America":
            continue
        name = sr.record[name_idx]
        abbr = US_STATE_NAMES.get(name)
        if not abbr:
            continue
        geom = shape(shape_to_geometry(sr.shape))
        by_state.setdefault(abbr, []).append(geom)

    ne_features = []
    deg_features = []
    wm_features = []
    for abbr in sorted(by_state):
        fips = STATE_FIPS_BY_ABBR.get(abbr)
        if not fips:
            continue
        merged = unary_union(by_state[abbr])
        if not merged.is_valid:
            merged = merged.buffer(0)
        merged = to_multipolygon(merged)

        # Raw NE export (unmodified)
        ne_features.append({
            "type": "Feature",
            "properties": {
                "state_fips": fips,
                "state_abbr": abbr,
                "state_name": next(n for n, a in US_STATE_NAMES.items() if a == abbr),
                "source_outline_id": "natural-earth-10m",
            },
            "geometry": mapping(merged),
        })

        # Inset-applied degrees version
        positioned = apply_alaska_hawaii_inset(abbr, merged)
        deg_features.append({
            "type": "Feature",
            "properties": {
                "state_fips": fips,
                "state_abbr": abbr,
                "state_name": next(n for n, a in US_STATE_NAMES.items() if a == abbr),
                "source_outline_id": "natural-earth-10m-inset",
                "inset_applied": abbr in {"AK", "HI"},
            },
            "geometry": mapping(positioned),
        })

        wm = reproject_geom_to_wm(positioned)
        if not wm.is_valid:
            wm = wm.buffer(0)
        wm_features.append({
            "type": "Feature",
            "properties": {
                "state_fips": fips,
                "state_abbr": abbr,
                "state_name": next(n for n, a in US_STATE_NAMES.items() if a == abbr),
                "source_outline_id": "natural-earth-10m-inset-wm",
                "inset_applied": abbr in {"AK", "HI"},
            },
            "geometry": mapping(wm),
        })

    out_ne = Path(args.out_natural_earth)
    out_deg = Path(args.out_degrees)
    out_wm = Path(args.out_wm)
    out_ne.parent.mkdir(parents=True, exist_ok=True)
    out_deg.parent.mkdir(parents=True, exist_ok=True)
    out_wm.parent.mkdir(parents=True, exist_ok=True)
    out_ne.write_text(json.dumps({"type": "FeatureCollection", "features": ne_features}), encoding="utf-8")
    out_deg.write_text(json.dumps({"type": "FeatureCollection", "features": deg_features}), encoding="utf-8")
    out_wm.write_text(json.dumps({"type": "FeatureCollection", "features": wm_features}), encoding="utf-8")
    print(f"Wrote {len(wm_features)} state outlines (WM) to {out_wm}")


if __name__ == "__main__":
    main()
