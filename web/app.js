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
  colorBy: "state",       // "state" | "metro" (metro: each metro gets its own hue across state lines)
  metroPalette: "Hashed hues",
  metroRural: "faded state", // metro mode: rural tiles as "faded state" hue or flat "grey"
  cdBlendMin: 0.10,       // plain mode: lightness blend for a state's first CD...
  cdBlendMax: 0.55,       // ...and its last (blend toward white)
  urbanAnchorBlend: 0.0,  // urban mode: blend at the metro anchor tile (0 = full state hue)
  urbanEdgeBlend: 0.30,   // blend at the outermost claimed metro tile
  urbanCurve: 1.0,        // gamma on the anchor->edge ramp (<1 lightens fast, >1 keeps the core dark longer)
  ruralBlend: 0.75,       // flat blend for rural tiles
  ruralDesat: 0.0,        // 0..1 desaturate rural tiles toward grey
  minMetroTiles: 1,       // a metro cluster drawing fewer tiles than this counts as rural
  metroDepth: 1.0,        // fraction of each cluster's outward depth counted as urban (1 = all)
  tileOpacity: 0.88,
  tileStroke: "#192328",
  tileStrokeOpacity: 0.75,
  tileStrokeWidth: 0.6,
  stateBorderWidth: 0,    // 0 = off; >0 draws state outlines over the district tiles
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
// Metro hues are keyed by a hash of the metro name, not first-seen order, so a metro keeps
// its color in every Congress and every session (Boston is the same hue in 1813 and 2025).
// Cross-state portions share a name post-1950 (NY/NJ "New York--Jersey City--Newark");
// linked-but-separately-anchored areas (SF–Oakland vs San Jose) get distinct hues.
const METRO_PALETTES = ["Hashed hues", ...Object.keys(PALETTES)];
function hashString(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}
function metroKey(props) {
  return String(props.metro_cluster || "").replace(/ \([A-Z]{2}\)$/, "");
}
function metroColor(props) {
  const h = hashString(metroKey(props));
  if (DESIGN.metroPalette === "Hashed hues") return d3.hcl((h % 3600) / 10, 62, 52).formatRgb();
  const scheme = (PALETTES[DESIGN.metroPalette] || PALETTES.Tableau10)();
  return scheme[h % scheme.length];
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
  const identity = { k: 1, x: 0, y: 0 };
  if (!stableProjection || !fitGeo) return identity;
  if (autoZoomToggle && !autoZoomToggle.checked) return identity;
  const b = geometryBounds(fitGeo);
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
  const t = (idx - 1) / total;
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

// Highest metro_rank actually drawn per state+cluster, so the gradient spans each cluster's
// real extent. metro_cluster_seats can overstate it when a walled-in cluster spills seats.
function clusterMaxRanks(features) {
  const maxRank = new Map();
  for (const f of features) {
    const p = f.properties;
    if (!p.is_metro || p.metro_rank == null) continue;
    const key = `${p.state_abbr}|${p.metro_cluster}`;
    maxRank.set(key, Math.max(maxRank.get(key) ?? 0, Number(p.metro_rank)));
  }
  return maxRank;
}

// Where this tile falls on the metro gradient (0 = anchor .. 1 = edge), or null when it
// counts as rural under the current thresholds. Thresholds only ever demote metro tiles
// to rural (the tiler's labels are the most inclusive definition), so the result is
// nested: raising minMetroTiles or lowering metroDepth peels off small metros / suburbs.
function urbanPosition(props, maxRank) {
  if (!props.is_metro) return null;
  const span = maxRank.get(`${props.state_abbr}|${props.metro_cluster}`) ?? 0;
  if (span + 1 < DESIGN.minMetroTiles) return null;
  const t = span > 0 ? Number(props.metro_rank) / span : 0;
  if (DESIGN.metroDepth < 1 && t > DESIGN.metroDepth) return null;
  const keptSpan = Math.max(DESIGN.metroDepth, 1e-9);
  return Math.min(1, t / keptSpan);
}

function urbanRuralColor(props, maxRank) {
  const byMetro = DESIGN.colorBy === "metro";
  const t = urbanPosition(props, maxRank);
  const base = byMetro && t != null ? metroColor(props) : stateColor(props.state_abbr || "unknown");
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
    const resp = await fetch(`./${path}`);
    if (!resp.ok) return;
    const geo = await resp.json();
    if (!geo?.features?.length) return;
    const b = geometryBounds(geo);
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

async function drawFrame(entry) {
  const featurePath = entry.state_feature_path || entry.feature_path;
  const cdPath = entry.cd_feature_path;
  const showDistricts = Boolean(showDistrictsToggle?.checked) && Boolean(cdPath);
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
    // Coloring by metro needs the metro labels, so it implies the urban/rural encoding.
    const urbanRural = Boolean(urbanRuralToggle?.checked) || DESIGN.colorBy === "metro";
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
          `CD ${d.properties.cd_index ?? "?"} of ${d.properties.house_seats ?? "?"}`,
          `Hexes: ${d.properties.hex_count ?? 5}${d.properties.is_boundary_tile ? " (boundary)" : ""}`,
          ...(urbanRural
            ? [urbanPosition(d.properties, maxRank) != null
                ? `Metro: ${d.properties.metro_cluster ?? "?"}`
                : d.properties.is_metro ? `Rural (below threshold; metro: ${d.properties.metro_cluster ?? "?"})` : "Rural"]
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
  } else {
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

// Re-render the current frame after DESIGN changed. Coalesced to one draw per animation
// frame so dragging a slider doesn't queue dozens of redraws.
let redrawPending = false;
function redraw({ palette = false } = {}) {
  if (palette) buildStateColor();
  applyDesignStyles();
  if (redrawPending || !timeline.length) return;
  redrawPending = true;
  requestAnimationFrame(async () => {
    redrawPending = false;
    await setFrame(frameIndex);
  });
}
window.hexDesign = { DESIGN, DESIGN_DEFAULTS, PALETTES, METRO_PALETTES, redraw };

async function setFrame(i) {
  frameIndex = i;
  range.value = String(i);
  const entry = timeline[i];
  await drawFrame(entry);
}

function setupControls() {
  range.min = "0";
  range.max = String(timeline.length - 1);
  range.value = "0";

  range.addEventListener("input", async (e) => {
    stopPlayback();
    await setFrame(Number(e.target.value));
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
    await loadIndex();
    await buildStableProjection();
    setupControls();
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
