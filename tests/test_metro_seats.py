import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import metro_seats as m  # noqa: E402


def _names(year):
    return [x.name for x in m.qualifying_metros(year)]


# ---------------------------------------------------------------- chain linkage

def test_chain_links_within_13km_only_and_chains_transitively():
    # three places ~10 km apart in a row (0.09 deg lat ~ 10 km) plus one 20 km beyond
    places = [m.Place(n, "XX", -90.0, lat, 1) for n, lat in (("a", 40.0), ("b", 40.09), ("c", 40.18), ("d", 40.36))]
    comps = sorted(sorted(c) for c in m.chain_places(places))
    assert comps == [[0, 1, 2], [3]]


def test_chain_2010_spot_checks():
    # #33 decision 2, measured on 2010 CESTA places
    places = m.cesta_places(2010)
    where = {}
    for k, comp in enumerate(m.chain_places(places)):
        for i in comp:
            where[(places[i].name, places[i].st)] = k

    def linked(a, b):
        return where[a] == where[b]

    assert linked(("San Francisco", "CA"), ("San Jose", "CA"))
    assert linked(("Los Angeles", "CA"), ("Riverside", "CA"))
    assert linked(("Detroit", "MI"), ("Ann Arbor", "MI"))
    assert not linked(("Chicago", "IL"), ("Milwaukee", "WI"))
    assert not linked(("New York City", "NY"), ("Philadelphia", "PA"))


# ---------------------------------------------------------------- urbanized-area linking

def test_1950_merges_only_boston_providence_and_baltimore_dc():
    merged = sorted(n for n in _names(1950) if "+" in n)
    assert merged == ["Boston+Providence", "Washington+Baltimore"]


def test_1960_adds_bay_area_cincinnati_dayton_dallas_fort_worth():
    merged = {n for n in _names(1960) if "+" in n}
    assert {"San Francisco-Oakland+San Jose", "Cincinnati+Dayton", "Dallas+Fort Worth"} <= merged
    assert len(merged) == 5


@pytest.mark.parametrize("year", [1990, 2000, 2010, 2020])
def test_boundary_gap_rule(year):
    metros = m._ua_metros(year)  # all linked metros: Milwaukee falls outside the top N after 1990

    def metro_of(city):
        return next(x.name for x in metros if any(p.name.startswith(city) for p in x.portions))

    assert metro_of("San Francisco") == metro_of("San Jose")
    assert metro_of("Los Angeles") == metro_of("Riverside")
    assert metro_of("Chicago") != metro_of("Milwaukee")
    assert metro_of("New York") != metro_of("Philadelphia")
    assert metro_of("Baltimore") == metro_of("Washington")
    assert metro_of("Boston") == metro_of("Providence")


# ---------------------------------------------------------------- national ranking

def test_top_n_is_half_the_states_in_the_census_year():
    assert m.states_in_census(1790) == 13  # RI (May 1790) in, VT (1791) out
    assert m.top_n(1790) == 6
    assert m.top_n(2020) == 25


def test_1790_top_six():
    assert _names(1790) == ["Philadelphia", "New York City", "Boston", "Charleston", "Salem", "Baltimore"]


def test_unseated_state_still_ranks_but_is_not_drawn(monkeypatch):
    # A seceded (unseated) Louisiana keeps New Orleans in the 1860 ranking, so no smaller
    # city is promoted into the top N, and Louisiana itself draws nothing.
    seats = {c: dict(t) for c, t in m._seats_table().items()}
    del seats[40]["22"]
    monkeypatch.setattr(m, "_seats_table", lambda: seats)
    names = _names(1860)
    assert "New Orleans" in names and len(names) == m.top_n(1860)
    assert m._drawing_fips("LA", 40) is None
    assert m._drawing_fips("LA", 39) == "22"


def test_dc_and_territories_rank_but_never_draw():
    assert "Washington" in _names(1860)
    assert m._drawing_fips("DC", 40) is None


# ---------------------------------------------------------------- seats

def test_largest_remainder_keeps_total():
    assert m.largest_remainder([600, 300, 100], 5) == [3, 2, 0]
    assert m.largest_remainder([1, 1], 1) == [1, 0]
    assert sum(m.largest_remainder([7, 5, 3, 2], 9)) == 9


def _fake(monkeypatch, metros, state_pop):
    monkeypatch.setattr(m, "qualifying_metros", lambda year: tuple(metros))
    monkeypatch.setattr(m, "_state_counts", lambda fips, c: (state_pop, 0))


def test_per_portion_rounding_half_up_and_zero_gets_no_anchor(monkeypatch):
    pt = ((-75.0, 40.0, 1),)
    metros = [
        m.Metro("Big", 500, (m.Portion("Big", "PA", 500, pt),)),      # 0.5 * 10 = 5
        m.Metro("Half", 50, (m.Portion("Half", "PA", 50, pt),)),      # 0.05 * 10 = 0.5 -> 1
        m.Metro("Tiny", 40, (m.Portion("Tiny", "PA", 40, pt),)),      # 0.4 -> 0, no anchor
    ]
    _fake(monkeypatch, metros, 1000)
    anchors = m.metro_anchors("PA", 119, seats=10)
    assert [(a.name, a.seats) for a in anchors] == [("Big", 5), ("Half", 1)]
    assert m.metro_seats("PA", 119, seats=10) == 6


def test_merged_portion_rounds_once_then_splits_by_area(monkeypatch):
    # two areas linked into one metro: rounding happens on the 0.36 * 10 = 3.6 -> 4 total,
    # then largest remainder splits 4 by 240:120 -> 3:1 (rounding each alone gives 2 + 1)
    pt = ((-122.0, 37.5, 1),)
    metros = [m.Metro("SF+SJ", 360, (m.Portion("SF", "CA", 240, pt), m.Portion("SJ", "CA", 120, pt)))]
    _fake(monkeypatch, metros, 1000)
    assert [(a.name, a.seats, a.metro) for a in m.metro_anchors("CA", 119, seats=10)] == [
        ("SF", 3, "SF+SJ"), ("SJ", 1, "SF+SJ")]


def test_cross_state_portions_count_toward_each_state(monkeypatch):
    pt = ((-74.0, 40.7, 1),)
    metros = [m.Metro("NY", 900, (m.Portion("New York", "NY", 600, pt), m.Portion("New York", "NJ", 300, pt)))]
    _fake(monkeypatch, metros, 1000)
    assert m.metro_seats("NY", 119, seats=10) == 6
    assert m.metro_seats("NJ", 119, seats=10) == 3
    assert m.metro_seats("CT", 119, seats=10) == 0


def test_real_cross_state_anchor_new_jersey():
    anchors = m.metro_anchors("NJ", 119)
    assert {a.name for a in anchors} == {"New York--Jersey City--Newark", "Philadelphia"}
    assert all(a.st == "NJ" for a in anchors)


def test_bay_area_labels_from_separate_anchors():
    names = {a.name: a.metro for a in m.metro_anchors("CA", 119)}
    assert names["San Francisco--Oakland"] == names["San Jose"]


def test_maine_block_gets_nothing_and_never_exceeds_seats():
    assert m.metro_seats("ME", 10) == 0
    for c in (1, 40, 83, 119):
        for fips, seats in m.seat_table(c).items():
            assert 0 <= m.metro_seats(fips, c, seats) <= seats
