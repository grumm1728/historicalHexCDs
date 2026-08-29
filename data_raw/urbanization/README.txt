State-level urban/rural population tables (wayfinder map #12, ticket #21).
See docs/research_urbanization_data.md for the full source research.

urpop0090.txt
  "Urban and Rural Population: 1900 to 1990" (US Census Bureau, fixed-width text).
  Downloaded 2026-07-10 from
  https://www2.census.gov/programs-surveys/decennial/tables/1990/1990-urban-pop/urpop0090.txt
  Caution: silently splices urban definitions — 1900-1940 figures are the
  places-2,500+ definition, 1950+ the urbanized-area definition.

State_Urban_Rural_Pop_2020_2010.xlsx
  State urban/rural population, 2020 and 2010 censuses (US Census Bureau).
  Downloaded 2026-07-10 from
  https://www2.census.gov/geo/docs/reference/ua/State_Urban_Rural_Pop_2020_2010.xlsx
  2020 uses the housing-unit-based urban definition; 2010 the UA/UC definition.

sf1_p002_2000.json
  Census 2000 SF1 table P002 (Urban and Rural), state level, via the Census API.
  Pulled 2026-07-10 from
  https://api.census.gov/data/2000/dec/sf1?get=NAME,P002001,P002002,P002005&for=state:*
  Columns: P002001 total, P002002 urban, P002005 rural (urban + rural = total,
  verified). 52 rows: 50 states + DC + Puerto Rico. 2000 uses the UA/UC definition.

nhgis0001_csv.zip / nhgis0001_csv/
  IPUMS NHGIS extract nhgis0001 (submitted + downloaded 2026-07-11 by Scott, free
  NHGIS account). State-level Total Population (NT1) and Urban Population 2,500+
  (NT2/NT3, the ICPSR 2896 retrospective places-2,500+ series) for every census
  1790-1890. One CSV + codebook per dataset; 1840/1880/1890 split total vs urban
  across two datasets, other years carry both tables in one file.
  Verified: national urban share per year matches the Census Bureau's published
  series (1790 5.13% ... 1890 35.28%); state counts 15 (1790) -> 51 (1890).
  Citation requirement: publications using these figures must cite IPUMS NHGIS
  (https://www.nhgis.org/frequently-asked-questions-faq).

composite_outline_predecessor_rows.csv
  Wayfinder ticket #23 (graduated from #16's composite-outline rule): when
  `build_effective_outlines` draws a parent state's outline inclusive of a
  not-yet-seated child (per `PREDECESSOR_PARENT` in tile_state_pentahexes.py),
  and the census tabulates that child's territory as its own row separate from
  the parent, the urban-seat formula must sum the parent's row with this extra
  row. One row per (parent, census_year) that actually needs summing; a
  `covers_children` note lists which PREDECESSOR_PARENT child(ren) that single
  extra row accounts for (never double-add it once per child).

  Checked every PREDECESSOR_PARENT pair against every NHGIS census year in its
  composite window (verified via the NHGIS state-name lists directly, not
  assumed):
    - Virginia/Kentucky (composite window: C1 only, 1790 census): NO ENTRY —
      Virginia's 1790 row already includes the Kentucky district; no separate
      "Kentucky" row exists in any pre-1792 census.
    - Virginia/West Virginia (composite window: C1-C37, 1790-1860 censuses):
      NO ENTRY — verified no "West Virginia" (or equivalent) row exists in any
      NHGIS census year before 1870 (West Virginia was a wartime political
      split in 1863, not a pre-existing organized territory like KY/TN/MS/AL;
      the 1870 census is the first to tabulate it, well after its C38
      first-seated Congress).
    - North Carolina/Tennessee (composite window: C1-C3, 1790 census only —
      Tennessee is already its own row by the 1800 census): ENTRY NEEDED,
      "Southwest Territory", 1790 only.
    - Georgia/Mississippi, Georgia/Alabama (composite windows through C14/C15
      respectively, covering the 1790/1800/1810 censuses): 1790 needs no
      entry (no separate territory row exists yet — Mississippi Territory
      wasn't organized until 1798); 1800 and 1810 both need "Mississippi
      Territory" (the one shared unorganized-territory row covering the
      future Alabama + Mississippi land before their 1817 split).
    - Massachusetts/Maine: NOT in scope for this table — Maine is likewise
      never tabulated separately before its own 1820 statehood, but ticket
      #16 already handles this case with its own rule ("Maine's block is 0%
      urban through Congress 16"), not by summing a predecessor row.

  Notable finding: all three rows needing summing (Southwest Territory 1790,
  Mississippi Territory 1800 and 1810) recorded ZERO urban population — these
  were frontier territories with no incorporated place over 2,500 people yet.
  So summing them only affects the population *denominator* (making the
  parent's urban share slightly lower than using its own row alone); it never
  adds to the urban numerator for any case in this table.
