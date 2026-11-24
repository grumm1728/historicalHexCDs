import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import number_seats as ns  # noqa: E402

R = ns.R


def seat(i, x, metro=""):
    return {"cd_index": i, "xy": (x * R, 0.0), "metro": metro}


def district(cd, x, metro=""):
    return {"cd": cd, "xy": (x * R, 0.0), "metro": metro}


def test_plain_matches_by_position():
    seats = [seat(1, 0), seat(2, 10), seat(3, 20)]
    districts = [district("03", 21), district("01", 1), district("02", 9)]
    assert ns.number_plain(seats, districts) == {1: "01", 2: "02", 3: "03"}


def test_floor_counts_unavoidable_mismatches():
    seats = [seat(1, 0, "M"), seat(2, 10), seat(3, 20)]
    districts = [district("01", 0, "M"), district("02", 10, "M"), district("03", 20)]
    assert ns.mismatch_floor(seats, districts) == 1


def test_lexicographic_puts_metro_districts_on_metro_seats():
    # The metro seat is far from the metro district; distance alone would mismatch twice.
    seats = [seat(1, 0, "M"), seat(2, 10), seat(3, 20)]
    districts = [district("01", 1), district("02", 9), district("03", 19, "M")]
    lex = ns.number_lexicographic(seats, districts)
    assert lex[1] == "03"
    assert ns.number_plain(seats, districts)[1] == "01"
