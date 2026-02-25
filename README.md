# Historical U.S. Polyhex Timeline

This project now uses a **state-level historical pipeline** as the canonical data path.

## Canonical pipeline (new)

Inputs:
- `data_raw/seats/congress_exact_seats.csv`
- `data_raw/nhgis/state_boundaries_by_congress.geojson`

Build:

```powershell
python scripts/build_all_historical.py
python scripts/build_web_assets.py
```

Validation:

```powershell
python scripts/validate_raw_inputs.py
python scripts/validate_outputs.py
```

## MVP fallback when historical outlines are unavailable

You can run in fallback mode using modern (Congress 118-derived) outlines across all Congresses:

```powershell
python scripts/create_modern_outline_fallback.py --from-congress 1 --to-congress 119
python scripts/build_all_historical.py --allow-modern-outline-fallback
```

`build_web_assets.py` already enables this fallback flag by default.

Important limitation: this is **not** historically accurate for state boundary changes; it is an MVP visualization fallback only.

## Current status

- Canonical output unit: state polyhex feature per state per Congress.
- Canonical files:
  - `data_processed/polyhex_states_by_congress/<congress>.geojson`
  - `data_processed/shapefiles/<congress>/HexState_<congress>.shp`
  - `data_processed/congress_index.json`
- Existing district-cell pipeline (`scripts/build_timeline.py`) is retained as legacy/bootstrap input support.

## Bootstrap from existing Congress 118 sample

If you only have the existing `HexCDv31`/legacy 118 output, generate starter raw inputs:

```powershell
python scripts/bootstrap_from_118.py
```

This creates minimal raw input files for Congress 118/119 only. It is useful for testing the pipeline wiring, not for full historical accuracy.

## Full historical data requirement

To generate valid outputs for all Congresses (1..current), provide full source data in the raw contracts above.
The seat table is enforced as congress-exact post-admission (no carry-forward approximation).

## Web app

Run locally with a server (not `file://`):

```powershell
python -m http.server 8000 --directory web
```

Open `http://localhost:8000`.

The app reads `web/data_processed/congress_index.json` and state-level feature paths from `state_feature_path`.

## GitHub Pages

Pages workflow is at `.github/workflows/pages.yml` and deploys `web/`.
Set `Settings -> Pages -> Source` to `GitHub Actions`.

## Data spec

See `docs/data_spec.md`.
