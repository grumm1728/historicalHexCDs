#!/usr/bin/env python3
"""Write the viewer's compact per-Congress frame bundle into the staged web data.

The GeoJSON in data_processed/ stays the source of truth; this is a web-only derivative
so scrubbing the timeline doesn't fetch and parse ~7.5 MB of GeoJSON per Congress.

For each timeline entry it writes ``frames/<n>.json``:
  * per layer (``cd``, ``state``, ``outline``): only the properties the viewer reads, stored
    column-wise (``keys`` + one ``rows`` array per feature), and a ``geom`` path;
  * ``geom/<kind>-<hash>.json``: the layer's geometry, coordinates quantized to ``Q`` metres
    and delta-encoded as integers. Identical geometry (the ~90 seat-identical Congresses,
    whose layout the tiler freezes) hashes to the same file, so it is fetched once.

Shared vertices quantize identically, so adjacent tiles stay crack-free. ``Q`` = 100 m is
~0.04 px at the viewer's maximum 3x zoom. Each staged ``congress_index.json`` entry gains
``web_frame_path``; the viewer falls back to the GeoJSON paths when it is missing.

Run after staging (``build_web_assets.py`` does) or standalone on an existing web/data_processed/.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = ROOT / "web" / "data_processed"
Q = 100.0  # quantization step, metres (Web Mercator units)

LAYER_KEYS = {
    "cd": [
        "state_fips", "state_abbr", "state_name", "house_seats", "cd_index", "hex_count",
        "is_boundary_tile", "is_metro", "metro_cluster", "metro_rank", "metro_name",
        "metro_national_rank", "metro_tiers",
    ],
    "state": ["state_fips", "state_abbr", "state_name", "house_seats", "cell_count"],
    "outline": ["state_fips", "state_abbr", "state_name", "house_seats"],
}
LAYER_PATH_FIELD = {"cd": "cd_feature_path", "state": "state_feature_path", "outline": "state_outline_path"}


def quantize(v: float) -> int:
    # floor(x + 0.5): the same rule for every vertex, so shared vertices stay shared.
    return math.floor(v / Q + 0.5)


def polygons_of(geometry: dict | None) -> list:
    if not geometry:
        return []
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError(f"unsupported geometry type {geometry['type']}")


def encode_features(features: list[dict]) -> list:
    """Each feature -> [polygon -> [ring -> flat [dx, dy, dx, dy, ...]]].

    Deltas run continuously across the whole layer (the first vertex is relative to 0,0),
    so the viewer decodes with one running cursor. Consecutive duplicate vertices after
    quantization are dropped; rings left with < 4 vertices (incl. closure) are dropped.
    """
    cx = cy = 0
    out = []
    for f in features:
        polys = []
        for poly in polygons_of(f.get("geometry")):
            rings = []
            for ring in poly:
                pts = []
                for x, y, *_ in ring:
                    p = (quantize(x), quantize(y))
                    if not pts or pts[-1] != p:
                        pts.append(p)
                if len(pts) < 4:
                    continue
                flat = []
                for x, y in pts:
                    flat += [x - cx, y - cy]
                    cx, cy = x, y
                rings.append(flat)
            if rings:
                polys.append(rings)
        out.append(polys)
    return out


def decode_features(encoded: list, q: float = Q) -> list:
    """Inverse of encode_features -> list of MultiPolygon coordinate arrays (metres)."""
    cx = cy = 0
    out = []
    for polys in encoded:
        mp = []
        for rings in polys:
            rr = []
            for flat in rings:
                ring = []
                for i in range(0, len(flat), 2):
                    cx += flat[i]
                    cy += flat[i + 1]
                    ring.append([cx * q, cy * q])
                rr.append(ring)
            mp.append(rr)
        out.append(mp)
    return out


def dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def build(web_data: Path = WEB_DATA) -> dict:
    index_path = web_data / "congress_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    frames_dir = web_data / "frames"
    geom_dir = frames_dir / "geom"
    geom_dir.mkdir(parents=True, exist_ok=True)
    written_geom: set[str] = set()
    total_bytes = 0

    for entry in index.get("timeline", []):
        n = int(entry["congress_number"])
        frame: dict = {"congress_number": n, "q": Q}
        for layer, field in LAYER_PATH_FIELD.items():
            rel = entry.get(field)
            if not rel or not (web_data.parent / rel).exists():
                continue
            fc = json.loads((web_data.parent / rel).read_text(encoding="utf-8"))
            features = fc.get("features", [])
            geom_text = dump({"q": Q, "f": encode_features(features)})
            name = f"{layer}-{hashlib.sha1(geom_text.encode()).hexdigest()[:12]}.json"
            if name not in written_geom:
                (geom_dir / name).write_text(geom_text, encoding="utf-8")
                written_geom.add(name)
                total_bytes += len(geom_text)
            keys = LAYER_KEYS[layer]
            frame[layer] = {
                "geom": f"geom/{name}",
                "keys": keys,
                "rows": [[f.get("properties", {}).get(k) for k in keys] for f in features],
            }
            if layer == "cd":
                frame["cd_props"] = fc.get("properties") or {}
        text = dump(frame)
        (frames_dir / f"{n}.json").write_text(text, encoding="utf-8")
        total_bytes += len(text)
        entry["web_frame_path"] = f"data_processed/frames/{n}.json"

    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    summary = {"frames": len(index.get("timeline", [])), "geom_files": len(written_geom), "bytes": total_bytes}
    print("web frames:", summary)
    return summary


if __name__ == "__main__":
    build()
