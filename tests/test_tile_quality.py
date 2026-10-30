import sys
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import tile_state_pentahexes as T


def test_is_straight_detects_all_three_axes():
    assert T._is_straight({(0, r) for r in range(5)})
    assert T._is_straight({(q, 0) for q in range(5)})
    assert T._is_straight({(q, -q) for q in range(5)})
    assert not T._is_straight({(0, 0), (0, 1), (0, 2), (0, 3), (1, 3)})


def test_refine_breaks_up_parallel_straights():
    # Two straight bars side by side (a 2x5 parallelogram) can always be re-split into
    # two rounder pentahexes; the swap pass must do so and keep a valid partition.
    a = [(0, r) for r in range(5)]
    b = [(1, r) for r in range(5)]
    out = T.refine_tiles_compactness([a, b], inside=set(a) | set(b))
    assert sorted(c for t in out for c in t) == sorted(a + b)
    assert all(len(t) == 5 and T._cells_connected(set(t)) for t in out)
    assert not any(T._is_straight(set(t)) for t in out)


def test_refine_never_starves_a_tile_of_inside_cells():
    a = [(0, r) for r in range(5)]
    b = [(1, r) for r in range(5)]
    inside = set(a) | {(1, 0), (1, 1), (1, 2)}  # b has 3 cells inside the outline
    out = T.refine_tiles_compactness([a, b], inside=inside)
    assert min(len(set(t) & inside) for t in out) >= 3


def test_drop_hairlines_keeps_real_holes_and_islands():
    hex_area = 1.0e9
    shell = box(0, 0, 100000, 100000).exterior
    hairline = [(1000, 1000), (60000, 1000), (60000, 1000.001), (1000, 1000.001)]
    real_hole = [(70000, 70000), (90000, 70000), (90000, 90000), (70000, 90000)]
    island = box(200000, 0, 205000, 5000)  # 2.5e7 m^2, a real (small) island
    needle = box(300000, 0, 300001, 10)
    geom = MultiPolygon([Polygon(shell, [hairline, real_hole]), island, needle])
    out = T._drop_hairlines(geom, 1e-4 * hex_area)
    assert len(out.geoms) == 2
    assert len(out.geoms[0].interiors) == 1
    filled = Polygon(hairline).area  # the hairline is filled back in, the needle removed
    assert abs(out.area - (geom.area - needle.area + filled)) < 1.0


def test_subset_run_splices_into_existing_summary(tmp_path):
    path = tmp_path / "warnings.json"
    path.write_text('{"warnings": [{"congress": 1, "v": "old"}, {"congress": 2, "v": "old"}, '
                    '{"congress": 3, "v": "old"}]}', encoding="utf-8")
    merged = T._merge_by_congress(path, "warnings", [{"congress": 2, "v": "new"}], "congress", {2})
    assert merged == [{"congress": 1, "v": "old"}, {"congress": 2, "v": "new"}, {"congress": 3, "v": "old"}]
    assert T._merge_by_congress(tmp_path / "missing.json", "warnings", [], "congress", {2}) == []
