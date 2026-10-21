"""Render the C1..C119 timeline as an animated GIF (for sharing), in the viewer's styling.

Two modes mirror the viewer's default looks (web/app.js DESIGN_DEFAULTS):
  plain  -- each state a Tableau10 hue, CDs stepped lighter by cd_index (cdColor)
  urban  -- metro tiles in their fixed metro color (metro_colors.json, tier 2.0x),
            darkest at the anchor and lighter toward the edge; rural tiles white

The frame is fixed to the union of all Congresses' extents (auto-zoom off), so the
map visibly grows west over time.

Usage: python scripts/make_timeline_gif.py [--mode plain|urban|both] [--out-dir exports]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_processed"

TABLEAU10 = ["#4e79a7", "#f28e2c", "#e15759", "#76b7b2", "#59a14f",
             "#edc949", "#af7aa1", "#ff9da7", "#9c755f", "#bab0ab"]
BACKGROUND = (249, 248, 243)
INK = (25, 35, 40)
CD_BLEND_MIN, CD_BLEND_MAX = 0.13, 0.55
URBAN_EDGE_BLEND, URBAN_CURVE = 0.35, 3
METRO_TIER = 4  # index into metro_tiers: 2.0x of top-N (viewer default)

SS = 2  # supersampling factor for antialiasing

CREDIT_WATERMARK = "@farrarscott  ·  hex map: The Downballot"
CREDIT_CORNER = "@farrarscott · hex district map design: The Downballot"


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend_white(rgb, mix):
    return tuple(round(c + (255 - c) * mix) for c in rgb)


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def load_frames(max_congress: int):
    frames = []
    for n in range(1, max_congress + 1):
        cds = json.loads((DATA / "polyhex_cds_by_congress" / f"{n}.geojson").read_text())
        states = json.loads((DATA / "polyhex_states_by_congress" / f"{n}.geojson").read_text())
        frames.append((n, cds, states))
    return frames


SPREAD_DETECT = 1.02  # layout scale vs C119 above which a frame used an anchor-spread rung
INSET_STATES = {"AK", "HI"}  # drawn as insets; not part of the spread configuration


def state_centroids(states):
    out = {}
    for f in states["features"]:
        pts = [p for poly in polygons(f["geometry"]) for p in poly[0]]
        if pts:
            out[f["properties"].get("state_abbr")] = (sum(p[0] for p in pts) / len(pts),
                                                      sum(p[1] for p in pts) / len(pts))
    return out


def fit_scale_translate(src, dst):
    """Least-squares (s, tx, ty) with dst ~ s*src + t over the states both share."""
    keys = [k for k in src if k in dst and k not in INSET_STATES]
    sx = sum(src[k][0] for k in keys) / len(keys)
    sy = sum(src[k][1] for k in keys) / len(keys)
    dx = sum(dst[k][0] for k in keys) / len(keys)
    dy = sum(dst[k][1] for k in keys) / len(keys)
    num = sum((src[k][0] - sx) * (dst[k][0] - dx) + (src[k][1] - sy) * (dst[k][1] - dy) for k in keys)
    den = sum((src[k][0] - sx) ** 2 + (src[k][1] - sy) ** 2 for k in keys)
    s = num / den
    return s, dx - s * sx, dy - s * sy


def spread_corrections(frames):
    """Undo the tiler's anchor-spread failure rung (ANCHOR_SPREAD_LADDER) per frame.

    Congresses that only tile with anchors spread ~4% about the national centre
    (C33-37, C43-47, C53-57, C63-72 today) otherwise pulse the whole map in and out at
    each reapportionment. Each spread frame is scale+translate fitted back onto the
    nearest earlier unspread frame, so the map holds still (its tiles draw ~4% smaller).
    """
    cents = {n: state_centroids(states) for n, _, states in frames}
    ref = cents[frames[-1][0]]
    spread = {n for n, c in cents.items() if len(c) > 2 and fit_scale_translate(ref, c)[0] > SPREAD_DETECT}
    out, last_plain = {}, None
    for n, _, _ in frames:
        if n not in spread:
            last_plain = n
        elif last_plain is not None:
            out[n] = fit_scale_translate(cents[n], cents[last_plain])
    return out


def metro_of(props):
    tiers = props.get("metro_tiers")
    if isinstance(tiers, list):
        t = tiers[min(METRO_TIER, len(tiers) - 1)]
        return None if t is None else {"cluster": t[0], "rank": float(t[1]), "metro": t[3] or t[0]}
    if not props.get("is_metro") or props.get("metro_rank") is None:
        return None
    return {"cluster": props["metro_cluster"], "rank": float(props["metro_rank"]),
            "metro": props.get("metro_name") or props["metro_cluster"]}


def metro_key(m) -> str:
    s = str(m["metro"] or "")
    return s[:-5] if len(s) > 5 and s[-5] == " " and s[-4] == "(" and s[-1] == ")" else s


def metro_rgb(m, abbr, metro_colors):
    ident = metro_colors["lookup"].get(f"{metro_key(m)}|{abbr}")
    idx = metro_colors["identities"].get(ident) if ident is not None else None
    if idx is None:
        idx = sum(ord(c) for c in metro_key(m))
    return hex_rgb(TABLEAU10[idx % len(TABLEAU10)])


class Renderer:
    def __init__(self, frames, width, height, mode):
        self.mode = mode
        self.W, self.H = width, height
        self.metro_colors = json.loads((DATA / "metro_colors.json").read_text())
        # State hue by first appearance across the timeline (stable for every frame).
        self.state_hue = {}
        for _, cds, _ in frames:
            for f in cds["features"]:
                abbr = f["properties"].get("state_abbr") or "unknown"
                if abbr not in self.state_hue:
                    self.state_hue[abbr] = hex_rgb(TABLEAU10[len(self.state_hue) % len(TABLEAU10)])
        self.correction = spread_corrections(frames)
        # Fixed view: union of every frame's (spread-corrected) bounds.
        xs, ys = [], []
        for n, _, states in frames:
            s, tx, ty = self.correction.get(n, (1.0, 0.0, 0.0))
            for f in states["features"]:
                for poly in polygons(f["geometry"]):
                    for x, y in poly[0]:
                        xs.append(s * x + tx)
                        ys.append(s * y + ty)
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        self.top_band = 110  # room for the title
        pad = 24
        avail_w = width - 2 * pad
        avail_h = height - self.top_band - pad
        k = min(avail_w / (maxx - minx), avail_h / (maxy - miny))
        ox = pad + (avail_w - k * (maxx - minx)) / 2
        oy = self.top_band + (avail_h - k * (maxy - miny)) / 2
        self.view = (ox, oy, minx, maxy, k)
        self.cur = (1.0, 0.0, 0.0)  # spread correction of the frame being drawn
        fonts = Path("C:/Windows/Fonts")
        self.font_title = ImageFont.truetype(str(fonts / "georgiab.ttf"), 40 * SS)
        self.font_sub = ImageFont.truetype(str(fonts / "georgia.ttf"), 22 * SS)
        self.font_small = ImageFont.truetype(str(fonts / "georgiai.ttf"), 17 * SS)
        self.font_watermark = ImageFont.truetype(str(fonts / "georgiab.ttf"), 30 * SS)

    def tf(self, x, y):
        ox, oy, minx, maxy, k = self.view
        s, tx, ty = self.cur
        x, y = s * x + tx, s * y + ty
        return (ox + (x - minx) * k) * SS, (oy + (maxy - y) * k) * SS

    def tile_color(self, props, max_rank):
        abbr = props.get("state_abbr") or "unknown"
        base = self.state_hue[abbr]
        if self.mode == "plain":
            idx = int(props.get("cd_index") or 1)
            total = max(1, int(props.get("house_seats") or 1))
            return blend_white(base, CD_BLEND_MIN + (CD_BLEND_MAX - CD_BLEND_MIN) * (idx - 1) / total)
        m = metro_of(props)
        if m is None:
            return (255, 255, 255)
        span = max_rank.get((abbr, m["cluster"]), 0)
        t = m["rank"] / span if span > 0 else 0
        return blend_white(metro_rgb(m, abbr, self.metro_colors), URBAN_EDGE_BLEND * t ** URBAN_CURVE)

    def render(self, n, cds, states):
        W, H = self.W * SS, self.H * SS
        self.cur = self.correction.get(n, (1.0, 0.0, 0.0))
        img = Image.new("RGB", (W, H), BACKGROUND)
        draw = ImageDraw.Draw(img)
        feats = cds["features"]
        max_rank = {}
        for f in feats:
            m = metro_of(f["properties"])
            if m:
                key = (f["properties"].get("state_abbr"), m["cluster"])
                max_rank[key] = max(max_rank.get(key, 0), m["rank"])

        def rings(geom):
            for poly in polygons(geom):
                yield [self.tf(x, y) for x, y in poly[0]], [[self.tf(x, y) for x, y in h] for h in poly[1:]]

        for f in feats:
            fill = self.tile_color(f["properties"], max_rank)
            for outer, holes in rings(f["geometry"]):
                draw.polygon(outer, fill=fill)
                for h in holes:
                    draw.polygon(h, fill=BACKGROUND)

        # Strokes on an alpha layer: thin translucent CD edges, then solid state borders.
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for f in feats:
            for outer, holes in rings(f["geometry"]):
                for ring in [outer, *holes]:
                    od.line(ring + ring[:1], fill=(*INK, 110), width=max(1, round(0.7 * SS)), joint="curve")
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for f in states["features"]:
            for outer, holes in rings(f["geometry"]):
                for ring in [outer, *holes]:
                    od.line(ring + ring[:1], fill=(*INK, 230), width=round(1.3 * SS), joint="curve")
        img = Image.alpha_composite(img, overlay).convert("RGB")

        draw = ImageDraw.Draw(img)
        props = cds.get("properties", {})
        start, end = props.get("start_date", "")[:4], props.get("end_date", "")[:4]
        seats = len(feats)
        n_states = len({f["properties"].get("state_abbr") for f in feats})
        x0 = 28 * SS
        draw.text((x0, 20 * SS), f"{ordinal(n)} Congress", font=self.font_title, fill=INK)
        sub = f"{start}\u2013{end}  \u00b7  {seats} districts  \u00b7  {n_states} states"
        tiers = props.get("metro_tiers") or []
        if self.mode == "urban" and tiers:
            sub += f"  \u00b7  top {tiers[min(METRO_TIER, len(tiers) - 1)]['top_n']} metros"
        draw.text((x0, 70 * SS), sub, font=self.font_sub, fill=(70, 78, 84))
        label = ("U.S. House districts, one 5-hex tile each \u00b7 metro districts colored, rural white"
                 if self.mode == "urban" else "U.S. House districts, one 5-hex tile each")
        lw = draw.textlength(label, font=self.font_small)
        draw.text((W - x0 - lw, H - 34 * SS), label, font=self.font_small, fill=(110, 116, 120))
        draw.text((x0, H - 34 * SS), CREDIT_CORNER, font=self.font_small, fill=(110, 116, 120))

        # Faint credit across the middle of the map: cropping it off would crop the map too.
        wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(wm)
        cy = (self.top_band * SS + H) / 2 + 40 * SS
        wd.text((W / 2, cy), CREDIT_WATERMARK, font=self.font_watermark, anchor="mm",
                fill=(*INK, 38), stroke_width=SS, stroke_fill=(255, 255, 255, 30))
        img = Image.alpha_composite(img.convert("RGBA"), wm).convert("RGB")
        return img.resize((self.W, self.H), Image.LANCZOS)


def write_gif(images, path: Path, frame_ms: int, hold_ms: int):
    pal = [im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in images]
    durations = [frame_ms] * len(pal)
    durations[0] = hold_ms // 2
    durations[-1] = hold_ms
    path.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(pal)} frames)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["plain", "urban", "both"], default="both")
    ap.add_argument("--out-dir", default=str(ROOT / "exports"))
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=760)
    ap.add_argument("--frame-ms", type=int, default=160)
    ap.add_argument("--hold-ms", type=int, default=3000)
    ap.add_argument("--max-congress", type=int, default=119)
    args = ap.parse_args()

    frames = load_frames(args.max_congress)
    modes = ["plain", "urban"] if args.mode == "both" else [args.mode]
    for mode in modes:
        r = Renderer(frames, args.width, args.height, mode)
        images = [r.render(n, cds, states) for n, cds, states in frames]
        write_gif(images, Path(args.out_dir) / f"hexcds_c1_c{args.max_congress}_{mode}.gif",
                  args.frame_ms, args.hold_ms)


if __name__ == "__main__":
    main()
