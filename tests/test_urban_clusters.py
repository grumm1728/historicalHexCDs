import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import urban_clusters as uc  # noqa: E402
import urban_seats as us  # noqa: E402

IDENTITY = {"anchor": (0.0, 0.0), "scale": 1.0, "displacement": (0.0, 0.0)}


def _layout_rec(congress: int, fips: str) -> dict:
    """Layout record the tiler wrote for this Congress. Before Maine statehood the file has
    two FIPS-25 features (MA-proper + the relabeled Maine block); match on seat count."""
    path = ROOT / "data_processed" / "state_outlines_by_congress" / f"{congress}.geojson"
    if not path.exists():
        pytest.skip("needs a tiler run (data_processed/ is generated)")
    seats = us.seat_table(congress)[fips]
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        if p["state_fips"] == fips and p.get("anchor_x") is not None and p["house_seats"] == seats:
            return {
                "anchor": (p["anchor_x"], p["anchor_y"]),
                "scale": p["area_scale"],
                "displacement": (p["displacement_x"], p["displacement_y"]),
            }
    raise AssertionError(f"no layout record for {fips} in C{congress}")


def _names(state: str, congress: int = 119) -> list[str]:
    fips = us._resolve_fips(state)
    return [c.name for c in uc.urban_clusters(fips, congress, _layout_rec(congress, fips))]


# ---------------------------------------------------------------- seat allocation

def test_allocation_sums_and_largest_absorbs_remainder():
    assert uc.allocate_seats([100], 7) == [7]
    assert uc.allocate_seats([60, 25, 15], 10) == [5, 3, 2]  # 2.5, 1.5 round up; largest takes rest
    assert uc.allocate_seats([90, 5, 5], 3) == [3, 0, 0]


def test_allocation_overshoot_keeps_largest_anchor():
    seats = uc.allocate_seats([34, 33, 33], 2)  # naive rounding gives 1+1+1 = 3
    assert sum(seats) == 2 and seats[0] >= 1


# ---------------------------------------------------------------- clustering mechanics

def _fake_cities(monkeypatch, spacing_r: float):
    # two cities on the equator, `spacing_r` hexes apart under the identity layout
    lon = spacing_r * uc.R / uc.EARTH * 180 / 3.141592653589793
    cities = [uc.City("Big", 0.0, 0.0, 1000), uc.City("Small", lon, 0.0, 500)]
    monkeypatch.setattr(uc, "top_cities", lambda abbr, year, n: cities[:n])


def test_merges_within_radius(monkeypatch):
    _fake_cities(monkeypatch, 2.8)
    [cluster] = uc.urban_clusters("NY", 119, IDENTITY, n_urban=4)
    assert cluster.name == "Big+Small" and cluster.seats == 4 and cluster.population == 1500
    # anchor is the population-weighted centroid: 1/3 of the way to Small
    assert cluster.xy[0] == pytest.approx(2.8 * uc.R / 3, rel=1e-3)


def test_separate_beyond_radius(monkeypatch):
    _fake_cities(monkeypatch, 3.0)
    clusters = uc.urban_clusters("NY", 119, IDENTITY, n_urban=4)
    assert [(c.name, c.seats) for c in clusters] == [("Big", 3), ("Small", 1)]


def test_no_lookup_without_urban_seats(monkeypatch):
    monkeypatch.setattr(uc, "top_cities", lambda *a: pytest.fail("looked up cities"))
    assert uc.urban_clusters("NY", 119, IDENTITY, n_urban=0) == []


def test_candidate_pool_capped_by_urban_seats():
    assert len(uc.top_cities("NY", 2020, min(uc.MAX_CANDIDATES, 2))) == 2
    assert [c.name for c in uc.top_cities("TX", 2020, 5)][:2] == ["Houston", "San Antonio"]


# ---------------------------------------------------------------- real groupings (#17 / #24)

def test_texas_groupings():
    names = _names("TX")
    assert "Dallas+Fort Worth" in names
    assert {"Houston", "San Antonio", "Austin"} <= set(names)


def test_new_york_groupings():
    names = _names("NY")
    assert names[0] == "New York City+Yonkers"
    assert not any("Buffalo" in n and "+" in n for n in names)


def test_california_sf_and_san_jose_separate():
    names = _names("CA")
    assert "San Francisco" in names and "San Jose" in names


def test_inset_states_anchor_inside_their_outline():
    from shapely.geometry import Point, shape

    path = ROOT / "data_processed" / "state_outlines_by_congress" / "119.geojson"
    if not path.exists():
        pytest.skip("needs a tiler run")
    geoms = {f["properties"]["state_fips"]: shape(f["geometry"])
             for f in json.loads(path.read_text(encoding="utf-8"))["features"]}
    for fips in ("02", "15"):
        for c in uc.urban_clusters(fips, 119, _layout_rec(119, fips)):
            assert geoms[fips].buffer(uc.R).contains(Point(c.xy)), c.name


# ---------------------------------------------------------------- coverage

def test_every_state_every_congress():
    for c in range(1, 120):
        for fips in us.seat_table(c):
            clusters = uc.urban_clusters(fips, c, IDENTITY)
            assert sum(x.seats for x in clusters) == us.urban_seats(fips, c)
            assert all(x.seats > 0 for x in clusters)
