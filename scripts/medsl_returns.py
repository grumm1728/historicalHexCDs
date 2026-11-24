"""House election returns per district from the MIT Election Data + Science Lab (#59).

Source: MEDSL, "U.S. House 1976-2024", Harvard Dataverse doi:10.7910/DVN/IG0UN2 (CC0),
saved as data_raw/medsl/1976-2024-house.tab (one row per candidate per ballot line).

Which race counts (decided in #59): the regular general election that seated the
Congress (year = the even year before it convenes). Special elections are ignored, in
keeping with the primary-member rule. Where a general-election runoff decided the seat
(Georgia, Louisiana), the runoff counts instead. Votes are summed **by candidate** across
ballot lines, so fusion lines (NY Working Families, Conservative) count for the
candidate's main party.

The `elections` block for a district:
  year, stage ("gen" | "runoff"), contest, winner_party, dem_votes, rep_votes,
  total_votes, votes_reported (false where the state prints no count for an unopposed
  candidate: MEDSL codes those as 1 vote, e.g. FL-20, OK-03 in 2024),
  dem_share_2p (D / (D+R), only for a D-R contest),
  waffle_share (the value the vote-share waffle fills to: dem_share_2p for D-R, 1.0 when
  no Republican ran against a Democrat, 0.0 the other way round, null for a third-party
  seat), candidates [{name, party, votes}] by votes. Ballot rows that are not votes for
  anyone (blank, over and under votes, void) are dropped; write-ins and "all others" stay
  as party "other".
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDSL_FILE = ROOT / "data_raw" / "medsl" / "1976-2024-house.tab"
MEDSL_CITATION = ("MIT Election Data and Science Lab, U.S. House 1976-2024, Harvard Dataverse, "
                  "doi:10.7910/DVN/IG0UN2 (CC0)")


NOT_VOTES = {"BLANK", "BLANKS", "BLANK VOTES", "OVER VOTES", "UNDER VOTES", "VOID", "SPOILED"}


def election_year(congress: int) -> int:
    return 1786 + 2 * congress  # C1 was elected in 1788, C119 in 2024


def party_letter(party: str) -> str:
    p = (party or "").upper()
    if "DEMOCRAT" in p:      # DEMOCRAT, DEMOCRATIC-FARMER-LABOR (MN), DEMOCRATIC-NPL (ND)
        return "D"
    if "REPUBLICAN" in p:
        return "R"
    return "other"


def _truthy(v: str) -> bool:
    return str(v).strip().upper() in ("TRUE", "T", "1")


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        yield from csv.DictReader(f, dialect=dialect)


def classify(candidates: list[dict]) -> dict:
    """Contest, winner and waffle share from candidates already summed across ballot lines."""
    ranked = sorted((c for c in candidates if c["votes"] > 0), key=lambda c: -c["votes"])
    dem = sum(c["votes"] for c in ranked if c["party"] == "D")
    rep = sum(c["votes"] for c in ranked if c["party"] == "R")
    n_d = sum(c["party"] == "D" for c in ranked)
    n_r = sum(c["party"] == "R" for c in ranked)
    if n_d and n_r:
        contest, share = "D-R", dem / (dem + rep)
    elif n_d:
        contest, share = ("D-D" if n_d > 1 else "D, no Republican"), 1.0
    elif n_r:
        contest, share = ("R-R" if n_r > 1 else "R, no Democrat"), 0.0
    else:
        contest, share = "third party only", None
    return {
        "contest": contest,
        "winner_party": ranked[0]["party"] if ranked else None,
        "votes_reported": any(c["votes"] > 1 for c in ranked),
        "dem_votes": dem,
        "rep_votes": rep,
        "dem_share_2p": round(dem / (dem + rep), 5) if n_d and n_r else None,
        "waffle_share": round(share, 5) if share is not None else None,
        "candidates": ranked,
    }


def election_records(congress: int, district_count: dict[str, int], path: Path = MEDSL_FILE) -> dict[str, dict[str, dict]]:
    """{state: {cd: elections block}} for the general election that seated `congress`."""
    year = election_year(congress)
    # (state, cd, stage) -> candidate name -> {"votes", "parties"}
    races: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(dict)
    totals: dict[tuple[str, str, str], int] = {}
    for r in _rows(path):
        if int(r["year"]) != year or r["stage"].strip().upper() != "GEN" or _truthy(r.get("special", "")):
            continue
        st = r["state_po"].strip()
        if st not in district_count:
            continue  # DC, territories
        cd = "00" if district_count[st] == 1 else f"{int(r['district']):02d}"
        stage = "runoff" if _truthy(r.get("runoff", "")) else "gen"
        name = (r["candidate"] or "").strip().replace('\\"', '"') or "(blank)"
        if name.upper() in NOT_VOTES:
            continue
        votes = int(float(r["candidatevotes"] or 0))
        c = races[(st, cd, stage)].setdefault(name, {"votes": 0, "parties": []})
        c["votes"] += votes
        c["parties"].append(party_letter(r["party"]))
        totals[(st, cd, stage)] = int(float(r["totalvotes"] or 0))

    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (st, cd, stage), cands in races.items():
        if stage == "gen" and (st, cd, "runoff") in races:
            continue  # the runoff decided this seat
        candidates = [{"name": n, "party": next((p for p in c["parties"] if p != "other"), "other"),
                       "votes": c["votes"]} for n, c in cands.items()]
        out[st][cd] = {"year": year, "stage": stage, "total_votes": totals[(st, cd, stage)], **classify(candidates)}
    return out
