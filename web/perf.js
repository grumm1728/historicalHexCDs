// Scrub-performance benchmark harness. Inert unless the URL has ?perf. Drives app.js
// through window.hexPerfHooks and exposes window.hexPerf:
//   await hexPerf.sweep({ cold })  - draw every Congress in order, one at a time; per-frame
//                                    time includes a paint (next animation frame).
//   await hexPerf.drag({ hz })     - fire slider `input` events at `hz` across the whole
//                                    timeline like a fast drag; reports how long the map
//                                    takes to show the final Congress after the last event,
//                                    and whether it ends on the right one.
// `cold` clears the viewer's in-memory fetch cache first (the browser HTTP cache may still
// serve the bytes; parse and draw costs are always paid).
(() => {
  if (!new URLSearchParams(window.location.search).has("perf")) return;
  const hooks = () => window.hexPerfHooks;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // Wait for the next animation frame (the paint that shows the draw). rAF never fires in a
  // hidden pane, so fall back to a timer there and say so.
  let rafMissed = 0;
  const nextPaint = () =>
    new Promise((resolve) => {
      if (document.hidden) { rafMissed += 1; setTimeout(resolve, 16); return; }
      requestAnimationFrame(() => resolve());
    });
  // The display's own frame interval, measured on an idle page (the desktop pane can run at
  // 30 Hz), so fps numbers can be read against what the screen can show at all.
  async function displayHz() {
    if (document.hidden) return null;
    const ts = [];
    for (let i = 0; i < 31; i += 1) ts.push(await new Promise((r) => requestAnimationFrame(r)));
    return Math.round(1000 / ((ts[30] - ts[0]) / 30));
  }
  function stats(times) {
    const s = [...times].sort((a, b) => a - b);
    const q = (p) => s[Math.min(s.length - 1, Math.floor(p * s.length))];
    const r = (x) => Math.round(x * 10) / 10;
    return { n: s.length, p50: r(q(0.5)), p95: r(q(0.95)), max: r(s[s.length - 1]), total: r(s.reduce((a, b) => a + b, 0)) };
  }

  // jsMs = setFrame until its draw resolves (fetch + parse + DOM work); frameMs = until the
  // next animation frame after that, so 1000/frameMs.p50 is the scrub rate actually shown.
  async function sweep({ cold = false } = {}) {
    const h = hooks();
    if (cold) h.clearCaches();
    rafMissed = 0;
    const hz = await displayHz();
    const n = h.timeline().length;
    const js = [];
    const frame = [];
    const tStart = performance.now();
    for (let i = 0; i < n; i += 1) {
      const t0 = performance.now();
      await h.setFrame(i);
      js.push(performance.now() - t0);
      await nextPaint();
      frame.push(performance.now() - t0);
    }
    const fps = Math.round((n / (performance.now() - tStart)) * 1000 * 10) / 10;
    const out = { mode: cold ? "sweep-cold" : "sweep-warm", displayHz: hz, fps, jsMs: stats(js), frameMs: stats(frame), rafMissed };
    console.log("[perf]", JSON.stringify(out));
    return out;
  }

  async function drag({ hz = 60, cold = false, settleMs = 500, timeoutMs = 120000 } = {}) {
    const h = hooks();
    if (cold) h.clearCaches();
    const n = h.timeline().length;
    const drawnSeen = new Set();
    const tStart = performance.now();
    let tLast = 0;
    let tLastCall = 0;
    for (let i = 0; i < n; i += 1) {
      tLastCall = performance.now();
      h.scrubTo(i);
      tLast = performance.now();
      drawnSeen.add(h.lastDrawn().index);
      if (i < n - 1) await sleep(1000 / hz);
    }
    // Catch-up: first time the final Congress is drawn after the last input event.
    let caughtUp = null;
    while (performance.now() - tLast < timeoutMs) {
      drawnSeen.add(h.lastDrawn().index);
      if (h.lastDrawn().index === n - 1 && h.lastDrawn().t >= tLastCall) { caughtUp = Math.max(tLast, h.lastDrawn().t); break; }
      await sleep(4);
    }
    // Then make sure no stale in-flight draw overwrites it.
    await sleep(settleMs);
    const finalIndex = h.lastDrawn().index;
    const out = {
      mode: `drag-${hz}hz${cold ? "-cold" : ""}`,
      inputMs: Math.round(tLast - tStart),
      // Wall time per input event; anything above 1000/hz is main-thread time the draws
      // stole from the drag itself (the slider thumb stutters).
      msPerEvent: Math.round(((tLast - tStart) / n) * 10) / 10,
      catchUpMs: caughtUp == null ? null : Math.round(caughtUp - tLast),
      framesShownDuringDrag: drawnSeen.size,
      endsOnFinal: finalIndex === n - 1,
    };
    console.log("[perf]", JSON.stringify(out));
    return out;
  }

  async function all() {
    const results = [await sweep({ cold: true }), await sweep({ cold: false }), await drag({ hz: 60, cold: true }), await drag({ hz: 60 })];
    console.log("[perf] all", JSON.stringify(results));
    return results;
  }

  window.hexPerf = { sweep, drag, all };
  console.log("[perf] harness ready: await hexPerf.all()");
})();
