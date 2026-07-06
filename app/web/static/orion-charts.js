// ORION charts — dependency-free SVG line/bar charts for drilldowns.
// Styling lives in orion.css (.oc-*); this module only builds geometry.
// All text goes through textContent/setAttribute — no HTML injection paths.

(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

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

  // series: [{day: "YYYY-MM-DD", value: number}]
  // options: {rolling: series, baseline: number, target: number, unit, decimals,
  //           height, bars: boolean}
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

    const width = 440;
    const height = opts.height || 190;
    const pad = { top: 12, right: 10, bottom: 22, left: 38 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    const values = series.map((p) => p.value);
    const extra = [opts.baseline, opts.target].filter((v) => v !== null && v !== undefined);
    let lo = Math.min(...values, ...extra);
    let hi = Math.max(...values, ...extra);
    if (lo === hi) { lo -= 1; hi += 1; }
    const span = hi - lo;
    lo -= span * 0.08;
    hi += span * 0.08;

    const x = (i) => pad.left + (series.length === 1 ? innerW / 2 : (i / (series.length - 1)) * innerW);
    const y = (v) => pad.top + innerH - ((v - lo) / (hi - lo)) * innerH;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });

    // area fade gradient (id is per-document; reuse if present)
    if (!document.getElementById("oc-fade")) {
      const defs = el("defs", {});
      const grad = el("linearGradient", { id: "oc-fade", x1: 0, y1: 0, x2: 0, y2: 1 });
      const stop1 = el("stop", { offset: "0%", "stop-color": "rgba(138,230,255,0.22)" });
      const stop2 = el("stop", { offset: "100%", "stop-color": "rgba(138,230,255,0)" });
      grad.appendChild(stop1);
      grad.appendChild(stop2);
      defs.appendChild(grad);
      svg.appendChild(defs);
    }

    // horizontal grid: 3 lines + labels
    for (let i = 0; i <= 2; i += 1) {
      const value = lo + ((hi - lo) * i) / 2;
      const gy = y(value);
      svg.appendChild(el("line", { class: "oc-grid", x1: pad.left, x2: width - pad.right, y1: gy, y2: gy }));
      const label = el("text", { class: "oc-axis", x: pad.left - 6, y: gy + 3, "text-anchor": "end" });
      label.textContent = niceLabel(value, opts.decimals);
      svg.appendChild(label);
    }

    // x labels: first + last date
    const first = el("text", { class: "oc-axis", x: pad.left, y: height - 6 });
    first.textContent = shortDate(series[0].day);
    svg.appendChild(first);
    if (series.length > 1) {
      const last = el("text", {
        class: "oc-axis", x: width - pad.right, y: height - 6, "text-anchor": "end",
      });
      last.textContent = shortDate(series[series.length - 1].day);
      svg.appendChild(last);
    }

    if (opts.target !== null && opts.target !== undefined) {
      const ty = y(opts.target);
      svg.appendChild(el("line", { class: "oc-target", x1: pad.left, x2: width - pad.right, y1: ty, y2: ty }));
    }

    if (opts.bars) {
      const bw = Math.max(2, Math.min(16, (innerW / series.length) * 0.6));
      series.forEach((p, i) => {
        svg.appendChild(el("rect", {
          class: "oc-bar", x: x(i) - bw / 2, y: y(Math.max(p.value, 0)),
          width: bw, height: Math.max(1, Math.abs(y(0) - y(p.value))),
          rx: 1.5,
        }));
      });
    } else {
      const points = series.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`);
      const areaPath = `M${points.join(" L")} L${x(series.length - 1).toFixed(1)},${(pad.top + innerH).toFixed(1)} L${x(0).toFixed(1)},${(pad.top + innerH).toFixed(1)} Z`;
      svg.appendChild(el("path", { class: "oc-area", d: areaPath }));
      svg.appendChild(el("polyline", { class: "oc-line", points: points.join(" ") }));

      if (opts.rolling && opts.rolling.length > 1) {
        const byDay = new Map(series.map((p, i) => [p.day, i]));
        const rollPts = opts.rolling
          .filter((p) => byDay.has(p.day))
          .map((p) => `${x(byDay.get(p.day)).toFixed(1)},${y(p.value).toFixed(1)}`);
        if (rollPts.length > 1) {
          svg.appendChild(el("polyline", { class: "oc-roll", points: rollPts.join(" ") }));
        }
      }
      const lastPoint = series[series.length - 1];
      svg.appendChild(el("circle", {
        class: "oc-dot", cx: x(series.length - 1), cy: y(lastPoint.value), r: 2.6,
      }));
    }

    container.appendChild(svg);
  }

  window.OrionCharts = { lineChart, niceLabel };
})();
