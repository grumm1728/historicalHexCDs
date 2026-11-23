"""Printable blank maps: pentahex district outlines + state borders, no fill.

Every map shares one fixed frame and scale (the union of the selected maps'
bounds, fitted to a Letter landscape page), so district sizes are comparable
across eras and the pages register when stacked. Writes one vector PDF per year, a combined
multi-page PDF, and PNG previews to output/printable_maps/.

    python scripts/make_printable_maps.py            # default years
    python scripts/make_printable_maps.py 1912 1950  # any years

CD features are already one polygon per district (the 5 hexes dissolved and
snapped to the outline), so interior hex edges never appear.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
CDS = ROOT / "data_processed" / "polyhex_cds_by_congress"
STATES = ROOT / "data_processed" / "polyhex_states_by_congress"
OUT = ROOT / "output" / "printable_maps"

DEFAULT_YEARS = [2026, 1976, 1926, 1876, 1826, 1790]
PAGE_W, PAGE_H = 11.0, 8.5          # inches, Letter landscape
MARGIN = 0.5
TITLE_H = 0.55                      # space reserved for the title line
CD_LW = 0.45                        # points
STATE_LW = 1.4


def congress_for_year(year: int) -> int:
    """Congress in session during `year` (C1 began 1789; 1790 -> C1)."""
    return max(1, (year - 1789) // 2 + 1)


def load(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return d, [shape(f["geometry"]) for f in d["features"]]


def geom_path(g) -> MplPath:
    verts, codes = [], []
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            xy = list(ring.coords)
            verts += xy
            codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(xy) - 2) + [MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def bounds(geoms):
    xs0, ys0, xs1, ys1 = zip(*(g.bounds for g in geoms))
    return min(xs0), min(ys0), max(xs1), max(ys1)


def main(years: list[int]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    maps = []
    for y in years:
        n = congress_for_year(y)
        meta, cds = load(CDS / f"{n}.geojson")
        _, states = load(STATES / f"{n}.geojson")
        maps.append((y, n, meta["properties"], cds, states, bounds(cds)))

    # One shared frame: the union of every selected map's bounds, so the pages
    # register exactly (stack them and the states line up) at one scale.
    avail_w = PAGE_W - 2 * MARGIN
    avail_h = PAGE_H - 2 * MARGIN - TITLE_H
    fx0 = min(b[0] for *_, b in maps)
    fy0 = min(b[1] for *_, b in maps)
    fx1 = max(b[2] for *_, b in maps)
    fy1 = max(b[3] for *_, b in maps)
    m_per_in = max((fx1 - fx0) / avail_w, (fy1 - fy0) / avail_h)
    cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2

    combined = PdfPages(OUT / "printable_maps_all.pdf")
    for y, n, props, cds, states, b in maps:
        fig = plt.figure(figsize=(PAGE_W, PAGE_H))
        # Axes covering the map area; limits chosen so 1 inch == m_per_in metres.
        ax = fig.add_axes([MARGIN / PAGE_W, MARGIN / PAGE_H, avail_w / PAGE_W, avail_h / PAGE_H])
        ax.set_xlim(cx - avail_w * m_per_in / 2, cx + avail_w * m_per_in / 2)
        ax.set_ylim(cy - avail_h * m_per_in / 2, cy + avail_h * m_per_in / 2)
        ax.set_aspect("equal")
        ax.axis("off")
        for g in cds:
            ax.add_patch(PathPatch(geom_path(g), fill=False, lw=CD_LW, ec="black", joinstyle="round"))
        for g in states:
            ax.add_patch(PathPatch(geom_path(g), fill=False, lw=STATE_LW, ec="black", joinstyle="round"))
        start, end = props["start_date"][:4], props["end_date"][:4]
        fig.text(MARGIN / PAGE_W, 1 - MARGIN / PAGE_H, f"{y}", fontsize=20, weight="bold", va="top")
        fig.text(MARGIN / PAGE_W + 0.9 / PAGE_W, 1 - MARGIN / PAGE_H - 0.06 / PAGE_H,
                 f"{n}{suffix(n)} Congress ({start}–{end}) · {len(cds)} districts",
                 fontsize=12, va="top")
        stem = f"printable_{y}_C{n}"
        fig.savefig(OUT / f"{stem}.pdf")
        fig.savefig(OUT / f"{stem}.png", dpi=150)
        combined.savefig(fig)
        plt.close(fig)
        print(f"{y}: C{n}, {len(cds)} CDs -> {stem}.pdf")
    combined.close()
    print(f"shared scale: 1 in = {m_per_in / 1000:.0f} km (hex space) -> {OUT}")


def suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or DEFAULT_YEARS)
