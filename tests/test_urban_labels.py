import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from urban_clusters import UrbanCluster, label_urban_tiles  # noqa: E402


def _row(n: int):
    """n tiles in a line at x = 0..n-1, each adjacent to its neighbours."""
    centers = [(float(i), 0.0) for i in range(n)]
    adjacency = [{j for j in (i - 1, i + 1) if 0 <= j < n} for i in range(n)]
    return centers, adjacency


def _cluster(name: str, x: float, seats: int, y: float = 0.0) -> UrbanCluster:
    return UrbanCluster(name, (x, y), 1000, seats, (name,))


def test_nearest_first_contiguous_growth():
    centers, adj = _row(10)
    labels, spills = label_urban_tiles(centers, adj, [_cluster("A", 4.2, 3)])
    claimed = {i: l.rank for i, l in enumerate(labels) if l}
    assert claimed == {4: 0, 5: 1, 3: 2} and spills == []


def test_bfs_only_claims_adjacent_tiles():
    # tile 1 is nearest the anchor overall but not adjacent to the seed's region
    centers = [(0.0, 0.0), (0.0, 0.9), (5.0, 0.0)]
    adj = [{2}, set(), {0}]
    labels, spills = label_urban_tiles(centers, adj, [_cluster("A", 0.0, 2, y=0.1)])
    assert labels[0].rank == 0 and labels[1] is None and labels[2].rank == 1
    assert spills == []


def test_small_cluster_keeps_its_city_next_to_a_big_one():
    # Big (5 seats) would swallow tile 6 growing to completion first; round-robin lets
    # Small seed on its own city tile
    centers, adj = _row(10)
    labels, spills = label_urban_tiles(centers, adj, [_cluster("Big", 3.0, 5), _cluster("Small", 6.0, 1)])
    assert labels[6].cluster == "Small" and labels[6].rank == 0
    assert sum(1 for l in labels if l and l.cluster == "Big") == 5 and spills == []


def test_round_robin_larger_cluster_wins_contested_tile():
    centers, adj = _row(3)
    labels, _ = label_urban_tiles(centers, adj, [_cluster("Big", 0.0, 2), _cluster("Small", 2.0, 1)])
    assert [l.cluster for l in labels] == ["Big", "Big", "Small"]


def test_voronoi_preference_keeps_regions_on_their_side():
    # tile 2 (1.6 from A) is nearer A than tile 1 (1.7 from A), but nearer B's anchor
    # (1.4) - the Voronoi preference sends A to tile 1 and leaves tile 2 to B
    centers = [(0.0, 0.0), (-1.7, 0.0), (1.6, 0.0), (3.0, 0.0)]
    adj = [{1, 2}, {0}, {0, 3}, {2}]
    labels, _ = label_urban_tiles(centers, adj, [_cluster("A", 0.0, 2), _cluster("B", 3.0, 2)])
    assert [l.cluster for l in labels] == ["A", "A", "B", "B"]


def test_rural_when_unclaimed_and_counts_exact():
    centers, adj = _row(8)
    labels, _ = label_urban_tiles(centers, adj, [_cluster("A", 0.0, 2), _cluster("B", 7.0, 1)])
    assert sum(l is not None for l in labels) == 3
    assert labels[7].cluster == "B" and labels[7].seats == 1


def test_walled_in_cluster_spills_to_larger_and_stays_contiguous():
    # Big claims the middle; Small's anchor sits at the left end with only 1 free tile there
    centers, adj = _row(5)
    labels, spills = label_urban_tiles(centers, adj, [_cluster("Big", 2.0, 3), _cluster("Small", 0.0, 2)])
    assert [l.cluster if l else None for l in labels] == ["Small", "Big", "Big", "Big", "Big"]
    assert labels[4].seats == 4 and labels[0].seats == 1  # seats = tiles actually held
    [sp] = spills
    assert (sp.cluster, sp.allocated, sp.placed, sp.recipients) == ("Small", 2, 1, (("Big", 1),))


def test_no_spills_when_clusters_fit():
    centers, adj = _row(10)
    _, spills = label_urban_tiles(centers, adj, [_cluster("A", 1.0, 3), _cluster("B", 8.0, 2)])
    assert spills == []


def test_partial_tiling_never_overclaims():
    centers, adj = _row(2)
    labels, _ = label_urban_tiles(centers, adj, [_cluster("A", 0.0, 5)])
    assert all(labels)


def test_detached_last_resort_keeps_state_total():
    # two islands: A's region fills the left island; the right island is unreachable
    centers = [(0.0, 0.0), (1.0, 0.0), (10.0, 0.0)]
    adj = [{1}, {0}, set()]
    labels, [sp] = label_urban_tiles(centers, adj, [_cluster("A", 0.0, 3)])
    assert all(l.cluster == "A" for l in labels) and labels[2].rank == 2
    assert (sp.placed, sp.recipients, sp.detached) == (2, (("A", 1),), 1)
