# CLAUDE.md

## At the start of each session

Run `gh issue list` to check open issues for current bugs and ideas before starting work.

## What this project is

Historical **hex congressional-district maps** ("HexCDs"). A cartogram covering all
119 U.S. Congresses where each congressional district is drawn as a **pentahex**
(exactly 5 hexagons), each state is scaled so its area ∝ its House delegation, and
the styling targets the `hexmap_reference_files/HexCDv31wm/` reference. Output is
GeoJSON consumed by a static viewer in `web/`.

## The source idea: HexCDv31wm

`hexmap_reference_files/HexCDv31wm/` is the reference shapefile that this project
replicates and extends historically. HexCDv31wm is a manually-authored hex-CD cartogram
for the modern Congress: each state is a compact blob of hexagons, each CD is a
pentahex (5 contiguous hexes), states are sized proportionally to their House delegation,
and the overall arrangement is recognizably a US map but sacrifices geographic precision
for equal-area-per-seat legibility.

Key properties we preserve from the reference:
- **Pentahex = exactly 5 hexes per CD, always connected.** No exceptions.
- **State area ∝ House delegation.** A 2-seat state gets 10 hexes; a 52-seat state gets 260.
- **Outline-snapped borders.** Each state's visible edge follows its scaled geographic
  silhouette, not raw hex edges — this is the "HexCDv31wm look" (see option-3 snap below).

The reference covers only the modern (118th) Congress. This project generates the same
style for all 119 Congresses from seat data + historic state outlines.

## Scaling state outlines

The core cartographic idea (and the hardest part to get right):

Each state's **real geographic outline** is scaled uniformly so its area equals
`seats × 5 × hex_area` around the state's real centroid. This gives each state a
"budget footprint" — scaled outlines are the allocation guide, not the final geometry.

**Why scaling works:** A scaled outline contains approximately the right number of hex-grid
cells inside it (since one cell ≈ one hex of the target area). The allocator then uses the
scaled outline as a magnet, growing exactly `seats×5` connected cells per state with
strong preference for cells inside the state's own outline. The result is a near-perfect
match between the outline's shape and the allocated cell territory.

**What scaling can't fix:** Scaling is isotropic (same factor in all directions), so it
preserves the real outline's shape. Elongated states (MD, NY panhandle) stay elongated;
peninsulas (Cape Cod, Long Island) remain and the allocator may not fill them. The residual
gap between the scaled outline and the cell territory is handled by the option-3 snap (see below).

**Overlap resolution:** After scaling, small dense states inflate into neighbours. A
worst-pair iterative resolver pushes overlapping pairs apart along their centroid vector
until the layout is non-overlapping (`target_gap = 0.5R`). This is purely a placement
nudge — the outline shapes don't change, only their positions.

## The pentahex partition algorithm

`partition_into_pentahexes()` in `tile_state_pentahexes.py` is the combinatorial core
and is self-contained enough to be extracted as a standalone library.

**What it does:** Given a connected set of hex cells whose size is a multiple of 5,
partitions them into connected groups of exactly 5 (pentahexes). Each pentahex becomes
one congressional district.

**Algorithm:** Greedy region-grow, seeded from boundary cells (highest external degree
first — cells that "stick out" are hardest to tile later and should be fixed early).
At each step, grows the current pentahex toward the lowest-degree neighbor to avoid
stranding cells. After each tile is placed, calls `is_partition_feasible()` to verify the
remaining cells can still be fully tiled (each connected component must be a multiple of 5);
backtracks the seed choice if not.

