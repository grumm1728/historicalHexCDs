Official Census urbanized-area (UA) populations, state portions, and locations,
1950-2020 (wayfinder map #12, research ticket #34; decisions 3-5 of #33).
See docs/research_urbanized_areas.md for the full source research, the
pre-1990 boundary answer, and the linking-rule measurements.

All files below were retrieved 2026-09-22 from census.gov / www2.census.gov
(US Census Bureau, public domain) unless noted. Nothing here needed an
account or API key, except the 1970/1980 NHGIS extract (nhgis0002_csv/,
requested by Scott through his NHGIS account, added 2026-10-10).

ua_state_portions.csv  (GENERATED -- python scripts/normalize_urbanized_areas.py)
  One row per (census year, urbanized area, state portion). Columns:
    year, ua_code, ua_name, state_fips, portion_pop, total_pop,
    portion_land_sqkm, total_land_sqkm, lon, lat, loc_source, part_note
  Years present: 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020.
  loc_source: stf1c_intpt_part (1990 official internal point of the state part),
  gazetteer_intpt (2010/2020 official UA internal point, single-state areas),
  polygon_reppoint / polygon_x_state_reppoint (representative point of the UA
  polygon, or of UA polygon ∩ state polygon, computed from the boundary files
  below), cesta_first_named_city (1950-1980: first-named central city's
  coordinates from data_raw/cities/1790-2010_MASTER.csv; only the portion in
  that city's state gets a point).
  part_note (1950/1960 only): published / derived_total_minus_other_parts /
  derived_whole_state / multistate_unsplit (title names several states but the
  split was not transcribed; row carries the whole area under the first-named
  state -- all such areas rank 46th or lower in 1960).

-------------------------------------------------------------------------------
DEFINITIONS PER YEAR (sources in the research note)
  1950  UA concept introduced: a central city of 50,000+ plus its contiguous
        densely settled urban fringe. 157 areas. No UAs in Alaska, Hawaii,
        Puerto Rico or the possessions.
  1960  Same concept, criteria refined; 213 areas incl. Honolulu.
  1970, 1980  UAs of 50,000+ (central city of 50,000+ plus densely settled fringe).
  1990  396 UAs in the 50 states + DC (STF 1C); Puerto Rico had separate UAs
        (boundaries below; populations not in STF 1C).
  2000  Delineation became purely density-based (blocks/block groups of
        1,000+/sq mi core, 500+/sq mi surrounding); "urban clusters" (UCs,
        2,500-49,999) introduced alongside UAs (50,000+). 465 UAs: 452 in the
        50 states + DC, 11 in Puerto Rico, Hagatna (Guam), Saipan (N. Mariana
        Is.). Corrected lists were issued Aug and Nov 2002, but "the Census Bureau's official Census 2000 urban/rural
        data do not contain these changes" -- the original (tabulated) lists are
        used here.
  2010  UA (50,000+) / UC as in 2000; 486 UAs in the 50 states + DC, 11 in Puerto
        Rico = 497 (no Island Area reached 50,000 as a UA).
  2020  UA/UC distinction dropped: every qualifying area is an "urban area"
        (at least 2,000 housing units or 5,000 people; delineation primarily on
        housing-unit density). The large-area tier used here is urban areas of
        50,000+ population (510: 498 in the 50 states + DC, 11 in Puerto
        Rico, 1 in Guam): per the Census Bureau these
        "form the urban cores of metropolitan statistical areas", i.e. the same
        50,000 line that defined UAs 1950-2010.

-------------------------------------------------------------------------------
FILE INVENTORY

census_ua_reference/   (text/xlsx lists from
                        https://www2.census.gov/geo/docs/reference/ua/ and the
                        gazetteer directory)
  ua2k.txt, st2kua.txt            2000 UAs, national list and state-part list
                                  (pop, land area m^2). USED for 2000.
  uaucdef.txt, convert.txt        2000 record layout / area-unit notes.
  ua_natl_corr.txt, ua_state_corr.txt, ua_state_100302.txt
                                  2000 corrected lists (Aug 23 / Nov 20 2002).
                                  Kept for reference, NOT used (not what SF1
                                  tabulated). Net change: Hagatna GU and
                                  San Rafael--Novato CA removed; Hanford CA and
                                  Cumberland MD--WV--PA added.
  ua_list_ua.txt, ua_st_list_ua.txt
                                  2010 UAs, national and state-part lists
                                  (pop, HU, land/water area). USED for 2010.
  ua_list_all.txt, ua_st_list_all.txt
                                  2010 UAs + UCs (same layout), reference.
  PctUrbanRural_State.txt         2010 state totals incl. POP_UA (verification).
  PopAreaChngeUA.txt              2010 vs 2000 population and land area per UA
                                  (verification of 2000/2010 values).
  2000_2010uadif.txt              2000->2010 UA code/name differences.
  urdef.txt                       1990 urban/rural definitions (Oct 1995).
  2020_Census_ua_list_all.xlsx, 2020_Census_ua_st_list_all.xlsx
                                  2020 urban areas, national and state-part
                                  lists (pop, housing, land/water area). USED.
  Gaz_ua.zip                      2010 gazetteer, UA/UC internal points.
                                  https://www2.census.gov/geo/docs/maps-data/data/gazetteer/Gaz_ua.zip
  2023_Gaz_ua_national.zip        gazetteer carrying the 2020-criteria urban
                                  areas' internal points (the "2020_Gazetteer"
                                  UA file still carries 2010 areas).
                                  https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_ua_national.zip

boundaries/   (cartographic boundary shapefiles, zipped as downloaded)
  ua99_d90_shp.zip (+ ua02_ AK, ua15_ HI, ua72_ PR)  1990 UAs
      https://www2.census.gov/geo/tiger/PREVGENZ/ua/  (geographic lon/lat with no .prj --
      treated as NAD83; a NAD27 datum shift is <0.1 km, immaterial here;
      the 50-state file has 837 polygons for 396 UAs; PR file has 17 polygons)
  ua99_d00_shp.zip   2000 UAs + UCs (LSAD 75 = UA, 76 = UC), 7.0 MB
      https://www2.census.gov/geo/tiger/PREVGENZ/ua/ua00shp/ua99_d00_shp.zip
  cb_2013_us_ua10_500k.zip   2010 UAs + UCs, 1:500k, 9.3 MB
      https://www2.census.gov/geo/tiger/GENZ2013/cb_2013_us_ua10_500k.zip
  cb_2020_us_ua20_corrected_500k.zip   2020 urban areas (corrected release),
      1:500k, 9.4 MB
      https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_ua20_corrected_500k.zip
  cb_2020_us_state_500k.zip   2020 state boundaries, used only to split UA
      polygons into state portions for the portion points.
      https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_state_500k.zip
  The full TIGER/Line UA files (tl_2010_us_uac10.zip etc.) were not needed; the
  generalized cb/PREVGENZ versions are enough for 13-km-scale distances.

