"""Fixed metro colors for the viewer's color-by-metro mode.

Each national metro gets one color index for all 119 Congresses, keyed by a stable
identity: the leading city of its first-named (largest) urbanized area, so renames
("Los Angeles-Long Beach" -> "Los Angeles--Long Beach--Anaheim+...") keep the color and
a merged metro takes its larger partner's color (Boston+Providence is Boston's).
Same-named cities in different places (Portland OR / Portland ME) are split by the
states their tiles occupy.

Colors are a graph coloring of every pair of metros whose tiles ever touch, in any
Congress and any metro tier (gaps between states count as touching), so touching metros
never share a color. Nearby metros and overall balance are soft preferences.

Reads data_processed/polyhex_cds_by_congress/, writes data_processed/metro_colors.json:
  {"colors": K, "identities": {id: color}, "lookup": {"<metro name>|<state abbr>": id}}
Run after the tiler:  python scripts/build_metro_colors.py
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
CDS_DIR = ROOT / "data_processed" / "polyhex_cds_by_congress"
OUT = ROOT / "data_processed" / "metro_colors.json"
R = 35000.0
TOUCH = 0.6 * R    # tiles closer than this touch (state gutters are 0.5R)
NEAR = 4.0 * R     # soft: prefer different colors this close
COLORS = 8         # the smallest viewer palette (Set2/Pastel2/Dark2/Accent) has 8

HYPHEN_CITIES = {"Wilkes-Barre", "Winston-Salem"}
ALIASES = {  # one metro, several leading-city spellings or co-leads over time
    "New York City": "New York",
    "St Louis": "St. Louis",
    "St Paul": "St. Paul",
    "St Petersburg": "St. Petersburg",
    "Urban Honolulu": "Honolulu",
    "Bradenton": "Sarasota",
    "Palm Bay": "Melbourne",
    "Virginia Beach": "Norfolk",
    "Murrieta": "Temecula",
}


def metro_key(name: str) -> str:
    """The viewer's metroKey(): drop a trailing ' (XX)' state tag."""
    return re.sub(r" \([A-Z]{2}\)$", "", name)


def leading_city(name: str) -> str:
    """'Los Angeles--Long Beach--Anaheim+Riverside...' -> 'Los Angeles'."""
    city = metro_key(name).split("+")[0].split("--")[0]
    if city not in HYPHEN_CITIES:
        city = city.split("-")[0]           # 1950-1980 names: 'Albany-Schenectady-Troy'
    city = city.split("/")[0].split(",")[0].strip()
    return ALIASES.get(city, city)


def load(congress: int):
    fc = json.loads((CDS_DIR / f"{congress}.geojson").read_text(encoding="utf-8"))
    tiles = []
    for f in fc["features"]:
        p = f["properties"]
        tiers = p.get("metro_tiers")
        if not isinstance(tiers, list):
            tiers = [[p["metro_cluster"], p["metro_rank"], None, p.get("metro_name") or p["metro_cluster"]]
                     if p.get("is_metro") else None]
        names = [metro_key(t[3] or t[0]) if t else None for t in tiers]
        if any(names):
            tiles.append((shape(f["geometry"]), p["state_abbr"], names))
    return tiles


def identities(appearances: dict[tuple[str, str], Counter], co_states: list[set]) -> dict[tuple[str, str], str]:
    """(metro name, state) -> identity: leading city, split by connected state groups."""
    by_city: dict[str, set[str]] = defaultdict(set)
    tiles_in: dict[tuple[str, str], int] = Counter()
    for (name, st), n in appearances.items():
        by_city[leading_city(name)].add(st)
        tiles_in[(leading_city(name), st)] += sum(n.values())
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for city, states in co_states:
        states = sorted(states)
        for s in states[1:]:
            parent[find((city, s))] = find((city, states[0]))
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for city, states in by_city.items():
        for s in states:
            groups[find((city, s))].append(s)
    ident: dict[tuple[str, str], str] = {}
    for (city, _), states in groups.items():
        multi = sum(1 for (c, _r) in groups if c == city) > 1
        home = max(states, key=lambda s: (tiles_in[(city, s)], s))
        label = f"{city} ({home})" if multi else city
        for s in states:
            ident[(city, s)] = label
    return {(name, st): ident[(leading_city(name), st)] for (name, st) in appearances}


