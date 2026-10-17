import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_metro_colors as bmc


@pytest.mark.parametrize("name, city", [
    ("Los Angeles--Long Beach--Anaheim+Riverside--San Bernardino", "Los Angeles"),
    ("Los Angeles-Long Beach", "Los Angeles"),
    ("Boston+Providence-Pawtucket", "Boston"),
    ("New York City", "New York"),
    ("New York-Northeastern New Jersey (NY)", "New York"),
    ("Davenport, Iowa-Rock Island-Moline", "Davenport"),
    ("Louisville/Jefferson County", "Louisville"),
    ("Wilkes-Barre", "Wilkes-Barre"),
    ("Virginia Beach--Norfolk", "Norfolk"),
])
def test_leading_city_is_stable_across_renames_and_merges(name, city):
    assert bmc.leading_city(name) == city


def test_same_city_name_in_unconnected_states_splits():
    appearances = {("Portland", "OR"): Counter({70: 2}), ("Portland", "WA"): Counter({70: 1}),
                   ("Portland", "ME"): Counter({10: 1})}
    ident = bmc.identities(appearances, [("Portland", {"OR", "WA"}), ("Portland", {"ME"})])
    assert ident[("Portland", "OR")] == ident[("Portland", "WA")] == "Portland (OR)"
    assert ident[("Portland", "ME")] == "Portland (ME)"


def test_touching_metros_never_share_a_color_and_soft_prefers_distinct():
    hard = Counter({("A", "B"): 1, ("B", "C"): 1, ("A", "C"): 1})
    soft = Counter({("C", "D"): 5})
    col = bmc.color(["A", "B", "C", "D"], hard, soft, 3)
    assert len({col["A"], col["B"], col["C"]}) == 3
    assert col["D"] != col["C"]
    with pytest.raises(RuntimeError):
        bmc.color(["A", "B", "C"], hard, Counter(), 2)
