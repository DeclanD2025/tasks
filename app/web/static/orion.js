// ORION web — CSP-safe behaviour, PWA registration, and offline write queue.

const DB_NAME = "orion-offline";
const DB_VERSION = 1;
const QUEUE_STORE = "queuedWrites";
const QUEUE_HEADER = { "X-Orion-Queue": "1", "X-Requested-With": "fetch" };

let syncInFlight = false;

function statusEl() {
  return document.getElementById("sync-status");
}

function setSyncStatus(message, tone = "") {
  const el = statusEl();
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    el.className = "sync-status";
    return;
  }
  el.hidden = false;
  el.textContent = message;
  el.className = `sync-status ${tone}`.trim();
}

function openQueueDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(QUEUE_STORE)) {
        const store = db.createObjectStore(QUEUE_STORE, { keyPath: "id" });
        store.createIndex("createdAt", "createdAt");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(mode, callback) {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, mode);
    const store = tx.objectStore(QUEUE_STORE);
    let value;
    tx.oncomplete = () => {
      db.close();
      resolve(value);
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
    value = callback(store);
  });
}

function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function queueCount() {
  return withStore("readonly", (store) => requestToPromise(store.count()));
}

async function queuedItems() {
  return withStore("readonly", (store) => requestToPromise(store.getAll()));
}

async function deleteQueued(id) {
  return withStore("readwrite", (store) => store.delete(id));
}

function mutationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `orion-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function ensureMutationInput(form) {
  let input = form.querySelector('input[name="client_mutation_id"]');
  if (!input) {
    input = document.createElement("input");
    input.type = "hidden";
    input.name = "client_mutation_id";
    form.appendChild(input);
  }
  if (!input.value) input.value = mutationId();
  return input.value;
}

function formEntries(form) {
  return Array.from(new FormData(form).entries()).map(([name, value]) => [
    name,
    typeof File !== "undefined" && value instanceof File ? value.name : String(value),
  ]);
}

function formDataFromEntries(entries) {
  const body = new FormData();
  entries.forEach(([name, value]) => body.append(name, value));
  return body;
}

async function enqueueForm(form) {
  const id = ensureMutationInput(form);
  const payload = {
    id,
    action: form.action,
    method: (form.method || "post").toUpperCase(),
    label: form.dataset.offlineLabel || "entry",
    entries: formEntries(form),
    createdAt: Date.now(),
  };
  await withStore("readwrite", (store) => store.put(payload));
  const count = await queueCount();
  setSyncStatus(`${count} ${count === 1 ? "entry" : "entries"} queued for sync`, "queued");
  return payload;
}

async function postEntries(item) {
  const response = await fetch(item.action, {
    method: item.method || "POST",
    body: formDataFromEntries(item.entries),
    headers: QUEUE_HEADER,
    credentials: "same-origin",
  });
  if (response.status === 401) return { ok: false, loginRequired: true };
  if (!response.ok) return { ok: false };
  const payload = await response.json().catch(() => ({}));
  return { ok: payload.status === "ok", location: payload.location };
}

async function syncQueue({ redirect = false } = {}) {
  if (syncInFlight || !navigator.onLine) return;
  syncInFlight = true;
  try {
    const items = (await queuedItems()).sort((a, b) => a.createdAt - b.createdAt);
    if (!items.length) {
      setSyncStatus("");
      return;
    }
    setSyncStatus(`Syncing ${items.length} queued ${items.length === 1 ? "entry" : "entries"}`, "syncing");
    let lastLocation = "";
    for (const item of items) {
      const result = await postEntries(item);
      if (result.loginRequired) {
        setSyncStatus("Unlock Orion to sync queued entries", "queued");
        return;
      }
      if (!result.ok) {
        setSyncStatus("Sync paused; will retry when connection returns", "queued");
        return;
      }
      await deleteQueued(item.id);
      lastLocation = result.location || lastLocation;
    }
    setSyncStatus("Queued entries synced", "ok");
    window.setTimeout(() => setSyncStatus(""), 2500);
    if (redirect && lastLocation) window.location.assign(lastLocation);
  } catch {
    const count = await queueCount().catch(() => 0);
    if (count) setSyncStatus(`${count} queued; sync will retry`, "queued");
  } finally {
    syncInFlight = false;
  }
}

async function submitQueuedForm(form) {
  ensureMutationInput(form);
  const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const item = {
      action: form.action,
      method: (form.method || "post").toUpperCase(),
      entries: formEntries(form),
    };
    if (navigator.onLine) {
      const result = await postEntries(item);
      if (result.ok) {
        window.location.assign(result.location || form.action);
        return;
      }
      if (result.loginRequired) {
        await enqueueForm(form);
        window.location.assign("/login");
        return;
      }
    }
    await enqueueForm(form);
    if (!form.matches("[data-keep-values]")) form.reset();
  } catch {
    await enqueueForm(form);
    if (!form.matches("[data-keep-values]")) form.reset();
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function syncRangeInput(input) {
  const value = Number(input.value || input.min || 0);
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const output = input.closest(".range-row, .focus-range-field")?.querySelector("output");
  const label = input.closest(".focus-range-field")?.querySelector(".focus-range-readout b");
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  input.style.setProperty("--range-pct", `${pct}%`);
  if (output) output.value = input.value;
  if (label) label.textContent = input.getAttribute(`data-label-${input.value}`) || "";
}

// Keep range sliders and their readouts in sync.
document.addEventListener("input", (event) => {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.type === "range") syncRangeInput(input);
});

document.querySelectorAll('input[type="range"]').forEach(syncRangeInput);

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-offline-queue]")) return;
  event.preventDefault();
  submitQueuedForm(form);
});

let restTimer = null;

function formatSeconds(total) {
  const value = Math.max(0, Math.ceil(total));
  const minutes = Math.floor(value / 60).toString().padStart(2, "0");
  const seconds = (value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function startRest(seconds) {
  const pill = document.querySelector("[data-rest-pill]");
  const remaining = document.querySelector("[data-rest-remaining]");
  if (!pill || !remaining) return;
  const end = Date.now() + seconds * 1000;
  pill.hidden = false;
  window.clearInterval(restTimer);
  const tick = () => {
    const left = Math.max(0, (end - Date.now()) / 1000);
    remaining.textContent = formatSeconds(left);
    if (left <= 0) {
      window.clearInterval(restTimer);
      setSyncStatus("Rest complete", "ok");
      window.setTimeout(() => setSyncStatus(""), 2200);
      pill.hidden = true;
    }
  };
  tick();
  restTimer = window.setInterval(tick, 500);
}

document.addEventListener("click", (event) => {
  const timerButton = event.target.closest?.("[data-rest-seconds]");
  if (timerButton) startRest(Number(timerButton.dataset.restSeconds || 120));
  if (event.target.matches?.("[data-rest-stop]")) {
    window.clearInterval(restTimer);
    const pill = document.querySelector("[data-rest-pill]");
    if (pill) pill.hidden = true;
  }
});

// Draw the orbital score arc on load (CSS transition does the easing).
document.addEventListener("DOMContentLoaded", async () => {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  }

  const count = await queueCount().catch(() => 0);
  if (count) setSyncStatus(`${count} queued for sync`, "queued");
  syncQueue();

  const activeWorkout = document.querySelector("[data-started-at]");
  const timer = document.querySelector("[data-workout-timer]");
  if (activeWorkout && timer) {
    const start = new Date(activeWorkout.dataset.startedAt).getTime();
    window.setInterval(() => {
      const mins = Math.max(0, Math.floor((Date.now() - start) / 60000));
      timer.textContent = `${mins}m`;
    }, 15000);
  }

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll(".ring .arc").forEach((arc) => {
    const target = arc.getAttribute("stroke-dasharray");
    if (!target) return;
    const total = target.split(" ")[1];
    arc.setAttribute("stroke-dasharray", `0 ${total}`);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => arc.setAttribute("stroke-dasharray", target));
    });
  });
});

window.addEventListener("online", () => syncQueue({ redirect: false }));
window.addEventListener("focus", () => syncQueue({ redirect: false }));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") syncQueue({ redirect: false });
});

// ═══════════════════════════════════════════════════════════════ v2 cockpit
// More-sheet, detail drawer, weather signal, scale hints, meditation timer,
// nutrition search. All DOM building uses textContent — no injection paths.

function qs(sel, root) { return (root || document).querySelector(sel); }
function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ------------------------------------------------------------ more sheet
(function moreSheet() {
  function close() {
    const sheet = qs("#more-sheet");
    const backdrop = qs("[data-sheet-backdrop]");
    if (sheet) sheet.hidden = true;
    if (backdrop) backdrop.hidden = true;
    qs("[data-more-toggle]")?.setAttribute("aria-expanded", "false");
  }

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest?.("[data-more-toggle]");
    const sheet = qs("#more-sheet");
    const backdrop = qs("[data-sheet-backdrop]");
    if (!sheet || !backdrop) return;

    if (toggle) {
      const open = sheet.hidden;  // opening now?
      sheet.hidden = !open;
      backdrop.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      return;
    }
    // A tap on the backdrop, or anywhere that isn't inside the open sheet,
    // dismisses it. Links inside the sheet navigate and are left alone.
    if (!sheet.hidden && !event.target.closest("#more-sheet")) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
  });
  // Safety net: never let the sheet survive a page transition.
  window.addEventListener("pageshow", close);
})();

// ---------------------------------------------------------- detail drawer
const Drawer = (() => {
  let lastFocus = null;

  function root() { return qs("[data-drawer]"); }
  function body() { return qs("[data-drawer-body]"); }

  function open() {
    const drawer = root();
    const backdrop = qs("[data-drawer-backdrop]");
    if (!drawer) return;
    lastFocus = document.activeElement;
    drawer.hidden = false;
    backdrop.hidden = false;
    body().replaceChildren(make("div", "drawer-loading", "Reading telemetry…"));
    qs("[data-drawer-close]")?.focus();
  }

  function close() {
    const drawer = root();
    const backdrop = qs("[data-drawer-backdrop]");
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    backdrop.hidden = true;
    if (lastFocus?.focus) lastFocus.focus();
  }

  function section(title, text) {
    const wrap = make("div", "d-section");
    wrap.appendChild(make("span", "k", title));
    const p = make("p", "", text);
    wrap.appendChild(p);
    return wrap;
  }

  function renderDetail(detail, days) {
    const container = body();
    container.replaceChildren();

    container.appendChild(make("h2", "d-title", detail.title));

    const latest = make("div", "d-latest");
    const value = detail.latest === null || detail.latest === undefined
      ? "—" : window.OrionCharts.niceLabel(detail.latest, detail.decimals);
    latest.appendChild(make("b", "", value));
    if (detail.unit) latest.appendChild(make("span", "unit", detail.unit));
    container.appendChild(latest);

    if (detail.baseline7 !== null && detail.baseline7 !== undefined && detail.latest !== null) {
      const diff = detail.latest - detail.baseline7;
      const better = detail.lower_better ? diff < 0 : diff > 0;
      const tone = Math.abs(diff) < Math.abs(detail.baseline7) * 0.03 ? "" : (better ? "good" : "watch");
      const line = make("div", "d-baseline");
      const span = make("span", tone,
        `${diff >= 0 ? "+" : "−"}${window.OrionCharts.niceLabel(Math.abs(diff), detail.decimals)} vs 7-day ${window.OrionCharts.niceLabel(detail.baseline7, detail.decimals)}`);
      line.appendChild(span);
      if (detail.baseline30 !== null && detail.baseline30 !== undefined) {
        line.appendChild(document.createTextNode(`  ·  30-day ${window.OrionCharts.niceLabel(detail.baseline30, detail.decimals)}`));
      }
      container.appendChild(line);
    }

    if (detail.series && detail.series.length) {
      const ranges = make("div", "d-ranges");
      [7, 30, 90].forEach((r) => {
        const btn = make("button", r === days ? "active" : "", `${r}d`);
        btn.type = "button";
        btn.addEventListener("click", () => load(detail.kind, r));
        ranges.appendChild(btn);
      });
      container.appendChild(ranges);

      const chart = make("div", "d-chart");
      container.appendChild(chart);
      window.OrionCharts.lineChart(chart, detail.series, {
        kind: detail.kind,
        unit: detail.unit,
        rolling: detail.rolling7,
        baseline: detail.baseline30,
        band: detail.band,
        lower_better: detail.lower_better,
        decimals: detail.decimals,
        bars: detail.kind === "training_load" || detail.kind === "mindfulness",
      });
    } else if (detail.empty) {
      const emptyNote = section("No data yet", detail.missing_action || "");
      container.appendChild(emptyNote);
    }

    if (detail.facts && detail.facts.length) {
      const wrap = make("div", "d-section");
      wrap.appendChild(make("span", "k", "The numbers behind it"));
      const facts = make("div", "d-facts");
      detail.facts.forEach((fact) => {
        const row = make("div", "d-fact");
        row.appendChild(make("span", "fk", fact.label));
        row.appendChild(make("span", "fv", fact.value));
        if (fact.detail) row.appendChild(make("span", "fd", fact.detail));
        facts.appendChild(row);
      });
      wrap.appendChild(facts);
      container.appendChild(wrap);
    }

    if (detail.meaning) container.appendChild(section("What this means", detail.meaning));
    if (detail.how) container.appendChild(section("How it's calculated", detail.how));
    if (detail.caveat) container.appendChild(section("Caveat", detail.caveat));

    if (detail.related && detail.related.length) {
      const wrap = make("div", "d-section");
      wrap.appendChild(make("span", "k", "Related"));
      const chips = make("div", "d-related");
      detail.related.forEach((rel) => {
        const chip = make("button", "", rel.title);
        chip.type = "button";
        chip.addEventListener("click", () => load(rel.kind, 90));
        chips.appendChild(chip);
      });
      wrap.appendChild(chips);
      container.appendChild(wrap);
    }

    const meta = make("div", "d-meta");
    if (detail.source) meta.appendChild(make("span", "", `source: ${detail.source}`));
    if (detail.freshness) meta.appendChild(make("span", "", `latest: ${detail.freshness}`));
    container.appendChild(meta);
  }

  async function load(kind, days) {
    try {
      const response = await fetch(`/api/detail/${kind}?days=${days}`, { credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      renderDetail(await response.json(), days);
    } catch {
      body().replaceChildren(make("div", "drawer-loading", "Telemetry unavailable. Try again."));
    }
  }

  function show(kind) { open(); load(kind, 90); }

  // --------------------------------------------------------- weather drawer
  function weatherRow(label, value) {
    const row = make("div", "d-fact");
    row.appendChild(make("span", "fk", label));
    row.appendChild(make("span", "fv", value));
    return row;
  }

  async function showWeather() {
    open();
    const container = body();
    try {
      const [weatherRes, airRes] = await Promise.all([
        fetch("/api/signals/weather", { credentials: "same-origin" }),
        fetch("/api/signals/air", { credentials: "same-origin" }),
      ]);
      const weather = await weatherRes.json();
      const air = airRes.ok ? await airRes.json() : { ok: false };
      container.replaceChildren();

      container.appendChild(make("h2", "d-title", weather.location || "Weather"));
      if (!weather.ok) {
        container.appendChild(section("Signal unavailable",
          "Open-Meteo could not be reached. Ambient context only — nothing else in ORION depends on it."));
        return;
      }
      updatePill(weather);
      const current = weather.data.current || {};
      const latest = make("div", "d-latest");
      latest.appendChild(make("b", "", `${Math.round(current.temperature_2m)}°`));
      latest.appendChild(make("span", "unit",
        `${weather.summary ? weather.summary.label : ""} · feels ${Math.round(current.apparent_temperature)}°`));
      container.appendChild(latest);

      const hourly = weather.data.hourly || {};
      const times = hourly.time || [];
      const nowIso = new Date().toISOString().slice(0, 13);
      const startIndex = times.findIndex((t) => t.slice(0, 13) >= nowIso);
      if (startIndex >= 0) {
        const wrap = make("div", "d-section");
        wrap.appendChild(make("span", "k", "Next hours"));
        const facts = make("div", "d-facts");
        for (let i = startIndex; i < Math.min(startIndex + 6, times.length); i += 1) {
          const hour = times[i].slice(11, 16);
          const temp = Math.round(hourly.temperature_2m?.[i] ?? 0);
          const rain = hourly.precipitation_probability?.[i];
          facts.appendChild(weatherRow(hour,
            `${temp}°${rain !== null && rain !== undefined ? ` · ${rain}% rain` : ""}`));
        }
        wrap.appendChild(facts);
        container.appendChild(wrap);
      }

      const daily = weather.data.daily || {};
      if (daily.time && daily.time.length > 1) {
        const wrap = make("div", "d-section");
        wrap.appendChild(make("span", "k", "Tomorrow"));
        const facts = make("div", "d-facts");
        facts.appendChild(weatherRow("Range",
          `${Math.round(daily.temperature_2m_min[1])}° – ${Math.round(daily.temperature_2m_max[1])}°`));
        if (daily.precipitation_probability_max) {
          facts.appendChild(weatherRow("Rain chance", `${daily.precipitation_probability_max[1]}%`));
        }
        if (daily.uv_index_max) facts.appendChild(weatherRow("UV max", String(daily.uv_index_max[1])));
        if (daily.sunrise && daily.sunset) {
          facts.appendChild(weatherRow("Light",
            `${daily.sunrise[1].slice(11, 16)} → ${daily.sunset[1].slice(11, 16)}`));
        }
        wrap.appendChild(facts);
        container.appendChild(wrap);
      }

      const windWrap = make("div", "d-section");
      windWrap.appendChild(make("span", "k", "Now"));
      const windFacts = make("div", "d-facts");
      if (current.wind_speed_10m !== undefined) {
        windFacts.appendChild(weatherRow("Wind", `${Math.round(current.wind_speed_10m)} mph`));
      }
      if (current.relative_humidity_2m !== undefined) {
        windFacts.appendChild(weatherRow("Humidity", `${current.relative_humidity_2m}%`));
      }
      if (air.ok && air.aqi !== null && air.aqi !== undefined) {
        windFacts.appendChild(weatherRow("Air quality", `${air.aqi} · ${air.band}`));
      }
      windWrap.appendChild(windFacts);
      container.appendChild(windWrap);

      const meta = make("div", "d-meta");
      meta.appendChild(make("span", "", "source: Open-Meteo (free, keyless)"));
      meta.appendChild(make("span", "", `fetched ${weather.age}${weather.stale ? " · stale" : ""}`));
      meta.appendChild(make("span", "", "context only — never drives training"));
      container.appendChild(meta);
    } catch {
      container.replaceChildren(make("div", "drawer-loading", "Signal unavailable."));
    }
  }

  function updatePill(weather) {
    const pill = qs("[data-weather-pill]");
    if (!pill || !weather.summary) return;
    pill.replaceChildren();
    const glyph = make("span", "w-glyph", weather.summary.glyph);
    glyph.setAttribute("aria-hidden", "true");
    pill.appendChild(glyph);
    pill.appendChild(make("span", "w-temp", `${weather.summary.temp}°`));
    pill.appendChild(make("span", "w-cond", weather.summary.label));
  }

  document.addEventListener("click", (event) => {
    const detailTrigger = event.target.closest?.("[data-detail]");
    if (detailTrigger) { show(detailTrigger.dataset.detail); return; }
    const signalTrigger = event.target.closest?.("[data-drawer-signal]");
    if (signalTrigger) { showWeather(); return; }
    if (event.target.closest?.("[data-drawer-close]")) { close(); return; }
    const backdrop = qs("[data-drawer-backdrop]");
    if (backdrop && !backdrop.hidden && event.target === backdrop) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
  });

  return { show, showWeather, updatePill };
})();

// Refresh the masthead pill quietly after load (cache-first server side).
document.addEventListener("DOMContentLoaded", () => {
  if (!qs("[data-weather-pill]")) return;
  fetch("/api/signals/weather", { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : null))
    .then((weather) => { if (weather?.ok) Drawer.updatePill(weather); })
    .catch(() => {});
});

// ----------------------------------------------- vital sparkline enhancement
// Upgrade the server-rendered fallback sparklines into toned gradient charts.
// Purely progressive: no JS → the flat polyline still renders honestly.
(function sparklines() {
  function enhance(root) {
    if (!window.OrionCharts?.vitalSparkline) return;
    (root || document).querySelectorAll("svg.spark-svg[data-spark]").forEach((svg) => {
      if (svg.dataset.enhanced) return;
      const values = svg.dataset.spark.split(",").map(Number).filter((n) => !Number.isNaN(n));
      if (values.length < 2) return;
      const chart = window.OrionCharts.vitalSparkline(values, svg.dataset.sparkKind || "");
      chart.classList.add("spark-svg");
      chart.dataset.enhanced = "1";
      svg.replaceWith(chart);
    });
  }
  document.addEventListener("DOMContentLoaded", () => enhance());
  // Re-enhance after HTMX/queue swaps re-render metric cards.
  document.body?.addEventListener?.("htmx:afterSwap", (e) => enhance(e.target));
})();

// ------------------------------------------- trend charts (Stoic/Mind trends)
// Render [data-trend] containers into toned trend charts from a bare number[].
(function trends() {
  function enhance(root) {
    if (!window.OrionCharts?.trendChart) return;
    (root || document).querySelectorAll("[data-trend]").forEach((box) => {
      if (box.dataset.trendDone) return;
      const scale = Number(box.dataset.trendScale || 1);
      const values = box.dataset.trend.split(",").map(Number)
        .filter((n) => !Number.isNaN(n)).map((n) => n * scale);
      window.OrionCharts.trendChart(box, values, {
        kind: box.dataset.trendKind || "accent",
        unit: box.dataset.trendUnit || "",
        decimals: Number(box.dataset.trendDecimals || 0),
      });
      box.dataset.trendDone = "1";
    });
  }
  document.addEventListener("DOMContentLoaded", () => enhance());
})();

// ------------------------------------------------------- scale label hints
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "radio") return;
  const scale = input.closest("[data-scale]");
  if (!scale) return;
  const hint = qs(`[data-scale-hint="${scale.dataset.scale}"]`);
  if (hint) hint.textContent = input.dataset.scaleLabel || "";
});

// --------------------------------------------------------- meditation timer
(function meditation() {
  let timer = null;

  function fmt(seconds) {
    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  }

  document.addEventListener("click", (event) => {
    const start = event.target.closest?.("[data-med-minutes]");
    const stop = event.target.closest?.("[data-med-stop]");
    const stage = qs("[data-med-stage]");
    if (!stage) return;

    if (start) {
      const minutes = Number(start.dataset.medMinutes || 3);
      const kind = start.dataset.medKind || "meditation";
      const total = minutes * 60;
      const end = Date.now() + total * 1000;
      stage.classList.add("active");
      qs("[data-med-orb]")?.classList.add("breathing");
      const timeEl = qs("[data-med-time]");
      const phaseEl = qs("[data-med-phase]");
      if (phaseEl) phaseEl.textContent = kind.replace(/_/g, " ");
      window.clearInterval(timer);
      const tick = () => {
        const left = Math.max(0, (end - Date.now()) / 1000);
        if (timeEl) timeEl.textContent = fmt(left);
        if (left <= 0) {
          window.clearInterval(timer);
          qs("[data-med-orb]")?.classList.remove("breathing");
          if (phaseEl) phaseEl.textContent = "complete — log how it landed";
          if (navigator.vibrate) navigator.vibrate([120, 80, 120]);
          const form = qs("[data-med-form]");
          if (form) {
            const durationInput = form.querySelector('input[name="duration_minutes"]');
            const kindSelect = form.querySelector('select[name="kind"]');
            if (durationInput) durationInput.value = String(minutes);
            if (kindSelect) {
              const option = Array.from(kindSelect.options).find((o) => o.value === kind);
              if (option) kindSelect.value = kind;
            }
            form.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }
      };
      tick();
      timer = window.setInterval(tick, 500);
    }
    if (stop) {
      window.clearInterval(timer);
      stage.classList.remove("active");
      qs("[data-med-orb]")?.classList.remove("breathing");
    }
  });
})();

// --------------------------------------------------------- nutrition search
(function foodSearch() {
  let debounce = null;

  function hit(food, group) {
    const btn = make("button", "food-hit");
    btn.type = "button";
    btn.appendChild(make("span", "fh-name", food.name));
    const brandBits = [food.brand, group === "generic" ? "UK generic" : "",
      group === "off" ? "Open Food Facts" : "", group === "local" ? "your foods" : ""]
      .filter(Boolean).join(" · ");
    btn.appendChild(make("span", "fh-brand", brandBits));
    btn.appendChild(make("span", "fh-cal",
      food.calories_100g !== null && food.calories_100g !== undefined
        ? `${Math.round(food.calories_100g)} kcal/100g` : "—"));
    btn.addEventListener("click", () => pick(food));
    return btn;
  }

  function pick(food) {
    const form = qs("[data-log-form]");
    if (!form) return;
    form.querySelector('input[name="name"]').value = food.name;
    form.querySelector('input[name="food_id"]').value = food.id || "";
    form.querySelector('input[name="food_payload"]').value = food.id ? "" : JSON.stringify(food);
    const grams = form.querySelector('input[name="grams"]');
    grams.value = food.serving_size ? String(Math.round(food.serving_size)) : "100";
    const servingNote = qs("[data-portion-note]");
    if (servingNote) {
      servingNote.textContent = food.serving_size
        ? `1 ${food.serving_unit || "serving"} ≈ ${Math.round(food.serving_size)} g`
        : "per-100g values; set the weight";
    }
    form.hidden = false;
    updatePreview();
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    grams.focus();
    grams.select();
  }

  function updatePreview() {
    const form = qs("[data-log-form]");
    const preview = qs("[data-portion-preview]");
    if (!form || !preview) return;
    const payloadRaw = form.querySelector('input[name="food_payload"]').value;
    const grams = Number(form.querySelector('input[name="grams"]').value || 0);
    let per100 = null;
    if (payloadRaw) {
      try { per100 = JSON.parse(payloadRaw); } catch { per100 = null; }
    }
    if (!per100 || !grams || per100.calories_100g === null || per100.calories_100g === undefined) {
      preview.textContent = "";
      return;
    }
    const kcal = Math.round((per100.calories_100g * grams) / 100);
    const protein = per100.protein_100g !== null && per100.protein_100g !== undefined
      ? ` · ${Math.round((per100.protein_100g * grams) / 100)}g protein` : "";
    preview.textContent = `≈ ${kcal} kcal${protein}`;
  }

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (input.matches?.("[data-food-search]")) {
      window.clearTimeout(debounce);
      const q = input.value.trim();
      const results = qs("[data-search-results]");
      if (!results) return;
      if (q.length < 2) { results.replaceChildren(); return; }
      debounce = window.setTimeout(async () => {
        try {
          const response = await fetch(`/api/nutrition/search?q=${encodeURIComponent(q)}`,
            { credentials: "same-origin" });
          const data = await response.json();
          results.replaceChildren();
          ["local", "generic", "off"].forEach((group) => {
            (data[group] || []).forEach((food) => results.appendChild(hit(food, group)));
          });
          if (!results.children.length) {
            results.appendChild(make("p", "hint",
              "Nothing found — use Quick add, or add it manually and ORION will remember it."));
          }
        } catch {
          results.replaceChildren(make("p", "hint", "Search unavailable — quick add still works."));
        }
      }, 300);
    }
    if (input.matches?.('[data-log-form] input[name="grams"]')) updatePreview();
  });
})();

// ----------------------------------------------------- small page behaviours
document.addEventListener("click", (event) => {
  const focusSearch = event.target.closest?.("[data-focus-search]");
  if (focusSearch) {
    const input = qs("[data-food-search]");
    if (input) {
      input.scrollIntoView({ behavior: "smooth", block: "center" });
      input.focus();
    }
  }
  const reveal = event.target.closest?.("[data-reveal]");
  if (reveal) {
    const target = qs(reveal.dataset.reveal);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.querySelector("input, select, textarea")?.focus();
    }
  }
});

// Inline charts declared in markup: data-inline-chart + data-chart-series JSON.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-inline-chart]").forEach((node) => {
    let series = [];
    try { series = JSON.parse(node.dataset.chartSeries || "[]"); } catch { series = []; }
    if (series.length && window.OrionCharts) {
      window.OrionCharts.lineChart(node, series, {
        decimals: Number(node.dataset.chartDecimals ?? 1),
        bars: node.dataset.chartBars === "1",
        target: node.dataset.chartTarget ? Number(node.dataset.chartTarget) : undefined,
      });
    }
  });
});

// Destructive forms declare data-confirm="message".
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form instanceof HTMLFormElement && form.dataset.confirm) {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }
});

// Currency converter on Money — pure client arithmetic over server-cached rates.
(function fxConverter() {
  function update() {
    const amountEl = qs("[data-fx-amount]");
    const currencyEl = qs("[data-fx-currency]");
    const resultEl = qs("[data-fx-result]");
    if (!amountEl || !currencyEl || !resultEl) return;
    let rates = {};
    try { rates = JSON.parse(amountEl.dataset.fxRates || "{}"); } catch { rates = {}; }
    const rate = rates[currencyEl.value];
    const amount = Number(amountEl.value || 0);
    resultEl.textContent = rate
      ? `${(amount * rate).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currencyEl.value}`
      : "—";
  }
  document.addEventListener("input", (e) => {
    if (e.target.matches?.("[data-fx-amount]")) update();
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches?.("[data-fx-currency]")) update();
  });
})();
