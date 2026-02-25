const statusEl = document.getElementById("statusMessage");
const playBtn = document.getElementById("playBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const range = document.getElementById("congressRange");
const label = document.getElementById("congressLabel");
const tooltip = document.getElementById("tooltip");

const width = 960;
const height = 600;

let timeline = [];
let frameIndex = 0;
let timer = null;
let svg;
let stateColor;

function setStatus(message) {
  statusEl.hidden = false;
  statusEl.textContent = message;
}

function clearStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
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

async function drawFrame(entry) {
  const featurePath = entry.state_feature_path || entry.feature_path;
  const resp = await fetch(`./${featurePath}`);
  if (!resp.ok) {
    throw new Error(`Failed to load ${featurePath}`);
  }
  const geo = await resp.json();

  const projection = d3.geoAlbersUsa().fitSize([width, height], geo);
  const path = d3.geoPath(projection);

  svg.selectAll("g").remove();
  const g = svg.append("g");

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
    .on("mouseleave", () => {
      tooltip.hidden = true;
    });
}

async function setFrame(i) {
  frameIndex = i;
  range.value = String(i);
  const entry = timeline[i];
  label.textContent = `${entry.congress_number}th Congress (${entry.start_date} to ${entry.end_date})`;
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
