# Research: official urbanized-area populations, state portions and locations, 1950–2020

Goal (issue #34, from decisions 3–5 of #33): for every census 1950–2020, get the Census
Bureau's own **urbanized-area (UA)** populations, each area's **in-state portions**, and
a **location** per area and per portion (boundaries preferred, for decision 3's
"link areas within 13 km boundary-to-boundary"). Also answer whether digital UA
boundaries exist before 1990, and if not, propose and measure a substitute linking
rule. Researched 2026-09-22 against primary sources (census.gov, www2.census.gov,
IPUMS NHGIS). Every claim cites the page or file that supports it. The raw files and
their inventory are in `data_raw/urbanized_areas/` (see its `README.txt`). The tidy
output is `data_raw/urbanized_areas/ua_state_portions.csv`, written by
`scripts/normalize_urbanized_areas.py`. The measurements come from
`scripts/diag_ua_linking.py`.

## Summary and recommendation

| Census | UA populations | State portions | Location | Boundaries | Status |
|---|---|---|---|---|---|
| 1950 | 157 areas, transcribed (sum matches published total exactly) | 17 principal multi-state areas transcribed from the 1960 state volumes | first-named central city (CESTA) | printed maps only | **acquired** |
| 1960 | 213 areas, transcribed (sum matches exactly) | same 17 areas | first-named central city (CESTA) | printed maps only | **acquired** |
| 1970 | NHGIS `1970_Cnt2`, "Urbanized Area (by State)" | yes (the level *is* state parts) | none published digitally | none | **needs NHGIS extract** |
| 1980 | NHGIS `1980_STF1`, "Urban Area" + "State (by Urban Area)" | yes | none published digitally | none | **needs NHGIS extract** |
| 1990 | STF 1C, 396 UAs | yes, with the Bureau's internal points | official internal point per part | cartographic boundary file | **acquired** |
| 2000 | `ua2k.txt`, 465 UAs | `st2kua.txt` | polygon representative point | cartographic boundary file | **acquired** |
| 2010 | `ua_list_ua.txt`, 497 UAs | `ua_st_list_ua.txt` | gazetteer internal point | cb 1:500k | **acquired** |
| 2020 | urban areas of 50,000+ (510) | `2020_Census_ua_st_list_all.xlsx` | gazetteer internal point | cb 1:500k | **acquired** |

Headline findings:

1. **No digital UA boundaries exist before 1990.** NHGIS offers Urban Area GIS files only
   for 1990, 2000, 2009–2024. The Census Bureau's oldest UA cartographic boundary file is
   the 1990 `ua99_d90`. Before 1990 the only boundaries are the printed maps in the
   decennial volumes. Details are below.
2. **Decision 3's 13 km boundary rule fails its own validation when it runs on official UA
   polygons.** The 13 km figure was calibrated on CESTA *place* points (#33). UA polygons
   are far larger and often touch. Single linkage at 13 km over all UAs chains New York to
   Philadelphia (their direct gap is 5.5–22.7 km, and the chain also runs through
   Trenton, Allentown and others). It also chains Chicago to Milwaukee through Kenosha and
   Racine. Both fail in **every** year 1990–2020. The rule also builds a 46-area chain in
   2010, running from Boston to Washington with 45.7 M people.
3. **Rules that do pass all four tests in all four boundary years** make the chain only
   between large areas, where both ends are at least 500,000:
   - boundary gap ≤ 5 km, or
   - (internal-point distance − r_a − r_b) ≤ 25 km, or
   - first-named-city distance ≤ 100 km.

   The first-named-city rule is the one that can run before 1990. All three rules also
   merge areas that decision 2 expected to stay separate. **Baltimore + Washington** and
   **Boston + Providence** merge, because their official UAs touch (gap 0.0 km in
   2000–2020). So do Akron + Cleveland and, from 2000, New York + Bridgeport + New Haven
   + Hartford. Those merges are geographic facts about the Census polygons, not artifacts
   of the rule.

**Recommendation for #36 (implementation).** Use `ua_state_portions.csv` as the metro
input from 1950 on. Take one decision back to Scott before coding: the linking rule.
Keep it to large UAs and do not chain through small ones. Pick one of:

- **Option A:** first-named-city distance ≤ 100 km with both UAs ≥ 500,000. It is
  uniform for 1950–2020 and needs no boundaries. It merges SF+SJ in 1960+, LA+Riverside
  in 1990+, and Baltimore+DC and Boston+Providence in every year.
- **Option B:** a short curated merge list, like the curated `SEAM_JUNCTION_PAIRS`
  precedent in the tiler. For example "SF-Oakland + San Jose" and "LA + Riverside–San
  Bernardino (+ Mission Viejo)", applied whenever both areas exist.
- **Option C:** use official UAs unlinked. That drops the "Bay Area whole" goal.

Whichever is chosen, the NHGIS extract below closes the 1970/1980 gap.

## 1. What exists per census year

### 1950 — the urbanized-area concept is introduced

- Concept: "The Census Bureau began identifying densely populated urbanized areas of
  50,000 or more population with the 1950 Census." Source: 2020 Census Urban Areas FAQs
  (Feb 2023), PDF p. 7, <https://www2.census.gov/geo/pdfs/reference/ua/Census_UA_2020FAQs_Feb2023.pdf>.
  In 1950 each UA was built around one or more central cities of 50,000+. The urban
  fringe comprised contiguous incorporated places of 2,500+, denser small places, and
  unincorporated territory of at least 500 dwelling units per sq mi. Source: 1950 Vol. I
  Introduction,
  <https://www2.census.gov/library/publications/decennial/1950/population-volume-1/vol-01-02.pdf>.
- Coverage: "There were no urbanized areas delineated in the Territories or possessions"
  (same Introduction). So there are no 1950 UAs in Alaska, Hawaii or Puerto Rico. DC
  (Washington, D.C.) is a UA.
- Populations: U.S. Summary Table 17, "Population and land area of urbanized areas: 1950",
  and Table 18, "Rank of urbanized areas…". Both are in
  <https://www2.census.gov/library/publications/decennial/1950/population-volume-1/vol-01-04.pdf>
  (pages 1-26 to 1-29). The text layer is garbled OCR, so all 157 rows of Table 18 were
  transcribed from page images into `published_tables/ua_1950_published.csv`. The sum is
  **69,249,148**, exactly the Table 17 total.
- State portions: the 1950 titles often omit a second state (for example "Chicago, Ill."
  includes NW Indiana). The 1950 parts come from the "1950" column of each 1960 state
  volume's Table 10 (see 1960). For all 17 transcribed areas, the 1950 parts sum exactly
  to the 1950 totals.
- Land area: printed in Table 17 and again in 1960 Table 22. Not transcribed; see Gaps.

### 1960

- Populations: U.S. Summary Table 22, "Population and land area of urbanized areas: 1960
  and 1950", pp. 1-40 to 1-49, and Table 23, "Rank…", p. 1-50. Both are in
  <https://www2.census.gov/library/publications/decennial/1960/population-volume-1/vol-01-01-f.pdf>.
  That is a scan with no text layer. All 213 rows of Table 23 were transcribed into
  `published_tables/ua_1960_published.csv`. The sum is **95,848,487**, exactly Table 22's
  "United States (1960, 213 areas)". The 1960 titles name every state, for example
  "Philadelphia, Pa.-N.J.".
- State portions: each state part of 1960 Vol. I has **Table 10, "Population of
  urbanized areas: 1960 and 1950"**. It gives "That part of the area in <State>" (or "In
  <State>" subtotals in the host state) for both years, plus every component county, MCD
  and place. Examples used here:
  - New Jersey p. 32-19,
    <https://www2.census.gov/library/publications/decennial/1960/population-volume-1/21260894v1p32ch2.pdf>
  - Illinois p. 15-39/15-41,
    <https://www2.census.gov/library/publications/decennial/1960/population-volume-1/vol-01-15-c.pdf>
  - Maryland p. 22-14, `09768080v1p22ch2.pdf`
  - Kentucky p. 19-18, `41887123v1p19ch2.pdf`
  - Kansas p. 18-29, `vol-01-18-c.pdf`
  - Massachusetts p. 23-15, `37722946v1p23ch2.pdf`
  - Washington p. 49-18, `41887126v1p49ch2.pdf`

  Parts were transcribed for the 17 areas listed in `ua_state_parts_1950_1960.csv`.
  That covers every multi-state UA in the 1960 top 31, which is well past the top-N cut
  of floor(50/2) = 25. Printed parts were checked against their county components.
  Where only one part is printed, the other is derived as total minus that part.
  Washington's D.C. part is the whole District.
- Boundaries: each state volume carries "Urbanized areas (separate map for each area)".
  These are printed maps, for example Kentucky pp. 19-20ff.
- Territories: Honolulu is a UA (Hawaii became a state in 1959). Puerto Rico UAs, if any,
  would be in Part 53. Not checked.

### 1970 and 1980 — NHGIS only (tabular)

NHGIS's geographic-level metadata answers which datasets carry UA levels. Source: the
NHGIS Data Finder's level-detail endpoint (`/metadata/geog_level?istads_id=…`) on
<https://data2.nhgis.org/main>:

- **Urban Area** (NHGIS code 400): source tables from **1980 STF 1, 1980 STF 3, 1980 STF
  4…**, 1990 STF 1–4, 2000 SF 1–4, 2010 SF 1, 2020 DHC, and ACS. GIS files are available
  for "1990, 2000, 2009, 2010, 2006-2010, 2011, … 2024".
- **Urbanized Area (by State)** (code 038): "1970_Cnt2: Count 2 - 100% Data [Tracts,
  Urban Areas, Metro Areas, etc.]". GIS files: none.
- **State (by Urban Area)** (code 410): 1980 STF 1/2a/2b/3/4, 1990, 2000, 2010, 2020,
  and ACS. GIS files: none.
- **Place (by State--Urbanized Area)** (code 04397): 1970 Count 4Pa/4Pb/4H only. These
  cover places of 2,500+ only, per the time-series notes on
  <https://data2.nhgis.org/main/all_tst_details>.

No NHGIS dataset carries a UA level for 1950 or 1960. The NHGIS data-availability grid
confirms the Urban Area GIS row: no marks under 1980, 1950–1970, or earlier
(<https://www.nhgis.org/data-availability>).

The Census Bureau's own 1980 volumes are scans with no text layer, for example
<https://www2.census.gov/library/publications/decennial/1980/volume-1/united-states-summary/1980a_usc-01.pdf>.
NHGIS is therefore the practical route for 1970 and 1980.

### 1990

- 1990 STF 1C (national file):
  <https://www2.census.gov/census_1990/stf1c/stf1c0us.dbf.zip>. Summary level 400 is the
  UA and 410 is the UA–State part (`document/sum_lev.asc` in the same directory). The
  geographic header carries `AREALAND` (km² with 3 implied decimals) and `INTPTLAT` /
  `INTPTLNG` (internal point) for each UA **and each state part**. There are 396 UAs and
  458 parts. The UA total is 158,258,878, which equals the file's own US "inside
  urbanized area" component (GEOCOMP 02).
- STF 1C covers the 50 states and DC. Puerto Rico's 1990 UAs have boundaries (below), but
  their populations are in the separate PR STF 1 files. Not acquired.
- Boundaries: `ua99_d90_shp.zip`, plus AK, HI and PR files, at
  <https://www2.census.gov/geo/tiger/PREVGENZ/ua/>.

### 2000 — density-based delineation, urban clusters added

- Criteria: "core census block groups or blocks that have a population density of at
  least 1,000 people per square mile and surrounding census blocks that have an overall
  density of at least 500 people per square mile". Urban clusters (2,500–49,999) were
  introduced (2000 Urban and Rural Classification page,
  <https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural/2000-urban-rural.html>;
  FAQs PDF p. 7, above).
- Lists: `ua2k.txt` (national) and `st2kua.txt` (state parts), at
  <https://www2.census.gov/geo/docs/reference/ua/>. There are 465 UAs: 452 in the 50
  states + DC, 11 in PR, Hagatna (Guam) and Saipan.
- **Use the original lists, not the corrected ones.** The Aug/Nov 2002 corrected lists
  exist, but "The Census Bureau's official Census 2000 urban/rural data do not contain
  these changes" (same page). This is verified: the original 50-state + DC sum is
  **192,323,824** once Hagatna (132,241) is excluded. That equals the Bureau's published
  2000 UA population on the Urban Areas QuickFacts page,
  <https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural/ua-quickfacts.html>.
- Boundaries: `ua99_d00_shp.zip` (UAs + UCs),
  <https://www2.census.gov/geo/tiger/PREVGENZ/ua/ua00shp/>.

### 2010

- Lists: `ua_list_ua.txt` and `ua_st_list_ua.txt` (same directory), with 497 UAs: 486 US
  and 11 PR. The 50 states + DC sum is **219,922,123**, matching the QuickFacts figure.
  The per-state sums match `PctUrbanRural_State.txt` `POP_UA` for every state including
  PR.
- Internal points: 2010 gazetteer `Gaz_ua.zip`,
  <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/>.
- Boundaries: `cb_2013_us_ua10_500k.zip`, <https://www2.census.gov/geo/tiger/GENZ2013/>.
  The full TIGER/Line version is under `TIGER2010/UA/2010/`.

### 2020 — UA/UC distinction dropped; choice of the large-area tier

- "Starting with the 2020 Census, the Census Bureau ceased distinguishing between
  urbanized areas and urban clusters". An urban area now needs "at least 2,000 housing
  units or at least 5,000 people" and is delineated "primarily" on housing-unit density
  (FAQs, PDF p. 7). The criteria-difference document explains why the 50,000 line was
  dropped as a *type* distinction
  (<https://www2.census.gov/geo/pdfs/reference/ua/Census_UA_CritDiff_2010_2020.pdf>).
- **Tier chosen: 2020 urban areas with population ≥ 50,000.** Justification: the Bureau
  still uses that line functionally. "Urban areas of 50,000 or more people form the urban
  cores of metropolitan statistical areas", and "Each metropolitan statistical area will
  contain at least one urban area of 50,000 or more people" (FAQs, PDF pp. 5–6). That
  continues the 1950–2010 UA threshold. The tier has 510 areas: 498 in the 50 states +
  DC, 11 in PR and 1 in Guam. Only the qualification threshold and density measure
  changed, so large areas are comparable across 2010→2020. Small-town areas are not, but
  they never reach the top-N metros.
- Lists: `2020_Census_ua_list_all.xlsx` and `2020_Census_ua_st_list_all.xlsx`. Over all
  2,644 urban areas, the state-part sums equal the published 2020 state urban totals for
  every state (US 265,149,027). Internal points come from the 2023 gazetteer UA file.
  Note that the "2020_Gazetteer" UA file still carries the 2010 areas.
- Boundaries: `cb_2020_us_ua20_corrected_500k.zip`,
  <https://www2.census.gov/geo/tiger/GENZ2020/shp/>.

### Spot checks (largest three areas)

| Year | New York | Los Angeles | Chicago | Cross-check |
|---|---|---|---|---|
| 1950 | 12,296,117 | 3,996,946 | 4,920,816 | Table 17 = Table 18 = 1960 Table 22 "1950" column |
| 1960 | 14,114,927 | 6,488,791 | 5,959,213 | Table 22 = Table 23 |
| 1990 | 16,044,012 | 11,402,946 | 6,792,087 | STF 1C level 400 = sum of level 410 |
| 2000 | 17,799,861 | 11,789,487 | 8,307,904 | = `PopAreaChngeUA.txt` UA00POP |
| 2010 | 18,351,295 | 12,150,996 | 8,608,208 | = `PopAreaChngeUA.txt` UAPOP |
| 2020 | 19,426,449 | 12,237,376 | 8,671,746 | state sums = published state urban totals |

No verification mismatches remain. One 1950 transcription misread (Beaumont) was caught
by the 69,249,148 checksum and fixed.

## 2. Do digital UA boundaries exist before 1990? — No

- NHGIS: the Urban Area level has GIS files for "1990, 2000, 2009, 2010, … 2024" only.
  The 1970 and 1980 UA levels have "GIS files: none" (geographic-level metadata above;
  data-availability grid at <https://www.nhgis.org/data-availability>).
- Census cartographic boundary files: the `PREVGENZ/ua/` directory's oldest files are the
  1990 `ua99_d90` / `ua02_d90` / `ua15_d90` / `ua72_d90`
  (<https://www2.census.gov/geo/tiger/PREVGENZ/ua/>). TIGER itself began with the 1990
  census.
- What does exist before 1990: printed UA maps in the decennial volumes. The 1960 state
  parts carry "Urbanized areas (separate map for each area)", with shaded incorporated
  places, unincorporated urban places and other urban territory on MCD/CCD base maps.
  Digitizing them would mean georeferencing roughly 200 scanned maps. It is feasible but
  out of scope. The component lists in the same Table 10 (every MCD and place in the UA,
  with population) are the more practical pre-1990 footprint.

## 3. Linking rule: measurements (1990–2020, where polygons exist)

Method (`scripts/diag_ua_linking.py`): polygons are projected to EPSG:5070. For every
pair of areas within 60 km boundary-to-boundary, the script computes:

- the boundary gap;
- the substitute "internal-point distance − r_a − r_b", with r = √(land area/π);
- the same substitute using first-named-city coordinates (CESTA), which is the only
  centre available before 1990;
- the plain first-named-city distance.

It then runs single linkage.

**The four decision-3 test pairs (direct values):**

| Pair (want) | Year | Boundary gap | Internal-point substitute | City distance |
|---|---|---|---|---|
| SF–Oakland + San Jose (link) | 1990/2000/2010/2020 | 0.0 / 0.0 / 0.0 / 0.0 | 17.0 / 23.4 / 7.3 / 21.2 | 75 |
| LA + Riverside–San Bernardino (link) | 1990/2000/2010/2020 | 0.0 / 0.0 / 0.0 / 0.0 | 10.1 / 9.5 / 10.9 / 8.7 | 94 |
| Chicago + Milwaukee (separate) | 1990/2000/2010/2020 | 37.8 / 38.6 / 38.3 / 37.4 | 75 / 57 / 63 / 64 | 139 |
| New York + Philadelphia (separate) | 1990/2000/2010/2020 | 22.7 / 10.8 / 5.5 / 11.5 | 62 / 47 / 38 / 41 | 130–140 |

**Decision 3 as written (boundary gap ≤ 13 km, all UAs):** it passes SF+SJ and
LA+Riverside but **fails Chicago+Milwaukee and NY+Philadelphia in all four years**. The
failure comes from chaining (Kenosha, Racine and Round Lake Beach bridge Chicago to
Milwaukee) and, from 2000, from the direct NY–Philadelphia gap (5.5–11.5 km). Largest
chains at 13 km: in 1990, 19 areas and 24.3 M people from Norwalk/NY through Trenton and
Philadelphia to Wilmington; in 2010, 46 areas and 45.7 M people from Boston to
Washington.

**Substitute as a stand-in for the 13 km boundary rule:** it fits poorly at the pair
level. At 13 km the internal-point substitute agrees on 81/148 (1990), 92/239 (2000),
122/283 (2010) and 120/273 (2020) boundary links, and misses most of the rest. Its best
single threshold (+20 to +28 km) still disagrees on 39–96 pairs per year. The
city-point substitute is worse and never links SF+SJ or LA+Riverside at 13 km. A
radius-corrected distance cannot reproduce polygon adjacency: UAs are elongated and
coast- or valley-shaped (Miami–Port St. Lucie touch, yet their city-point substitute is
121 km).

**Rules that pass all four tests in all four years** (only UAs ≥ 500,000 link, and they
do not chain through smaller ones):

| Rule | Extra merges beyond the tests (2010 shown; similar every year) |
|---|---|
| Boundary gap ≤ 5 km | Akron+Cleveland; Allentown+Philadelphia; Baltimore+Washington; Boston+Providence; Bridgeport+Hartford+New Haven+NY+Springfield; Cincinnati+Dayton; Concord+SF+SJ; LA+Mission Viejo+Riverside; Ogden+Salt Lake City |
| Internal-point substitute ≤ 25 km | same minus Cincinnati+Dayton and Ogden+SLC |
| First-named-city distance ≤ 100 km | boundary-gap-5 set plus Detroit+Toledo, Tampa+Sarasota+Cape Coral, Sacramento joins the Bay Area, and Providence joins the NY–CT group through Springfield/Hartford in 2000–2010 |

The 1990 merge sets are the same idea but smaller: Akron+Cleveland, Baltimore+Washington,
Boston+Providence, Fort Lauderdale+Miami+West Palm Beach, Hartford+Springfield,
LA+Riverside and SF+SJ. The full lists per year are printed by the script.

**Applied before 1990** with the city rule (≥ 500,000, ≤ 100 km):

- 1950: Boston+Providence, Baltimore+Washington. San Jose (176k) and Riverside (1950 had
  only San Bernardino, 136k) are below 500k.
- 1960: SF+San Jose (75 km), Boston+Providence, Baltimore+Washington,
  Cincinnati+Dayton, Dallas+Fort Worth. San Bernardino–Riverside (378k) stays separate
  from LA.

Historically this is defensible. In 1950 San Jose really was separated from SF–Oakland
by orchards, and the 1950/1960 UA definitions kept them apart. Keeping "the Bay Area
whole" in 1950 is a design choice, not a census fact.

**Conflict with #33 to resolve in #36.** Decision 2 measured Baltimore–DC and
Boston–Providence staying apart through 17 km, but that was on CESTA place points. On
official UA polygons those pairs touch (gap 0.0 km from 2000; Boston–Providence 1.2 km
in 1990). No boundary- or distance-based rule can merge SF+SJ (gap 0) while keeping
Baltimore+DC (gap 0) apart. If those must stay separate, the rule has to be a curated
merge list (Option B in the summary).

## 4. NHGIS extract to request (Scott — needs your free NHGIS account)

No IPUMS API key was found in the environment (`IPUMS_API_KEY` is unset; the repo has
only a Census API key). The existing `data_raw/urbanization/nhgis0001_csv` was a manual
Data Finder extract by Scott. Request one extract at <https://data2.nhgis.org/main>:

| Dataset (NHGIS code) | Geographic level(s) | Table(s) | Notes |
|---|---|---|---|
| 1970 Census: Count 2 – 100% Data [Tracts, Urban Areas, Metro Areas, etc.] (`1970_Cnt2`) | **Urbanized Area (by State)** — NHGIS level `urb_area_038` | **NT1** Sex by Race (sum all cells = total persons). Optionally NT4A Household Relationship, which NHGIS itself sums for 1970 totals | 1970 has only the by-state level; UA totals = sum of parts |
| 1980 Census: STF 1 – 100% Data (`1980_STF1`) | **Urban Area** (`urb_area`, code 400) **and State (by Urban Area)** (`state_410`, code 410) | **NT1A** Persons | gives totals and state parts |
| (optional) 1970 Count 4Pa (`1970_Cnt4Pa`) | Place (by State--Urbanized Area) (`place_04397`) | its persons table | component places of 2,500+ per UA, giving population-weighted centres for 1970 |

- Settings: CSV, "include additional descriptive header row", no GIS files. None exist
  for these levels.
- Save the zip as `data_raw/urbanized_areas/nhgis0002_csv.zip`. The normalizer has
  1970/1980 as an unimplemented hook and needs a small loader once the files exist.
- NHGIS citation is required in publications
  (<https://www.nhgis.org/frequently-asked-questions-faq>).
- 1970/1980 locations: NHGIS source tables carry codes and names, not coordinates. Use the
  first-named central city (CESTA), as for 1950/1960.

## 5. Gaps and risks

- **1970/1980 missing** until the extract above arrives. This is the only blocking gap
  for #36.
- **1950/1960 land areas not transcribed.** They sit in 1960 U.S. Summary Table 22, pdf
  pages 40–49 (both years). They are only needed if a radius-based rule is chosen. The
  recommended options do not need them.
- **1950/1960 state parts** cover the 17 principal multi-state areas. Fifteen smaller
  1960 multi-state UAs (rank ≥ 46: Omaha, Youngstown–Warren, Davenport, South Bend,
  Chattanooga, …) are carried whole under their first-named state (`part_note =
  multistate_unsplit`). Their parts are in the same state-volume Table 10s if needed.
- **Name-based joins across years.** UA codes are not stable before 1990 (1950/1960 have
  no codes in the files). Matching areas across censuses, or to CESTA cities, is by
  first-named city. A few titles need care (hyphenated cities such as "Wilkes-Barre" or
  "Winston-Salem"; "New York-Northeastern New Jersey").
- **Territories.** Puerto Rico UAs are present for 2000, 2010 and 2020, plus Guam 2000 and
  2020 and Saipan 2000. PR 1990 populations are not acquired (boundaries are). There were
  no UAs in any territory in 1950. 1960–1980 PR is unchecked. Decision 4 ranks whole
  censuses, so San Juan (2.1–2.5 M in 2000–2010) enters the ranking in years where it is
  present and is absent in years where it is missing. Keep that in mind for the ranking.
- **Definition breaks** at 1950 (introduction), 2000 (density-based blocks, UCs) and 2020
  (housing-unit density, no UA/UC). Large-area populations are comparable across these;
  small areas are not. Nothing is retabulated backward (FAQs).
- **1990 area units / datum** are inferred. `AREALAND` is treated as km²×1000 because it
  is consistent with the 2000 areas. The 1990 shapefile has no `.prj` and is treated as
  NAD83; a NAD27 shift is < 0.1 km. Neither affects the km-scale linking results.
- **Repository size.** About 36 MB of files were added (the largest are 9.4 MB). This
  follows the `data_raw/urbanization` convention of committing source zips.
  (Two unneeded files that came down with their directories, the 1990 STF 1C age tables
  and the 2000 airport list, were deleted.)
