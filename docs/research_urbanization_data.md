# Research: urban/rural population shares per state, 1790–2020

Goal: a machine-readable input giving urban vs rural population per state for every
decennial census 1790–2020, to drive a future "how many of a state's House seats are
urban" layer. Researched 2026-07-10 against primary sources (Census Bureau, IPUMS
NHGIS, ICPSR). Every claim cites the page that owns it.

## Summary and recommendation

No single download covers 1790–2020 at the state level. The practical stack is four
sources spliced at census-year boundaries, each machine-readable:

| Years | Primary source | Format | Registration |
|---|---|---|---|
| 1790–1890 | ICPSR 2896 (Haines) `URB790`…`URB890` state rows, most conveniently extracted through NHGIS | CSV (NHGIS extract) | free NHGIS account |
| 1900–1990 | Census Bureau `urpop0090.txt` ("Urban and Rural Population: 1900 to 1990") | fixed-width text | none |
| 2000 | Census 2000 SF1 table P002 (Urban and Rural) via the Census API or data.census.gov | JSON/CSV | free API key |
| 2010 + 2020 | Census Bureau `State_Urban_Rural_Pop_2020_2010.xlsx` | XLSX | none |

Cross-check: NHGIS time series table **D15 "Persons by Urban/Rural Status"**
(1970–2020, state level) for the modern end, and the 1990 CPH-2 **Table 4** national
totals (1790–1990 under both definitions) for the historical end.

The main surprise: urban/rural was never tabulated *at the time* for the earliest
censuses — the standard 1790–1930 urban figures were computed retrospectively by the
Census Bureau for the 1930 census ("Original Worksheets of the Urban Population
Prepared for the 1930 Federal Census"), applying the places-of-2,500+ rule backward.
That retrospective series is exactly what ICPSR 2896 digitized, so the 1790–1940 run
is definitionally *consistent* (all places-2,500+), and the one real break in the
series is at 1950 (see definition history below).

## Per-source detail

### 1. ICPSR 2896 — Haines, "Historical, Demographic, Economic, and Social Data: The United States, 1790-2002"

- Study page: <https://www.icpsr.umich.edu/web/ICPSR/studies/2896> (returns 403 to
  anonymous fetchers; the catalog entry is reachable in a browser). Full codebook PDF
  mirrored openly by NHGIS:
  <https://www.nhgis.org/sites/www.nhgis.org/files/histseries-icpsr02896-1790-2002.pdf>.
- County **and state** level data for each census 1790–2002; each part carries a
  `LEVEL` variable (1=county, 2=state, 3=USA), FIPS codes, and was checked so counties
  sum to states and states to the national total (codebook processing notes, pp. 3–7 of
  the PDF above).