**Compactness tiebreak + fallback (`use_compact`):** Among equal-lowest-degree candidates,
`grow_one` prefers the cell touching the most current-tile cells, so pentahexes round into
blobs instead of long sticks (fixes the elongated interior districts like PA-34). This
tiebreak can occasionally dead-end the greedy heuristic on a *tileable* shape, so the caller
in `place_pentahex_tiles` retries `partition_into_pentahexes(..., use_compact=False)` — the
original anti-stranding-only growth — whenever the compact pass fails to fully tile a state.
The fallback is byte-for-byte the proven heuristic, so the `warnings: 0` invariant holds.
A separate interior-only swap pass (`refine_tiles_compactness`) then trades cells between
adjacent tiles to reduce sticks further; it never moves a *territory-edge* cell, so the
state's clipped silhouette (and thus the option-3 snap) is unchanged and no slivers appear.

**Limitations:** The greedy heuristic can reach dead ends on pathological shapes (long
tendrils, narrow necks). For this project those are handled upstream by the allocator's
shape-guidance rather than by backtracking in the partitioner. If extracting this as a
library, a full backtracking fallback would be needed for arbitrary inputs.

**Interface (for extraction):**
```python
tiles = partition_into_pentahexes(
    cells: set[tuple[int,int]],      # axial (q,r) coords of allocated hex cells
    boundary_cells: set[tuple[int,int]],  # subset that touch the territory edge
) -> list[list[tuple[int,int]]]      # list of 5-cell tiles; [] on failure
```

## The edge problem: state outline edges vs hex edges

This is the subtlest design tension in the project. Understanding it is essential before
touching `render_state_tiles` or the allocator.

**Root cause:** Hex cells are allocated by center-in-polygon. A cell is in state X if its
center falls inside X's scaled outline. This means a row of cells along a straight outline
edge (e.g. the 42°N CA–OR line, the Mason–Dixon line for MD) is either *entirely included*
or *entirely excluded*, depending on whether the cell centers land just inside or just outside
the line. Because the hex grid is fixed and the outline position shifts with scale/displacement,
this is essentially a matter of luck per Congress.

**Two failure modes:**
- **Overshoot:** Hex cells extend beyond the outline → the clipping step trims them flush.
  This is fine and produces the clean straight edge.
- **Undershoot:** The nearest hex row's centers fall just outside the outline → those cells
  aren't allocated, leaving a gap between the top of the hex territory and the outline.
  Clipping can't fill this (intersection only trims, never extends).

**The option-3 snap (render_state_tiles):**
After clipping, the residual `outline − union(tiles)` is computed and redistributed:
- Small slivers → merged into the best-adjacent tile (by buffer-overlap area).
- Larger components (a whole straight-edge strip) → split by a Voronoi of adjacent tiles'
  boundary seeds, so the strip is distributed across all facing tiles rather than dumped
  on one.

This guarantees `state_union == outline` exactly, at the cost of some tiles having
`tile_area_ratio > 1.0`. Most boundary tiles land at 0.7–1.2; geographic outliers
(Long Island tip, Cape Cod) can reach ~2.8×. That's the correct behaviour — a tile that
covers a narrow peninsula genuinely covers more real area than five interior hexes.

**The allocator's anti-steal rule:** A secondary edge problem is that small states
allocated early (smallest-need-first ordering) can grow through a big neighbour's outline
because the growth heuristic treated "inside another state's outline" the same as "free
ocean". Fixed with a 3-tier preference: own-outline (tier 0) > free/ocean (tier 1) >
another state's outline (tier 2, last resort). This improved PA's outline coverage from
82% → 91% and reduced residual-gap size across the board.

**The anti-steal / tileability tradeoff:** The anti-steal rule can force a small coastal
state onto fragmented cells that are genuinely un-tileable (MD across the Chesapeake, MA
in early Congresses). Handled by a **self-correcting meta-loop** in `place_pentahex_tiles`:
failing states are added to `steal_exempt` and the whole allocation is redone with theft
allowed for them. Converges within a few passes; worst case = the original theft-allowed
allocation with 0 warnings.

## Great Lakes clip & multi-component states (Michigan)

**The problem:** Cells are allocated center-in-polygon against each state's outline. A
state whose administrative outline runs out over open lake water (Michigan, whose outline
spans Lakes Michigan/Huron/Superior between the Upper and Lower Peninsulas) would fill the
lakes with hexes — districts floating in open water.

