# Research: anchor-city data (largest city per state, per decennial census, with coordinates)

*Research notes, 2026-07-10. Question: what primary source(s) give city populations per
decennial census across all of U.S. history, so that for any state and census year we can
derive an anchor city (or a ranked list of a state's largest cities) with lat/lon?*

All numeric claims below marked "verified" were checked directly against the cited file or
page during this research (the Stanford CSV was downloaded and queried with Python).

## Summary and recommendation

**Primary recommendation: the U.S. Census Bureau / Stanford CESTA "historical U.S. city
populations 1790–2010" dataset** —
[github.com/cestastanford/historical-us-city-populations](https://github.com/cestastanford/historical-us-city-populations)
— as the single base table, extended to 2020 with the Census Bureau's
[SUB-EST2024 subcounty CSV](https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/)
(column `CENSUS2020POP` carries the official April 1, 2020 census count for every
incorporated place).

Why this wins:

- It is one CSV (`data/1790-2010_MASTER.csv`, 2.1 MB, 8,915 place rows — verified), wide
  format with one population column per census 1790–2010, **already carrying lat/lon for
  every row** (Census gazetteer coords where available, Bing-geocoded otherwise; verified:
  0 of 8,915 rows lack both), plus 2010 place FIPS for joining to modern Census products.
- Its population figures are the Census Bureau's own: the core is "a US Census Bureau
  dataset of ~7,500 incorporated cities whose population surpassed 2,500 people at some
  point," per the
  [README](https://github.com/cestastanford/historical-us-city-populations/blob/master/README.md),
  with small documented supplements (state data centers, Lahmeyer's Populstat for sub-2,500
  values). Compiled data is public domain; scripts MIT.
- Because it covers **all** 2,500+ places, not a national top-100, the largest city
  **per state** per census is directly derivable — the fatal flaw of the top-100 tables
  (see "Per-state coverage" below) doesn't apply.

**Cross-check / documentation source:** Campbell Gibson, *Population of the 100 Largest
Cities and Other Urban Places in the United States: 1790 to 1990*, Census Population
Division Working Paper No. 27 (June 1998) —
[census.gov/library/working-papers/1998/demo/POP-twps0027.html](https://www.census.gov/library/working-papers/1998/demo/POP-twps0027.html).
It exists, is authoritative, and its "Notes for Individual Places" are the best single
reference for annexations/consolidations/renames — but its top-N structure makes it
unsuitable as the per-state base table (details below).

**Known gap requiring a small curated patch:** in the earliest censuses several seated
states have *no* place at all in the census urban universe (verified from the CSV: Delaware
has no recorded place until 1840, Vermont until 1850, New Jersey until 1810, Georgia and
North Carolina until 1800). Zeros in the CSV mean "not tabulated," not "population zero."
For those state×decade cells the anchor must come from a hand-curated mini-table
(~a dozen rows) sourced from the scanned decennial volumes, or by carrying the state's
first-available anchor backward.

Proposed deliverable table (one row per state×census with data):
`state_fips, census_year, city_name, city_pop, lat, lon, rank_in_state` — see
"Recommended derivation" at the end.

## Per-source detail

### 1. Census Bureau / Stanford CESTA compilation (recommended base)

- **What:** "United States city population data, 1790–2010", compiled by Erik Steiner,
  Spatial History Project, Center for Spatial and Textual Analysis (CESTA), Stanford,
  from a Census Bureau dataset. Repo:
  [cestastanford/historical-us-city-populations](https://github.com/cestastanford/historical-us-city-populations).
- **File (verified):** `data/1790-2010_MASTER.csv` (2,157,987 bytes; 8,915 data rows).
  Columns: `ID, ST, City, CityST, 1790 … 2010 (23 decade columns), STPLFIPS_2010,
  Name_2010, County, LAT, LON, LAT_BING, LON_BING, City Source, Population Source,
  Place Type, County_Name1`.
- **Universe (per README):** ~7,500 Census Bureau places that ever exceeded 2,500
  population; 1790–1940 figures include places of 2,500+ regardless of incorporation,
  1950+ focuses on incorporated places (plus Hawaii CDPs); a few hundred sub-2,500 and
  township/CDP records added from state data centers and Populstat.
- **Coordinates (verified):** `LAT/LON` are the Census gazetteer's representative point
  (blank for 1,389 rows — mostly places that no longer exist as 2010 census places);
  `LAT_BING/LON_BING` fill every remaining row. **No row lacks both**, and no
  state-largest-city row in any decade lacks coordinates.
- **Machine readability / licensing:** plain CSV in a public GitHub repo; data public
  domain, code MIT (per README). No registration.
- **Caveats (README + verified):** 0 means missing, not zero (e.g. Wilmington DE is 0
  until 8,367 in 1840 despite being Delaware's chief town throughout — the early censuses
  simply didn't tabulate it as an urban place); San Francisco 1850 is an estimate
  (original returns lost); seven consolidated cities have "balance" records; renames can
  produce duplicate rows; county fields are incomplete. Includes an `IT` state code
  (Indian Territory) that needs mapping/exclusion. Stops at **2010** — no 2020 column.

### 2. Gibson, Working Paper No. 27 (verify + cross-check; not the base)

- **What:** Campbell Gibson (Census Population Division), June 1998. Landing page:
  [census.gov/library/working-papers/1998/demo/POP-twps0027.html](https://www.census.gov/library/working-papers/1998/demo/POP-twps0027.html);
  full HTML/text tables under
  [www2.census.gov/library/working-papers/1998/demo/pop-twps0027/](https://www2.census.gov/library/working-papers/1998/demo/pop-twps0027/twps0027.html).
- **Coverage (verified against the landing page):** all 21 censuses 1790–1990. Tables
  1–22 rank the largest urban places at each census — the full 100 only from 1840 on;
  earlier censuses list the entire urban universe, which was smaller (24 places in 1790,
  33 in 1800, 46 in 1810, 61 in 1820, 90 in 1830). Land area and density from 1910.
  Summary tables 23–26 (peak populations, rank thresholds, geographic distribution by
  state/region). Format: downloadable plain-text tables — parseable but positional, not
  CSV.
- **Value here:** the authoritative *documentation* layer. Its per-state "Notes for
  Individual Places" record annexations, consolidations, name changes and
  extended-city cases — exactly the traps a name-based join hits (see coordinates
  section). Related: Working Paper No. 76 adds race/Hispanic-origin detail for the same
  places ([POP-twps0076](https://www.census.gov/library/working-papers/2005/demo/POP-twps0076.html)).
- **Why not the base:** top-100 only (see next section).

### 3. NHGIS (IPUMS) — place tables and Place Points

- **Tabular data:** NHGIS publishes place-level population tables only from **1970
  onward** (nominal time-series tables begin 1970; standardized tables begin 1990), per
  [nhgis.org/data-availability](https://www.nhgis.org/data-availability) and the
  time-series overview. So NHGIS cannot supply the 1790–1960 place populations this
  feature needs.
- **Place Points (useful for coordinates):**
  [nhgis.org/place-points](https://www.nhgis.org/place-points) — GIS point files locating
  incorporated/unincorporated/census-designated places for the whole U.S., decennially
  **1900–2010** plus 2009–2015. Points are chiefly GNIS coordinates ("the historical,
  functional center" of each place, fixed across time), with places missing from GNIS
  digitized from georeferenced Census maps. Identifiers `GISJOIN` (year-specific) and
  `NHGISPLACE` (time-consistent). Shapefile format; requires free IPUMS registration and
  citation per the IPUMS use policy.
- **Verdict:** the best *fallback* coordinate source for pre-1940 places that the
  Stanford CSV geocoded via Bing, and the best 2020 place-population source if we prefer
  a registered-download of the official 2020 tables over SUB-EST.

### 4. Census Bureau Gazetteer files (modern coordinates)

- [census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html);
  raw files under
  [www2.census.gov/geo/docs/maps-data/data/gazetteer/](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/).
- Annual pipe-delimited text files per geography type including **Places**, with `GEOID`
  (state FIPS + place FIPS), name, and `INTPTLAT`/`INTPTLONG` (internal-point latitude
  and longitude in decimal degrees) — record layouts documented at
  [gaz-record-layouts](https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/gaz-record-layouts.html).
- Joins cleanly to the Stanford CSV via `STPLFIPS_2010`, and to SUB-EST2024 via
  state+place FIPS. Covers only places existing in the file's vintage — historical-only
  places (Brooklyn, Allegheny) are absent, hence the Stanford/NHGIS coordinates matter.

### 5. Census Bureau SUB-EST2024 (the 2020 extension)

- [City and Town Population Totals: 2020–2025](https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-cities-and-towns.html);
  national CSV verified at
  [www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/](https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/)
  (`sub-est2024.csv`, ~6.8 MB, plus per-state FIPS-numbered subsets).
- Contains every incorporated place and MCD with state/place FIPS and the
  **April 1, 2020 census base count** (`CENSUS2020POP`) — the cleanest machine-readable
  route to official 2020 place populations without data.census.gov API work or IPUMS
  registration. (The formal alternative is the 2020 Census P1 table at place level via
  [data.census.gov](https://data.census.gov) or NHGIS.)

### 6. ICPSR (not useful here)

- ICPSR Study 2896, Michael Haines, *Historical, Demographic, Economic, and Social Data:
  The United States, 1790–2002*
  ([icpsr.umich.edu/web/ICPSR/studies/2896](https://www.icpsr.umich.edu/web/ICPSR/studies/2896))
  is the standard historical-census research compilation, but it is **county/state-level**
  (its `level` variable is 1=county, 2=state, 3=USA) — no place-level populations.
  Requires ICPSR institutional login. Not needed for this feature.

### 7. Scanned decennial volumes (last-resort backfill)

- The Census Bureau hosts the scanned originals (e.g. the per-state "Number of
  Inhabitants" tables listing every incorporated place each census) under
  [www2.census.gov/prod2/decennial/documents/](https://www2.census.gov/prod2/decennial/documents/)
  (verified: catalog-numbered PDF sets, not machine-readable). Only needed to source the
  handful of hand-curated early-era anchor rows described below.

## The coordinates problem

Historical population tables carry no lat/lon; the join strategies, best first:

1. **Already solved in the base CSV.** The Stanford compilation ships `LAT/LON` (Census
   gazetteer) and `LAT_BING/LON_BING` for every row (verified: no row lacks both, and no
   row that is ever a state's largest city lacks both). For an anchor-city feature —
   which needs "roughly where in the state is this city" — Bing-geocoded precision is
   more than sufficient.
2. **FIPS join for modern places.** `STPLFIPS_2010` → Census Gazetteer `GEOID` gives
   official internal points for the ~6,800 rows that are 2010 places (2,115 rows lack a
   2010 FIPS — verified — mostly places absorbed or dissolved before 2010).
3. **GNIS / NHGIS Place Points for vanished places.** GNIS
   ([USGS domestic names download](https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data),
   pipe-delimited national text file, feature class "Populated Place", includes historical
   names) or NHGIS Place Points 1900–2010 locate places that no longer exist.

**Pitfalls of any name+state join** (all documented in Gibson's Notes for Individual
Places, [POP-twps0027](https://www.census.gov/library/working-papers/1998/demo/POP-twps0027.html)):

- **Consolidations:** Brooklyn was an independent city — the nation's 3rd/4th largest —
  through 1890, then consolidated into New York City in 1898; Allegheny, PA (a top-100
  city) was annexed by Pittsburgh in 1907; Spring Garden, Northern Liberties, Kensington
  etc. were absorbed in Philadelphia's 1854 consolidation. A naive join drops or
  double-counts these.
- **Renames:** e.g. Barrow, AK → Utqiaġvik (2016); the README warns renames can appear as
  duplicate rows with split time series.
- **"Balance" records:** consolidated city-county records (Nashville-Davidson, Louisville
  etc.) appear as "balance" populations in modern products, with different names than the
  historical city rows.
- **Independent/coextensive cities:** Virginia's independent cities and city-county
  consolidations (Jacksonville–Duval 1968) change what "the city" means mid-series; the
  population jump is real annexation, not error.

## Per-state coverage: the top-N problem, empirically

The requirement is the largest city **per state**, so a national top-100 table is
structurally insufficient: a small state's largest city routinely falls below the national
cutoff. Concrete, verified demonstration: **Key West was Florida's largest city in 1880
(pop 9,890) and 1890 (18,080)** — verified from the Stanford CSV — yet is far below
Gibson's 100th-place threshold for those censuses, so Florida simply has no entry in the
top-100 tables for 1880. No Census product was found that directly publishes
"largest city per state per census" as a series; it must be derived from an
all-places table. Both candidate all-places sources:

- **Stanford CSV (chosen):** every place that ever exceeded 2,500 → per-state ranking is a
  simple group-by. Because the threshold is "ever exceeded 2,500," a state's early small
  towns are still present as long as they eventually grew (e.g. Chicago's 1840 pop 4,470
  is in the table).
- **Scanned "Number of Inhabitants" volumes:** complete per-state place lists each census,
  but scanned PDFs — only worth touching for the curated early-era patch rows.

**Verified early-era holes (seated states with no tabulated place):** DE until 1840,
VT until 1850, NJ until 1810, GA and NC until 1800 (from the CSV; consistent with
Gibson's 1790 table containing only 24 urban places nationwide). For the hex map this
affects roughly Congresses 1–26 for a handful of states, and needs ~a dozen curated rows
(e.g. Wilmington DE, Savannah GA, New Bern NC, Trenton/Newark NJ, Windsor/Burlington VT)
or a carry-back rule.

## The anchor must be per-era: verified largest-city flips

All verified from the Stanford CSV (plus 2020 census for Alabama):

| State | Flip | Evidence |
|---|---|---|
| CA | San Francisco → Los Angeles at 1920 | 1910: SF 416,912 vs LA 319,198; 1920: LA 576,673 vs SF 506,676 |
| AL | Mobile → Birmingham at 1910; Birmingham → Huntsville at 2020 | 1900: Mobile 38,469 vs Birmingham 38,415 (margin of 54!); 1910: Birmingham 132,685. 2020 census: Huntsville 215,006 vs Birmingham 200,733 ([Census 2020 results, via press coverage of the official counts](https://www.alreporter.com/2021/08/14/2020-census-results-show-that-huntsville-is-the-largest-city-in-the-state-of-alabama/)) |
| FL | Key West → Jacksonville at 1900 (later Miami metro dominance never made Miami the largest *city*) | 1890: Key West 18,080 vs Jacksonville 17,201; 1900: Jacksonville 28,429 |
| VA | Richmond → Norfolk (1960s) → Virginia Beach by 1990 | 1950: Richmond 230,310 vs Norfolk 213,513; 1990: Virginia Beach 393,069 vs Norfolk 261,229 vs Richmond 203,056 |
| TN | Nashville → Memphis (by 1860) → Nashville again at 2020 | 1850: Nashville 10,165 vs Memphis 8,841; 1900: Memphis 102,320 vs Nashville 80,865; 2010 (CSV): Memphis 646,889 still ahead of Nashville 601,222; 2020 census: Nashville-Davidson 689,447 vs Memphis 633,104 ([Census QuickFacts comparison](https://www.census.gov/quickfacts/fact/table/nashvilledavidsonmetropolitangovernmentbalancetennessee,memphiscitytennessee/RHI125221)) |
| MO | St. Louis → Kansas City at 1990 | 1980: St. Louis 452,801 vs KC 448,028; 1990: KC 435,146 vs St. Louis 396,685 |

A static per-state anchor would misplace the urban cluster for large stretches of the
timeline in at least these six states; a per-census anchor is required.

## Recommended derivation

Combine three inputs, in one preprocessing script:

1. `1790-2010_MASTER.csv` (Stanford/Census) — populations 1790–2010 + coordinates.
2. `sub-est2024.csv` (`CENSUS2020POP` where `SUMLEV` = place) — adds the 2020 column,
   joined on `STPLFIPS_2010` = state FIPS + place FIPS (name+state fallback for FIPS
   misses; log unmatched).
3. A small curated `anchor_overrides.csv` for (a) the verified early-era holes
   (DE/VT/NJ/GA/NC etc.), (b) any consolidation quirks we care about (e.g. whether the
   pre-1900 NY anchor should be Manhattan's point or the NYC consolidated point), and
   (c) name canonicalization (Utqiaġvik, "balance" records).

Processing: melt the wide CSV to long; **treat 0 as missing**; attach coordinates
(`LAT/LON`, else `LAT_BING/LON_BING`); map `ST` → state FIPS (drop/route `IT`);
apply overrides; rank within state×year by population.

Output table (checked into `data_raw/`), one row per state × census year × ranked city
(keep top 3–5 per state for flexibility):

```
state_fips, census_year, city_name, city_pop, lat, lon, rank_in_state
01,        1900,        Mobile,    38469,    30.668426, -88.1002261, 1
01,        1900,        Birmingham,38415,    33.5274441,-86.799047,  2
...
```

The hex tiler then maps `(state_fips, congress→census_year)` → rank-1 anchor (with the
census year for Congress N chosen as the apportionment census, matching how seat counts
are already derived), and projects lat/lon into the state's scaled-outline space to pick
the hex cells nearest the anchor for the urban-district cluster.

Interpolation policy between censuses is a design choice for the feature, not the data:
the simplest rule — the anchor for a Congress is the largest city at the census governing
that Congress's apportionment — keeps anchors stable for a decade at a time, matching the
project's existing decennial-reapportionment rhythm.

## Source list

- Stanford CESTA / U.S. Census Bureau, *U.S. city populations 1790–2010*:
  <https://github.com/cestastanford/historical-us-city-populations> (README:
  <https://github.com/cestastanford/historical-us-city-populations/blob/master/README.md>)
- Gibson, C., Census Population Division Working Paper 27 (1998):
  <https://www.census.gov/library/working-papers/1998/demo/POP-twps0027.html> and
  <https://www2.census.gov/library/working-papers/1998/demo/pop-twps0027/twps0027.html>
- Gibson & Jung, Working Paper 76 (2005):
  <https://www.census.gov/library/working-papers/2005/demo/POP-twps0076.html>
- IPUMS NHGIS data availability: <https://www.nhgis.org/data-availability>;
  Place Points: <https://www.nhgis.org/place-points>
- Census Gazetteer files:
  <https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html>;
  layouts: <https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/gaz-record-layouts.html>;
  data: <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/>
- Census SUB-EST (2020s city/town totals):
  <https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-cities-and-towns.html>;
  files: <https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/>
- USGS GNIS domestic names download:
  <https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data>
- ICPSR 2896 (Haines): <https://www.icpsr.umich.edu/web/ICPSR/studies/2896>
- Scanned decennial publications: <https://www2.census.gov/prod2/decennial/documents/>
