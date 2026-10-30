# Historical Hex Congressional Districts

A hex-map cartogram of the U.S. House for **every Congress from the 1st (1789) to the
119th (2025)**. Each congressional district is drawn as a **pentahex** (five connected
hexagons), and each state is sized in proportion to its House delegation while keeping a
recognizable version of its real outline.

**Live viewer:** <https://grumm1728.github.io/historicalHexCDs/>

The style follows the [Downballot](https://www.the-downballot.com/) (formerly Donnermaps)
[hex district map](https://docs.google.com/spreadsheets/d/13XkF59JKzvw4SeSq5mbgIFrJfYjK4amg9JoQE5e9grQ/edit?gid=0#gid=0),
which covers only the modern Congress. This project generates maps in the same style for
all 119 Congresses from historical seat counts and state outlines.

## What the maps show

- **One pentahex per seat.** A 2-seat state has 10 hexes; a 52-seat state has 260.
- **State shapes follow real outlines.** Each state's outline is scaled to its seat-based
  area and placed at its position in the modern reference map, so the layout stays stable
  across Congresses and only changes when seat counts change.
- **Historical states.** Parent states include their not-yet-admitted children (early
  Virginia includes Kentucky and West Virginia; Massachusetts includes the District of
  Maine through 1820).
- **Urban / rural shading.** Districts belonging to nationally significant metros are
  labelled and colored by metro, using historical census places before 1950 and Census
  urbanized areas from 1950 on. Each metro keeps the same color in every Congress.

Districts are not geographically real: they show *how many* seats a state had, not where
the real district lines ran.

## Viewer

The viewer in `web/` is a static D3 page. Run it locally with any static server (not
`file://`):

```bash
python -m http.server 8000 --directory web
```

Then open <http://localhost:8000>. On Windows, `run_local_web.bat` or `run_local_web.ps1`
does the same.

Controls: step or play through Congresses, toggle districts, state silhouettes, auto-zoom,
and urban/rural shading. Open `index.html?dev` for the experimental Design panel (metro
cutoff tiers, colors, and other tuning).

## Building the data

Requirements: Python 3.13 with the packages in `requirements.txt` (shapely, pyproj,
pyshp, openpyxl). The GIF renderer also needs Pillow.

```bash
pip install -r requirements.txt
```

Full rebuild (pipeline plus staging into `web/data_processed/`):

```bash
python scripts/build_web_assets.py
```

This runs `build_all_historical.py`, which validates inputs, builds the seat table and
hex grid, tiles every Congress (`tile_state_pentahexes.py`), exports shapefiles, assigns
metro colors, and writes `data_processed/congress_index.json`. **A full run takes about
20–35 minutes.** A clean build ends with `warnings: 0` in
`data_processed/tiling_warnings.json`.

To re-run only the tiler, without staging to `web/`:

```bash
python scripts/tile_state_pentahexes.py
```

### Inputs

- `data_raw/seats/congress_exact_seats.csv`: House seats per state per Congress, exact to
  each Congress (admission-year apportionments included).
- Modern Natural Earth state outlines (Great Lakes water clipped out), used for every
  Congress.
- `data_raw/reference/hexcdv31_anchors.json`: state positions taken from the reference
  hex map in `hexmap_reference_files/HexCDv31wm/`.
- Census places and urbanized areas under `data_raw/` for the metro labels.

### Outputs (`data_processed/`)

| Path | Contents |
| --- | --- |
| `polyhex_cds_by_congress/<n>.geojson` | One feature per district, with metro labels |
| `polyhex_states_by_congress/<n>.geojson` | One feature per state |
| `state_outlines_by_congress/<n>.geojson` | Real and scaled state outlines |
| `shapefiles/<n>/` | Shapefile exports |
| `congress_index.json` | Index of Congresses, dates, and file paths |
| `metro_colors.json` | Fixed color index per metro |
| `tiling_warnings.json` | States that failed to tile (should be empty) |

Field definitions are in [docs/data_spec.md](docs/data_spec.md).

### Timeline GIF

```bash
python scripts/make_timeline_gif.py --mode both
```

Writes plain and urban/rural C1–C119 animations to `exports/` (not committed).

## Validation and tests

```bash
python scripts/validate_raw_inputs.py
python scripts/validate_outputs.py
python scripts/validate_metro_counts.py
python -m pytest tests
```

`validate_metro_counts.py` compares the metro district counts for C113–C119 against the
share of each state's population living in real metro districts, and fails if fewer than
90% of states are within ±1 seat in any Congress. See the
[report](docs/metro_validation_c113_c119.md) and its
[CSV](docs/metro_validation_c113_c119.csv).

The **Verify Tiling** workflow (`.github/workflows/verify-tiling.yml`) runs the full
pipeline on pull requests that touch `scripts/`, `data_raw/`, or `requirements.txt`, and
requires `warnings: 0`.

## How it works

The short version, in pipeline order:

1. **Layout.** Scale each state's outline to `seats × 5` hexes of area, place it at its
   reference-map position, align shared straight borders (36°30′, the 37th parallel, the
   Mexico and Canada lines), and push overlapping states apart.
2. **Allocation.** Grow exactly `seats × 5` connected hex cells per state, preferring cells
   inside the state's own outline over open space, and open space over a neighbour's
   outline.
3. **Partition.** Split each state's cells into connected 5-cell districts, then swap cells
   between neighbouring districts to make them more compact.
4. **Render.** Clip districts to the scaled outline and hand any leftover gaps to the
   nearest district, so each state's drawn shape matches its outline exactly.
5. **Metro labels.** Assign each metro's seats to the districts nearest its anchor cities.

[CLAUDE.md](CLAUDE.md) has the full design notes, constraints, and measured trade-offs.
More in `docs/`: [tiling quality audit](docs/audit_tiling_quality.md),
[metro assignment](docs/metro_joint_assignment.md), [performance](docs/perf.md), and the
research notes behind the urbanization data.

## Deployment

`.github/workflows/pages.yml` deploys `web/` to GitHub Pages
(Settings → Pages → Source: GitHub Actions).

## Legacy scripts

`bootstrap_from_118.py`, `build_timeline.py`, and `generate_polyhex_states.py` come from
the earlier template-based approach and are kept for reference;
`build_all_historical.py --legacy-template-generator` still runs the old generator.
`create_modern_outline_fallback.py` is still used: `build_web_assets.py` passes
`--allow-modern-outline-fallback`, which applies modern outlines to every Congress when
no historical boundary file is present.

## License

[![CC BY-SA 4.0](https://licensebuttons.net/l/by-sa/4.0/88x31.png)](https://creativecommons.org/licenses/by-sa/4.0/)

Licensed under
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/).

Hex map design by [The Downballot](https://www.the-downballot.com/), whose
[hex map](https://docs.google.com/spreadsheets/d/13XkF59JKzvw4SeSq5mbgIFrJfYjK4amg9JoQE5e9grQ/edit?gid=0#gid=0)
is also CC BY-SA 4.0.
