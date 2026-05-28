const statusEl = document.getElementById("statusMessage");
const playBtn = document.getElementById("playBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const range = document.getElementById("congressRange");
const label = document.getElementById("congressLabel");
const tooltip = document.getElementById("tooltip");
const outlineOnlyToggle = document.getElementById("outlineOnlyToggle");
const showDistrictsToggle = document.getElementById("showDistrictsToggle");
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
// Distinguish CDs within a state by hashing state+cd_index into d3's category palette,
// with a stable per-state base hue overlay so adjacent CDs in the same state look related.
function cdColor(props) {
  const base = stateColor(props.state_abbr || "unknown");
  // Modulate base luminance by cd_index so adjacent CDs in the same state differ visibly.
  const idx = Number(props.cd_index) || 1;
  const total = Math.max(1, Number(props.house_seats) || 1);
  const t = (idx - 1) / total;
  // Blend base with white by 0..0.45 across CDs.
  try {
    const c = d3.color(base);
    if (!c) return base;
    const mix = 0.10 + 0.45 * t;
    c.r = Math.round(c.r + (255 - c.r) * mix);
    c.g = Math.round(c.g + (255 - c.g) * mix);
    c.b = Math.round(c.b + (255 - c.b) * mix);
    return c.formatRgb();
  } catch {
    return base;
  }
}
const outlineGeometryCache = new Map();
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
  }, 1300);
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
  const v5Frames = timeline.filter((e) => String(e.generator_version || "").startsWith("v5") && e.cd_feature_path);
  const ref = v5Frames.length
    ? v5Frames.reduce((a, b) => ((a.cd_feature_count || 0) >= (b.cd_feature_count || 0) ? a : b))
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

function isV5Frame(entry) {
  return String(entry?.generator_version || "").startsWith("v5");
}

async function drawFrame(entry) {
  const featurePath = entry.state_feature_path || entry.feature_path;
  const cdPath = entry.cd_feature_path;
  const showDistricts = Boolean(showDistrictsToggle?.checked) && Boolean(cdPath);
  const v5 = isV5Frame(entry);

  const fetches = [fetch(`./${featurePath}`)];
  fetches.push(entry.state_outline_path ? fetch(`./${entry.state_outline_path}`) : Promise.resolve(null));
  fetches.push(showDistricts ? fetch(`./${cdPath}`) : Promise.resolve(null));
  const [cellResp, outlineResp, cdResp] = await Promise.all(fetches);

  if (!cellResp.ok) throw new Error(`Failed to load ${featurePath}`);
  const geo = await cellResp.json();
  const rawOutlineGeo = outlineResp && outlineResp.ok ? await outlineResp.json() : null;
  const cdGeo = cdResp && cdResp.ok ? await cdResp.json() : null;

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

  // v5 uses absolute WM coordinates that already respect the cartogram layout.
  // The legacy collision relax was for the old template generator only.
  const outlineGeo = rawOutlineGeo
    ? (v5 ? rawOutlineGeo : applyCollisionLayout(rawOutlineGeo, congressNumber))
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
    g.selectAll("path.cd-tile")
      .data(cdGeo.features)
      .join("path")
      .attr("class", "cd-tile")
      .attr("d", path)
      .attr("fill", (d) => cdColor(d.properties))
      .on("mousemove", (event, d) => {
        tooltip.hidden = false;
        tooltip.style.left = `${event.offsetX + 16}px`;
        tooltip.style.top = `${event.offsetY + 16}px`;
        tooltip.innerHTML = [
          `<strong>${d.properties.state_name || "Unknown"}</strong>`,
          `CD ${d.properties.cd_index ?? "?"} of ${d.properties.house_seats ?? "?"}`,
          `Hexes: ${d.properties.hex_count ?? 5}${d.properties.is_boundary_tile ? " (boundary)" : ""}`,
          `Congress: ${entry.congress_number}`,
        ].join("<br>");
      })
      .on("mouseleave", () => { tooltip.hidden = true; });
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

async function setFrame(i) {
  frameIndex = i;
  range.value = String(i);
  const entry = timeline[i];
  label.textContent = `${ordinal(Number(entry.congress_number))} Congress (${entry.start_date} to ${entry.end_date})`;
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
}

async function main() {
  setControlsEnabled(false);

  if (!window.d3) {
    setStatus("D3 failed to load. Ensure web/vendor/d3.min.js exists.");
    return;
  }

  if (window.location.protocol === "file:") {
    setStatus("This app cannot run from file:// because browsers block local fetch. Start a local server: python -m http.server 8000 --directory web and open http://localhost:8000");
    return;
  }

  svg = d3.select("#mapSvg");
  stateColor = d3.scaleOrdinal(d3.schemeTableau10);

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
