const STATIC_CACHE = "orion-static-v6";
const PAGE_CACHE = "orion-pages-v6";
const STATIC_ASSETS = [
  "/static/orion.css",
  "/static/orion.js",
  "/static/orion-charts.js",
  "/static/orion-map.js",
  "/static/orion-scan.js",
  "/static/orion-icon.svg",
  "/manifest.webmanifest"
];

const OFFLINE_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#030304">
  <title>ORION offline</title>
  <style>
    html, body { min-height: 100%; margin: 0; background: #030304; color: #eef1f4; }
    body { display: grid; place-items: center; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 24px; }
    main { max-width: 420px; border: 1px solid rgba(255,255,255,.12); border-radius: 14px; padding: 22px; background: rgba(14,15,18,.9); }
    h1 { margin: 0 0 10px; font-size: 24px; }
    p { margin: 0; color: #a2aab4; line-height: 1.5; }
  </style>
</head>
<body><main><h1>ORION is offline</h1><p>Previously opened pages can still load. Queued entries will sync when Orion can reach the server again.</p></main></body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => ![STATIC_CACHE, PAGE_CACHE].includes(key))
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

async function networkFirstPage(request) {
  const cache = await caches.open(PAGE_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return (
      await cache.match(request) ||
      await cache.match("/") ||
      new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
    );
  }
}

async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);
  const refresh = fetch(request).then((response) => {
    if (response.ok) {
      caches.open(STATIC_CACHE).then((cache) => cache.put(request, response.clone()));
    }
    return response;
  });
  return cached || refresh;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(staleWhileRevalidate(request));
  }
});