**The fix (two parts):**
1. **`fetch_modern_state_outlines.py` land-clips the outline.** It downloads Natural Earth
   `ne_10m_lakes`, unions the named Great Lakes, and subtracts them from each state in
   `GREAT_LAKES_CLIP_ABBRS` (today just `MI`), dropping tiny islands (`clip_to_land`,
   `min_part_frac`). Michigan becomes a 2-part MultiPolygon (UP + LP). Only the pipeline
   outputs (`*_modern.geojson` deg + `*_modern_wm.geojson`) are clipped; the raw NE export
   (`state_outlines_natural_earth.geojson`) stays the full admin outline. Provenance is
   tagged `natural-earth-10m-lakeclip-*`.
2. **`allocate_territories` allocates split land as components.** For FIPS in
   `MULTI_COMPONENT_FIPS` (today `{"26"}`), a state's own-outline cells are split into
   connected components; `_split_targets_multiple_of_5` gives each component a multiple-of-5
   share of `need` proportional to its size, and each is seeded + grown independently
   (`grow_region`). **No bridge or partition change is needed:** because the components are
   never hex-adjacent, `partition_into_pentahexes` (which only grows through adjacent cells,
   and whose feasibility check already requires each component to be a multiple of 5) tiles
   each peninsula cleanly and no pentahex straddles the water gap.

**Gotchas:**
- The branch is **gated to `MULTI_COMPONENT_FIPS`** so it never perturbs island states
  (NY/MA/HI/AK/...) that already tile fine as one blob. Re-sweep all 119 Congresses before
  adding a FIPS here.
- When MI's delegation is small, the scaled outline shrinks the UP/LP gap below one hex
  width: the two parts' cells become adjacent and MI allocates as a single connected blob
  (still land-only — no lake fill). When the gap stays open, the multi-component path gives
  each peninsula its own whole number of pentahexes. Both outcomes are warning-free.

## Historical composite outlines (parent absorbs not-yet-seated children)

**The problem:** The pipeline uses **modern** outlines for all 119 Congresses, so a parent
state is drawn at its modern extent even before its children separated — early Virginia
appears without Kentucky/West Virginia, Massachusetts without Maine, etc.

**The fix:** `build_effective_outlines(outlines, seated_fips)` builds a per-Congress outline
view in which each parent's geometry is `unary_union(parent + every not-yet-seated child)`.
`main()` calls it right after `seat_by_fips` is built and uses the result (`eff_outlines`)
for `compute_scaled_layout`, the centroid/anchor fallback, and per-state rendering/clipping.
It overrides only affected parents and never mutates the module-level `outlines` cache.

**Lineage is curated, timing is data-driven.** `PREDECESSOR_PARENT` (child FIPS → parent
FIPS) is the one hand-maintained piece — `formed_from` metadata routes through territories,
not parent states, so it can't be auto-derived. The **cutover Congress is NOT hardcoded**: a
child detaches the first Congress it has `house_seats > 0` (i.e. appears in `seat_by_fips`).
Per the corrected seat table that yields KY→C2, TN→C4, MS→C15, AL→C16, WV→C38 (admission-
year apportionments, fixed in `data_raw/seats/congress_exact_seats.csv`).

**Maine is the exception — it is NOT in `PREDECESSOR_PARENT`.** Maine is the one child
geographically *separated* from its parent (New Hampshire lies between Maine and
Massachusetts), so unioning it into MA's outline made the allocator seed/size the Maine lobe
arbitrarily. Instead `main()` uses `MAINE_IN_MA` (per-Congress `(maine_total_districts,
me_labeled_districts)`): it splits MA's delegation into MA-proper (allocated in MA's outline)
and a Maine block (allocated in Maine's *own* modern outline, sized to the historical Maine
district count), then **relabels** the Maine tiles back to Massachusetts at render time
(Maine was not yet a state). C16 is the admission-year wrinkle — 7 Maine-territory seats were
still MA plus Maine's 1 at-large (8 tiles: 7→MA, 1 kept ME); the full 7-seat reassignment to
Maine lands in C17, where Maine becomes an ordinary `seat_by_fips` state. This sizes the Maine
lobe correctly with no allocator/partition changes — only seat injection + a render relabel.

