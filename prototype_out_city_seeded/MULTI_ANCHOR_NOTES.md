# PROTOTYPE NOTES — multi-anchor validation for partition-change (wayfinder ticket #24)

**Question:** does city-seeded compact-first partitioning ([#18](https://github.com/grumm1728/historicalHexCDs/issues/18))
generalize to states with genuinely many simultaneous urban anchors — New York
(up to 5: NYC, Buffalo, Rochester, Syracuse, Albany) and Texas (up to 4-5:
Houston, Dallas, San Antonio, Austin, El Paso) — the real stress cases
[#17](https://github.com/grumm1728/historicalHexCDs/issues/17)'s grilling
revealed, or does the bail rate get worse than California's already-nontrivial
4/17 (~24%) from the original prototype?

**Harness:** `scripts/prototype_multi_anchor_validation.py` extends #18's proven
monkeypatch harness (`scripts/prototype_city_seeded_partition.py`, brought over
unmodified) with **real** mechanisms instead of #18's crude hardcoded fractions:

- `scripts/prototype_real_urban_formula.py` implements #16's actual formula
  (`round(share × seats)`, the real census→Congress step function reusing the
  existing apportionment `effective_year` cutover, spliced across all four real
  data eras: NHGIS 1790-1890, `urpop0090.txt` 1900-1990, SF1 P002 2000, the
  Census XLSX for 2010/2020) and #17's actual cluster identification (real
  CESTA top-`min(5,urban_seats)` cities, single-linkage merge at 2.9R measured
  in the state's own live-captured hex-space scale, per-cluster seat allocation
  by rounding). Deliberately skips composite-outline summing (#23) and the
  `MAINE_IN_MA` 0% rule (#16 decision 7) — neither applies to NY or TX.
- Validated the formula module standalone before wiring it in: NY's 1900 urban
  share came out to 72.9%, an exact match to the Census Bureau's own published
  1900 table figure. C119 anchor identification exactly reproduced the cluster
  groupings hand-computed during #17's grilling (Dallas+Fort Worth merge,
  Houston/San Antonio/Austin separate; NYC+Yonkers merge, Buffalo/Rochester
  separate).
- Anchor positioning uses the **live** layout captured during this run's own
  `compute_scaled_layout` call (`P._latest_layout`), not a separate file read —
  per the #20 lesson that recomputing or re-reading position data out of band
  can silently give the wrong answer.

## Verdict: generalizes better than the original 1-2 anchor test, not worse

Full 119-Congress sweep, `warnings: 0` throughout (90 Congresses reused via the
identical-input fast path; 46 real NY/TX attempts):

- **NY: 29/29 ok, zero bails** — even at 5 simultaneous anchors, its hardest
  predicted case.
- **TX: 13/14 ok (excluding 3 early Congresses with `urban_seats=0`, where no
  anchor was ever attempted), exactly 1 bail** (Congress 78). Investigated: C78
  and C73 have the *identical* anchor set and nearly identical seat count — C73
  succeeded, C78 didn't. An isolated, Congress-specific geometry quirk in that
  particular cell allocation, not a systemic multi-anchor problem. Fell back
  cleanly to the baseline partition exactly as designed.
- **Combined bail rate: 1/43 meaningful attempts (~2.3%)** — dramatically
  better than California's 4/17 (~24%) from the original #18 prototype. The
  harder multi-anchor states performed *better* than the simpler 1-2 anchor
  case, suggesting CA's bail rate is about its specific gnarly coastal
  geometry (Long Island, mountains, offshore islands), not anchor count.

Renders: `multi_anchor_c119_36.png` (NY: NYC+Yonkers dominant cluster reaching
far upstate — a faithful consequence of NY's real ~87.5% urban share, not a
bug; Buffalo and Rochester correctly isolated as their own small clusters),
`multi_anchor_c119_48.png` (TX: four cleanly separated, compact, contiguous
clusters — Dallas+Fort Worth, Houston, San Antonio, Austin).

## Disposition

Reported to Scott 2026-07-12: evidence doesn't change the current decision
([#19](https://github.com/grumm1728/historicalHexCDs/issues/19)'s hybrid
stays — label-only remains adopted now) but substantially de-risks
partition-change as a documented future upgrade. Branch
`prototype/multi-anchor-validation` is throwaway; delete whenever convenient.
