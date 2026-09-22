import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import urban_seats as u  # noqa: E402


def test_census_cutover_step_function():
    assert u.congress_to_census_year(1) == 1790  # C1-C2 backfill
    assert u.congress_to_census_year(2) == 1790
    assert u.congress_to_census_year(3) == 1790  # VA's first apportionment takes effect
    assert u.congress_to_census_year(12) == 1800
    assert u.congress_to_census_year(13) == 1810  # GA's verified jump
    assert u.congress_to_census_year(72) == 1910  # no 1920 reapportionment
    assert u.congress_to_census_year(73) == 1930
    assert u.congress_to_census_year(119) == 2020


def test_new_york_1900_matches_published_share():
    # Census Bureau's published 1900 NY urban share: 72.9%
    assert u.urban_share("NY", 58) == pytest.approx(0.729, abs=0.0005)


def test_formula_rounds_and_clamps():
    share = u.urban_share("NY", 119)
    seats = u.seat_table(119)["36"]
    assert u.urban_seats("NY", 119) == round(share * seats)
    assert u.urban_seats("NY", 119, seats=0) == 0
    assert 0 <= u.urban_seats("NY", 119, seats=1) <= 1


def test_half_rounds_up(monkeypatch):
    monkeypatch.setattr(u, "urban_share", lambda state, congress: 0.5)
    assert u.urban_seats("NY", 119, seats=1) == 1
    assert u.urban_seats("NY", 119, seats=5) == 3  # 2.5 -> 3 (banker's round would give 2)


def test_georgia_sums_mississippi_territory_while_composite():
    ga_total, ga_urban = u.census_counts(1810)["Georgia"]
    mt_total, mt_urban = u.census_counts(1810)["Mississippi Territory"]
    # C15: Mississippi seated but Alabama still drawn inside Georgia -> shared row added
    assert u.urban_share("GA", 15) == pytest.approx((ga_urban + mt_urban) / (ga_total + mt_total))
    # C16: both children seated -> Georgia's own row only
    assert u.urban_share("GA", 16) == pytest.approx(ga_urban / ga_total)


def test_north_carolina_sums_southwest_territory_until_tennessee_seated():
    nc_total, _ = u.census_counts(1790)["North Carolina"]
    swt_total, _ = u.census_counts(1790)["Southwest Territory"]
    assert u._state_counts("37", 3)[0] == nc_total + swt_total
    assert u._state_counts("37", 4)[0] == nc_total  # Tennessee first seated C4


def test_maine_block_is_rural_while_part_of_massachusetts():
    for c in range(1, 17):
        assert u.urban_seats("ME", c) == 0
    # MA-proper block uses the fused Massachusetts share on its reduced seat count
    ma_seats = u.seat_table(16)["25"]
    assert ma_seats == 13  # 20 MA seats minus the 7 Maine-territory seats
    assert u.urban_seats("MA", 16) == round(u.urban_share("MA", 16) * ma_seats) == 2


def test_urpop_source_typos_are_repaired():
    # printed totals: Nevada 1940 "0", Delaware 1930 230,380 (real 238,380)
    assert u.census_counts(1940)["Nevada"] == (43_291 + 66_956, 43_291)
    assert u.census_counts(1930)["Delaware"] == (238_380, 123_146)


def test_every_state_every_congress():
    for c in range(1, 120):
        seats = u.seat_table(c)
        for fips, n in seats.items():
            assert 0 <= u.urban_seats(fips, c) <= n
    assert len(u.seat_table(119)) == 50
