/* Resilience Brothers — Service Worker (iter96 rewrite)
 *
 * ROOT CAUSE of the two production bugs reported by the operator:
 *
 * (1) "Unstyled page after opening the app" (RB logo huge, plain HTML text)
 * (2) "White screen after entering / exiting the app several times, only
 *      a hard-refresh brings it back"
 *
 * Both are the classic PWA "stale HTML + missing hashed chunks" trap:
 * the previous SW served a *cached* index.html that pointed to
 * JS/CSS chunks whose content-hashed filenames no longer exist after
 * a redeploy → the browser 404s the CSS (unstyled) or the JS (white).
 *
 * FIX STRATEGY:
 *   • Network-first for HTML (/, /index.html, navigation requests):
 *     ALWAYS try the network so a fresh deploy is picked up on the
 *     next tab focus. Fall back to cached shell ONLY when offline.
 *   • Cache-first for content-hashed assets under /static/*: the hash
 *     in the filename guarantees immutability so we can cache them
 *     forever, and the freshly-fetched HTML will reference the new
 *     hashes automatically.
 *   • Runtime cache for cross-origin images / fonts (unchanged).
 *   • Every install bumps SW_VERSION → activate purges *every* older
 *     cache so stale chunks can't come back.
 *   • skipWaiting + clients.claim so the new SW takes over instantly;
 *     the client-side registrar then triggers a one-shot reload.
 *   • Safety net: if a same-origin fetch returns 404 for a /static/*
 *     asset, wipe every cache + notify clients to reload.
 */

// Bump this string whenever the SW logic itself changes so old versions
// can never resurrect on a client after a deploy. The build pipeline
// also stamps a fresh build id into /build-id.json which the client
// polls to detect deploys even if the SW body is unchanged.
const SW_VERSION = "rb-2026-07-21-01";
const HTML_CACHE = `${SW_VERSION}-html`;
const STATIC_CACHE = `${SW_VERSION}-static`;
const RUNTIME_CACHE = `${SW_VERSION}-runtime`;

const OFFLINE_URLS = [
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(OFFLINE_URLS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => !k.startsWith(SW_VERSION))
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
      // Broadcast so the client-side registrar can trigger a soft
      // reload — this is the piece that eliminates the "white screen
      // until manual refresh" behaviour the operator reported.
      .then(() =>
        self.clients.matchAll({ type: "window", includeUncontrolled: true })
      )
      .then((clientsArr) => {
        for (const c of clientsArr) c.postMessage({ type: "SW_ACTIVATED", version: SW_VERSION });
      })
  );
});

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function isNavigationRequest(request) {
  return (
    request.mode === "navigate" ||
    (request.method === "GET" &&
      request.headers.get("accept")?.includes("text/html"))
  );
}

async function nukeCachesAndTellClients(reason) {
  const keys = await caches.keys();
  await Promise.all(keys.map((k) => caches.delete(k)));
  const clientsArr = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });
  for (const c of clientsArr) {
    c.postMessage({ type: "SW_FORCE_RELOAD", reason });
  }
}

// ---------------------------------------------------------------------
// Fetch handler
// ---------------------------------------------------------------------

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Pass-through for API — always network, so auth cookies + real-time
  // data are never affected by the SW.
  if (url.pathname.startsWith("/api/")) return;

  // 1) HTML / navigation requests → network-first with cached-shell
  //    fallback. This is the key change that stops the "cached stale
  //    index.html referencing missing chunks" bug.
  if (isNavigationRequest(request)) {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request, { cache: "no-store" });
          // Cache the freshly-fetched shell for the *next* offline use.
          if (fresh && fresh.status === 200) {
            const cache = await caches.open(HTML_CACHE);
            cache.put("/", fresh.clone());
          }
          return fresh;
        } catch (_) {
          // Offline: fall back to the last-known-good shell.
          const cache = await caches.open(HTML_CACHE);
          const fallback = await cache.match("/");
          if (fallback) return fallback;
          // Nothing cached — surface a minimal offline notice.
          return new Response(
            "<h1>Offline</h1><p>Resilience Brothers is unreachable. Reconnect and refresh.</p>",
            { status: 503, headers: { "content-type": "text/html; charset=utf-8" } }
          );
        }
      })()
    );
    return;
  }

  // 2) Same-origin content-hashed assets (CRA emits filenames like
  //    /static/js/main.abc123.js and /static/css/main.def456.css).
  //    These are IMMUTABLE — cache forever, network only if not cached.
  //    Safety net: if the network returns 404, we treat it as a stale-
  //    chunk redeploy signal, wipe every cache and ask clients to reload.
  if (
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/static/") ||
      url.pathname.startsWith("/currency-icons/") ||
      url.pathname.startsWith("/icons/") ||
      url.pathname === "/manifest.webmanifest")
  ) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);
        const cached = await cache.match(request);
        if (cached) return cached;
        try {
          const response = await fetch(request);
          if (response && response.status === 200) {
            cache.put(request, response.clone());
            return response;
          }
          if (response && response.status === 404 && url.pathname.startsWith("/static/")) {
            // A missing hashed chunk almost always means the client is
            // running an old shell. Wipe + reload to recover instantly.
            await nukeCachesAndTellClients("stale-chunk-404");
          }
          return response;
        } catch (_) {
          return cached || Response.error();
        }
      })()
    );
    return;
  }

  // 3) Cross-origin fonts / images → cache-first.
  if (
    request.destination === "image" ||
    request.destination === "font" ||
    request.destination === "style"
  ) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(RUNTIME_CACHE);
        const cached = await cache.match(request);
        if (cached) return cached;
        try {
          const response = await fetch(request);
          if (response && response.status === 200) {
            cache.put(request, response.clone());
          }
          return response;
        } catch {
          return cached || Response.error();
        }
      })()
    );
  }
});

// ---------------------------------------------------------------------
// Messages from the app (soft-reload + skipWaiting hand-off)
// ---------------------------------------------------------------------

self.addEventListener("message", (event) => {
  const data = event.data;
  // Support both the legacy string form and the new {type} object form.
  if (data === "SKIP_WAITING" || (data && data.type === "SKIP_WAITING")) {
    self.skipWaiting();
  }
  if (data && data.type === "CLEAR_CACHES") {
    event.waitUntil(nukeCachesAndTellClients("client-requested"));
  }
});

// ---------------------------------------------------------------------
// PUSH NOTIFICATIONS — unchanged behaviour
// ---------------------------------------------------------------------

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "Resilience Brothers", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Resilience Brothers";
  const options = {
    body: data.body || "",
    icon: data.icon || "/icons/icon-192.png",
    badge: data.badge || "/icons/icon-192.png",
    tag: data.tag || "rb-notification",
    data: { url: data.url || "/" },
    vibrate: [120, 60, 120],
    requireInteraction: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientsArr) => {
        for (const c of clientsArr) {
          if (c.url.includes(self.location.origin) && "focus" in c) {
            c.navigate(targetUrl);
            return c.focus();
          }
        }
        if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
      })
  );
});