- Verified urban/rural variables (from a full-text scan of the codebook): `URB790`,
  `URB800`, `URB810` ("Urban population (places 2,500+)"), `URB820` (plus a separate
  25,000+ variant), `URB830`, `URB840`, `URB850`/`URB860`/`URB880`/`URB900` ("Population
  in places 2,500+"), `URB870`, `URB890`, `URB910`–`URB950`, and explicit rural
  counterparts from 1900 on (`RUR900`, `RUR1910`, `RURAL20`, `RURAL30`, `URBAN40`…).
  So state-level urban population exists for **every census 1790–1950** in one dataset;
  rural = total − urban for the early years where no explicit rural variable exists.
- Source provenance per the codebook data-sources section: 1790–1930 urban figures come
  from *A Century of Population Growth* (1909) tables and the Census Bureau's "Original
  Worksheets of the Urban Population Prepared for the 1930 Federal Census" — i.e. the
  Bureau's own retrospective places-2,500+ tabulation.
- Format: ASCII data with SAS/SPSS/Stata setups per the codebook processing notes.
  Access requires a free ICPSR (MyData) sign-in on icpsr.umich.edu.
- **Easier route to the same numbers:** NHGIS states ICPSR 2896 is "the secondary source
  of most of NHGIS's pre-1970 nation, state and county-level tables"
  (<https://www.nhgis.org/tabular-data-sources>), so the `URBxxx` figures are selectable
  per-census-year source tables in the NHGIS Data Finder and arrive as CSV.

### 2. IPUMS NHGIS

- Site: <https://www.nhgis.org/>; data availability:
  <https://www.nhgis.org/data-availability> (county and state tables since 1790).
- **Time series tables** (<https://www.nhgis.org/time-series-tables>, full listing at
  <https://data2.nhgis.org/main/all_tst_details>): "Persons by Urban/Rural Status"
  exists as tables **D15** (1970, 1980, 1990, 2000, 2010, 2020; nation/region/division/
  state/county/…), **A57** (urban split by inside/outside urbanized areas, 1970–2010),
  and 2010-standardized variants (D16, CL9). **None reach back before 1970** — so the
  time-series product alone cannot cover the historical era; use the per-census source
  tables (from ICPSR 2896) instead.
- Format: CSV extracts, delivered by email-notified extract system; free registration
  required to submit an extract (browsing/building requires none); publications must
  cite NHGIS (<https://www.nhgis.org/frequently-asked-questions-faq>).

### 3. Census Bureau historical tables (no registration)

- **US-level, 1790–1990, both definitions:** 1990 CPH-2 "Table 4. Population: 1790 to
  1990" — <https://www2.census.gov/programs-surveys/decennial/1990/tables/cph-2/table-4.pdf>
  (from the CPH-2 report, <https://www.census.gov/library/publications/1992/dec/cph-2.html>).
  Verified contents: total/urban/rural + percent urban for every census 1790–1990, with
  a "current urban definition" block (1950–1990) and a "previous urban definition" block
  (1790–1960) — the two definitions overlap at 1950 and 1960. US-level only; PDF.
  Useful as the authoritative cross-check for national totals and for quantifying the
  1950 definitional break (1950: 64.0% urban current-def vs 59.6% previous-def).
- **State-level, 1900–1990, machine-readable:** "Table 1. Urban and Rural Population:
  1900 to 1990" —
  <https://www2.census.gov/programs-surveys/decennial/tables/1990/1990-urban-pop/urpop0090.txt>.
  Fixed-width text; rows for US, regions, divisions, and every state; columns: total
  population, urban population, rural population, percent urban, percent rural, per
  decade 1900–1990. Verified definition splice: its 1900 US urban figure (30,214,832)
  matches Table 4's *previous* (places-2,500+) definition and its 1950 figure
  (96,846,817) matches the *current* (urbanized-area) definition — i.e. the file uses
  places-2,500+ for 1900–1940 and the urbanized-area definition for 1950–1990. Alaska
  footnotes note off-cycle enumerations ("Actual date of 1940 census for Alaska was
  1939", "…1930 census for Alaska was 1929").
- **State-level, 2010 + 2020:** "State-level 2020 and 2010 Census Urban and Rural
  Information…sorted by state FIPS code" —
  <https://www2.census.gov/geo/docs/reference/ua/State_Urban_Rural_Pop_2020_2010.xlsx>
  (verified HTTP 200, ~38 KB), linked from
  <https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html>.
  The 2010-only predecessor also still exists:
  <https://www2.census.gov/geo/docs/reference/ua/PctUrbanRural_State.xls> (verified 200).
- **State-level, 2000:** Census 2000 SF1 table P002 "Urban and Rural", via
  data.census.gov or the API (e.g.
  `https://api.census.gov/data/2000/dec/sf1?get=P002001,P002002,P002005&for=state:*`).
  Note: the Census API now rejects keyless requests ("A valid key must be included with
  each data API request" — observed 2026-07); keys are free. The 2020 equivalent is DHC
  table P2 (<https://data.census.gov/table/DECENNIALDHC2020.P2>), but the XLSX above
  covers 2020 without an API.

## Urban-definition history (and whether tables are retabulated)

Primary reference: Census history page "Urban and Rural Areas"
(<https://www.census.gov/about/history/historical-censuses-and-surveys/census-programs-surveys/geography/urban-and-rural-areas.html>)
and the urban-rural program page
(<https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html>).

- **1880/1890/1900 (as originally published):** minimum place sizes of 8,000, 4,000,
  and 2,500 respectively. **1910:** threshold standardized at incorporated places of
  2,500+, and this rule was applied through 1940.
- **Retrospective series:** for the 1930 census the Bureau computed urban population
  back to 1790 under the uniform places-2,500+ rule (the "Original Worksheets" cited in
  the ICPSR 2896 codebook). The standard historical tables (CPH-2 Table 4 "previous
  urban definition" rows, and ICPSR 2896's `URBxxx`) all use this uniform rule — so
  1790–1940 is internally consistent even though "urban" wasn't an 1880s-era concept
  for most of it.
- **1950:** urbanized-area concept introduced (dense unincorporated fringe counts as
  urban); by 1960 a density threshold of ~1,000 persons/sq-mi applied. Historical data
  were **not** retabulated backward under this definition — instead 1950 and 1960 were
  published under *both* definitions (visible in CPH-2 Table 4), giving a two-census
  overlap to calibrate the break (~4.4 points at the national level in 1950).
- **2000:** urban clusters added; delineation became purely density-based, no longer
  tied to place boundaries.
- **2020:** urban areas redefined on **housing-unit** density; an area qualifies with at
  least 2,000 housing units or 5,000 population; the urbanized-area/urban-cluster
  distinction was dropped
  (<https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html>;
  fact sheet:
  <https://www.census.gov/content/dam/Census/library/factsheets/2022/dec/2020-census-urban-rural-fact-sheet.pdf>;
  press release:
  <https://www.census.gov/newsroom/press-releases/2022/urban-rural-populations.html>).
  2010 and earlier data were not retabulated; the Bureau publishes 2010-vs-2020
  criteria comparisons and reclassified-area lists instead.

**Consequence for the pipeline:** the series has one large break (1950) and two smaller
ones (2000, 2020). Keep the era's own definition per row and tag it — do not attempt to
harmonize, since no retabulated backward series exists at the state level.

## Coverage gaps and edge cases

- **Zero urban population is real data, not missing.** In 1790 only 24 places nationally
  cleared 2,500 (CPH-2 Table 4, cited above); several early states/territories have
  urban_pop = 0. Store 0, not null.
- **Territories before statehood:** the decennial census enumerated territories, and
  ICPSR 2896 "included all missing territories and the District of Columbia" (study
  description, ICPSR 2896 catalog). But territory boundaries don't map 1:1 onto modern
  state FIPS (Dakota Territory pre-1889, Indian Territory + Oklahoma Territory pre-1907)
  — the pipeline only needs *seated* states (those with House delegations), which
  sidesteps most of this.
- **Alaska/Hawaii:** off-cycle early enumerations (AK "1940" census taken 1939, "1930"
  taken 1929 — footnotes in `urpop0090.txt`); they only matter here from statehood
  (1959, first apportioned census 1960), which `urpop0090.txt` covers.
- **Pre-1970 NHGIS time series do not exist for urban/rural** (verified against
  <https://data2.nhgis.org/main/all_tst_details>); use per-census source tables.
- **Revision flags:** the Bureau marks some figures `r` (revised) — e.g. 1850 urban and
  1970 urban in CPH-2 Table 4. Prefer the latest publication's value; note the flag if
  carried.
- **Census→Congress join:** urban shares are per *census year*; a Congress should join
  to the census governing its apportionment (same census the seat table derives from),
  so the urban-seat layer stays consistent with `house_seats`.

## Recommended table shape

`data_raw/urbanization/state_urban_rural_by_census.csv`:

| column | type | notes |
|---|---|---|
| `state_fips` | string(2) | matches the project's canonical key (docs/data_spec.md) |
| `state_abbr` | string(2) | secondary key, as in the seats table |
| `census_year` | int | 1790…2020 |
| `total_pop` | int | |
| `urban_pop` | int | 0 is meaningful |
| `rural_pop` | int | invariant: `total_pop == urban_pop + rural_pop` |
| `urban_share` | float | derived = urban/total; stored for convenience |
| `urban_definition_id` | string | `places2500` (1790–1940), `ua1950` (1950–1990), `ua_uc2000` (2000–2010), `hu2020` (2020) |
| `source_id` | string | e.g. `icpsr2896`, `census-urpop0090`, `census-sf1-2000`, `census-ua-2020` |

Primary key `(state_fips, census_year, urban_definition_id)` — the definition id in the
key lets the 1950/1960 both-definition overlap rows coexist if ever ingested, and makes
the three definitional breaks explicit to downstream code (e.g. a viewer can annotate
the 1950 step instead of rendering it as organic urbanization). Counts, not just
shares, are stored because the eventual "urban seats" derivation
(`round(urban_share × house_seats)` or a largest-remainder variant) benefits from exact
integers for auditability, and because counts allow re-aggregation (region/nation
checks against CPH-2 Table 4). Rows are simply absent for state×year combinations not
enumerated (pre-admission with no territory data) — absence means "not enumerated",
zero means "enumerated, no urban population".

## Final recommendation

1. **Primary:** ICPSR 2896 via an **NHGIS extract** (CSV, free registration) for
   1790–1890 state rows; **`urpop0090.txt`** for 1900–1990 (no registration, one fixed-
   width file, already spliced the way the Bureau itself presents history);
   **`State_Urban_Rural_Pop_2020_2010.xlsx`** for 2010/2020; **SF1 P002 via the Census
   API** (free key) for 2000.
2. **Cross-check:** NHGIS time series **D15** (state, 1970–2020) against the modern
   rows, and **CPH-2 Table 4** national totals (both definitions) against the sum of
   state rows per census. The 1900–1950 overlap between ICPSR 2896 and `urpop0090.txt`
   double-covers the splice point.
3. Tag every row with `urban_definition_id`; never harmonize across the 1950/2000/2020
   breaks — no official retabulated state-level series exists.
