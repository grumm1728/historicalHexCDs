Place congress-exact seat file here:
- congress_exact_seats.csv

Required columns:
- congress_number,state_fips,state_abbr,state_name,house_seats,admitted,source_seat_version

Current source workflow:
- `python scripts/rebuild_seats_from_wikipedia.py`
- Source table: Wikipedia "United States congressional apportionment" -> "Past apportionments"
- This maps apportionment effective years to Congress windows.

Known caveat:
- Civil War-era unrepresented delegations are not yet modeled separately from apportioned seats.

See docs/data_spec.md for full contract.
