# Viewer scrub performance

How smoothly the web viewer redraws as the Congress slider is dragged. Measured with the
`?perf` harness (`web/perf.js`) in the desktop app's built-in Chromium pane, served from
localhost (60 Hz display, pane visible). Run it yourself:

```
python -m http.server 8000 --directory web
# open http://localhost:8000/?perf, then in the console:
await hexPerf.all()
```

- **sweep**: draws every Congress in order. `jsMs` is load + parse + DOM work per frame;
  `frameMs` is until the next animation frame (so at 60 Hz the floor is 16.7 ms).
- **drag**: fires slider `input` events at 60 Hz across all 119 Congresses. `msPerEvent` above
  16.7 is main-thread time the draws stole from the drag; `catchUpMs` is how long after the last
  event the map shows the final Congress.
- **cold** clears the viewer's in-memory caches and disables the background preload (every
  frame loads on demand; the browser HTTP cache may still serve bytes).

## Results (2026-10-16, branch `exp/scrub-perf`)

| Metric | Before | After |
|---|---|---|
| Cold sweep fps | 4.9 | 60 |
| Cold sweep `frameMs` p50 / p95 / max | 42 / 1003 / 1058 | 16.6 / 27.8 / 36.4 |
| Warm sweep `jsMs` p50 / p95 | 12.3 / 23.1 | 0.5 / 6.7 |
| Warm sweep `frameMs` p95 | 26.9 | 16.8 |
| Cold drag `msPerEvent` / `catchUpMs` | 45.4 / 132 | 18.9 / 5 |
| Warm drag `msPerEvent` / `catchUpMs` | 20.9 / 0 | 16.8 / 4 |
| JS heap after one pass | ~2,950 MB | ~295 MB |
| Bytes fetched per Congress (C119) | ~7.5 MB GeoJSON | ~0.1 MB (geometry shared) |
| All 119 Congresses | ~650 MB | 23 MB (87 shared geometry files) |
| Preload entire timeline | n/a | 0.7 s |
| First map after load | 2.9 MB C119 fetch just for the projection | 69 ms, ~1 MB |

The ~1 s stalls in the old cold sweep were garbage collection: every parsed GeoJSON stayed
in `fetchCache`, so the heap grew to ~3 GB.

## What changed

1. **Compact frame bundle** (`scripts/build_web_frames.py`, run by `build_web_assets.py`
   after staging). Per Congress, `frames/<n>.json` stores only the properties the viewer reads,
   column-wise. Geometry lives in `frames/geom/<layer>-<hash>.json`: quantized to 100 m (about
   0.04 px at the 3× maximum zoom) and delta-encoded. Seat-identical Congresses hash to the
   same file. The source GeoJSON is untouched, and the viewer falls back to it when no bundle exists.
2. **Memoized frames.** Each Congress loads once into items carrying a precomputed SVG path
   string in the stable projection, and the decoded geometry is then dropped. Fills are cached per
   (frame, design version, toggles). `redraw()` bumps the version so dev-panel edits still apply.
3. **Persistent SVG.** Layers are created once. Keyed joins reuse `<path>` nodes and write
   `d`/`fill` only when they change. Frozen layouts share path strings, so `d` is skipped entirely.
   Tooltips are delegated from the layer.
4. **Latest-wins input.** Slider `input` is coalesced to one draw per animation frame, and a
   generation token drops superseded async draws. The camera eases from its current transform.
5. **Prefetch ±3, then preload everything** at idle once the first frame is up. Outline
   geometry loads only when the silhouette toggle is on.

## Parity

`hexPerfHooks.drawLegacy(i)` still renders a Congress with the old code path. Across C1, C16,
C38, C39, C68 and C119 in five modes (metro, state/CD shading, urban/rural, states-only +
silhouettes, metro + silhouettes), both paths produce the same path count, classes and fills,
and every path's bounding box agrees within 0.012 px.

## Not measured

- A true network-cold load from GitHub Pages. Pages gzips the JSON, which helps the 23 MB
  bundle, but the first scrub over a slow connection still depends on preload progress.
- Lower-end hardware, Firefox, or Safari.
