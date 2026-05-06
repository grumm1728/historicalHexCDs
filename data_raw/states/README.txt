State-level metadata and modern outline datasets:

- state_metadata.csv
  - 50-state admission metadata keyed by FIPS/abbr/state name
  - Includes admission order, parsed ISO admission date, and source provenance

- state_outlines_modern.geojson
  - 50 modern MVP state outlines used for current scaling workflow
  - These are fallback cartogram/state-shape outlines, not true historical boundary snapshots

Generation scripts:

- python scripts/rebuild_state_metadata.py
- python scripts/build_modern_state_outlines_dataset.py

