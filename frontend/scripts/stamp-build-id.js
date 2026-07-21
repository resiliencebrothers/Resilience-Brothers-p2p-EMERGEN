#!/usr/bin/env node
/**
 * iter96 — stamps a fresh build id into public/build-id.json every
 * time `yarn build` runs. The service-worker's client-side registrar
 * polls this file every 2 min to catch redeploys that happen while
 * a tab is idle, and auto-reload the PWA when the id changes.
 *
 * We drop the file into /public so CRA copies it verbatim into the
 * production /build folder — served next to /manifest.webmanifest.
 * Dev builds also refresh it so local reloads mirror production.
 */
const fs = require("fs");
const path = require("path");

const buildId =
  process.env.EMERGENT_BUILD_ID ||
  process.env.RENDER_GIT_COMMIT ||
  process.env.VERCEL_GIT_COMMIT_SHA ||
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

const payload = {
  buildId,
  builtAt: new Date().toISOString(),
};

const publicDir = path.resolve(__dirname, "..", "public");
if (!fs.existsSync(publicDir)) fs.mkdirSync(publicDir, { recursive: true });

const outPath = path.join(publicDir, "build-id.json");
fs.writeFileSync(outPath, JSON.stringify(payload, null, 2) + "\n", "utf8");

// eslint-disable-next-line no-console
console.info(`[stamp-build-id] wrote ${outPath} — ${buildId}`);
