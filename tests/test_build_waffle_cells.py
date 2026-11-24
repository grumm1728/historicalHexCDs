import math
import sys
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_waffle_cells import split_seat  # noqa: E402

CENTERS = [(0, 0), (1.5, 0.866), (1.5, -0.866), (3, 0), (0, 1.732)]


def hexagon(cx, cy):
    return Polygon([(cx + math.cos(math.pi / 3 * k), cy + math.sin(math.pi / 3 * k)) for k in range(6)])


def test_pieces_partition_a_clipped_tile():
    tile = unary_union([hexagon(*c) for c in CENTERS]).intersection(box(-0.5, -2, 4, 3))
    pieces = split_seat(tile, CENTERS)
    assert [r for r, _ in pieces] == [0, 1, 2, 3, 4]
    assert unary_union([p for _, p in pieces]).symmetric_difference(tile).area < 1e-9


def test_ranks_run_north_to_south_then_west_to_east():
    from shapely.geometry import Point

    tile = unary_union([hexagon(*c) for c in CENTERS])
    pieces = dict(split_seat(tile, CENTERS))
    expected = {0: (0, 1.732), 1: (1.5, 0.866), 2: (0, 0), 3: (3, 0), 4: (1.5, -0.866)}
    for rank, center in expected.items():
        assert pieces[rank].contains(Point(center))
