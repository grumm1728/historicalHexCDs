# Tiling & outline quality audit (Oct 2026, branch `audit/tiling-quality`)

Follow-up to issue #6. Started from four reported spots — PA's west edge (C1), the
Chesapeake in MD (C7), west Texas and northeast Arizona (C119) — then swept all 119
Congresses for the same defects with a geometric audit (rendered CDs vs the scaled
outline in `state_outlines_by_congress/`).

## Findings: three independent causes

| Defect | What you see | Cause | Where (baseline, C1–C119) |
|---|---|---|---|
| **Hairline holes** | dashed "ticks" just inside a straight state edge | option-3 snap: the residual strip (outline − tiles) is cut against the hex zigzag with float noding; re-unioning it onto its tile leaves zero-area interior rings | **3,223** rings, all 119 Congresses. PA 358, OH 320, MD 288, TX 249, IN 200, MA 154, NH 150, WA 130, IL 120, NY 117 … PA C1 west edge, TX-20's 103°W panhandle edge (11 rings in C119), AZ-5's east edge |
| **Unclipped interior tiles** | raw hexes drawn over water inside a state's envelope | `render_state_tiles` only clipped tiles that touch the *cell-territory* edge; a tile in the middle of the territory can still sit over a bay or lake that is outside the outline | MD (Chesapeake, up to 1.76 hexes, C3–7 and C83–119), IL (Lake Michigan, C103–119), WA (Puget Sound), CA (SF Bay), NY, VA, PA C23–27 |
| **Lake water in outlines** | IL's Lake Michigan wedge filled with districts | Natural Earth admin-1 outlines include Great Lakes water; only MI was land-clipped | IL 2.8%, IN 0.6%, MN 3.1%, NY 7.6%, OH 8.0%, PA 1.7%, WI 14.2% of the outline is lake |

So the four reported spots are two causes: PA C1, west TX and NE AZ are hairline holes (the
same artefact on three straight edges); the Maryland bay is an unclipped interior tile.

Other findings from the sweep:

- **MA C63–72: a whole district in the gutter.** MA-6 is allocated entirely outside MA's
  outline, in the empty gap between MA, CT and RI, and overlaps RI-3. It's an allocator/layout
  problem (MA at 16 seats can't fit its outline among crowded neighbours, so it grows into
  free cells), not a render bug; `render_tile` keeps the plain hexes when the clip would erase
  the tile. Not fixed directly, but gone after the full regen (see below).
- **MA C1–15 "overshoot"** is expected: the Maine block is allocated in Maine's outline and
  relabelled MA (see `MAINE_IN_MA`); the outline layer only has MA proper.
- KY C13–14 had a 0.14-hex hole in one tile; gone after the render changes.

## Fixes on this branch

1. **Clip every tile** to the scaled outline (`render_state_tiles`), not only territory-edge
   tiles. Removes all water overshoot (MD/IL/WA/CA/NY/VA/PA).
2. **`_drop_hairlines`** after the residual merge: drops interior rings and parts under
   1e-4 hex area (real holes/islands are orders of magnitude larger).
3. **Land-clip all Great Lakes states** (`GREAT_LAKES_CLIP_ABBRS` = IL, IN, MI, MN, NY, OH,
   PA, WI). `clip_to_land` now drops only small *lake-touching* parts, so NY keeps its Long
   Island Sound islands. Reference anchors re-fitted
   (`scripts/extract_reference_anchors.py`); only the lake states moved, and reference IoU
   rose for all of them but OH:

   | | IL | IN | MN | NY | OH | PA | WI |
   |---|---|---|---|---|---|---|---|
   | IoU before | 0.906 | 0.867 | 0.908 | 0.598 | 0.897 | 0.769 | 0.858 |
   | IoU after  | 0.939 | 0.870 | 0.946 | 0.618 | 0.857 | 0.780 | 0.945 |

4. **Fewer straight 5×1 pentahexes** (`refine_tiles_compactness`): straight bars get an
   extra −2 in the swap score, and edge cells may now be swapped (guarded so no tile loses
   inside-outline cells — the reason edge swaps were excluded before). A second penalty
   spreads outside-outline cells so no tile is left mostly water (the land clip exposed one:
   NY-13 in C73 at 0.003× area).
5. `--congresses` option on the tiler for fast subset runs (stateless anchored mode).

### Measured effect

