Historical city population tables (wayfinder map #12, ticket #21).
See docs/research_anchor_city_data.md for the full source research.

1790-2010_MASTER.csv
  "United States city population data, 1790-2010" — US Census Bureau data compiled
  by Erik Steiner, Spatial History Project / CESTA, Stanford. All ~8,915 places that
  ever exceeded 2,500 population; one column per census 1790-2010; lat/lon on every
  row (Census gazetteer coords, Bing-geocoded fallback); 2010 place FIPS.
  Public domain (data), MIT (scripts).
  Downloaded 2026-07-10 (2,157,987 bytes, matches researched size) from
  https://raw.githubusercontent.com/cestastanford/historical-us-city-populations/master/data/1790-2010_MASTER.csv
  Caution: 0 means "not tabulated", not zero population.

sub-est2024.csv
  Census Bureau subcounty population estimates vintage 2024 (national file), used
  for the April 1, 2020 census place populations to extend the CESTA table to 2020.
  Downloaded 2026-07-10 from
  https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv
  Note: this vintage carries ESTIMATESBASE2020 (estimates base, ~= the April 2020
  census count), not a CENSUS2020POP column. Join to CESTA via STATE+PLACE FIPS;
  place rows are SUMLEV 162 (incorporated place) / 170 (consolidated city).