**Area is unchanged.** The union supplies only *shape* — each state is still scaled to its
own `seats×5×hex_area`, so an early composite parent is a larger-silhouette but
seat-correctly-sized blob. As with any layout change, a bigger early VA/MA/GA silhouette can
crowd a neighbour, so re-sweep all 119 Congresses for `warnings: 0` after touching this.

## NE de-jam and the density/geography tradeoff

**The problem:** The Northeast (NY/PA/NJ/CT/RI/MA/NH/VT/MD/DE/ME/DC) contains ~85 seats
in a small real area. After scaling, these states inflate into large outlines that jam
together. The overlap resolver only pushes pairs apart — it never pulls distant states
together — so the NE stays crowded while the sparse West floats with large gaps.

**What we tried and why it didn't work:** A global tilegram-style warp (force-directed,
Dorling-style, shrink-toward-center) that closes western gaps while preserving order.
Result: any setting that materially closes western gaps produces a roundish blob that
loses the US silhouette (fill ~35%). The gap isn't a layout bug — it's structural: those
states have few seats, so in an equal-area-per-seat cartogram that region is genuinely
sparse. Density and geographic fidelity are a hard tradeoff. We chose geographic fidelity.

**What we did:** Targeted local expansion of just the NE cluster's anchors, radially
outward from the seat-weighted NE centroid, before overlap resolution. This gives the
cluster internal breathing room without distorting the rest of the map. The overlap
resolver absorbs the push where the cluster meets its inland neighbours.

**`NE_EXPAND = 1.25`** is the constant. Hard ceiling: 1.3 reshapes early Massachusetts
(14 seats, C3–C7) into a genuinely un-tileable elongated shape → warnings. Always
re-sweep all 119 Congresses (`_measure_after_fix`-style status sweep) before raising it.
The CLAUDE.md invariant is: **a clean regen ends with `warnings: 0`**.

**Future:** The right solution for a truly gap-free national cartogram is a purpose-built
balanced hex-region partition (Gastner–Newman diffusion or a custom hex-lattice allocation
that assigns states to contiguous lattice regions sized to delegation). This would
reproduce the HexCDv31wm reference exactly but requires building a different algorithmic
foundation. The current approach (scaled outlines + displacement) is a good approximation
that preserves geographic intuition.

## Pipeline (how a full rebuild runs)

`scripts/build_web_assets.py` is the top entry point:

1. `build_all_historical.py --allow-modern-outline-fallback` (default `--max-congress 119`):
   - `validate_raw_inputs.py` → `build_seat_table.py` → `build_boundary_timeline.py`
   - `build_hex_grid.py --R 35000 --ymin 2500000`
   - **`tile_state_pentahexes.py`** ← the core generator (see below)
   - `export_shapefiles.py` (writes `data_processed/shapefiles/<n>/`)
   - writes `data_processed/congress_index.json` (`render_mode: "clipped_polyhex_only"`)
2. Stages a full copy of `data_processed/` → `web/data_processed/` (rmtree + copytree).

Regenerate just the tiling (fast, no web staging): `python scripts/tile_state_pentahexes.py`.
Local preview: `python -m http.server 8000 --directory web`.

## Core generator: scripts/tile_state_pentahexes.py

Per Congress it writes `polyhex_cds_by_congress/<n>.geojson` (one Feature per CD),
`polyhex_states_by_congress/<n>.geojson` (state dissolve),
`state_outlines_by_congress/<n>.geojson` (real + scaled outlines), plus
`polyhex_states_by_congress/_index.json` and `tiling_warnings.json`.

