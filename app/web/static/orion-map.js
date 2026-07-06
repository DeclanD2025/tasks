// ORION maps — lazy Leaflet over Carto dark tiles, with an offline-safe
// constellation-style SVG fallback when tiles or the vendor lib are missing.
// Geometry is fetched from ORION's own API; tiles are the only external load.

(function () {
  "use strict";

  let leafletLoading = null;

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (leafletLoading) return leafletLoading;
    leafletLoading = new Promise((resolve, reject) => {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "/static/vendor/leaflet.css";
      document.head.appendChild(css);
      const script = document.createElement("script");
      script.src = "/static/vendor/leaflet.js";
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("leaflet missing"));
      document.head.appendChild(script);
    });
    return leafletLoading;
  }

  function svgFallback(container, points) {
    const lats = points.map((p) => p.lat);
    const lngs = points.map((p) => p.lng);
    const minLat = Math.min(...lats); const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs); const maxLng = Math.max(...lngs);
    const spanLat = (maxLat - minLat) || 0.001;
    const spanLng = (maxLng - minLng) || 0.001;
    // Rough aspect correction: shrink longitude by cos(midLat).
    const midLat = (minLat + maxLat) / 2;
    const stretch = Math.cos((midLat * Math.PI) / 180);
    const width = 400;
    const height = 400 * (spanLat / (spanLng * stretch || 0.001));
    const clampedH = Math.max(140, Math.min(420, height));
    const svgNs = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${clampedH}`);
    const poly = document.createElementNS(svgNs, "polyline");
    poly.setAttribute("points", points.map((p) => {
      const x = ((p.lng - minLng) / spanLng) * (width - 24) + 12;
      const y = clampedH - (((p.lat - minLat) / spanLat) * (clampedH - 24) + 12);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" "));
    svg.appendChild(poly);
    const wrap = document.createElement("div");
    wrap.className = "map-fallback";
    wrap.appendChild(svg);
    container.appendChild(wrap);
  }

  async function mountMap(container, points) {
    try {
      const L = await loadLeaflet();
      const mapEl = document.createElement("div");
      mapEl.className = "map-el";
      container.appendChild(mapEl);
      const map = L.map(mapEl, { zoomControl: true, attributionControl: true });
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; OpenStreetMap &copy; CARTO",
        subdomains: "abcd",
        maxZoom: 19,
      }).addTo(map);
      const latlngs = points.map((p) => [p.lat, p.lng]);
      const line = L.polyline(latlngs, { color: "#8ae6ff", weight: 3, opacity: 0.9 }).addTo(map);
      L.circleMarker(latlngs[0], {
        radius: 5, color: "#6cd9a6", fillColor: "#6cd9a6", fillOpacity: 0.9,
      }).addTo(map);
      L.circleMarker(latlngs[latlngs.length - 1], {
        radius: 5, color: "#e5737f", fillColor: "#e5737f", fillOpacity: 0.9,
      }).addTo(map);
      map.fitBounds(line.getBounds(), { padding: [24, 24] });
      // Tiles can be blocked offline; the polyline still renders over the
      // dark base, which is an acceptable degraded state.
    } catch {
      svgFallback(container, points);
    }
  }

  async function init(container) {
    const url = container.dataset.mapGeometry;
    if (!url) return;
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      if (!data.points || data.points.length < 2) {
        container.appendChild(Object.assign(document.createElement("p"),
          { className: "hint", textContent: "No GPS trace for this route yet." }));
        return;
      }
      mountMap(container, data.points);
    } catch {
      container.appendChild(Object.assign(document.createElement("p"),
        { className: "hint", textContent: "Route geometry unavailable." }));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Lazy-init maps as they scroll into view; maps are heavy, pages are not.
    const targets = Array.from(document.querySelectorAll("[data-map-geometry]"));
    if (!targets.length) return;
    if (!("IntersectionObserver" in window)) {
      targets.forEach(init);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          observer.unobserve(entry.target);
          init(entry.target);
        }
      });
    }, { rootMargin: "200px" });
    targets.forEach((t) => observer.observe(t));
  });
})();
