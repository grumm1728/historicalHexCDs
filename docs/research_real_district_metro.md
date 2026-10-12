# Research: real district boundaries C113–C119 and a metro-district rule

Goal (issue #35, decision 9 of #33): get the real congressional districts for Congresses
113–119 and calibrate a rule that classifies a real district as "metro". The result should
give a per-state metro-district count for each Congress, ready for the validation ticket
#37's ±1 comparison against our map's `metro_seats`. Researched 2026-10-11. The data and its
provenance are in `data_raw/congressional_districts/` (see its `README.txt`). The numbers
come from `scripts/build_real_district_metro.py`.

## Summary

- **Data.** Census cartographic-boundary CD files (1:500k, with `ALAND`), one vintage per
  Congress. They capture every mid-decade redraw: FL/NC/VA in C115, PA in C116, and
  NY/NC/GA/AL/LA in C119. Census tract centers of population (2010, 2020) give the
  population inside each district.
- **One gap: North Carolina C117.** Census never published NC's 2019 remedial plan, so the
  2016 plan stands in (flagged `nc_c117_proxy`). It doesn't affect the counts: NC has no
  top-25 metro in 2010, so it has 0 metro districts under either plan.
- **Chosen rule.** A real district is **metro when at least half of its population lives
  inside an urbanized area of a qualifying metro.** "Qualifying" means the census's top-25
  linked metros (`metro_seats.qualifying_metros`), the same set our map labels.
- **Not chosen: a land-area or density cutoff.** No density cutoff separates big-metro
  districts well; the best one, 250 people/km², agrees with the chosen rule on only 87% of
  districts.
- **Result.** 170–175 real metro districts per Congress, against the model's 172–175. Per
  state, the real counts fall within ±1 of `metro_seats` for **98% of states in C113–C117
  and 100% in C118–C119**. The one miss is Texas in C113–C117 (15 real vs 17 modelled; see
  below).
- **Caveat for #37.** The population rule shares the qualifying-metro list and urbanized
  areas with the model. It therefore validates the **seat formula and its rounding**, not
  the choice of *which* metros qualify. The density numbers below are the independent check
  on that choice.

## Why not land area or density

The issue's premise holds: within a state, districts have equal population, so a small
land area means a dense district. Measured on all 3,045 real districts, though, density
picks out *urban* districts, not *big-metro* ones. Both of these errors are large.

- **Big-metro exurbs are sparse.** Salt Lake City is split across all four Utah districts
  (C118–C119), each 55–85% inside the metro but at 8–72 people/km². Other examples are
  TX-25 and TX-36 in C119 (33 and 50/km²), WA-08 (30/km²) and CA-41 (221/km²). Many
  suburban districts include empty hills or farmland. CA-14 (Hayward–Livermore) has 73% of
  its people inside the Bay Area urbanized area but only 16% of its land, at 506/km².
- **Cores of smaller metros are dense.** Examples include FL-10 (Orlando), TX-37 (Austin),
  OH-03 (Columbus), NC-12 (Charlotte), IN-07 (Indianapolis), WI-04 (Milwaukee, 2,032/km²),
  HI-01 (Honolulu) and NY-26 (Buffalo). All exceed 1,000/km², but none of these metros is
  in the top 25.

Agreement of each alternative with the chosen rule, over all 3,045 districts:

| alternative | agreement | metro but below cutoff | above cutoff but not metro |
|---|---:|---:|---:|
| density ≥ 250 /km² | 87.1% | 188 | 204 |
| density ≥ 500 /km² | 83.9% | 385 | 105 |
| density ≥ 750 /km² | 81.6% | 500 | 60 |
| density ≥ 1,000 /km² | 78.4% | 613 | 44 |
| density ≥ 1,500 /km² | 72.3% | 831 | 12 |
| ≥ half of *land* in a qualifying UA | 85.3% | | |

Measuring *land* share (the issue's third starting point, taken literally) undercounts for
the same exurb reason. Only 106–109 districts per Congress pass it. Weighting by population
(tract centers of population) fixes this. Tract populations summed per district match the
state's population ÷ seats to within −4.8%…+7.0% (sd 1.0%), which is a check on the method.

## Sensitivity of the chosen rule

The population share is strongly bimodal. 1,427 districts have under 1% of their people in a
qualifying metro, 507 have over 99%, and only 141 (4.6%) fall between 0.4 and 0.6. Moving
the cutoff therefore shifts the national total only modestly:

| Congress | model | **0.5 (chosen)** | 0.3 | 0.4 | 0.6 | 0.7 | land ≥ 0.5 | density ≥ 250 | density ≥ 1,000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C113 | 172 | **171** | 194 | 182 | 162 | 155 | 108 | 175 | 89 |
| C114 | 172 | **171** | 194 | 182 | 162 | 155 | 108 | 175 | 89 |
| C115 | 172 | **170** | 193 | 182 | 162 | 154 | 108 | 173 | 88 |
| C116 | 172 | **170** | 193 | 182 | 163 | 155 | 109 | 175 | 87 |
| C117 | 172 | **170** | 192 | 182 | 163 | 155 | 109 | 175 | 87 |
| C118 | 175 | **175** | 202 | 184 | 163 | 151 | 107 | 173 | 95 |
| C119 | 175 | **175** | 203 | 185 | 163 | 151 | 106 | 172 | 98 |

Share of states within ±1 seat of the model (a preview for #37; ≥ 90% passes):

| Congress | **0.5** | 0.3 | 0.4 | 0.6 | 0.7 | land ≥ 0.5 | density ≥ 250 | density ≥ 1,000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C113–C114 | **98%** | 92% | 96% | 96% | 94% | 72% | 84% | 62% |
| C115–C117 | **98%** | 92% | 96% | 96% | 92% | 72% | 84% | 62% |
| C118 | **100%** | 92% | 98% | 94% | 92% | 70% | 80% | 60% |
| C119 | **100%** | 92% | 98% | 94% | 92% | 70% | 78% | 54% |

Every population-share cutoff from 0.3 to 0.7 passes in every Congress. The rule is not
tuned to a knife-edge.

## Notes for #37's diagnoses

- **Texas, C113–C117: 15 real vs 17 modelled.** The 2011 Texas map spreads the big metros
  into districts that reach far into rural counties. TX-05 and TX-26 (Dallas, 46% and 40%),
  TX-36 and TX-10 (Houston, 47% and 31%) and TX-21 (San Antonio, 37%) all fall just under
  half. At a 0.4 cutoff Texas counts 17, matching the model. This is district-drawing (how
  the metro's population is split between districts), not a data or linking error. Under
  the 2021 map (C118–C119) the counts agree at 19.
- **Utah: 0 → 4.** In C113–C117 no Utah metro is in the top 25. In 2020 Salt Lake
  City+Ogden+Provo is, and the four-way split of Salt Lake County puts a majority of every
  district inside the metro (model: 3). It is within ±1, but it shows how cracking inflates
  real counts.
- **The issue's Bay Area example (C119).** By *majority of population* the
  San Francisco–Oakland area holds CA-11, 12, 14 and 15, and Concord–Walnut Creek adds CA-10.
  San Jose holds CA-16 and 17, while CA-18 and 19 are only about one-third inside. The
  census.gov map eyeball (SF ≈ 6, San Jose ≈ 4) counts districts that *touch* each metro.
  For California as a whole, real 35 vs model 36 (C119).
- **Density's false "not metro" calls are the definition's open question.** Orlando,
  Austin, Columbus, Charlotte, Indianapolis and Milwaukee each have dense real districts but
  fall outside the top 25 (`floor(states/2)`). If #37 wants an independent challenge to
  that cutoff, the density-≥250 column is the closest proxy, and its 78–84% pass rate is
  the size of the effect.

## Per-state metro-district counts (chosen rule)

`real metro / seats`. Bold marks a difference of more than 1 from the model. The 25 states
not listed have 0 in every Congress: AK, AL, AR, HI, IA, ID, KS, KY, LA, ME, MS, MT, NC,
ND, NE, NH, NM, OK, SC, SD, TN, VT, WI, WV, WY. Machine-readable, with the model's count
alongside: `data_raw/congressional_districts/real_metro_counts_c113_c119.csv`.

| state | C113 | C114 | C115 | C116 | C117 | C118 | C119 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AZ | 5/9 | 5/9 | 5/9 | 5/9 | 5/9 | 5/9 | 5/9 |
| CA | 33/53 | 33/53 | 33/53 | 33/53 | 33/53 | 35/52 | 35/52 |
| CO | 3/7 | 3/7 | 3/7 | 3/7 | 3/7 | 4/8 | 4/8 |
| CT | 3/5 | 3/5 | 3/5 | 3/5 | 3/5 | 3/5 | 3/5 |
| DE | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0/1 | 0/1 |
| FL | 12/27 | 12/27 | 11/27 | 11/27 | 11/27 | 11/28 | 11/28 |
| GA | 6/14 | 6/14 | 6/14 | 6/14 | 6/14 | 6/14 | 6/14 |
| IL | 12/18 | 12/18 | 12/18 | 12/18 | 12/18 | 12/17 | 12/17 |
| IN | 1/9 | 1/9 | 1/9 | 1/9 | 1/9 | 1/9 | 1/9 |
| MA | 7/9 | 7/9 | 7/9 | 7/9 | 7/9 | 6/9 | 6/9 |
| MD | 5/8 | 5/8 | 5/8 | 5/8 | 5/8 | 5/8 | 5/8 |
| MI | 5/14 | 5/14 | 5/14 | 5/14 | 5/14 | 4/13 | 4/13 |
| MN | 4/8 | 4/8 | 4/8 | 4/8 | 4/8 | 4/8 | 4/8 |
| MO | 2/8 | 2/8 | 2/8 | 2/8 | 2/8 | 2/8 | 2/8 |
| NJ | 11/12 | 11/12 | 11/12 | 11/12 | 11/12 | 11/12 | 11/12 |
| NV | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 |
| NY | 17/27 | 17/27 | 17/27 | 17/27 | 17/27 | 17/26 | 17/26 |
| OH | 6/16 | 6/16 | 6/16 | 6/16 | 6/16 | 3/15 | 3/15 |
| OR | 2/5 | 2/5 | 2/5 | 2/5 | 2/5 | 2/6 | 2/6 |
| PA | 7/18 | 7/18 | 7/18 | 7/18 | 7/18 | 7/17 | 7/17 |
| RI | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| TX | 15/36 **(model 17)** | 15/36 **(model 17)** | 15/36 **(model 17)** | 15/36 **(model 17)** | 15/36 **(model 17)** | 19/38 | 19/38 |
| UT | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 4/4 | 4/4 |
| VA | 3/11 | 3/11 | 3/11 | 3/11 | 3/11 | 3/11 | 3/11 |
| WA | 6/10 | 6/10 | 6/10 | 6/10 | 6/10 | 6/10 | 6/10 |

Reproduce: `python scripts/build_real_district_metro.py` (about 10 s; needs geopandas, as
`build_ua_large_area_gaps.py` does).
