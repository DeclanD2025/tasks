// ORION charts — dependency-free SVG telemetry charts for the health views.
// Styling lives in orion.css (.oc-*); this module owns geometry + interaction.
// Composed from small pure render functions (the React model, no framework):
// each `draw*` takes data + resolved options and returns SVG nodes; nothing
// reaches outside its arguments. All text goes through textContent/setAttribute
// — there is no HTML-injection path.

(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  // ---- per-vital semantics -------------------------------------------------
  // One hue per metric, chosen by the job the number does, drawn from ORION's
  // existing token set (validated for >=3:1 contrast on the dark surface).
  // Each chart is a *single* series, so hues need only separate from the
  // surface, not from each other. `id` keys the per-metric gradient.
  const PALETTE = {
    pulse:  { stroke: "#ff8b6b", soft: "rgba(255,139,107,0.20)" },
    crit:   { stroke: "#e5737f", soft: "rgba(229,115,127,0.20)" },
    accent: { stroke: "#8ae6ff", soft: "rgba(138,230,255,0.22)" },
    good:   { stroke: "#6cd9a6", soft: "rgba(108,217,166,0.20)" },
    violet: { stroke: "#b8a4ff", soft: "rgba(184,164,255,0.20)" },
    warn:   { stroke: "#dfae6a", soft: "rgba(223,174,106,0.20)" },
    silver: { stroke: "#c8d0d8", soft: "rgba(200,208,216,0.16)" },
  };

  // Which token each metric wears. Cardio → warm; recovery/calm → cool/green;
  // mind → violet; load → amber. Anything unmapped falls back to accent.
  const METRIC_TONE = {
    resting_hr: "pulse", hrv: "good", readiness: "accent",
    sleep: "violet", sleep_debt: "warn", weight: "silver",
    vo2max: "accent", run_distance: "accent", steps: "accent",
    active_energy: "pulse", training_load: "warn",
    mindfulness: "violet", mood: "good", stress: "crit",
    blood_pressure: "crit", spo2: "accent", respiratory: "accent",
  };

  // Accepts either a metric kind (mapped via METRIC_TONE) or a direct tone name
  // ("good", "violet", …) so callers can request a tone explicitly.
  function toneFor(kind) {
    return PALETTE[METRIC_TONE[kind]] || PALETTE[kind] || PALETTE.accent;
  }

  function el(name, attrs) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attrs || {})) {
      node.setAttribute(key, value);
    }
    return node;
  }

  function niceLabel(value, decimals) {
    if (value === null || value === undefined) return "—";
    const d = decimals === 0 ? 0 : (Math.abs(value) >= 100 ? 0 : (decimals ?? 1));
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 0, maximumFractionDigits: d,
    });
  }

  function shortDate(iso) {
    const d = new Date(iso + "T00:00:00");
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  // A stable, per-document gradient for a given tone (created once, reused).
  function ensureGradient(svg, tone, id) {
    if (document.getElementById(id)) return id;
    const defs = el("defs", {});
    const grad = el("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.appendChild(el("stop", { offset: "0%", "stop-color": tone.soft }));
    grad.appendChild(el("stop", {
      offset: "100%", "stop-color": tone.soft.replace(/[\d.]+\)$/, "0)"),
    }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    return id;
  }

  // ---- scale helpers (pure) ------------------------------------------------
  function computeScale(series, extra, height, pad) {
    const values = series.map((p) => p.value);
    const extras = (extra || []).filter((v) => v !== null && v !== undefined);
    let lo = Math.min(...values, ...extras);
    let hi = Math.max(...values, ...extras);
    if (lo === hi) { lo -= 1; hi += 1; }
    const span = hi - lo;
    lo -= span * 0.10;
    hi += span * 0.12;
    const innerH = height - pad.top - pad.bottom;
    return { lo, hi, y: (v) => pad.top + innerH - ((v - lo) / (hi - lo)) * innerH };
  }

  // series: [{day:"YYYY-MM-DD", value:number}]
  // options: {kind, rolling, baseline, target, band:[lo,hi], unit, decimals,
  //           height, bars, lower_better}
  function lineChart(container, series, options) {
    const opts = options || {};
    container.replaceChildren();
    if (!series || series.length === 0) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No recorded points in this window.";
      container.appendChild(p);
      return;
    }

    const tone = toneFor(opts.kind);
    const width = 460;
    const height = opts.height || 210;
    const pad = { top: 14, right: 12, bottom: 24, left: 40 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    const band = opts.band && opts.band.length === 2 ? opts.band : null;
    const scale = computeScale(
      series,
      [opts.baseline, opts.target, band && band[0], band && band[1]],
      height, pad,
    );
    const y = scale.y;
    const x = (i) => pad.left + (series.length === 1 ? innerW / 2 : (i / (series.length - 1)) * innerW);

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", class: "oc-chart" });
    const gradId = `oc-fade-${opts.kind || "accent"}`;
    ensureGradient(svg, tone, gradId);

    // 1) normal-range band (drawn first, behind everything)
    if (band) {
      const top = y(Math.max(band[0], band[1]));
      const bot = y(Math.min(band[0], band[1]));
      svg.appendChild(el("rect", {
        class: "oc-band", x: pad.left, y: top,
        width: innerW, height: Math.max(1, bot - top),
      }));
      const bl = el("text", { class: "oc-band-label", x: width - pad.right, y: top - 4, "text-anchor": "end" });
      bl.textContent = "typical range";
      svg.appendChild(bl);
    }

    // 2) horizontal grid + y labels
    for (let i = 0; i <= 2; i += 1) {
      const value = scale.lo + ((scale.hi - scale.lo) * i) / 2;
      const gy = y(value);
      svg.appendChild(el("line", { class: "oc-grid", x1: pad.left, x2: width - pad.right, y1: gy, y2: gy }));
      const label = el("text", { class: "oc-axis", x: pad.left - 7, y: gy + 3, "text-anchor": "end" });
      label.textContent = niceLabel(value, opts.decimals);
      svg.appendChild(label);
    }

    // 3) x labels: first + last date
    const first = el("text", { class: "oc-axis", x: pad.left, y: height - 7 });
    first.textContent = shortDate(series[0].day);
    svg.appendChild(first);
    if (series.length > 1) {
      const last = el("text", { class: "oc-axis", x: width - pad.right, y: height - 7, "text-anchor": "end" });
      last.textContent = shortDate(series[series.length - 1].day);
      svg.appendChild(last);
    }

    // 4) baseline + target reference lines
    if (opts.baseline !== null && opts.baseline !== undefined) {
      svg.appendChild(el("line", {
        class: "oc-baseline", x1: pad.left, x2: width - pad.right,
        y1: y(opts.baseline), y2: y(opts.baseline),
      }));
    }
    if (opts.target !== null && opts.target !== undefined) {
      svg.appendChild(el("line", {
        class: "oc-target", x1: pad.left, x2: width - pad.right,
        y1: y(opts.target), y2: y(opts.target),
      }));
    }

    // 5) the data
    if (opts.bars) {
      drawBars(svg, series, x, y, innerW, tone);
    } else {
      drawArea(svg, series, x, y, innerH, pad, gradId, tone);
      drawRolling(svg, series, opts.rolling, x, y);
      drawExtremes(svg, series, x, y, opts.decimals, tone);
    }

    container.appendChild(svg);
    if (!opts.bars && series.length > 1) {
      attachCrosshair(container, svg, series, { x, y, width, height, pad, tone, opts });
    }
  }

  // ---- data-mark render functions -----------------------------------------
  function drawArea(svg, series, x, y, innerH, pad, gradId, tone) {
    const pts = series.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`);
    const base = (pad.top + innerH).toFixed(1);
    const areaPath = `M${pts.join(" L")} L${x(series.length - 1).toFixed(1)},${base} L${x(0).toFixed(1)},${base} Z`;
    const area = el("path", { class: "oc-area", d: areaPath, fill: `url(#${gradId})` });
    svg.appendChild(area);
    const line = el("polyline", { class: "oc-line", points: pts.join(" "), stroke: tone.stroke });
    svg.appendChild(line);
  }

  function drawRolling(svg, series, rolling, x, y) {
    if (!rolling || rolling.length <= 1) return;
    const byDay = new Map(series.map((p, i) => [p.day, i]));
    const rollPts = rolling
      .filter((p) => byDay.has(p.day))
      .map((p) => `${x(byDay.get(p.day)).toFixed(1)},${y(p.value).toFixed(1)}`);
    if (rollPts.length > 1) {
      svg.appendChild(el("polyline", { class: "oc-roll", points: rollPts.join(" ") }));
    }
  }

  // Min, max and latest markers — the three points a reader actually wants.
  function drawExtremes(svg, series, x, y, decimals, tone) {
    let loI = 0, hiI = 0;
    series.forEach((p, i) => {
      if (p.value < series[loI].value) loI = i;
      if (p.value > series[hiI].value) hiI = i;
    });
    const lastI = series.length - 1;
    const marker = (i, cls) => {
      if (i === lastI) return;
      svg.appendChild(el("circle", { class: `oc-extreme ${cls}`, cx: x(i), cy: y(series[i].value), r: 3 }));
    };
    if (series.length > 4) { marker(hiI, "hi"); marker(loI, "lo"); }

    // latest: filled dot with a surface ring + glow, plus a value label
    svg.appendChild(el("circle", { class: "oc-dot-ring", cx: x(lastI), cy: y(series[lastI].value), r: 5.5 }));
    const dot = el("circle", { class: "oc-dot", cx: x(lastI), cy: y(series[lastI].value), r: 3.4 });
    dot.setAttribute("fill", tone.stroke);
    svg.appendChild(dot);
  }

  function drawBars(svg, series, x, y, innerW, tone) {
    const bw = Math.max(2, Math.min(18, (innerW / series.length) * 0.62));
    const lastI = series.length - 1;
    const zero = y(0);
    series.forEach((p, i) => {
      const rect = el("rect", {
        class: `oc-bar ${i === lastI ? "current" : ""}`.trim(),
        x: x(i) - bw / 2, y: y(Math.max(p.value, 0)),
        width: bw, height: Math.max(1, Math.abs(zero - y(p.value))),
        rx: 2,
      });
      rect.setAttribute("fill", i === lastI ? tone.stroke : tone.soft);
      svg.appendChild(rect);
    });
  }

  // ---- hover crosshair -----------------------------------------------------
  // A vertical guide + focus dot + floating readout that tracks the nearest
  // point. Pointer-driven, keyboard-safe (the SVG stays role=img for AT; the
  // readout is supplementary, and the value is always in the drawer header).
  function attachCrosshair(container, svg, series, ctx) {
    const { x, y, width, height, pad, tone, opts } = ctx;
    const guide = el("line", { class: "oc-cross", x1: 0, x2: 0, y1: pad.top, y2: height - pad.bottom, opacity: 0 });
    const focus = el("circle", { class: "oc-focus", r: 4, opacity: 0 });
    focus.setAttribute("stroke", tone.stroke);
    svg.appendChild(guide);
    svg.appendChild(focus);

    const readout = make("div", "oc-readout");
    readout.hidden = true;
    container.appendChild(readout);
    container.classList.add("oc-interactive");

    const nearest = (px) => {
      const innerW = width - pad.left - pad.right;
      const rel = (px - pad.left) / innerW;
      return Math.max(0, Math.min(series.length - 1, Math.round(rel * (series.length - 1))));
    };

    function move(clientX) {
      const rect = svg.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * width;
      const i = nearest(px);
      const p = series[i];
      const cx = x(i), cy = y(p.value);
      guide.setAttribute("x1", cx); guide.setAttribute("x2", cx); guide.setAttribute("opacity", 1);
      focus.setAttribute("cx", cx); focus.setAttribute("cy", cy); focus.setAttribute("opacity", 1);
      readout.hidden = false;
      readout.replaceChildren(
        make("span", "d", shortDate(p.day)),
        make("span", "v", `${niceLabel(p.value, opts.decimals)}${opts.unit ? " " + opts.unit : ""}`),
      );
      // position readout above the point, clamped to the container
      const frac = cx / width;
      readout.style.left = `${Math.max(4, Math.min(88, frac * 100 - 6))}%`;
    }

    function leave() {
      guide.setAttribute("opacity", 0);
      focus.setAttribute("opacity", 0);
      readout.hidden = true;
    }

    svg.addEventListener("pointermove", (e) => move(e.clientX));
    svg.addEventListener("pointerleave", leave);
    svg.style.touchAction = "pan-y";
  }

  // ---- vital sparkline (for the metric cards) ------------------------------
  // A richer replacement for the flat 28px polyline: gradient wash, tone by
  // metric, a glowing latest dot. `values` is a bare number[] (card series).
  function vitalSparkline(values, kind) {
    const tone = toneFor(kind);
    const w = 100, h = 30;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "oc-spark", preserveAspectRatio: "none", "aria-hidden": "true" });
    const clean = (values || []).filter((v) => typeof v === "number" && !Number.isNaN(v));
    if (clean.length < 2) return svg;

    const lo = Math.min(...clean), hi = Math.max(...clean);
    const span = hi - lo || 1;
    const x = (i) => (i / (clean.length - 1)) * w;
    const y = (v) => h - 3 - ((v - lo) / span) * (h - 6);

    const gradId = `oc-spark-${kind || "accent"}`;
    ensureGradient(svg, tone, gradId);
    const pts = clean.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    svg.appendChild(el("path", {
      class: "oc-spark-area", fill: `url(#${gradId})`,
      d: `M${pts.join(" L")} L${w},${h} L0,${h} Z`,
    }));
    const line = el("polyline", { class: "oc-spark-line", points: pts.join(" ") });
    line.setAttribute("stroke", tone.stroke);
    svg.appendChild(line);
    const dot = el("circle", { class: "oc-spark-dot", cx: x(clean.length - 1), cy: y(clean[clean.length - 1]), r: 2.2 });
    dot.setAttribute("fill", tone.stroke);
    svg.appendChild(dot);
    return svg;
  }

  // ---- trend chart (bare number[] over N periods, no dates) ----------------
  // For the Stoic/Mind trends tab: renders a 0..100-ish index series as a toned
  // area with the mean as a baseline and the latest point labelled. Reuses
  // lineChart by synthesising sequential day keys.
  function trendChart(container, values, opts) {
    const o = opts || {};
    const clean = (values || []).filter((v) => typeof v === "number" && !Number.isNaN(v));
    container.replaceChildren();
    if (clean.length < 2) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "Not enough history yet — keep logging and the line fills in.";
      container.appendChild(p);
      return;
    }
    const today = new Date();
    const series = clean.map((v, i) => {
      const d = new Date(today);
      d.setDate(today.getDate() - (clean.length - 1 - i));
      return { day: d.toISOString().slice(0, 10), value: v };
    });
    const mean = clean.reduce((a, b) => a + b, 0) / clean.length;
    lineChart(container, series, {
      kind: o.kind || "accent",
      unit: o.unit || "",
      baseline: Number(mean.toFixed(1)),
      decimals: o.decimals ?? 0,
      height: o.height || 150,
    });
  }

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  window.OrionCharts = { lineChart, vitalSparkline, trendChart, niceLabel, toneFor };
})();
