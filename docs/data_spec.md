# Historical Data Specification

Canonical state key strategy:
- Primary key: `state_fips` (2-char string)
- Secondary key: `state_abbr` (2-char USPS)

Canonical output fields (state-level polyhex per Congress):
- `congress_number` (int)
- `start_date` (YYYY-MM-DD)
- `end_date` (YYYY-MM-DD)
- `state_fips` (string)
- `state_abbr` (string)
- `state_name` (string)
- `house_seats` (int)
- `admitted` (bool)
- `cell_count` (int, must equal `house_seats` when admitted)
- `source_boundary_id` (string)
- `source_seat_version` (string)
- `generator_version` (string)
- `geometry` (GeoJSON Polygon/MultiPolygon; polyhex state unit)

Raw input contracts:

1) Seats input
- Path: `data_raw/seats/congress_exact_seats.csv`
- Required columns:
  - `congress_number`
  - `state_fips`
  - `state_abbr`
  - `state_name`
  - `house_seats`
  - `admitted`
  - `source_seat_version`
- This table is authoritative at Congress granularity.

2) Boundary input (NHGIS-normalized)
- Path: `data_raw/nhgis/state_boundaries_by_congress.geojson`
- FeatureCollection where each feature has properties:
  - either `congress_number` OR (`from_congress` and `to_congress`)
  - `state_fips`, `state_abbr`, `state_name`
  - `source_boundary_id`
- Geometry is a state boundary outline for the applicable Congress window.

Processed outputs:
- `data_processed/seats/state_seats_by_congress.csv`
- `data_processed/seats/state_seats_index.json`
- `data_processed/boundaries/by_congress/<congress>.geojson`
- `data_processed/boundaries/states_by_congress_index.json`
- `data_processed/polyhex_states_by_congress/<congress>.geojson`
- `data_processed/polyhex_cds_by_congress/<congress>.geojson` (v5 pentahex tiler, one feature per CD)
- `data_processed/state_outlines_by_congress/<congress>.geojson`
- `data_processed/hex_grid/hex_grid.geojson`, `hex_grid_meta.json` (v5 national grid)
- `data_processed/states/state_outlines_modern_wm.geojson` (real Natural Earth outlines in EPSG:3857, used by v5)
- `data_processed/shapefiles/<congress>/HexState_<congress>.shp`
- `data_processed/congress_index.json`
- `data_processed/tiling_warnings.json` (v5 tiler partial/fallback rows)

v5 per-CD feature properties (`polyhex_cds_by_congress/<n>.geojson`):
- `congress_number`, `start_date`, `end_date`
- `state_fips`, `state_abbr`, `state_name`, `house_seats`
- `cd_index` (1..house_seats, stable ordering; NOT the historical district number)
- `hex_count` (5 for full pentahex; can be < 5 for unfilled boundary tiles)
- `is_boundary_tile` (true if any of the tile's hexes touches the state perimeter)
- `tile_area_ratio` (rendered_area / (5 * hex_area))
- `generator_version` (`v5-pentahex-tiling`)

v5 state-level feature additions (`polyhex_states_by_congress/<n>.geojson`):
- `cells_used` (total hex cells assigned to this state)
- `tiling_status` ∈ `{ok, partial, fallback-silhouette}`