def color(nodes: list[str], hard: Counter, soft: Counter, k: int) -> dict[str, int]:
    """DSatur over the touching graph; ties go to the color least used by nearby metros."""
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in hard:
        adj[a].add(b)
        adj[b].add(a)
    near: dict[str, Counter] = defaultdict(Counter)
    for (a, b), w in soft.items():
        near[a][b] += w
        near[b][a] += w
    col: dict[str, int] = {}
    used = Counter()
    while len(col) < len(nodes):
        def priority(n):
            return (len({col[m] for m in adj[n] if m in col}), len(adj[n]), sum(near[n].values()), n)
        n = max((n for n in nodes if n not in col), key=priority)
        banned = {col[m] for m in adj[n] if m in col}
        free = [c for c in range(k) if c not in banned]
        if not free:
            raise RuntimeError(f"{n}: {k} colors are not enough for its touching neighbours")
        penalty = Counter()
        for m, w in near[n].items():
            if m in col:
                penalty[col[m]] += w
        col[n] = min(free, key=lambda c: (penalty[c], used[c], c))
        used[col[n]] += 1
    return col


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-congress", type=int, default=119)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    appearances: dict[tuple[str, str], Counter] = defaultdict(Counter)  # (name, st) -> congress counts
    co_states: list[tuple[str, set]] = []
    pairs: Counter = Counter()  # (name, state, name, state, touching) per tier -> tile pairs
    for c in range(1, args.max_congress + 1):
        tiles = load(c)
        n_tiers = max(len(t[2]) for t in tiles) if tiles else 0
        for tier in range(n_tiers):
            states = defaultdict(set)
            for _, st, names in tiles:
                if tier < len(names) and names[tier]:
                    appearances[(names[tier], st)][c] += 1
                    states[names[tier]].add(st)
            co_states += [(leading_city(n), s) for n, s in states.items()]
        geoms = [t[0] for t in tiles]
        tree = STRtree(geoms)
        for i, (g, st, names) in enumerate(tiles):
            for j in tree.query(g.buffer(NEAR)):
                if j <= i:
                    continue
                d = g.distance(geoms[j])
                if d >= NEAR:
                    continue
                other = tiles[j]
                for tier in range(min(len(names), len(other[2]))):
                    a, b = names[tier], other[2][tier]
                    if a and b and a != b:
                        pairs[(a, st, b, other[1], d < TOUCH)] += 1

    ident = identities(appearances, co_states)
    # Two different names sharing an identity in the same Congress would be two metros
    # drawn in one color; the aliases must never cause that.
    by_c: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for (name, st), cs in appearances.items():
        for c in cs:
            by_c[c][ident[(name, st)]].add(name)
    clashes = sorted({(c, i, tuple(sorted(ns))) for c, m in by_c.items() for i, ns in m.items() if len(ns) > 1})

    hard, soft = Counter(), Counter()
    for (a, sa, b, sb, touching), n in pairs.items():
        ia, ib = ident[(a, sa)], ident[(b, sb)]
        if ia != ib:
            (hard if touching else soft)[tuple(sorted((ia, ib)))] += n
    nodes = sorted(set(ident.values()))
    col = color(nodes, hard, soft, COLORS)
    assert all(col[a] != col[b] for a, b in hard)

    out = {
        "colors": COLORS,
        "identities": {n: col[n] for n in nodes},
        "lookup": {f"{name}|{st}": ident[(name, st)] for (name, st) in sorted(ident)},
    }
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(nodes)} metro identities, {len(hard)} touching pairs, "
          f"{len(set(col.values()))}/{COLORS} colors used -> {args.out.relative_to(ROOT)}")
    for c, i, ns in clashes:
        print(f"  note C{c}: {i} has several names in one frame (same metro across tiers?): {ns}")


if __name__ == "__main__":
    main()
