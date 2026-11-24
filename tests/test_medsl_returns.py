import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import medsl_returns as mr  # noqa: E402

HEADER = "year\tstate_po\tdistrict\tstage\trunoff\tspecial\tcandidate\tparty\tcandidatevotes\ttotalvotes\n"


def write(tmp_path, rows):
    p = tmp_path / "house.tab"
    p.write_text(HEADER + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")
    return p


def test_election_year():
    assert mr.election_year(119) == 2024
    assert mr.election_year(1) == 1788


def test_party_letter():
    assert mr.party_letter("DEMOCRATIC-FARMER-LABOR") == "D"
    assert mr.party_letter("REPUBLICAN") == "R"
    assert mr.party_letter("WORKING FAMILIES") == "other"


def test_fusion_votes_sum_to_main_party(tmp_path):
    p = write(tmp_path, [
        (2024, "NY", 3, "GEN", "FALSE", "FALSE", "A DEM", "DEMOCRAT", 60, 160),
        (2024, "NY", 3, "GEN", "FALSE", "FALSE", "A DEM", "WORKING FAMILIES", 20, 160),
        (2024, "NY", 3, "GEN", "FALSE", "FALSE", "B REP", "REPUBLICAN", 80, 160),
    ])
    el = mr.election_records(119, {"NY": 26}, p)["NY"]["03"]
    assert el["contest"] == "D-R"
    assert el["dem_votes"] == 80 and el["rep_votes"] == 80
    assert el["waffle_share"] == 0.5


def test_runoff_replaces_general_and_specials_are_ignored(tmp_path):
    p = write(tmp_path, [
        (2024, "LA", 6, "GEN", "FALSE", "FALSE", "A DEM", "DEMOCRAT", 45, 100),
        (2024, "LA", 6, "GEN", "FALSE", "FALSE", "B REP", "REPUBLICAN", 55, 100),
        (2024, "LA", 6, "GEN", "TRUE", "FALSE", "A DEM", "DEMOCRAT", 70, 100),
        (2024, "LA", 6, "GEN", "TRUE", "FALSE", "B REP", "REPUBLICAN", 30, 100),
        (2024, "LA", 5, "GEN", "FALSE", "TRUE", "C REP", "REPUBLICAN", 99, 99),
    ])
    out = mr.election_records(119, {"LA": 6}, p)["LA"]
    assert out["06"]["stage"] == "runoff" and out["06"]["waffle_share"] == 0.7
    assert "05" not in out


def test_one_party_contests_fill_all_five_cells(tmp_path):
    p = write(tmp_path, [
        (2024, "CA", 12, "GEN", "FALSE", "FALSE", "A DEM", "DEMOCRAT", 60, 100),
        (2024, "CA", 12, "GEN", "FALSE", "FALSE", "B DEM", "DEMOCRAT", 40, 100),
        (2024, "AK", 0, "GEN", "FALSE", "FALSE", "C REP", "REPUBLICAN", 90, 100),
        (2024, "AK", 0, "GEN", "FALSE", "FALSE", "D LIB", "LIBERTARIAN", 10, 100),
    ])
    out = mr.election_records(119, {"CA": 52, "AK": 1}, p)
    assert out["CA"]["12"]["contest"] == "D-D" and out["CA"]["12"]["waffle_share"] == 1.0
    assert out["AK"]["00"]["contest"] == "R, no Democrat" and out["AK"]["00"]["waffle_share"] == 0.0


def test_unopposed_without_a_count_and_non_votes_dropped(tmp_path):
    p = write(tmp_path, [
        (2024, "FL", 20, "GEN", "FALSE", "FALSE", "A DEM", "DEMOCRAT", 1, 1),
        (2024, "MA", 3, "GEN", "FALSE", "FALSE", "B DEM", "DEMOCRAT", 260, 360),
        (2024, "MA", 3, "GEN", "FALSE", "FALSE", "BLANKS", "NA", 90, 360),
        (2024, "MA", 3, "GEN", "FALSE", "FALSE", "ALL OTHERS", "NA", 10, 360),
    ])
    out = mr.election_records(119, {"FL": 28, "MA": 9}, p)
    assert out["FL"]["20"]["votes_reported"] is False and out["FL"]["20"]["waffle_share"] == 1.0
    assert [c["name"] for c in out["MA"]["03"]["candidates"]] == ["B DEM", "ALL OTHERS"]
    assert out["MA"]["03"]["votes_reported"] is True
