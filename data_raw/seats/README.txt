Place congress-exact seat file here:
- congress_exact_seats.csv
- state_seats_by_apportionment.csv

Required columns:
- congress_number,state_fips,state_abbr,state_name,house_seats,admitted,source_seat_version
- apportionment_label,effective_year,state_fips,state_abbr,state_name,house_seats,admitted,source_seat_version

Current source workflow:
- `python scripts/rebuild_seats_from_wikipedia.py`
- Source table: Wikipedia "United States congressional apportionment" -> "Past apportionments"
- This maps apportionment effective years to Congress windows.
- It writes:
  - `congress_exact_seats.csv` (state x congress_number)
  - `state_seats_by_apportionment.csv` (state x effective_year)

Known caveat:
- Civil War-era unrepresented delegations are not yet modeled separately from apportioned seats.

See docs/data_spec.md for full contract.
