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
