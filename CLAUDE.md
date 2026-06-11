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

## Temporal stability, split pop-off, and gentle compaction

The layout is no longer computed independently per Congress. `compute_scaled_layout`
takes two inputs that tie the timeline together (both threaded from `main()`):

**1. Temporal seeding (`seed_centroids`).** `main()` keeps a persistent `prev_centroids`
dict (FIPS → resolved centroid) and passes each Congress the previous Congress's resolved
positions. A scaled state starts at its carried position, so the overlap resolver only
nudges it incrementally — most consecutive Congresses have **zero** state movement, and the
only real motion happens at decennial reapportionments (seat counts change → scales change →
the resolver re-packs). This is the intended "gradual growth, no congress-to-congress jumps."
`prev_centroids` is *merged* (never reset) so a state that briefly drops out keeps its place
on return.

**Identical-input fast path (makes "nothing changed ⇒ nothing moves" exact).** Re-seeding a
carried equilibrium is only *approximately* a fixed point: the polygon overlap resolver
re-runs from the circle equilibrium every Congress and lands sub-hex differently, so before
this fast path 90 of 118 transitions had byte-identical seat tables but only 1 rendered
frozen (Maryland, squeezed between PA/VA/DE, wobbled >1R in many quiet transitions). Now
`main()` computes a per-Congress signature (post-Maine-adjustment seat table +
`MAINE_IN_MA` entry); when it matches the previous Congress's, the previous
layout/tiles/statuses are reused verbatim and only rendering (deterministic on identical
inputs) re-runs for correct dates/metadata. This freezes all seat-identical transitions
exactly — including C118→C119, which previously echoed an escalation with a mean 6.4R /
max 19R move despite zero seat changes — and skips the dominant layout/allocation cost for
~90 of 119 Congresses. The fast path is gated on the previous Congress having tiled fully
`ok`, so a failing Congress is never frozen in (recomputation keeps its self-healing chance).

**Home-retention escalation (keeps `warnings: 0` with minimal disruption).** Carrying a
cramped arrangement forward can, over many Congresses, drift a *growing* state into a
boxed-in packing that won't tile (observed: NY C53–57, MI C83–87 — both `partial`, the
allocator couldn't reach `need` cells). A *global* home-retention pull was rejected: it makes
the home-pull and overlap-push reach a limit cycle that never settles, so every Congress
jitters (~5R) even in stable periods. Instead `main()` uses **pure carry by default** (a
stationary state has *zero* drift) and only when a Congress fails does it retry with carried
seeds pulled progressively toward each state's fixed compacted home along `RETENTION_LADDER`
(0.15…1.0), adopting the **smallest pull that reduces warnings** (1.0 == full fresh
placement). A state's home is seat-independent, so the pull always moves toward the
deterministic, known-tileable fresh layout. This localizes motion to the few failing
Congresses and uses the minimum nudge: e.g. C52→C53 (NY peak, 1893) settles with a small
retention (~6R reflow that self-heals within two Congresses) rather than a 26–39R whole-map
snap. Net result: ~90 of 118 transitions are perfectly stable; the rest are reapportionment
growth. Mirrors the self-correcting spirit of the `steal_exempt` meta-loop; never adopted
when worse.

**2. Split pop-off.** A child state's first seated Congress has no carried position, so it
is seeded adjacent to its parent's *current drawn* position, offset by the real centroid gap
(`parent_prev_centroid + (child_real_centroid − parent_real_centroid)`). KY/WV emerge on
VA's flank, TN off NC, AL/MS off GA — each "pops off" the parent instead of teleporting to
its own raw centroid. Lineage reuses `PREDECESSOR_PARENT`. (Maine needs no special seed: it
is allocated in its own outline throughout the `MAINE_IN_MA` era, so its position is already
carried in `prev_centroids` before it becomes an ordinary state.)

