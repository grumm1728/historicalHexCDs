Real congressional district boundaries for Congresses 113-119, plus 2010/2020 tract
population, used to count which real districts are "metro" (issue #35, decision 9 of
#33; consumed by the validation ticket #37). See docs/research_real_district_metro.md
for the chosen rule, its calibration and sensitivity, and the per-state counts.

All files were retrieved 2026-10-11 from www2.census.gov (US Census Bureau, public
domain). No account or API key was needed. The shapefiles are kept zipped, as downloaded.

-------------------------------------------------------------------------------
SOURCE FILES

Cartographic boundary congressional districts, 1:500k, national (50 states + DC + PR +
island areas, 441 features each). Fields: STATEFP, CD1xxFP (district number; "00" =
at-large), GEOID, CDSESSN, ALAND/AWATER (m^2, from the full-resolution TIGER/Line
geometry, so the generalization does not affect them).

  file                          used for  URL (https://www2.census.gov/geo/tiger/...)
  cb_2013_us_cd113_500k.zip     C113      GENZ2013/cb_2013_us_cd113_500k.zip
  cb_2014_us_cd114_500k.zip     C114      GENZ2014/shp/cb_2014_us_cd114_500k.zip
  cb_2016_us_cd115_500k.zip     C115      GENZ2016/shp/cb_2016_us_cd115_500k.zip
  cb_2018_us_cd116_500k.zip     C116      GENZ2018/shp/cb_2018_us_cd116_500k.zip
  cb_2020_us_cd116_500k.zip     C117      GENZ2020/shp/cb_2020_us_cd116_500k.zip
  cb_2022_us_cd118_500k.zip     C118      GENZ2022/shp/cb_2022_us_cd118_500k.zip
  cb_2024_us_cd119_500k.zip     C119      GENZ2024/shp/cb_2024_us_cd119_500k.zip

  Mid-decade redistricting is captured by the vintages (measured as districts whose
  geometry changes with IoU < 0.9 between consecutive files):
    C114 -> C115  FL (21 districts), NC (11), VA (5)   (2016 court-ordered maps)
    C115 -> C116  PA (18)                              (2018 court-drawn map)
    C118 -> C119  NY (14), NC (14), GA (9), AL (6), LA (6)
  C113 -> C114, C116 -> C117: no change.

  KNOWN GAP: there is no Census file for the 117th Congress. Census carried the 116th
  districts forward (the 2020 file is cd116 and matches the 2018 file except for
  shoreline generalization in NY/NJ/CA). That is right for every state except North
  Carolina, which voted in 2020 under its 2019 remedial plan (Session Law 2019-249, HB
  1029), defined in the bill as lists of 2010 blocks and VTDs, with no Census shapefile.
  NC C117 therefore uses the 2016 plan and is flagged `nc_c117_proxy`. Under the chosen
  rule it doesn't matter: NC has no qualifying (top-25) metro in 2010, so it has 0 metro
  districts under either plan.

Tract centers of population (one row per census tract: STATEFP, COUNTYFP, TRACTCE,
POPULATION, LATITUDE, LONGITUDE). The 2020 file starts with a UTF-8 BOM.

  CenPop2010_Mean_TR.txt   2010 tracts (74,002)  C113-C117
      https://www2.census.gov/geo/docs/reference/cenpop2010/tract/CenPop2010_Mean_TR.txt
  CenPop2020_Mean_TR.txt   2020 tracts (85,395)  C118-C119
      https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR.txt

  Each tract is assigned whole to the district (and urbanized area) containing its
  center of population. Check: the summed tract population of every district is within
  -4.8%..+7.0% of its state's census population / seats (median 0.0%, sd 1.0%).

Urbanized-area boundaries are reused from ../urbanized_areas/boundaries/
(cb_2013_us_ua10_500k.zip for 2010, cb_2020_us_ua20_corrected_500k.zip for 2020).

-------------------------------------------------------------------------------
GENERATED FILES  (python scripts/build_real_district_metro.py, ~10 s)

real_districts_c113_c119.csv   one row per voting district, 435 x 7 = 3,045 rows (DC's
  and the territories' delegates are dropped). Columns:
    congress, state_fips, state, cd, seats (state's delegation),
    aland_km2              Census ALAND / 1e6
    ideal_pop              state census population / seats (2010 for C113-117, 2020 for
                           C118-119; the same totals metro_seats uses)
    tract_pop              summed population of tracts whose center falls in the district
    density_per_km2        ideal_pop / aland_km2
    metro_land_frac        share of the district polygon inside a qualifying metro's UAs
    metro_pop_frac         share of tract_pop inside a qualifying metro's UAs
    metro_name             the qualifying metro holding most of that population
    is_metro               metro_pop_frac >= 0.5   (the chosen rule)
    nc_c117_proxy          1 for NC in C117 (see KNOWN GAP)
  "Qualifying metro" = metro_seats.qualifying_metros(census year): the census's top-25
  linked urbanized-area metros, exactly the set the tiler labels.

real_metro_counts_c113_c119.csv   one row per (Congress, state), 350 rows. Columns:
    congress, state_fips, state, seats,
    model_metro_seats      metro_seats.metro_seats(state, congress), i.e. our map's count
    real_metro             real districts with is_metro = 1   (the chosen rule)
    real_metro_pop30/40/60/70   same with the population-share cutoff at 0.3..0.7
    real_metro_land50      metro_land_frac >= 0.5
    real_metro_d250..d1500 density_per_km2 >= 250..1500
    nc_c117_proxy
