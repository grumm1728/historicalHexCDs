# PROTOTYPE NOTES — city-seeded compact-first partitioning (wayfinder ticket #18)

**Question:** seed `partition_into_pentahexes` at a state's city anchor, grow compact
urban pentahexes first, let the rural remainder absorb the stringy leftovers — does it
tile reliably, and what do the clusters look like?

**Harness:** `scripts/prototype_city_seeded_partition.py` — monkeypatches the tiler
(zero production edits), re-partitions CA/IL/NY on the *same* allocated cells, and on
any dead-end keeps the proven baseline tiles, so `warnings: 0` holds by construction.
Anchors: SF+LA, Chicago, NYC with crude fixed urban-seat fractions (0.20/0.35, 0.50,
0.60 of the delegation — the real counts are ticket #16's job).

## Verdict: the mechanism works

Full 119-Congress sweep (66 real attempts — the identical-input fast path reuses 90
congresses): **61 ok, 4 bail, 1 no-anchor-share; sweep ends `warnings: 0`.**

- NY 29/29 ok, IL 19/19 ok, CA 13/17 — all four bails are California (C58, C83, C93,
  C98), the only two-anchor state and the gnarliest coastal silhouette.
- Compactness *improves*: mean internal edges/tile 6.12 → 6.41 across the sweep
  (58 of 61 successes got blobbier, 3 marginally worse).
- Cluster shapes are the desired picture: compact urban blobs radiating from the real
  city position mapped through the state's layout transform (anchor + scale·(p−anchor)
  + displacement), rural tiles filling the rest. See `c119_06.png` (SF vs LA),
  `c119_36.png`, `c68_06.png` (historic era).

## Design findings for the real implementation (feeds ticket #19)

1. **Pure compactness growth dead-ends** — with no anti-stranding term it orphans cell
   pockets (CA bailed immediately at C119 on the first attempt). A per-tile two-stage
   growth fixes it: try pure-compact `(-internal, dist)` first, fall back to the
   production-style `(degree, -internal, dist)` ordering. After that, only 10 of 884
   urban tiles ever needed the relaxed stage, and the residual bail rate is 4/66 (~6%),
   all in the hardest state.
2. **Bails are cheap and local** — the fallback is "keep the baseline partition for
   that state that congress", so the invariant never breaks; a real implementation
   could also escalate per-anchor (drop the smaller anchor first) before full bail.
3. **The urban/rural boundary is decided by the partition, so `refine_tiles_compactness`
   must not run afterwards** (it trades cells across tile borders and would smear the
   urban cluster edge). The prototype skips it for city-seeded states; visually the
   tiles are fine without it.
4. Anchor mapping needs nothing new: `layout[fips]` already carries anchor/scale/
   displacement; city lon/lat → web mercator → hex space is three lines.

## What this does NOT answer

- Real urban seat counts per era (ticket #16) and multi-cluster splitting rules
  (ticket #17) — the crude fractions here make NY's C119 cluster over-large (16/26).
- Whether label-only (color nearest existing tiles, no partition change) is "good
  enough" visually vs this — that comparison is ticket #19's decision.

**Disposition:** throwaway. Branch `prototype/city-seeded-partition`; delete after
ticket #19 is decided. Nothing here touches production paths.
