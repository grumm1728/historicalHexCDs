// Experimental design dev panel (exp/dev-panel). Edits window.hexDesign.DESIGN in place
// and asks app.js to redraw. Settings persist per browser in localStorage; "Copy JSON"
// exports them so a tuned look can be pasted back into DESIGN_DEFAULTS.
(() => {
  const api = window.hexDesign;
  if (!api) return;
  const { DESIGN, DESIGN_DEFAULTS, PALETTES, redraw } = api;
  const STORE_KEY = "hexcd.design.v1";

  // [key, label, kind, min, max, step]  — kind: range | color | palette. Strings are headings/hints.
  const SCHEMA = [
    "Color scheme",
    ["palette", "State palette", "palette"],
    ["mapBackground", "Map background", "color"],
    "Districts (plain mode)",
    ["cdBlendMin", "Lightest-first blend", "range", 0, 1, 0.01],
    ["cdBlendMax", "Lightest-last blend", "range", 0, 1, 0.01],
    "Urban / rural shading",
    ["urbanAnchorBlend", "Metro core blend", "range", 0, 1, 0.01],
    ["urbanEdgeBlend", "Metro edge blend", "range", 0, 1, 0.01],
    ["urbanCurve", "Core→edge curve", "range", 0.2, 3, 0.05],
    ["ruralBlend", "Rural blend", "range", 0, 1, 0.01],
    ["ruralDesat", "Rural desaturate", "range", 0, 1, 0.01],
    "Urban definition (thresholds)",
    "Only demotes tiles the tiler labeled metro — the tiler's top-N metro rule is the outer bound.",
    ["minMetroTiles", "Min metro size (CDs)", "range", 1, 20, 1],
    ["metroDepth", "Suburb depth kept", "range", 0, 1, 0.05],
    "Lines",
    ["tileOpacity", "Tile fill opacity", "range", 0.2, 1, 0.01],
    ["tileStroke", "District line color", "color"],
    ["tileStrokeOpacity", "District line opacity", "range", 0, 1, 0.01],
    ["tileStrokeWidth", "District line width", "range", 0, 3, 0.1],
    ["stateBorderColor", "State border color", "color"],
    ["stateBorderWidth", "State border width", "range", 0, 4, 0.1],
    "Motion & camera",
    ["playMs", "Play step (ms)", "range", 300, 4000, 50],
    ["zoomMs", "Camera ease (ms)", "range", 0, 2000, 50],
    ["viewPad", "Zoom padding", "range", 0, 0.3, 0.01],
    ["viewKmax", "Max zoom", "range", 1, 6, 0.1],
  ];

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (saved && typeof saved === "object") {
        for (const k of Object.keys(DESIGN_DEFAULTS)) if (k in saved) DESIGN[k] = saved[k];
      }
    } catch { /* storage unavailable: defaults */ }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(DESIGN)); } catch { /* ignore */ }
  }

  const fmt = (v, step) => (step >= 1 ? String(v) : Number(v).toFixed(step < 0.1 ? 2 : 1));

  const panel = document.createElement("aside");
  panel.className = "devpanel";
  panel.hidden = true;
  panel.setAttribute("aria-label", "Design tuning panel");
  const rows = new Map();

  function build() {
    panel.innerHTML = "";
    const h = document.createElement("h2");
    h.textContent = "Design (experimental)";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "×";
    close.title = "Close";
    close.addEventListener("click", () => { panel.hidden = true; });
    h.append(close);
    panel.append(h);

    let sawHeading = false;
    for (const item of SCHEMA) {
      if (typeof item === "string") {
        // First string after a heading is a hint; otherwise it's a heading.
        if (sawHeading) {
          const p = document.createElement("p");
          p.className = "hint";
          p.textContent = item;
          panel.append(p);
          sawHeading = false;
        } else {
          const h3 = document.createElement("h3");
          h3.textContent = item;
          panel.append(h3);
          sawHeading = true;
        }
        continue;
      }
      sawHeading = false;
      const [key, label, kind, min, max, step] = item;
      const row = document.createElement("div");
      row.className = "row";
      const id = `dp-${key}`;
      const lab = document.createElement("label");
      lab.htmlFor = id;
      lab.textContent = label;
      const out = document.createElement("output");
      let input;
      if (kind === "palette") {
        input = document.createElement("select");
        for (const name of Object.keys(PALETTES)) {
          const o = document.createElement("option");
          o.value = o.textContent = name;
          input.append(o);
        }
      } else {
        input = document.createElement("input");
        input.type = kind;
        if (kind === "range") Object.assign(input, { min, max, step });
      }
      input.id = id;
      input.addEventListener("input", () => {
        DESIGN[key] = kind === "range" ? Number(input.value) : input.value;
        sync(key);
        save();
        redraw({ palette: key === "palette" });
      });
      row.append(lab, input, out);
      panel.append(row);
      rows.set(key, { row, input, out, kind, step });
    }

    const actions = document.createElement("div");
    actions.className = "actions";
    const mk = (text, fn) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.addEventListener("click", fn);
      actions.append(b);
      return b;
    };
    const copyBtn = mk("Copy JSON", async () => {
      const diff = Object.fromEntries(Object.keys(DESIGN_DEFAULTS)
        .filter((k) => DESIGN[k] !== DESIGN_DEFAULTS[k]).map((k) => [k, DESIGN[k]]));
      const text = JSON.stringify(Object.keys(diff).length ? diff : DESIGN, null, 2);
      try { await navigator.clipboard.writeText(text); copyBtn.textContent = "Copied ✓"; }
      catch { window.prompt("Copy settings:", text); }
      setTimeout(() => { copyBtn.textContent = "Copy JSON"; }, 1200);
    });
    mk("Reset all", () => {
      Object.assign(DESIGN, DESIGN_DEFAULTS);
      save();
      for (const k of rows.keys()) sync(k);
      redraw({ palette: true });
    });
    panel.append(actions);
  }

  function sync(key) {
    const r = rows.get(key);
    if (!r) return;
    if (document.activeElement !== r.input) r.input.value = DESIGN[key];
    r.out.textContent = r.kind === "range" ? fmt(DESIGN[key], r.step) : "";
    r.row.classList.toggle("changed", DESIGN[key] !== DESIGN_DEFAULTS[key]);
  }

  load();
  build();
  for (const k of rows.keys()) sync(k);
  document.body.append(panel);
  redraw({ palette: true });

  const toggle = () => { panel.hidden = !panel.hidden; };
  document.getElementById("devPanelBtn")?.addEventListener("click", toggle);
  document.addEventListener("keydown", (e) => {
    if (e.key === "`" && !/input|select|textarea/i.test(e.target.tagName)) toggle();
  });
  if (new URLSearchParams(location.search).has("dev")) panel.hidden = false;
})();