16-Congress sample (C1, 7, 13, 23, …, 113, 117, 118, 119; 5,390 tiles):

| | baseline (render fixes + lake clip only) | this branch |
|---|---|---|
| straight 5×1 | 159 (2.9%) | **3** (IL only) |
| 4-internal-edge "sticks" | 429 | 105 |
| 7-internal-edge blobs | 2,500 | 3,039 |
| slivers (area ratio < 0.4) | 7 | 2 |
| area ratio p5 / p50 / p95 | 0.79 / 1.00 / 1.24 | 0.79 / 1.00 / 1.24 |

Of the 159 straights, 48 lay entirely along the territory edge: the greedy growth's
anti-stranding rule (grow toward the lowest-degree neighbour) runs a tile along an edge row,
and the old interior-only swap pass couldn't touch those.

**On "the right balance" for 5×1s:** the penalty only fires when a single swap can replace a
straight with something no worse, so the 3 that remain are forced by their surroundings. If
some 5×1s are actually *wanted* (e.g. along a straight border they read well), lower
`STRAIGHT_PENALTY` to 1 (then only swaps that also keep the internal-edge total win) or 0
(old behaviour, plus edge swaps).

### Full 119-Congress regen

`python scripts/tile_state_pentahexes.py` → **`warnings: 0`** (90 identical-input Congresses
reused). Audit of all 119 Congresses, before (staged `web/` copy of the old output) vs after:

| | before | after |
|---|---|---|
| hairline holes (< 1e-3 hex) | 3,218 | 30 (5 tiny real rings, repeated across seat-identical Congresses) |
| state-Congresses with tiles outside their outline (> 0.05 hex) | 118 | 16 (all MA C1–16: the expected Maine-block relabel) |
| slivers (area ratio < 0.4) | 83 | 21 |
| needle parts (< 1e-3 hex) | 8,205 | 5,327 |
| multipart CDs | 5,312 | 5,628 (interior tiles now split by bays, e.g. across the Chesapeake) |
| state-vs-state overlaps (> 0.01 hex) | — | 0 |

The MA C63–72 gutter district also disappeared in the full regen — presumably because the
re-fitted lake-state anchors (NY's moved 24 km) shift the crowded Northeast; not separately
verified, and it could come back with any future layout change.

## San Francisco: C117 vs C118

Not random — the labeller is deterministic — but it is *chaotic*: small input changes move
clusters a long way. Three things change between C117 and C118:

1. **New census.** C118 uses the 2020 urbanized areas. **Sacramento** enters the national
   top-N (3 CA seats), Concord becomes Concord–Walnut Creek, Temecula joins the LA chain, and
   San Diego keeps all 4 of its seats (in C117 it was walled in and spilled 3 to LA).
2. **Different tiles.** CA goes from 53 to 52 seats, so the scaled outline, allocation and
   partition are all different; cluster growth runs over rendered-tile adjacency, so the
   partition matters.
3. **Geography vs population.** The outline is area-proportional, so the region around
   the Bay holds only ~3–4 tiles while the Bay Area metros need 8 seats (11 with
   Sacramento). Clusters *must* grow outward, and the round-robin, largest-first growth
   decides the direction by competition: in C117 SF–Oakland grows north-east into empty
   Central Valley; in C118 Sacramento and Concord have claimed that, so SF grows down the
   coast past San Jose, and LA (whose southern room is taken by San Diego's and Temecula's
   tiles) climbs the San Joaquin Valley to near Sacramento's latitude.

The sensitivity shows up on this branch too: after the tiling changes, C118's SF cluster
instead grows north up the coast, and LA no longer climbs the valley. A sturdier labeller
would assign tiles to clusters jointly (e.g. a min-cost assignment of tiles to anchors
weighted by distance, or growing each national metro as one region and splitting it
afterwards) rather than greedily. Suggested as a follow-up; nothing on this branch changes
the metro labeller itself.

## Follow-ups

- A guard for whole-tile-outside-outline districts (MA C63–72 was one; gone for now, but
  nothing prevents a recurrence — e.g. flag it in `tiling_warnings.json`).
- Joint (non-greedy) metro cluster assignment, for stable Bay Area / LA labels.
- Needle-thin *coastal* parts (~90 per modern Congress under 1e-3 hex): mostly real
  islands carried over from the outline; worth a look if they render as specks.
