const statusEl = document.getElementById("statusMessage");
const playBtn = document.getElementById("playBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const range = document.getElementById("congressRange");
const tooltip = document.getElementById("tooltip");
const outlineOnlyToggle = document.getElementById("outlineOnlyToggle");
const showDistrictsToggle = document.getElementById("showDistrictsToggle");
const autoZoomToggle = document.getElementById("autoZoomToggle");
const urbanRuralToggle = document.getElementById("urbanRuralToggle");
const civilWarBanner = document.getElementById("civilWarBanner");
const readoutCongress = document.getElementById("readoutCongress");
const readoutYears = document.getElementById("readoutYears");
const readoutStates = document.getElementById("readoutStates");
const readoutSeats = document.getElementById("readoutSeats");
const readoutLargest = document.getElementById("readoutLargest");
const timelineEvents = document.getElementById("timelineEvents");
const timelineTicks = document.getElementById("timelineTicks");
const timelineYears = document.getElementById("timelineYears");

const width = 960;
const height = 600;

let timeline = [];
let frameIndex = 0;
let timer = null;
let svg;
let stateColor;
let stableProjection = null;
let stablePath = null;

// Auto-zoom camera: a zoom/pan transform applied on top of the stable base projection so
// each Congress's footprint fills the viewport (early Congresses cover ~5% of the C119
// frame and sat far east). Geometry coordinates never change — only the <g> transform —
// and transitions are animated so a frame change reads as a camera move, not states
// moving. Because the layout is frozen across seat-identical Congresses, the fitted view
// is identical there too: a stable era has a perfectly still camera.
// Tunable design parameters. Defaults reproduce the shipped look; the dev panel
// (web/devpanel.js, experimental) edits this object in place and calls redraw().
const DESIGN_DEFAULTS = Object.freeze({
  palette: "Tableau10",
  colorBy: "metro",       // "state" | "metro" (metro: each metro gets its own hue across state lines)
  metroPalette: "Tableau10",
  metroRural: "faded state", // metro mode: rural tiles as "faded state" hue or flat "grey"
  cdBlendMin: 0.13,       // plain mode: lightness blend for a state's first CD...
  cdBlendMax: 0.55,       // ...and its last (blend toward white)
  urbanAnchorBlend: 0.0,  // urban mode: blend at the metro anchor tile (0 = full state hue)
  urbanEdgeBlend: 0.35,   // blend at the outermost claimed metro tile
  urbanCurve: 3,          // gamma on the anchor->edge ramp (<1 lightens fast, >1 keeps the core dark longer)
  ruralBlend: 1,          // flat blend for rural tiles (1 = white)
  ruralDesat: 0.0,        // 0..1 desaturate rural tiles toward grey
  metroTier: 4,           // index into the tiler's metro_tiers (0.5x..3x of top-N = states/2); 2 = 1.0x, 4 = 2.0x
  minMetroTiles: 1,       // a metro drawing fewer tiles than this (whole metro, all states) counts as rural
  metroDepth: 1.0,        // fraction of each cluster's outward depth counted as urban (1 = all)
  tileOpacity: 1,
  tileStroke: "#192328",
  tileStrokeOpacity: 0.36,
  tileStrokeWidth: 0.5,
  stateBorderWidth: 0.8,  // 0 = off; >0 draws state outlines over the district tiles
  stateBorderColor: "#192328",
  mapBackground: "#f9f8f3",
  playMs: 1300,
  zoomMs: 700,
  viewPad: 0.04,          // fractional padding around the fitted Congress bbox
  viewKmax: 3,            // max zoom factor (C1 is height-constrained at ~1.5)
});
const DESIGN = { ...DESIGN_DEFAULTS };
const PALETTES = {
  Tableau10: () => d3.schemeTableau10,
  Observable10: () => d3.schemeObservable10,
  Category10: () => d3.schemeCategory10,
  Set2: () => d3.schemeSet2,
  Set3: () => d3.schemeSet3,
  Pastel1: () => d3.schemePastel1,
  Pastel2: () => d3.schemePastel2,
  Dark2: () => d3.schemeDark2,
  Paired: () => d3.schemePaired,
  Accent: () => d3.schemeAccent,
};
// Metro colors come from data_processed/metro_colors.json (scripts/build_metro_colors.py):
// one color index per metro identity (its largest area's leading city), fixed for all
// Congresses and chosen so metros whose tiles ever touch never share a color. A merged
// metro takes its larger partner's color (Boston+Providence is Boston's). "Assigned hues"
// spaces the indices evenly around the hue wheel; named palettes use the same indices.
// "Hashed hues" is the old name-hash coloring, kept for comparison and as the fallback
// for a metro missing from the JSON.
const METRO_PALETTES = ["Assigned hues", "Hashed hues", ...Object.keys(PALETTES)];
let metroColors = null;  // {colors, identities: {id: index}, lookup: {"name|ST": id}}
function hashString(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}
// Metro tiers (tiler METRO_TIER_SCALES): the CD file lists [{scale, top_n}] and each tile
// carries metro_tiers[i] = null | [cluster, rank, cluster_tiles, metro_name, national_rank].
// Files from before the tiers existed fall back to the flat 1.0x fields.
let currentMetroTiers = null;  // FeatureCollection-level tier table of the drawn frame
function tileMetro(props) {
  const tiers = props.metro_tiers;
  if (Array.isArray(tiers)) {
    const t = tiers[Math.min(Math.max(0, DESIGN.metroTier), tiers.length - 1)];
    return t ? { cluster: t[0], rank: Number(t[1]), metro: t[3] || t[0], nationalRank: t[4] } : null;
  }
  if (!props.is_metro || props.metro_rank == null) return null;
  return { cluster: props.metro_cluster, rank: Number(props.metro_rank), metro: props.metro_name || props.metro_cluster, nationalRank: props.metro_national_rank };
}
function metroKey(m) {
  return String(m.metro || "").replace(/ \([A-Z]{2}\)$/, "");
}
function metroColor(m, stateAbbr) {
  const id = metroColors?.lookup[`${metroKey(m)}|${stateAbbr}`];
  const idx = id != null ? metroColors.identities[id] : null;
  const h = hashString(metroKey(m));
  if (DESIGN.metroPalette === "Hashed hues" || (idx == null && DESIGN.metroPalette === "Assigned hues")) {
    return d3.hcl((h % 3600) / 10, 62, 52).formatRgb();
  }
  if (DESIGN.metroPalette === "Assigned hues") {
    // Step 3/8 of the wheel per index (all 8 hues, consecutive indices 135° apart) and
    // alternate lightness, so the two indices nearest in hue (45° apart) differ in lightness.
    const n = metroColors.colors;
    return d3.hcl(20 + ((idx * 3) % n) * (360 / n), 62, idx % 2 ? 66 : 46).formatRgb();
  }
  const scheme = (PALETTES[DESIGN.metroPalette] || PALETTES.Tableau10)();
  return scheme[(idx ?? h) % scheme.length];
}
async function loadMetroColors() {
  try {
    const resp = await fetch("./data_processed/metro_colors.json");
    if (resp.ok) metroColors = await resp.json();
  } catch {
    metroColors = null;  // optional: metro mode falls back to hashed hues
  }
}
function buildStateColor() {
  stateColor = d3.scaleOrdinal((PALETTES[DESIGN.palette] || PALETTES.Tableau10)());
}
let currentView = { k: 1, x: 0, y: 0 };

function viewTransform(v) {
  return `translate(${v.x},${v.y}) scale(${v.k})`;
}

// Fit `fitGeo` (data-space features) into the viewport as a {k,x,y} transform over the
// stable projection. Identity when auto-zoom is off or anything needed is unavailable.
function computeTargetView(fitGeo) {
  if (!fitGeo) return { k: 1, x: 0, y: 0 };
  return computeTargetViewFromBounds(geometryBounds(fitGeo));
}
function computeTargetViewFromBounds(b) {
  const identity = { k: 1, x: 0, y: 0 };
  if (!stableProjection) return identity;
  if (autoZoomToggle && !autoZoomToggle.checked) return identity;
  if (!Number.isFinite(b.minX) || b.maxX <= b.minX || b.maxY <= b.minY) return identity;
  const p0 = stableProjection([b.minX, b.minY]);
  const p1 = stableProjection([b.maxX, b.maxY]);
  const x0 = Math.min(p0[0], p1[0]);
  const x1 = Math.max(p0[0], p1[0]);
  const y0 = Math.min(p0[1], p1[1]);
  const y1 = Math.max(p0[1], p1[1]);
  const bw = (x1 - x0) * (1 + 2 * DESIGN.viewPad);
  const bh = (y1 - y0) * (1 + 2 * DESIGN.viewPad);
  if (bw <= 0 || bh <= 0) return identity;
  // No lower clamp: a frame whose footprint exceeds the base projection's reference frame
  // (or whose padding pushes past it) zooms OUT slightly so it always fits the viewport.
  const k = Math.min(DESIGN.viewKmax, Math.min(width / bw, height / bh));
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  return { k, x: width / 2 - k * cx, y: height / 2 - k * cy };
}
// Distinguish CDs within a state by hashing state+cd_index into d3's category palette,
// with a stable per-state base hue overlay so adjacent CDs in the same state look related.
function cdColor(props) {
  const base = stateColor(props.state_abbr || "unknown");
  // Modulate base luminance by cd_index so adjacent CDs in the same state differ visibly.
  const idx = Number(props.cd_index) || 1;
  const total = Math.max(1, Number(props.house_seats) || 1);
  const t = total > 1 ? (idx - 1) / (total - 1) : 0;  // first CD -> cdBlendMin, last -> cdBlendMax
  // Blend base with white across CDs (cdBlendMin..cdBlendMax).
  return blendWithWhite(base, DESIGN.cdBlendMin + (DESIGN.cdBlendMax - DESIGN.cdBlendMin) * t);
}

// Urban/rural encoding (#20, issue #29): reuses cdColor's lightness-blend channel, but the
// blend is driven by the tiler's metro labels instead of the arbitrary cd_index. State hue
// is untouched. Metro tiles run 0.00 (cluster anchor, metro_rank 0) -> 0.30 (outermost
// claimed tile); rural tiles sit at a flat 0.75 — checked against the palette's palest hue
// (yellow) on the near-white page background, so don't raise it without re-checking.
// A state with no metro seats has no clusters, so all its tiles fall to the rural shade.
// (These are now DESIGN.urbanEdgeBlend / DESIGN.ruralBlend.)

function blendWithWhite(base, mix) {
  const c = d3.color(base);
  if (!c) return base;
  c.r = Math.round(c.r + (255 - c.r) * mix);
  c.g = Math.round(c.g + (255 - c.g) * mix);
  c.b = Math.round(c.b + (255 - c.b) * mix);
  return c.formatRgb();
}

function metroTooltip(props, maxRank) {
  const m = tileMetro(props);
  if (!m) return "Rural";
  const where = m.metro && m.metro !== m.cluster ? `${m.cluster} (${m.metro})` : m.cluster;
  const rank = m.nationalRank ? ` · #${m.nationalRank} nationally` : "";
  return urbanPosition(props, maxRank) != null
    ? `Metro: ${where}${rank}`
    : `Rural (below threshold; metro: ${where}${rank})`;
}

// Highest metro_rank actually drawn per state+cluster, so the gradient spans each cluster's
// real extent. metro_cluster_seats can overstate it when a walled-in cluster spills seats.
// .metroTiles counts each national metro's drawn tiles for the min-size threshold, so a
// one-seat area of a big metro (Temecula in LA) isn't peeled off as a "small metro".
function clusterMaxRanks(features) {
  const maxRank = new Map();
  maxRank.metroTiles = new Map();
  for (const f of features) {
    const m = tileMetro(f.properties);
    if (!m) continue;
    const key = `${f.properties.state_abbr}|${m.cluster}`;
    maxRank.set(key, Math.max(maxRank.get(key) ?? 0, m.rank));
    maxRank.metroTiles.set(metroKey(m), (maxRank.metroTiles.get(metroKey(m)) ?? 0) + 1);
  }
  return maxRank;
}

// Where this tile falls on the metro gradient (0 = anchor .. 1 = edge), or null when it
// counts as rural under the current thresholds. Thresholds only ever demote metro tiles
// to rural (the tiler's labels are the most inclusive definition), so the result is
// nested: raising minMetroTiles or lowering metroDepth peels off small metros / suburbs.
function urbanPosition(props, maxRank) {
  const m = tileMetro(props);
  if (!m) return null;
  const span = maxRank.get(`${props.state_abbr}|${m.cluster}`) ?? 0;
  if ((maxRank.metroTiles?.get(metroKey(m)) ?? span + 1) < DESIGN.minMetroTiles) return null;
  const t = span > 0 ? m.rank / span : 0;
  if (DESIGN.metroDepth < 1 && t > DESIGN.metroDepth) return null;
  const keptSpan = Math.max(DESIGN.metroDepth, 1e-9);
  return Math.min(1, t / keptSpan);
}

function urbanRuralColor(props, maxRank) {
  const byMetro = DESIGN.colorBy === "metro";
  const t = urbanPosition(props, maxRank);
  const base = byMetro && t != null ? metroColor(tileMetro(props), props.state_abbr) : stateColor(props.state_abbr || "unknown");
  if (t == null) {
    if (byMetro && DESIGN.metroRural === "grey") return blendWithWhite("#6b7378", DESIGN.ruralBlend);
    let c = base;
    if (DESIGN.ruralDesat > 0) {
      const h = d3.hcl(base);
      h.c *= 1 - DESIGN.ruralDesat;
      c = h.formatRgb();
    }
    return blendWithWhite(c, DESIGN.ruralBlend);
  }
  const ramp = Math.pow(t, DESIGN.urbanCurve);
  return blendWithWhite(base, DESIGN.urbanAnchorBlend + (DESIGN.urbanEdgeBlend - DESIGN.urbanAnchorBlend) * ramp);
}
const outlineGeometryCache = new Map();

// url -> Promise<parsed JSON>  (stores in-flight promises too, so concurrent
// calls for the same URL share one fetch rather than firing duplicates)
const fetchCache = new Map();

function cachedFetchJson(url) {
  if (!fetchCache.has(url)) {
    const p = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${url}`);
        return r.json();
      })
      .catch((err) => {
        fetchCache.delete(url); // allow retry on transient failures
        throw err;
      });
    fetchCache.set(url, p);
  }
  return fetchCache.get(url);
}

function prefetchFrame(i) {
  if (i < 0 || i >= timeline.length) return;
  const entry = timeline[i];
  const featurePath = entry.state_feature_path || entry.feature_path;
  if (featurePath) cachedFetchJson(`./${featurePath}`).catch(() => {});
  if (entry.cd_feature_path) cachedFetchJson(`./${entry.cd_feature_path}`).catch(() => {});
}
const CIVIL_WAR_HIDDEN_BY_CONGRESS = new Map([
  [37, new Set(["AL", "AR", "FL", "GA", "LA", "MS", "NC", "SC", "TN", "TX", "VA"])],
  [38, new Set(["AL", "AR", "FL", "GA", "LA", "MS", "NC", "SC", "TN", "TX", "VA"])],
  [39, new Set(["AL", "AR", "FL", "GA", "LA", "MS", "NC", "SC", "TX", "VA"])],
  [40, new Set(["MS", "TX", "VA"])],
]);

function geometryBounds(geo) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  function walk(v) {
    if (!Array.isArray(v)) return;
    if (v.length === 2 && Number.isFinite(v[0]) && Number.isFinite(v[1])) {
      const [x, y] = v;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      return;
    }
    for (const e of v) walk(e);
  }
  // Accept FeatureCollection / Feature / Geometry / raw coordinates.
  if (geo && typeof geo === "object" && !Array.isArray(geo)) {
    if (Array.isArray(geo.features)) {
      for (const f of geo.features) walk(f?.geometry?.coordinates);
    } else if (geo.geometry) {
      walk(geo.geometry.coordinates);
    } else if (geo.coordinates) {
      walk(geo.coordinates);
    }
  } else {
    walk(geo);
  }
  return { minX, minY, maxX, maxY };
}

function collectCoords(v, out) {
  if (!Array.isArray(v)) return;
  if (v.length === 2 && Number.isFinite(v[0]) && Number.isFinite(v[1])) {
    out.push(v);
    return;
  }
  for (const e of v) collectCoords(e, out);
}

function featureBounds(feature) {
  const pts = [];
  collectCoords(feature?.geometry?.coordinates, pts);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of pts) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

function translateCoords(v, dx, dy) {
  if (!Array.isArray(v)) return v;
  if (v.length === 2 && Number.isFinite(v[0]) && Number.isFinite(v[1])) {
    return [v[0] + dx, v[1] + dy];
  }
  return v.map((e) => translateCoords(e, dx, dy));
}

function applyCollisionLayout(outlineGeo, congressNumber) {
  if (!outlineGeo || !Array.isArray(outlineGeo.features) || outlineGeo.features.length < 2) {
    return outlineGeo;
  }
  if (outlineGeometryCache.has(congressNumber)) {
    return outlineGeometryCache.get(congressNumber);
  }

  const nodes = outlineGeo.features.map((f, i) => {
    const b = featureBounds(f);
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    const w = Math.max(0, b.maxX - b.minX);
    const h = Math.max(0, b.maxY - b.minY);
    const r = Math.max(0.001, Math.hypot(w, h) * 0.5);
    return { i, abbr: String(f?.properties?.state_abbr || ""), x: cx, y: cy, tx: cx, ty: cy, r };
  });

  const basePadding = 0.015;
  const repel = 0.5;
  const spring = 0.22;

  // Keep target congress exactly at source-of-truth spacing.
  const iterations = 110;
  for (let iter = 0; iter < iterations; iter += 1) {
    for (let a = 0; a < nodes.length; a += 1) {
      for (let b = a + 1; b < nodes.length; b += 1) {
        const n1 = nodes[a];
        const n2 = nodes[b];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const d = Math.hypot(dx, dy) || 1e-9;
        const minD = n1.r + n2.r + basePadding;
        if (d < minD) {
          const push = ((minD - d) / minD) * repel;
          const ux = dx / d;
          const uy = dy / d;
          n1.x -= ux * push;
          n1.y -= uy * push;
          n2.x += ux * push;
          n2.y += uy * push;
        }
      }
    }
    for (const n of nodes) {
      n.x += (n.tx - n.x) * spring;
      n.y += (n.ty - n.y) * spring;
    }
  }

  const shifts = new Map(nodes.map((n) => [n.i, { dx: n.x - n.tx, dy: n.y - n.ty }]));
  const byAbbr = new Map(nodes.map((n) => [n.abbr, { dx: n.x - n.tx, dy: n.y - n.ty }]));
  const outFeatures = outlineGeo.features.map((f, i) => {
    const shift = shifts.get(i) || { dx: 0, dy: 0 };
    return {
      ...f,
      geometry: {
        ...f.geometry,
        coordinates: translateCoords(f.geometry.coordinates, shift.dx, shift.dy),
      },
    };
  });

  const result = { ...outlineGeo, features: outFeatures, _shiftByAbbr: byAbbr };
  outlineGeometryCache.set(congressNumber, result);
  return result;
}


function setStatus(message) {
  statusEl.hidden = false;
  statusEl.textContent = message;
}

function clearStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
}

function setCivilWarBanner(message) {
  if (!civilWarBanner) return;
  if (!message) {
    civilWarBanner.hidden = true;
    civilWarBanner.textContent = "";
    return;
  }
  civilWarBanner.hidden = false;
  civilWarBanner.textContent = message;
}

function setControlsEnabled(enabled) {
  for (const el of [playBtn, prevBtn, nextBtn, range]) {
    el.disabled = !enabled;
  }
}

function stopPlayback() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
  playBtn.textContent = "Play";
}

function togglePlayback() {
  if (timer) {
    stopPlayback();
    return;
  }
  playBtn.textContent = "Pause";
  timer = setInterval(() => {
    const next = (frameIndex + 1) % timeline.length;
    setFrame(next);
  }, DESIGN.playMs);
}

async function loadIndex() {
  const resp = await fetch("./data_processed/congress_index.json");
  if (!resp.ok) {
    throw new Error("Unable to load web/data_processed/congress_index.json. Run: python scripts/build_web_assets.py");
  }
  const data = await resp.json();
  timeline = data.timeline || [];
  if (!timeline.length) {
    throw new Error("Timeline index is empty. Populate data_raw/seats and data_raw/nhgis inputs, then rebuild.");
  }
}

// Timeline annotations under/over the slider. Years are placed by interpolating each
// Congress's start year, so a mark lands between Congresses when it falls mid-term.
const TIMELINE_YEARS = [1800, 1850, 1900, 1950, 2000];
// The Apportionment Act of 1911 fixed the House at 435 seats from the 63rd Congress (1913);
// the 1929 act made the cap permanent.
const SEAT_CAP = { congress: 63, label: "435-seat cap", title: "Apportionment Act of 1911: House fixed at 435 seats from the 63rd Congress (1913)" };

let timelineEventEls = [];

// What changes the map, Congress by Congress, from the seat table: each state's first
// seated Congress and the Congresses whose seat table differs from the one before.
async function loadSeatHistory() {
  const resp = await fetch("./data_processed/seats/state_seats_by_congress.csv");
  if (!resp.ok) throw new Error(`seat table: HTTP ${resp.status}`);
  const rows = d3.csvParse(await resp.text());
  const names = new Map();
  const seats = new Map(); // congress -> Map(abbr -> seats)
  for (const r of rows) {
    names.set(r.state_abbr, r.state_name);
    const c = Number(r.congress_number);
    if (!seats.has(c)) seats.set(c, new Map());
    seats.get(c).set(r.state_abbr, Number(r.house_seats) || 0);
  }
  const firstSeated = new Map(); // congress -> [abbr]
  const changed = new Set();
  const seen = new Set();
  let prev = null;
  for (const c of [...seats.keys()].sort((x, y) => x - y)) {
    const cur = seats.get(c);
    for (const [abbr, n] of cur) {
      if (n > 0 && !seen.has(abbr)) {
        seen.add(abbr);
        if (!firstSeated.has(c)) firstSeated.set(c, []);
        firstSeated.get(c).push(abbr);
      }
      if (prev && (prev.get(abbr) || 0) !== n) changed.add(c);
    }
    prev = cur;
  }
  return { names, firstSeated, changed };
}

// Each census is apportioned from the Congress starting in the year ending in 3
// (1790 census -> 3rd Congress, 1793). Seat changes in any other Congress are admissions.
function censusYearOf(entry) {
  const y = Number(String(entry.start_date || "").slice(0, 4));
  return y % 10 === 3 ? y - 3 : null;
}

function abbrList(abbrs, max = 3) {
  return abbrs.length <= max ? abbrs.join(" ") : `${abbrs.length} states`;
}

function timelinePct(i) {
  return timeline.length > 1 ? (100 * i) / (timeline.length - 1) : 0;
}

function yearToIndex(year) {
  const starts = timeline.map((e) => Number(String(e.start_date || "").slice(0, 4)));
  for (let i = 0; i < starts.length - 1; i += 1) {
    if (year >= starts[i] && year < starts[i + 1]) {
      return i + (year - starts[i]) / (starts[i + 1] - starts[i]);
    }
  }
  return null;
}

function addMark(parent, cls, pct, text) {
  const el = document.createElement(cls.startsWith("tl-event") ? "button" : "div");
  el.className = `tl-mark ${cls}`;
  el.style.left = `${pct}%`;
  if (text != null) el.textContent = text;
  parent.appendChild(el);
  return el;
}

async function buildTimeline() {
  if (!timelineTicks) return;
  timelineTicks.replaceChildren();
  timelineYears.replaceChildren();
  timelineEvents.replaceChildren();
  timelineEventEls = [];

  let history = null;
  try {
    history = await loadSeatHistory();
  } catch (err) {
    console.warn("Timeline: seat history unavailable", err);
  }
  const names = history ? history.names : new Map();
  const fullNames = (abbrs) => abbrs.map((a) => names.get(a) || a).join(", ");
  const congressLabel = (e) => `${ordinal(Number(e.congress_number))} Congress (${String(e.start_date || "").slice(0, 4)})`;

  // Label events, collected first so they can be stacked left to right.
  const events = [];
  timeline.forEach((e, i) => {
    const c = Number(e.congress_number);
    const added = history?.firstSeated.get(c);
    // The original 13 states are the starting point, not additions.
    if (added && i > 0) {
      added.sort();
      events.push({ i, kind: "", text: `+${abbrList(added)}`, title: `${congressLabel(e)}: first seats for ${fullNames(added)}` });
    }
    // Civil War: states the viewer hides (seceded) and their return when un-hidden.
    const hidden = CIVIL_WAR_HIDDEN_BY_CONGRESS.get(c) || new Set();
    const prevHidden = (i > 0 && CIVIL_WAR_HIDDEN_BY_CONGRESS.get(Number(timeline[i - 1].congress_number))) || new Set();
    const seceded = [...hidden].filter((a) => !prevHidden.has(a)).sort();
    const returned = [...prevHidden].filter((a) => !hidden.has(a)).sort();
    if (seceded.length) {
      events.push({ i, kind: "civilwar", text: `${seceded.length} seceded`, title: `${congressLabel(e)}: seceded states absent: ${fullNames(seceded)}` });
    }
    if (returned.length) {
      events.push({ i, kind: "civilwar", text: `↩${abbrList(returned)}`, title: `${congressLabel(e)}: readmitted after the Civil War: ${fullNames(returned)}` });
    }
  });

  // Ticks: census apportionments are the major ticks; a Congress that changes the map
  // without a new census (admissions, Civil War) gets a medium tick.
  const eventIdx = new Set(events.map((ev) => ev.i));
  timeline.forEach((e, i) => {
    const c = Number(e.congress_number);
    const census = censusYearOf(e);
    const changed = history?.changed.has(c);
    let cls = "tl-tick";
    let title = `${ordinal(c)} Congress`;
    if (census != null && changed) {
      cls += " census";
      title += `: ${census} census apportionment takes effect`;
    } else if (census != null && i > 0) {
      cls += " census skipped";
      title += `: no reapportionment after the ${census} census`;
    } else if (changed || (i > 0 && eventIdx.has(i))) {
      cls += " offcensus";
      title += ": map changes without a new census";
    }
    addMark(timelineTicks, cls, timelinePct(i)).title = title;
  });

  for (const y of TIMELINE_YEARS) {
    const i = yearToIndex(y);
    if (i == null) continue;
    addMark(timelineYears, "tl-year", timelinePct(i), String(y));
  }

  const capIdx = timeline.findIndex((e) => Number(e.congress_number) === SEAT_CAP.congress);
  if (capIdx >= 0) {
    addMark(timelineTicks, "tl-tick cap", timelinePct(capIdx)).title = SEAT_CAP.title;
    const lab = addMark(timelineYears, "tl-cap-label", timelinePct(capIdx), SEAT_CAP.label);
    lab.title = SEAT_CAP.title;
  }

  events.sort((x, y) => x.i - y.i);
  for (const ev of events) {
    const el = addMark(timelineEvents, `tl-event ${ev.kind}`.trim(), timelinePct(ev.i), ev.text);
    el.type = "button";
    el.title = ev.title;
    el.setAttribute("aria-label", ev.title);
    el.addEventListener("click", () => {
      stopPlayback();
      setFrame(ev.i);
    });
    timelineEventEls.push({ el, i: ev.i });
  }
  stackTimelineEvents();
  updateTimelineMarks();
}

// Greedy row assignment: each label takes the lowest row whose previous label it clears.
function stackTimelineEvents() {
  const width = timelineEvents.clientWidth;
  if (!width) return;
  timelineEvents.parentElement.classList.toggle("compact", width < 640);
  const rowEnds = [];
  for (const { el } of timelineEventEls) {
    const w = el.offsetWidth;
    const left = (parseFloat(el.style.left) / 100) * width - w / 2;
    let row = rowEnds.findIndex((end) => left >= end + 4);
    if (row < 0) {
      row = rowEnds.length;
      rowEnds.push(0);
    }
    rowEnds[row] = left + w;
    el.style.setProperty("--row", String(row));
  }
  timelineEvents.parentElement.style.setProperty("--event-rows", String(Math.max(1, rowEnds.length)));
}

function updateTimelineMarks() {
  for (const { el, i } of timelineEventEls) el.classList.toggle("past", i < frameIndex);
}

// Build the stable, fits-every-frame projection from the largest frame's CDs
// (typically C119). The viewport never bounces because we fitSize once and
// reuse the projection for every frame.
async function buildStableProjection() {
  // Pick the frame with the most CDs (or the last one as a proxy).
  // Prefer the LATEST frame among max-CD ties: many Congresses share the 435 cap, but the
  // map's footprint keeps spreading over time, so the newest (C119) has the largest bbox.
  // (Fitting to the first 435-CD frame, 1963, cropped C119's edges off the viewport.)
  const cartogramFrames = timeline.filter((e) => isCartogramFrame(e) && e.cd_feature_path);
  const ref = cartogramFrames.length
    ? cartogramFrames.reduce((a, b) => ((b.cd_feature_count || 0) >= (a.cd_feature_count || 0) ? b : a))
    : timeline[timeline.length - 1];
  const path = ref.cd_feature_path || ref.state_feature_path;
  try {
    let b;
    if (ref.web_frame_path) {
      // Same bounds from the compact bundle (quantized to 100 m: far below a pixel).
      const meta = await (await fetch(`./${ref.web_frame_path}`)).json();
      const geomPath = (meta.cd || meta.state).geom;
      const json = await (await fetch(`./data_processed/frames/${geomPath}`)).json();
      b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
      for (const coords of decodeGeom(json)) coordsBounds(coords, b);
    } else {
      const resp = await fetch(`./${path}`);
      if (!resp.ok) return;
      const geo = await resp.json();
      if (!geo?.features?.length) return;
      b = geometryBounds(geo);
    }
    if (!Number.isFinite(b.minX)) return;
    // Add small padding so boundary tiles aren't flush against the SVG edge.
    const padX = (b.maxX - b.minX) * 0.02;
    const padY = (b.maxY - b.minY) * 0.02;
    const padded = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [[
              [b.minX - padX, b.minY - padY],
              [b.maxX + padX, b.minY - padY],
              [b.maxX + padX, b.maxY + padY],
              [b.minX - padX, b.maxY + padY],
              [b.minX - padX, b.minY - padY],
            ]],
          },
        },
      ],
    };
    stableProjection = d3.geoIdentity().reflectY(true).fitSize([width, height], padded);
    stablePath = d3.geoPath(stableProjection);
  } catch (err) {
    console.warn("buildStableProjection failed:", err);
  }
}

// v5+ generators emit absolute Web-Mercator coordinates that already respect the cartogram
// layout (v6 = pentahex scaled outlines). Only legacy template frames need the collision relax.
function isCartogramFrame(entry) {
  const v = String(entry?.generator_version || "");
  return v.startsWith("v5") || v.startsWith("v6");
}

// ---- Fast path: memoized compact frames drawn into persistent SVG layers ----------------
// Scrubbing used to fetch + parse ~7.5 MB of GeoJSON per Congress, keep every parsed file
// (~3 GB heap after one pass), and rebuild ~1,000 <path>s from scratch each frame. Now each
// Congress loads once into a small Frame — per layer, items {key, properties, d, b} with the
// SVG path string precomputed in the stable projection and the geometry dropped — preferably
// from the compact bundle written by scripts/build_web_frames.py (shared, deduplicated
// geometry files, so seat-identical Congresses reuse the very same path strings). Drawing a
// Frame is a keyed join that only touches attributes that changed.
const frameCache = new Map();  // timeline index -> Promise<Frame>
const geomCache = new Map();   // bundle geom path -> Promise<{d: string[], b: bounds[]}>
let designVersion = 0;         // bumped by redraw(); invalidates memoized fills
let layers = null;             // persistent <g> layers (created on first fast draw)
let drawn = null;              // {frame, urbanRural, maxRank, showOutline} of the shown frame
let drawGen = 0;               // latest-wins token: a superseded async draw is dropped

function coordsBounds(coords, b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }) {
  for (const poly of coords) {
    for (const ring of poly) {
      for (const [x, y] of ring) {
        if (x < b.minX) b.minX = x;
        if (y < b.minY) b.minY = y;
        if (x > b.maxX) b.maxX = x;
        if (y > b.maxY) b.maxY = y;
      }
    }
  }
  return b;
}

// Decode a bundle geom file (quantized, delta-encoded; see build_web_frames.py) into
// MultiPolygon coordinate arrays, one per feature.
function decodeGeom(json) {
  const q = json.q;
  let cx = 0;
  let cy = 0;
  return json.f.map((polys) =>
    polys.map((rings) =>
      rings.map((flat) => {
        const ring = new Array(flat.length / 2);
        for (let i = 0, k = 0; i < flat.length; i += 2, k += 1) {
          cx += flat[i];
          cy += flat[i + 1];
          ring[k] = [cx * q, cy * q];
        }
        return ring;
      })));
}

function loadGeom(path) {
  if (!geomCache.has(path)) {
    const p = fetch(`./data_processed/frames/${path}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`);
        return r.json();
      })
      .then((json) => {
        const d = [];
        const b = [];
        for (const coords of decodeGeom(json)) {
          d.push(stablePath({ type: "MultiPolygon", coordinates: coords }) || "");
          b.push(coordsBounds(coords));
        }
        return { d, b };
      })
      .catch((err) => {
        geomCache.delete(path);
        throw err;
      });
    geomCache.set(path, p);
  }
  return geomCache.get(path);
}

function makeItems(propsList, d, b, keyOf, hiddenSet) {
  const items = [];
  propsList.forEach((properties, j) => {
    if (hiddenSet.has(String(properties.state_abbr || "").toUpperCase())) return;
    items.push({ key: keyOf(properties), properties, d: d[j], b: b[j], i: items.length });
  });
  return items;
}
const cdKey = (p) => `${p.state_fips}-${p.cd_index}`;
const stateKey = (p) => String(p.state_fips ?? p.state_abbr);

// One layer of a Frame from the bundle: rows -> property objects, geometry from the shared file.
async function bundleLayer(layer, hiddenSet, keyOf) {
  if (!layer) return null;
  const { d, b } = await loadGeom(layer.geom);
  const props = layer.rows.map((row) => Object.fromEntries(layer.keys.map((k, j) => [k, row[j]])));
  return makeItems(props, d, b, keyOf, hiddenSet);
}

// Fallback without a bundle: same Frame shape from the GeoJSON (parsed, converted, released).
async function geojsonLayer(path, hiddenSet, keyOf) {
  if (!path) return null;
  const resp = await fetch(`./${path}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${path}`);
  const fc = await resp.json();
  const feats = fc.features || [];
  const d = feats.map((f) => (f.geometry ? stablePath(f) || "" : ""));
  const b = feats.map((f) => featureBounds(f));
  const items = makeItems(feats.map((f) => f.properties || {}), d, b, keyOf, hiddenSet);
  items.collectionProps = fc.properties || {};
  return items;
}

function loadFrame(i) {
  if (!frameCache.has(i)) {
    const entry = timeline[i];
    const hiddenSet = CIVIL_WAR_HIDDEN_BY_CONGRESS.get(Number(entry.congress_number)) || new Set();
    let p;
    if (entry.web_frame_path) {
      p = cachedFetchJson(`./${entry.web_frame_path}`).then(async (meta) => {
        fetchCache.delete(`./${entry.web_frame_path}`);
        const [state, cd] = await Promise.all([
          bundleLayer(meta.state, hiddenSet, stateKey),
          bundleLayer(meta.cd, hiddenSet, cdKey),
        ]);
        // Outlines are only drawn with the silhouette toggle, so their geometry loads lazily.
        let outline = null;
        const loadOutline = () => (outline ??= bundleLayer(meta.outline, hiddenSet, stateKey).catch(() => null));
        return { entry, state, cd, cdProps: meta.cd_props || {}, loadOutline, fills: null };
      });
    } else {
      p = Promise.all([
        geojsonLayer(entry.state_feature_path || entry.feature_path, hiddenSet, stateKey),
        entry.cd_feature_path ? geojsonLayer(entry.cd_feature_path, hiddenSet, cdKey).catch(() => null) : null,
      ]).then(([state, cd]) => {
        let outline = null;
        const loadOutline = () => (outline ??= entry.state_outline_path
          ? geojsonLayer(entry.state_outline_path, hiddenSet, stateKey).catch(() => null)
          : Promise.resolve(null));
        return { entry, state, cd, cdProps: cd?.collectionProps || {}, loadOutline, fills: null };
      });
    }
    p = p.catch((err) => {
      frameCache.delete(i);
      throw err;
    });
    frameCache.set(i, p);
  }
  return frameCache.get(i);
}

function prefetchAround(i) {
  for (const j of [i + 1, i - 1, i + 2, i - 2, i + 3, i - 3]) {
    if (j >= 0 && j < timeline.length) loadFrame(j).catch(() => {});
  }
}

// Once the first frame is up, quietly load the whole (compact) timeline one Congress at a
// time, yielding between them, so scrubbing anywhere later is a pure redraw. Skipped
// without a bundle: that would mean pulling every full GeoJSON.
let preloadStarted = false;
async function preloadAll() {
  if (preloadStarted || !timeline.every((e) => e.web_frame_path)) return;
  preloadStarted = true;
  for (let j = 0; j < timeline.length; j += 1) {
    try {
      await loadFrame(j);
    } catch {
      // a frame that fails here retries on demand
    }
    await new Promise((r) => setTimeout(r, 0));
  }
  window.dispatchEvent(new Event("hexperf:preloaded"));
}

function unionBounds(items) {
  const b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  for (const it of items) {
    if (it.b.minX < b.minX) b.minX = it.b.minX;
    if (it.b.minY < b.minY) b.minY = it.b.minY;
    if (it.b.maxX > b.maxX) b.maxX = it.b.maxX;
    if (it.b.maxY > b.maxY) b.maxY = it.b.maxY;
  }
  return b;
}

function ensureLayers() {
  if (layers) return layers;
  svg.selectAll("g").remove();
  const root = svg.append("g").attr("transform", viewTransform(currentView));
  layers = {
    root,
    outline: root.append("g"),
    tiles: root.append("g"),
    borders: root.append("g"),
    cells: root.append("g"),
  };
  const showTip = (event, lines) => {
    tooltip.hidden = false;
    tooltip.style.left = `${event.offsetX + 16}px`;
    tooltip.style.top = `${event.offsetY + 16}px`;
    tooltip.innerHTML = lines.join("<br>");
  };
  layers.tiles.on("mousemove", (event) => {
    const d = event.target.__data__;
    if (!d || !drawn) return;
    const p = d.properties;
    showTip(event, [
      `<strong>${p.state_name || "Unknown"}</strong>`,
      ...(drawn.urbanRural ? [metroTooltip(p, drawn.maxRank)] : []),
      `Congress: ${drawn.frame.entry.congress_number}`,
    ]);
  });
  layers.cells.on("mousemove", (event) => {
    const d = event.target.__data__;
    if (!d || !drawn) return;
    const p = d.properties;
    showTip(event, [
      `<strong>${p.state_name || "Unknown"}</strong>`,
      `State: ${p.state_abbr || "N/A"}`,
      `Seats: ${p.house_seats ?? "N/A"}`,
      `Cells: ${p.cell_count ?? "N/A"}`,
      `Congress: ${drawn.frame.entry.congress_number}`,
    ]);
  });
  layers.outline.on("mousemove", (event) => {
    const d = event.target.__data__;
    if (!d || !drawn) return;
    const p = d.properties;
    showTip(event, [
      `<strong>${p.state_name || "Unknown"}</strong>`,
      `Seats: ${p.house_seats ?? "N/A"}`,
      `Congress: ${drawn.frame.entry.congress_number}`,
    ]);
  });
  for (const g of [layers.outline, layers.tiles, layers.cells]) g.on("mouseleave", () => { tooltip.hidden = true; });
  return layers;
}

// Keyed join that reuses <path> nodes across Congresses and writes `d` / `fill` only when
// they actually changed (seat-identical Congresses share path strings, so `d` is skipped).
function joinPaths(layer, items, cls, fills) {
  layer
    .selectAll("path")
    .data(items, (d) => d.key)
    .join((enter) => enter.append("path").attr("class", cls))
    .each(function (d) {
      if (this._d !== d.d) {
        this.setAttribute("d", d.d);
        this._d = d.d;
      }
      const f = fills ? fills[d.i] : null;
      if (fills && this._f !== f) {
        this.setAttribute("fill", f);
        this._f = f;
      }
    });
}

function renderFrame(frame, outlineItems) {
  const { entry, state, cd } = frame;
  const L = ensureLayers();
  // State Silhouettes is its own plain view: faint outlines only, districts hidden.
  const silhouettes = Boolean(outlineItems);
  const showDistricts = Boolean(showDistrictsToggle?.checked) && Boolean(cd) && !silhouettes;
  const urbanRural = showDistricts && Boolean(urbanRuralToggle?.checked);

  currentMetroTiers = showDistricts ? frame.cdProps.metro_tiers || null : null;
  window.dispatchEvent(new Event("hexdesign:frame"));
  updateReadout(entry, state);

  // Camera: ease from wherever the camera is now (mid-move if still animating) to this
  // Congress's fitted view; identical layouts give an identical target and no move.
  const targetView = computeTargetViewFromBounds(unionBounds(state));
  const viewDelta =
    Math.abs(targetView.k - currentView.k) * Math.max(width, height) +
    Math.abs(targetView.x - currentView.x) +
    Math.abs(targetView.y - currentView.y);
  if (viewDelta > 1) {
    L.root.interrupt().transition().duration(DESIGN.zoomMs).ease(d3.easeCubicInOut).attr("transform", viewTransform(targetView));
  } else if (viewDelta > 0) {
    L.root.interrupt().attr("transform", viewTransform(targetView));
  }
  currentView = targetView;

  // Fills are memoized per frame for the current design + toggles. They are computed in the
  // same layer order as before (outlines, then tiles), so the ordinal state palette assigns
  // colors in the same sequence.
  const fillKey = `${designVersion}|${showDistricts}|${urbanRural}|${Boolean(outlineItems)}`;
  if (!frame.fills || frame.fills.key !== fillKey) {
    const maxRank = urbanRural ? clusterMaxRanks(cd) : null;
    frame.fills = {
      key: fillKey,
      maxRank,
      outline: outlineItems ? outlineItems.map((it) => stateColor(it.properties.state_abbr || "unknown")) : null,
      cd: showDistricts
        ? cd.map((it) => (urbanRural ? urbanRuralColor(it.properties, maxRank) : cdColor(it.properties)))
        : null,
      state: showDistricts ? null : state.map((it) => stateColor(it.properties.state_abbr || "unknown")),
    };
  }
  const fills = frame.fills;

  joinPaths(L.outline, outlineItems ? outlineItems.filter((it) => it.d) : [], "state-outline", fills.outline);
  joinPaths(L.tiles, showDistricts ? cd : [], "cd-tile", fills.cd);
  joinPaths(L.borders, (showDistricts || silhouettes) && DESIGN.stateBorderWidth > 0 ? state : [], "state-border", null);
  joinPaths(L.cells, showDistricts || silhouettes ? [] : state, "cell", fills.state);

  drawn = { frame, urbanRural, maxRank: fills.maxRank };
  clearStatus();
  setCivilWarBanner("");
}

async function drawFrame(entry) {
  // The fast path needs the stable projection (all v5/v6 cartogram data has one).
  if (!stablePath || !isCartogramFrame(entry)) {
    layers = null;
    await drawFrameLegacy(entry);
    return;
  }
  const gen = ++drawGen;
  const i = timeline.indexOf(entry);
  const frame = await loadFrame(i);
  const outlineItems = outlineOnlyToggle?.checked ? await frame.loadOutline() : null;
  if (gen !== drawGen) return false;  // a newer frame was requested meanwhile
  renderFrame(frame, outlineItems);
  prefetchAround(i);
  preloadAll();
  return true;
}

async function drawFrameLegacy(entry) {
  const featurePath = entry.state_feature_path || entry.feature_path;
  const cdPath = entry.cd_feature_path;
  const silhouetteMode = Boolean(outlineOnlyToggle?.checked) && Boolean(entry.state_outline_path);
  const showDistricts = Boolean(showDistrictsToggle?.checked) && Boolean(cdPath) && !silhouetteMode;
  const cartogram = isCartogramFrame(entry);

  const [geo, rawOutlineGeo, cdGeo] = await Promise.all([
    cachedFetchJson(`./${featurePath}`),
    entry.state_outline_path ? cachedFetchJson(`./${entry.state_outline_path}`).catch(() => null) : Promise.resolve(null),
    showDistricts ? cachedFetchJson(`./${cdPath}`).catch(() => null) : Promise.resolve(null),
  ]);

  const congressNumber = Number(entry.congress_number);
  const hiddenSet = CIVIL_WAR_HIDDEN_BY_CONGRESS.get(congressNumber) || new Set();
  geo.features = (geo.features || []).filter((f) => !hiddenSet.has(String(f?.properties?.state_abbr || "").toUpperCase()));
  if (rawOutlineGeo && Array.isArray(rawOutlineGeo.features)) {
    rawOutlineGeo.features = rawOutlineGeo.features.filter((f) => !hiddenSet.has(String(f?.properties?.state_abbr || "").toUpperCase()));
  }
  currentMetroTiers = cdGeo?.properties?.metro_tiers || null;
  window.dispatchEvent(new Event("hexdesign:frame"));
  if (cdGeo && Array.isArray(cdGeo.features)) {
    cdGeo.features = cdGeo.features.filter((f) => !hiddenSet.has(String(f?.properties?.state_abbr || "").toUpperCase()));
  }

  updateReadout(entry, geo.features);

  // Cartogram frames use absolute WM coordinates that already respect the layout.
  // The legacy collision relax was for the old template generator only.
  const outlineGeo = rawOutlineGeo
    ? (cartogram ? rawOutlineGeo : applyCollisionLayout(rawOutlineGeo, congressNumber))
    : null;
  const showSilhouettes = Boolean(outlineOnlyToggle?.checked);
  const outlineAvailable = Boolean(outlineGeo && Array.isArray(outlineGeo.features) && outlineGeo.features.length > 0);

  // Reuse the stable projection so the viewport doesn't bounce when seat counts
  // grow / shrink across Congresses. Fall back to per-frame fit only if the
  // stable projection wasn't built (e.g., loading a non-v5 frame).
  let path;
  if (stablePath) {
    path = stablePath;
  } else {
    let fitGeo = geo;
    if (showDistricts && cdGeo && cdGeo.features?.length) fitGeo = cdGeo;
    else if (showSilhouettes && outlineAvailable) fitGeo = outlineGeo;
    const b = geometryBounds(fitGeo);
    const projected = Math.abs(b.maxX) > 1000 || Math.abs(b.minX) > 1000 || Math.abs(b.maxY) > 1000 || Math.abs(b.minY) > 1000;
    const projection = projected
      ? d3.geoIdentity().reflectY(true).fitSize([width, height], fitGeo)
      : d3.geoAlbersUsa().fitSize([width, height], fitGeo);
    path = d3.geoPath(projection);
  }

  svg.selectAll("g").remove();
  const g = svg.append("g");

  // Auto-zoom camera: start at the previous view and ease to this Congress's fitted view,
  // so frame changes read as one smooth camera move. Identical layouts (the 90 frozen
  // seat-identical transitions) produce an identical target — a perfectly still camera.
  const targetView = computeTargetView(geo);
  g.attr("transform", viewTransform(currentView));
  const viewDelta =
    Math.abs(targetView.k - currentView.k) * Math.max(width, height) +
    Math.abs(targetView.x - currentView.x) +
    Math.abs(targetView.y - currentView.y);
  if (viewDelta > 1) {
    g.transition().duration(DESIGN.zoomMs).ease(d3.easeCubicInOut).attr("transform", viewTransform(targetView));
  } else if (viewDelta > 0) {
    g.attr("transform", viewTransform(targetView));
  }
  currentView = targetView;

  // Layer 1: state silhouettes (faint backdrop) when toggled.
  if (showSilhouettes && outlineAvailable) {
    const outlineData = outlineGeo.features
      .map((f) => ({ f, d: path(f) }))
      .filter((x) => Boolean(x.d));
    g.selectAll("path.state-outline")
      .data(outlineData)
      .join("path")
      .attr("class", "state-outline")
      .attr("d", (d) => d.d)
      .attr("fill", (d) => stateColor(d.f.properties.state_abbr || "unknown"));
  }

  // Layer 2: per-CD pentahex tiles when toggled (v5 only).
  if (showDistricts && cdGeo && cdGeo.features?.length) {
    const urbanRural = Boolean(urbanRuralToggle?.checked);
    const maxRank = urbanRural ? clusterMaxRanks(cdGeo.features) : null;
    g.selectAll("path.cd-tile")
      .data(cdGeo.features)
      .join("path")
      .attr("class", "cd-tile")
      .attr("d", path)
      .attr("fill", (d) => (urbanRural ? urbanRuralColor(d.properties, maxRank) : cdColor(d.properties)))
      .on("mousemove", (event, d) => {
        tooltip.hidden = false;
        tooltip.style.left = `${event.offsetX + 16}px`;
        tooltip.style.top = `${event.offsetY + 16}px`;
        tooltip.innerHTML = [
          `<strong>${d.properties.state_name || "Unknown"}</strong>`,
          ...(urbanRural
            ? [metroTooltip(d.properties, maxRank)]
            : []),
          `Congress: ${entry.congress_number}`,
        ].join("<br>");
      })
      .on("mouseleave", () => { tooltip.hidden = true; });
    if (DESIGN.stateBorderWidth > 0) {
      g.selectAll("path.state-border")
        .data(geo.features)
        .join("path")
        .attr("class", "state-border")
        .attr("d", path);
    }
  } else if (!(showSilhouettes && outlineAvailable)) {
    // Layer 2 fallback: state-level polyhex fill.
    g.selectAll("path.cell")
      .data(geo.features)
      .join("path")
      .attr("class", "cell")
      .attr("d", path)
      .attr("fill", (d) => stateColor(d.properties.state_abbr || "unknown"))
      .on("mousemove", (event, d) => {
        tooltip.hidden = false;
        tooltip.style.left = `${event.offsetX + 16}px`;
        tooltip.style.top = `${event.offsetY + 16}px`;
        tooltip.innerHTML = [
          `<strong>${d.properties.state_name || "Unknown"}</strong>`,
          `State: ${d.properties.state_abbr || "N/A"}`,
          `Seats: ${d.properties.house_seats ?? "N/A"}`,
          `Cells: ${d.properties.cell_count ?? "N/A"}`,
          `Congress: ${entry.congress_number}`,
        ].join("<br>");
      })
      .on("mouseleave", () => { tooltip.hidden = true; });
  }

  prefetchFrame(frameIndex + 1);
  clearStatus();
  setCivilWarBanner("");
}

function ordinal(n) {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

function updateReadout(entry, features) {
  const visible = (features || []).filter((f) => Number(f?.properties?.house_seats) > 0);
  const totalSeats = visible.reduce((s, f) => s + Number(f.properties.house_seats || 0), 0);
  const stateCount = visible.length;
  let largest = null;
  for (const f of visible) {
    if (!largest || Number(f.properties.house_seats) > Number(largest.properties.house_seats)) {
      largest = f;
    }
  }
  if (readoutCongress) readoutCongress.textContent = ordinal(Number(entry.congress_number));
  if (readoutYears) {
    const sy = String(entry.start_date || "").slice(0, 4);
    const ey = String(entry.end_date || "").slice(0, 4);
    readoutYears.textContent = sy && ey ? `${sy}–${ey}` : "-";
  }
  if (readoutStates) readoutStates.textContent = String(stateCount);
  if (readoutSeats) readoutSeats.textContent = String(totalSeats);
  if (readoutLargest) {
    readoutLargest.textContent = largest
      ? `${largest.properties.state_abbr} (${largest.properties.house_seats})`
      : "-";
  }
}

// Push the CSS-side design parameters onto the map's custom properties.
function applyDesignStyles() {
  const el = document.getElementById("mapSvg");
  if (!el) return;
  const set = (k, v) => el.style.setProperty(k, String(v));
  set("--tile-opacity", DESIGN.tileOpacity);
  set("--tile-stroke", DESIGN.tileStroke);
  set("--tile-stroke-opacity", DESIGN.tileStrokeOpacity);
  set("--tile-stroke-width", DESIGN.tileStrokeWidth);
  set("--state-border", DESIGN.stateBorderColor);
  set("--state-border-width", DESIGN.stateBorderWidth);
  el.style.background = DESIGN.mapBackground;
}

// Re-render the current frame after DESIGN changed. Coalesced to one draw per ~frame so
// dragging a slider doesn't queue dozens of redraws (a timer, not requestAnimationFrame,
// which never fires in a hidden tab).
let redrawPending = false;
function redraw({ palette = false } = {}) {
  if (palette) buildStateColor();
  designVersion += 1;
  applyDesignStyles();
  if (redrawPending || !timeline.length) return;
  redrawPending = true;
  setTimeout(async () => {
    redrawPending = false;
    await setFrame(frameIndex);
  }, 16);
}
window.hexDesign = {
  DESIGN, DESIGN_DEFAULTS, PALETTES, METRO_PALETTES, redraw,
  metroTiers: () => currentMetroTiers,
};
// Hooks for web/perf.js (the ?perf benchmark harness); not part of the design contract.
let lastDrawn = { index: -1, t: 0 };
window.hexPerfHooks = {
  timeline: () => timeline,
  lastDrawn: () => lastDrawn,
  setFrame: (i) => setFrame(i),
  scrubTo: (i) => {
    range.value = String(i);
    range.dispatchEvent(new Event("input"));
  },
  // The pre-fast-path renderer, for parity checks against the new one.
  drawLegacy: async (i) => {
    layers = null;
    drawn = null;
    frameIndex = i;
    await drawFrameLegacy(timeline[i]);
  },
  // Cold = nothing loaded and no background preload (worst case: every frame on demand).
  clearCaches: () => {
    fetchCache.clear();
    frameCache.clear();
    geomCache.clear();
    preloadStarted = true;
  },
  // Time to load the whole timeline from scratch the way the background preload does.
  preload: async () => {
    window.hexPerfHooks.clearCaches();
    preloadStarted = false;
    const t0 = performance.now();
    await preloadAll();
    return performance.now() - t0;
  },
};

async function setFrame(i) {
  frameIndex = i;
  range.value = String(i);
  updateTimelineMarks();
  const entry = timeline[i];
  const shown = await drawFrame(entry);
  if (shown !== false) lastDrawn = { index: i, t: performance.now() };
}

// Slider drags fire `input` far faster than frames can be shown, so coalesce them: keep only
// the latest requested Congress and draw it on the next animation frame (a timer in a hidden
// tab, where rAF never fires). Combined with drawFrame's latest-wins token, the map always
// converges on where the thumb is instead of replaying every Congress it passed.
let scrubPending = null;
function scheduleScrub(i) {
  const first = scrubPending == null;
  scrubPending = i;
  frameIndex = i;
  if (!first) return;
  const run = () => {
    const j = scrubPending;
    scrubPending = null;
    setFrame(j).catch((err) => console.error(err));
  };
  if (document.hidden) setTimeout(run, 0);
  else requestAnimationFrame(run);
}

function setupControls() {
  range.min = "0";
  range.max = String(timeline.length - 1);
  range.value = "0";

  range.addEventListener("input", (e) => {
    stopPlayback();
    scheduleScrub(Number(e.target.value));
  });

  playBtn.addEventListener("click", () => {
    togglePlayback();
  });

  prevBtn.addEventListener("click", async () => {
    stopPlayback();
    const next = frameIndex === 0 ? timeline.length - 1 : frameIndex - 1;
    await setFrame(next);
  });

  nextBtn.addEventListener("click", async () => {
    stopPlayback();
    const next = (frameIndex + 1) % timeline.length;
    await setFrame(next);
  });

  if (outlineOnlyToggle) {
    outlineOnlyToggle.addEventListener("change", async () => {
      stopPlayback();
      await setFrame(frameIndex);
    });
  }
  if (showDistrictsToggle) {
    showDistrictsToggle.addEventListener("change", async () => {
      stopPlayback();
      await setFrame(frameIndex);
    });
  }
  if (autoZoomToggle) {
    autoZoomToggle.addEventListener("change", async () => {
      await setFrame(frameIndex);
    });
  }
  if (urbanRuralToggle) {
    urbanRuralToggle.addEventListener("change", async () => {
      await setFrame(frameIndex);
    });
  }
}

async function main() {
  setControlsEnabled(false);

  // Check file:// FIRST: under file:// the d3 <script> usually fails to load too, so
  // checking d3 first masks this far more actionable message.
  if (window.location.protocol === "file:") {
    setStatus("This app cannot run from file:// because browsers block local fetch. Start a local server: python -m http.server 8000 --directory web and open http://localhost:8000");
    return;
  }

  if (!window.d3) {
    setStatus("D3 failed to load. Ensure web/vendor/d3.min.js exists.");
    return;
  }

  svg = d3.select("#mapSvg");
  buildStateColor();
  applyDesignStyles();

  try {
    await Promise.all([loadIndex(), loadMetroColors()]);
    await buildStableProjection();
    setupControls();
    buildTimeline();
    window.addEventListener("resize", () => stackTimelineEvents());
    await setFrame(0);
    setControlsEnabled(true);
    clearStatus();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatus(msg);
    console.error(err);
  }
}

main();