Constants: `R = 35000` m, `hex_area = 1.5·√3·R²`, each CD = 5 hexes, `need = seats·5`
cells, `GENERATOR_VERSION = "v6-pentahex-scaled-outlines"`.

Algorithm (in order):

1. **`compute_scaled_layout`** — scale each state's real outline to `seats·5·hex_area`
   around its real centroid; apply the **NE de-jam** (radially expand the `NE_FIPS`
   cluster by `NE_EXPAND` from the seat-weighted NE centroid); then iterative
   pairwise overlap-resolution to a non-overlapping layout (`target_gap = 0.5R`).
2. **`expand_grid_if_needed`** — grow the hex grid in-memory to cover the layout bbox.
3. **`build_cell_outline_map`** — cell → state FIPS by point-in-polygon vs scaled outlines.
4. **`allocate_territories`** — grow exactly `need` cells/state from seeds, smallest-need
   first, with a **3-tier anti-steal** preference: own outline (0) > unclaimed/ocean (1) >
   *another state's outline (2, last resort)*. Tier 2 stops small early-allocated
   neighbours from cannibalising a big state's border cells. `steal_exempt` states skip
   tier 2.
5. **`place_pentahex_tiles`** — allocate, then partition each state into pentahexes. A
   **self-correcting meta-loop**: any state that got its full cells but can't be tiled is
   added to `steal_exempt` and the whole thing re-allocated (theft-allowed growth yields a
   compact, tileable blob). Converges; worst case = original theft-allowed allocation.
6. **`partition_into_pentahexes`** — greedy region-grow into connected groups of 5.
7. **`render_state_tiles`** (the "option-3" snap) — boundary tiles are clipped to the
   scaled outline (`render_tile(clip_geom=...)`); the leftover gap (outline − union of
   tiles) is redistributed so the **state union equals the outline**: tiny slivers merge
   into the best-adjacent tile, larger components split across adjacent tiles by nearest
   tile (`_nearest_tile_split`, a Voronoi of adjacent tiles' boundary seeds).

## Invariants & gotchas

- **A clean regen ends with `warnings: 0`** (`data_processed/tiling_warnings.json`).
  A warning = a state with `tiling_status` `partial`/`no-tiles` (couldn't reach `need`
  cells, or its cell set won't tile into pentahexes).
- **`NE_EXPAND` is capped at 1.25.** 1.3 reshapes early Massachusetts (14 seats) into a
  genuinely un-tileable shape → warnings. Re-sweep all 119 Congresses before raising it.
- **Layout changes are fragile.** Any change to anchors/scaling/expansion can push some
  state into an un-tileable or boxed-in shape in *some* Congress; always re-check the full
  119-Congress warning count, not just one Congress.
- **Area ratio outliers are expected.** `tile_area_ratio ≈ 1.0` for interior tiles and
  most boundary tiles after option-3. Geographic outliers (Long Island tip, Cape Cod)
  reach ~2.8×. This is correct — do not treat >1.0 ratios as bugs.
- CD properties include `is_boundary_tile` and `tile_area_ratio` (≈1.0 after option-3;
  a few geographic outliers like the Long Island tip reach ~2.7×).
- **`write_geojson_with_retry`** exists because Windows intermittently throws
  `OSError 22 (EINVAL)` when the tiler writes 357 files in a tight loop (AV/indexer race).
  It writes a temp sibling + `os.replace` + escalating retry (12 attempts). Don't replace
  with a plain `write_text`.

## Environment

- Python 3.13, shapely 2.1.x. Windows + PowerShell.
- The long-running `python -m http.server ... --directory web` you may see is the local
  preview, not a build — it's expected to stay running.

## Key paths

- `scripts/` — pipeline; `tile_state_pentahexes.py` is the one to know.
- `data_processed/` — generated GeoJSON/shapefiles (source of truth); copied into `web/`.
- `data_raw/`, `hexmap_reference_files/HexCDv31wm/` — inputs / style reference.
- `web/` — static viewer; `web/data_processed/` is the staged copy.