stf1c_1990/   (1990 STF 1C national file, dBase, from
               https://www2.census.gov/census_1990/stf1c/)
  stf1c0us.dbf.zip   geographic header + table P1 (persons): SUMLEV 400 = UA,
                     410 = UA--State part; AREALAND = km^2 x 1000 (3 implied
                     decimals); INTPTLAT/INTPTLNG = internal point x 1e6. USED.
  unames.dbf.zip, stf1stru.dbf.zip, tables.dbf.zip   name/structure lookups.
  doc_sum_lev.asc, doc_usernote.asc   STF 1C summary-level documentation.

nhgis0002_csv/   (NHGIS extract, IPUMS NHGIS, University of Minnesota,
                  www.nhgis.org; CSV, no GIS files -- none exist for these levels)
  nhgis0002_ds95_1970_urb_area_038.csv   1970 Count 2 (1970_Cnt2), level
      "Urbanized Area (by State)" (038), table NT1 Sex by Race (CEB001-018).
      Each row is a state part; persons = sum of the 18 cells; a UA's total
      = sum of its parts. 286 parts of 248 UAs; no Puerto Rico rows.
  nhgis0002_ds104_1980_urb_area.csv      1980 STF 1 (1980_STF1), level
      "Urban Area" (400), table NT1A Persons (C7L001). 366 UAs.
  nhgis0002_ds104_1980_state_410.csv     same, level "State (by Urban Area)"
      (410): 422 state parts. LONGITUD/LATITUDE/LANDAREA are blank in both
      1980 files; no Puerto Rico rows.
  *_codebook.txt   NHGIS codebooks (variable definitions, citation).

published_tables/   (hand-transcribed from scanned Census volumes; no text
                     layer / unusable OCR, so values were read from page images
                     and checked against published totals)
  ua_1950_published.csv   rank, ua_name, population for all 157 1950 UAs.
      Source: Census of Population: 1950, Vol. I Number of Inhabitants,
      U.S. Summary, Table 18 "Rank of urbanized areas according to
      population: 1950", p. 1-29
      https://www2.census.gov/library/publications/decennial/1950/population-volume-1/vol-01-04.pdf
      (pdf page 28). Titles as printed (1950 titles often omit a second state,
      e.g. "Chicago, Ill." includes NW Indiana).
  ua_1960_published.csv   rank, ua_name, population for all 213 1960 UAs.
      Source: Census of Population: 1960, Vol. I Part 1 U.S. Summary, Table 23
      "Rank of urbanized areas according to population: 1960", p. 1-50
      https://www2.census.gov/library/publications/decennial/1960/population-volume-1/vol-01-01-f.pdf
      (pdf page 50).
  ua_state_parts_1950_1960.csv   state portions (1960 and 1950 columns) for 17
      multi-state UAs: every multi-state UA ranked in the 1960 top 31 plus
      Springfield-Chicopee-Holyoke, Wilmington, Trenton, Lawrence-Haverhill,
      Huntington-Ashland, Fall River, St. Joseph. Source = Table 10
      "Population of urbanized areas: 1960 and 1950" in the state parts of
      1960 Vol. I (page cited per row); the other state's part is derived as
      total minus published part(s) where only one part is printed.

-------------------------------------------------------------------------------
VERIFICATION (all exact unless stated)
  1950  sum of 157 transcribed UAs = 69,249,148 = Table 17 "Total (157 areas)"
        (the 1960 volume's revised 1950 figure is 69,252,234). One misread
        (Beaumont 94,109 -> 94,169) was caught by this check and fixed. Every
        1950 state-part pair sums to its 1950 UA total.
  1960  sum of 213 transcribed UAs = 95,848,487 = Table 22 "United States (1960,
        213 areas)". Ranks are monotone; 12 spot values cross-checked against
        Table 22 rows. Every state-part set sums to its UA total; published
        parts were checked against their printed county components.
  1970  248 UAs = the published 1970 count ("the 248 UAs delineated for the
        1970 Census", PC(S1)-108,
        https://www.census.gov/library/publications/1979/dec/pc-s1-108.html).
        Sum of parts = 118,446,566. NOT yet matched to a published national
        total (the 1970/1980 volumes are scans; not transcribed). Each state's
        UA sum is <= its urban population in ../urbanization/urpop0090.txt
        (UA share of urban 0.20-0.95). NY 16,206,841 (NY 11,369,576 + NJ
        4,837,265) / LA 8,351,266 / Chicago 6,714,578 (IL 6,185,156 + IN 529,422).
  1980  366 UAs; the 422 state parts sum exactly to the UA totals (both
        139,170,683). NOT yet matched to a published national total. Each
        state's UA sum is <= its urban population in urpop0090.txt (share
        0.37-0.96). NY 15,590,274 / LA 9,479,436 / Chicago 6,779,799.
  1990  sum over 396 UAs = 158,258,878 = STF 1C US "inside urbanized area"
        (GEOCOMP 02); parts sum to totals exactly.
  2000  50 states + DC sum = 192,323,824 = the Census Bureau's published
        2000 UA population (Urban Areas QuickFacts page); PR, Guam, Saipan
        carried separately. NY 17,799,861 / LA 11,789,487 / Chicago 8,307,904
        match PopAreaChngeUA.txt.
  2010  50 states + DC sum = 219,922,123 (published, QuickFacts); state sums
        equal PctUrbanRural_State.txt POP_UA for every state incl. PR.
        NY 18,351,295 / LA 12,150,996 / Chicago 8,608,208 match PopAreaChngeUA.
  2020  state-part sums over ALL 2,644 urban areas equal the published 2020
        state urban totals in ../urbanization/State_Urban_Rural_Pop_2020_2010.xlsx
        for every state (US 265,149,027). The 50k+ tier (510 areas) sums to
        240,473,430. NY--Jersey City--Newark 19,426,449; LA 12,237,376;
        Chicago 8,671,746.

-------------------------------------------------------------------------------
STILL MISSING
  1990 Puerto Rico UA populations (in the separate PR STF 1
  files), 1950/1960 land areas (printed in 1960 U.S. Summary Table 22,
  pdf pages 40-49 -- not transcribed), and the state splits of 15 small
  1960 multi-state UAs. Puerto Rico 1970/1980 (not in the extract), and
  1970/1980 land areas and official points (the extract has none; points
  fall back to the first-named city).
