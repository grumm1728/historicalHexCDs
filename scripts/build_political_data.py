"""Political records per district (#53): Voteview party + DW-NOMINATE, for the district view.

Writes `data_processed/political_by_congress/<n>.json`, keyed by state then district code
(Census style: "07", at-large "00"), with one block per source:

  {"congress": 119, "sources": {"voteview": {...citation...}},
   "districts": {"NY": {"07": {"voteview": {primary member fields, member_changes, members}}}}}

An `elections` block (#59, scripts/medsl_returns.py) sits beside `voteview` when the
MEDSL returns file is present and the Congress was elected in 1976 or later; it is null
for a district with no returns.

**Primary member** (CONTEXT.md): the first member seated in the Congress. Voteview's
member files carry no service dates. For C119 the first row in file order is the original
member in all 11 districts with two rows (data_raw/voteview/README.txt). Re-check this
before adding older Congresses. A member who switches party gets a second row under the
same icpsr; that counts as a member change too (the seat's party changed).

Before writing, checks that the numbering sidecar was built from the current seat file
(sha256), so a tiler re-run without re-numbering fails the build instead of colouring
the wrong seats.

Run:  python scripts/build_political_data.py [--congress 119 ...]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from medsl_returns import MEDSL_CITATION, MEDSL_FILE, election_records, election_year  # noqa: E402

PROC = ROOT / "data_processed"
VOTEVIEW_DIR = ROOT / "data_raw" / "voteview"
OUT_DIR = PROC / "political_by_congress"

PARTY_ABBR = {100: "D", 200: "R", 328: "I"}
VOTEVIEW_CITATION = ("Lewis, Poole, Rosenthal, Boche, Rudkin and Sonnet, Voteview: Congressional "
                     "Roll-Call Votes Database, https://voteview.com/")


def check_numbering_fresh(congress: int) -> dict:
    numbering = json.loads((PROC / "seat_numbering_by_congress" / f"{congress}.json").read_text(encoding="utf-8"))
    cds = ROOT / numbering["source"]["polyhex_cds"]
    if hashlib.sha256(cds.read_bytes()).hexdigest() != numbering["source"]["sha256"]:
        raise SystemExit(f"C{congress}: seat numbering is stale (built from an older {cds.name}); "
                         "re-run scripts/number_seats.py")
    return numbering


def _num(v: str):
    return float(v) if v not in ("", None) else None


def voteview_records(congress: int, district_count: dict[str, int]) -> dict[str, dict[str, dict]]:
    rows_by_district: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with (VOTEVIEW_DIR / f"H{congress}_members.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["chamber"] != "House" or r["state_abbrev"] not in district_count:
                continue  # drops the President row, DC and territorial delegates
            st = r["state_abbrev"]
            code = int(r["district_code"])
            cd = "00" if district_count[st] == 1 else f"{code:02d}"  # Voteview at-large = 1
            rows_by_district[(st, cd)].append(r)

    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (st, cd), rows in rows_by_district.items():
        first = rows[0]
        party_code = int(first["party_code"])
        out[st][cd] = {"voteview": {
            "icpsr": int(first["icpsr"]),
            "bioguide_id": first["bioguide_id"] or None,
            "name": first["bioname"],
            "party_code": party_code,
            "party": PARTY_ABBR.get(party_code, "other"),
            "nominate_dim1": _num(first["nominate_dim1"]),
            "nominate_dim2": _num(first["nominate_dim2"]),
            "member_changes": len(rows) - 1,
            "members": [{"name": r["bioname"], "party": PARTY_ABBR.get(int(r["party_code"]), "other")}
                        for r in rows],
        }}
    return out


def build(congress: int) -> dict:
    numbering = check_numbering_fresh(congress)
    district_count = {st: len(s["district_metro"]) for st, s in numbering["states"].items()}
    records = voteview_records(congress, district_count)
    for st, n in district_count.items():
        missing = sorted(set(numbering["states"][st]["district_metro"]) - set(records.get(st, {})))
        if missing:
            raise SystemExit(f"C{congress} {st}: no Voteview member for district(s) {missing}")
    sources = {"voteview": {"file": f"data_raw/voteview/H{congress}_members.csv",
                            "citation": VOTEVIEW_CITATION,
                            "primary_member": "first row in file order (first seated)"}}

    if MEDSL_FILE.exists() and election_year(congress) >= 1976:
        elections = election_records(congress, district_count)
        for st, by_cd in records.items():
            for cd, rec in by_cd.items():
                rec["elections"] = elections.get(st, {}).get(cd)
        sources["elections"] = {"file": MEDSL_FILE.relative_to(ROOT).as_posix(), "citation": MEDSL_CITATION,
                                "race": "regular general election (runoff if one decided the seat), "
                                        "votes summed by candidate across ballot lines"}
    return {
        "congress": congress,
        "sources": sources,
        "districts": {st: dict(sorted(records[st].items())) for st in sorted(records)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congress", type=int, nargs="*", default=[119])
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for congress in args.congress:
        if not (VOTEVIEW_DIR / f"H{congress}_members.csv").exists():
            raise SystemExit(f"C{congress}: no Voteview file in {VOTEVIEW_DIR}")
        data = build(congress)
        (OUT_DIR / f"{congress}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        n = sum(len(v) for v in data["districts"].values())
        print(f"C{congress}: {n} district political records")


if __name__ == "__main__":
    main()
