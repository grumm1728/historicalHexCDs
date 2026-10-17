import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_web_frames as bwf


def square(x0, y0, s):
    return [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s], [x0, y0]]


def test_round_trip_within_half_a_step():
    feats = [
        {"geometry": {"type": "Polygon", "coordinates": [square(-10808532.29, 3626313.79, 35000.4)]}},
        {"geometry": {"type": "MultiPolygon", "coordinates": [
            [square(-9000000.49, 4000000.51, 12345.6), square(-8995000.0, 4005000.0, 1000.2)],
            [square(-8000000.0, 5000000.0, 50000.0)],
        ]}},
    ]
    decoded = bwf.decode_features(bwf.encode_features(feats))
    assert len(decoded) == 2
    src = [[feats[0]["geometry"]["coordinates"]], feats[1]["geometry"]["coordinates"]]
    for mp_src, mp_dec in zip(src, decoded):
        assert len(mp_src) == len(mp_dec)
        for poly_src, poly_dec in zip(mp_src, mp_dec):
            for ring_src, ring_dec in zip(poly_src, poly_dec):
                assert len(ring_src) == len(ring_dec)
                for (x, y), (qx, qy) in zip(ring_src, ring_dec):
                    assert abs(x - qx) <= bwf.Q / 2 and abs(y - qy) <= bwf.Q / 2


def test_shared_vertices_stay_shared_and_degenerate_rings_drop():
    a = square(0.0, 0.0, 1000.0)
    b = square(1000.0, 0.0, 1000.0)  # shares the edge x = 1000 with a
    tiny = square(5000.0, 5000.0, 10.0)  # collapses to one quantized point
    dec = bwf.decode_features(bwf.encode_features([
        {"geometry": {"type": "Polygon", "coordinates": [a]}},
        {"geometry": {"type": "Polygon", "coordinates": [b]}},
        {"geometry": {"type": "Polygon", "coordinates": [tiny]}},
    ]))
    edge_a = {tuple(p) for p in dec[0][0][0] if p[0] == 1000.0}
    edge_b = {tuple(p) for p in dec[1][0][0] if p[0] == 1000.0}
    assert edge_a == edge_b and len(edge_a) == 2
    assert dec[2] == []


STAGED = ROOT / "web" / "data_processed"


@pytest.mark.skipif(not (STAGED / "frames").exists(), reason="no staged web frame bundle")
def test_staged_bundle_matches_source_geojson():
    index = json.loads((STAGED / "congress_index.json").read_text(encoding="utf-8"))
    for entry in (index["timeline"][0], index["timeline"][-1]):
        frame = json.loads((STAGED.parent / entry["web_frame_path"]).read_text(encoding="utf-8"))
        src = json.loads((STAGED.parent / entry["cd_feature_path"]).read_text(encoding="utf-8"))
        geom = json.loads((STAGED / "frames" / frame["cd"]["geom"]).read_text(encoding="utf-8"))
        decoded = bwf.decode_features(geom["f"], geom["q"])
        assert len(decoded) == len(src["features"]) == len(frame["cd"]["rows"])
        for f, row, mp in zip(src["features"], frame["cd"]["rows"], decoded):
            props = dict(zip(frame["cd"]["keys"], row))
            assert props["cd_index"] == f["properties"]["cd_index"]
            assert props["state_abbr"] == f["properties"]["state_abbr"]
            xs = [x for poly in bwf.polygons_of(f["geometry"]) for ring in poly for x, _ in ring]
            qxs = [x for poly in mp for ring in poly for x, _ in ring]
            assert abs(min(xs) - min(qxs)) <= bwf.Q / 2 and abs(max(xs) - max(qxs)) <= bwf.Q / 2
