/**
 * iter96 — PWA service-worker registrar with automatic soft-reload.
 *
 * Complements the new /public/service-worker.js. Behaviour:
 *
 *   1. Registers /service-worker.js with `updateViaCache: "none"` so
 *      the browser NEVER caches the SW file itself — a fresh copy is
 *      fetched every page load, allowing new-version detection to be
 *      almost instant.
 *   2. When a new SW is installed, tells it to `skipWaiting` so the
 *      old worker doesn't block activation.
 *   3. Reloads the page ONCE when the controller changes (i.e. the
 *      new SW just took over). This is the piece that guarantees the
 *      operator never sees "white screen after entering/exiting the
 *      app several times" again — the moment a fresh SW claims the
 *      tab, we reload with fresh HTML/CSS/JS.
 *   4. Listens for `SW_FORCE_RELOAD` from the SW's safety net
 *      (triggered on a 404 for a hashed chunk) and reloads.
 *   5. Also polls /build-id.json (dropped by the build) every ~2min
 *      to detect deploys that happen while a tab is idle in the
 *      background — if the id changed, hard-reloads.
 */

// Guard so we only reload ONCE per page-lifetime — otherwise a
// controllerchange loop could keep hammering location.reload().
let reloadedForNewVersion = false;

function softReload(reason) {
  if (reloadedForNewVersion) return;
  reloadedForNewVersion = true;
  // eslint-disable-next-line no-console
  console.info(`[SW] Reloading tab to pick up new version — ${reason}`);
  window.location.reload();
}

export function registerSW() {
  if (typeof window === "undefined") return;
  if (!("serviceWorker" in navigator)) return;
  // Skip in dev to avoid caching issues.
  if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
  ) {
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { updateViaCache: "none" })
      .then((reg) => {
        // Ask the SW to check for updates whenever the tab becomes
        // visible again — catches the "PWA left in the background"
        // deploy scenario.
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") {
            reg.update().catch(() => {});
          }
        });

        // A fresh SW showed up — swap it in as soon as it finishes
        // installing.
        reg.addEventListener("updatefound", () => {
          const newWorker = reg.installing;
          if (!newWorker) return;
          newWorker.addEventListener("statechange", () => {
            if (
              newWorker.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              // Old controller still around → hand-off.
              newWorker.postMessage({ type: "SKIP_WAITING" });
            }
          });
        });
      })
      .catch((err) => {
        if (process.env.NODE_ENV !== "production") {
          // eslint-disable-next-line no-console
          console.error("SW registration failed:", err);
        }
      });

    // When the controller changes we KNOW a new SW just took over —
    // reload once so this tab renders fresh HTML/CSS/JS chunks.
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      softReload("controllerchange");
    });

    // The SW can also *push* us a reload command from its 404 safety
    // net (stale hashed chunk detected) — react to that too.
    navigator.serviceWorker.addEventListener("message", (event) => {
      const data = event.data;
      if (data && data.type === "SW_FORCE_RELOAD") {
        softReload(`sw:${data.reason || "force"}`);
      }
    });

    // Background poll: detect a deploy even when no controllerchange
    // fires (e.g. iOS Safari PWA left running for hours). We hit
    // /build-id.json — a tiny file the build stamps with a unique id.
    // If it changed since page load, we clear caches + reload.
    const initialBuildIdPromise = fetchBuildId();
    setInterval(async () => {
      try {
        const current = await fetchBuildId();
        const initial = await initialBuildIdPromise;
        if (initial && current && initial !== current) {
          // Ask the SW to wipe caches so the reload lands on a clean
          // slate, then reload the tab.
          const reg = await navigator.serviceWorker.getRegistration();
          if (reg && reg.active) {
            reg.active.postMessage({ type: "CLEAR_CACHES" });
            // Reload will be triggered by the SW's SW_FORCE_RELOAD
            // broadcast, but reload here too as a belt-and-braces
            // safety net for browsers that ignore the message.
          }
          softReload("build-id-changed");
        }
      } catch (_) {
        // Poll failures are silent — probably a transient network glitch.
      }
    }, 120000); // 2min
  });
}

async function fetchBuildId() {
  try {
    const r = await fetch(`/build-id.json?ts=${Date.now()}`, {
      cache: "no-store",
    });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.buildId;
  } catch (_) {
    return null;
  }
}