**3. Gentle compaction (`COMPACTION`, replaces the old `NE_EXPAND`).** A state's
*first-appearance* "home" is its real centroid pulled `COMPACTION` of the way toward a fixed
national center (`compaction_center`, computed once in `main()` from the union of all modern
outlines incl. AK/HI insets). **Why this works and isn't a no-op:** the web viewer fits one
projection to the largest (C119) frame and reuses it for every Congress, so pulling toward a
*fixed* center translates sparse/early clusters toward frame-center — using the empty western
space to give the early eastern states a more central, legible footprint — while being
~invisible for the full modern map (a uniform scale-about-center that `fitSize` re-normalizes).
Because compaction sets only the *home* (not carried positions, so it never compounds) and the
overlap resolver still restores `target_gap = 0.5R`, the dense core is not re-jammed: the net
effect is closing western gaps, not shrinking the east. `COMPACTION = 1.0` disables it.
Since the viewer gained per-Congress **auto-zoom** (an animated camera transform fitted to
each Congress's footprint, default on in `web/app.js`), early-era legibility no longer
depends on compaction alone — don't strengthen `COMPACTION` to fix framing; that's the
camera's job now.

**The "condensed West" is cartogram-correct — measured, do not "fix" it.** Normalized to
each map's own CONUS bbox, our C119 matches the hand-authored HexCDv31wm reference almost
exactly (West centroid x-spread 24.0% vs 23.2%; E–W gap 52% vs 58%). The historical era's
tighter West (11–13% in C53–C68) reflects its genuinely small delegations (~25 seats in
1893 vs ~100 today); the apparent "empty western band" under the old fixed viewport was a
framing artifact that auto-zoom resolves.

**4. Directional adjacency springs (`build_adjacency` + the circle-model phase).** Scaling +
overlap-resolution alone only *repels*; it never preserves which states border which, so a
small state could float away from its neighbour (Delaware drifting off Maryland) or a
non-neighbour could wedge between two states that really touch (Missouri between KY/TN). Fix:
a real-geography adjacency graph (one edge per pair of outlines sharing a border, carrying the
unit direction between their real centroids) drives a fast **vectorized circle model** inside
`compute_scaled_layout` *before* the polygon overlap resolver. Each adjacent pair is sprung
toward separation `r_a+r_b+gap` (radii = `sqrt(area/π)`) **in its real relative direction**,
non-adjacent pairs only repel, and both forces are silent inside a **deadband** (`SPRING_DEADBAND`).
The deadband is load-bearing: it makes the converged configuration a true *fixed point*, so
re-seeding it next Congress produces zero movement — the circle equilibrium centroids
(`seed_centroid`) are what `main()` carries forward, preserving temporal stability, while the
polygon resolver still runs on the geometry for exact non-overlap. This gives "big state grows →
its springs lengthen → neighbours pushed out but kept in their real direction" for free (no
per-state rules), and keeps the neighbour graph intact (DE nestles in MD's corner abutting
MD/NJ/PA; KY–TN touch so MO can't sit between). **Adjacency-first**: springs are strong, but a
many-neighbour hub they over-constrain into an un-tileable shape (IL C63–72) is recovered by the
escalation ladder weakening/zeroing the springs for that Congress only.

**Failure recovery is a 2-D ladder (`ESCALATION_LADDER`).** A Congress that fails to tile is
retried down `((retention, spring_scale), …)`, adopting the first rung that reduces warnings:
`retention` pulls carried seeds toward home (fixes temporal-drift box-ins: NY C53–57, MI
C83–87); `spring_scale` weakens the adjacency springs (fixes hub over-constraint: IL). The
ladder ends at `(1.0, 0.0)` = fresh placement with no springs = the proven warning-free
baseline, so recovery is guaranteed and localized to the few failing Congresses.

**Invariant unchanged: a clean regen ends with `warnings: 0`.** Layout is still fragile —
any change to seeding/compaction/scaling/springs can box a state into an un-tileable shape in
*some* Congress, so always re-sweep all 119 and watch the large-state and many-neighbour
outliers (NY at peak ~C73, IL, PA, OH, CA/TX) first.

**Future (deferred option 1):** a purpose-built balanced hex-region partition
(Gastner–Newman diffusion or a custom hex-lattice allocation assigning states to contiguous
lattice regions sized to delegation) would reproduce the HexCDv31wm reference exactly and
truly close all gaps, but requires a different algorithmic foundation. The current approach
(scaled outlines + temporal seeding + gentle compaction + displacement) preserves geographic
intuition and temporal continuity as a strong approximation.

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
   around its real centroid; place it at its **carried position** (previous Congress's
   resolved centroid via `seed_centroids`), or for a first appearance at its **compacted
   home** (real centroid pulled `COMPACTION` toward the fixed `compaction_center`, with
   split children seeded off their parent); run the **directional adjacency-spring circle
   model** (`build_adjacency` edges + repulsion, deadband → idempotent `seed_centroid`); then
   iterative pairwise overlap-resolution to a non-overlapping layout (`target_gap = 0.5R`).
   See "Temporal stability / adjacency springs" section above.
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
- **`COMPACTION = 0.9` (lower = stronger pull toward `compaction_center`).** Replaces the
  old `NE_EXPAND` radial hack. Too-strong compaction re-jams the dense east into un-tileable
  shapes; re-sweep all 119 Congresses before lowering it. `1.0` disables compaction.
- **Layout changes are fragile.** Any change to seeding/compaction/scaling can push some
  state into an un-tileable or boxed-in shape in *some* Congress; always re-check the full
  119-Congress warning count, not just one Congress. Because layout is now temporally seeded
  (each Congress depends on the previous), always sweep from C1 in order.
- **Area ratio outliers are expected.** `tile_area_ratio ≈ 1.0` for interior tiles and
  most boundary tiles after option-3. Geographic outliers (Long Island tip, Cape Cod)
  reach ~2.8×. This is correct — do not treat >1.0 ratios as bugs.
- CD properties include `is_boundary_tile` and `tile_area_ratio` (≈1.0 after option-3;
  a few geographic outliers like the Long Island tip reach ~2.7×).
- **Sliver tiles (`tile_area_ratio < 0.4`) are a pre-existing option-3 artifact, not a
  regression.** A clean baseline already has ~9 in C68 (min ~0.02) — boundary tiles whose
  hexes mostly fall in clipped-away overshoot. Before treating slivers as a bug introduced by
  a change, compare counts against a `git stash` baseline; small per-Congress deltas are noise.
- **`write_geojson_with_retry`** exists because Windows intermittently throws
  `OSError 22 (EINVAL)` when the tiler writes 357 files in a tight loop (AV/indexer race).
  It writes a temp sibling + `os.replace` + escalating retry (12 attempts). Don't replace
  with a plain `write_text`.

## Iterating on the tiler (run time & fast loop)

- **A full regen is ~20–35 min**, dominated by `compute_scaled_layout` (~10s per late
  Congress — the overlap resolver, *not* the tiling). Don't assume a long-running tiler has
  hung; the "fast regen" note above is relative to the full web build, not wall-clock-short.
- **Long runs exceed the agent's ~10-min foreground command cap**, so run the tiler
  **detached** (PowerShell `Start-Process python -ArgumentList 'scripts/tile_state_pentahexes.py'
  -RedirectStandardOutput tiler_run.log -PassThru`) and watch completion by polling
  `data_processed/tiling_warnings.json`'s mtime **> the run's start time** (a stale-file age
  check both false-triggers and misses the finish). Final line of the log = `… warnings: 0`.
- **Iterate in-memory before paying for a full run:** import the module and call
  `compute_scaled_layout` / `place_pentahex_tiles` / `render_state_tiles` for a handful of
  representative Congresses (e.g. C1, C8, C13, C16, C68, C119) to check statuses and geometry.
  Early Congresses are fast. Use `git stash` to A/B against the committed baseline.

## Environment

- Python 3.13, shapely 2.1.x. Windows + PowerShell.
- The long-running `python -m http.server ... --directory web` you may see is the local
  preview, not a build — it's expected to stay running.

## Key paths

- `scripts/` — pipeline; `tile_state_pentahexes.py` is the one to know.
- `data_processed/` — generated GeoJSON/shapefiles (source of truth); copied into `web/`.
- `data_raw/`, `hexmap_reference_files/HexCDv31wm/` — inputs / style reference.
- `web/` — static viewer; `web/data_processed/` is the staged copy.
