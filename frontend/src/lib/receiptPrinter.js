// iter356/iter357 — Transporte de impresión para SUNMI D3 Mini T1730.
//
// El backend genera el flujo ESC/POS (bytes estándar de impresora térmica).
// Aquí decidimos CÓMO llega ese flujo a la impresora según el transporte:
//
//   • "simulacion" — no toca hardware: la UI muestra el ticket y el volcado
//     ESC/POS. 100% verificable sin el equipo.
//   • "sunmi"      — envía el ESC/POS por el JS USDK OFICIAL de SUNMI
//     (puente JS → `sendEscCommand`). El SDK habla con el servicio local del
//     equipo (ws://localhost:7070/ws) que instala la app "JS USDK" de la
//     Sunmi App Store. Solo reporta éxito ante un ACK positivo del equipo.
//   • "navegador"  — imprime el ticket en texto por el servicio de impresión
//     de Android/Chromium (window.print). Útil como alternativa.

export const DEFAULT_CONFIG = {
  transport: "simulacion",
  // El JS USDK oficial gestiona su propio socket (ws://localhost:7070/ws);
  // este valor queda informativo.
  sunmiWsUrl: "ws://localhost:7070/ws",
  width: 48, // 48 = 80mm · 32 = 58mm
  openDrawer: false,
  printLogo: true,
  business_name: "Resilience Brothers",
  business_line2: "Mercado & Inventario",
  business_line3: "",
  footer: "¡Gracias por su compra!",
  currency: "CUP",
};

const LS_KEY = "rb_printer_config_v1";

export function loadPrinterConfig() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function savePrinterConfig(cfg) {
  localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

export function hexPreview(b64) {
  try {
    const bin = atob(b64);
    const bytes = Array.from(bin, (c) => c.charCodeAt(0));
    return bytes.map((b) => b.toString(16).padStart(2, "0")).join(" ");
  } catch {
    return "";
  }
}

function b64ToHex(b64) {
  const bin = atob(b64);
  let hex = "";
  for (let i = 0; i < bin.length; i += 1) {
    hex += bin.charCodeAt(i).toString(16).padStart(2, "0");
  }
  return hex;
}

// ── JS USDK oficial de SUNMI ──────────────────────────────────────────────
// El SDK abre su WebSocket al servicio local del equipo y expone
// `printer.commandApi.sendEscCommand([hex])`, cuya promesa SOLO se resuelve
// ante un ACK positivo (code===1); si no hay socket rechaza al instante, y si
// el equipo responde otro código la promesa queda colgada → la cortamos con un
// timeout. Así NUNCA reportamos éxito ante error/sin respuesta/cierre.
let _sunmiSdkPromise = null;

async function getSunmiSdk() {
  if (!_sunmiSdkPromise) {
    _sunmiSdkPromise = (async () => {
      const mod = await import("sunmi-js-sdk");
      const SUNMI = mod.default || mod;
      const sdk = new SUNMI();
      sdk.init(); // abre ws://localhost:7070/ws (servicio JS USDK del equipo)
      try {
        // Lanza la app de impresión por el deep link sunmi:// (puede no resolver
        // fuera del equipo; no es bloqueante).
        await sdk.launchPrinterService();
      } catch {
        /* noop */
      }
      return sdk;
    })();
  }
  return _sunmiSdkPromise;
}

function sdkSocket(sdk) {
  return sdk && sdk.printer && sdk.printer.commandApi && sdk.printer.commandApi.socket;
}

function waitForConnection(sdk, timeoutMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      const s = sdkSocket(sdk);
      if (s && s.connected) return resolve(true);
      if (Date.now() - start >= timeoutMs) return resolve(false);
      setTimeout(tick, 150);
      return undefined;
    };
    tick();
  });
}

function withTimeout(promise, ms, message) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(message)), ms);
    Promise.resolve(promise).then(
      (v) => { clearTimeout(t); resolve(v); },
      (e) => { clearTimeout(t); reject(e instanceof Error ? e : new Error(String(e))); },
    );
  });
}

// Envía ESC/POS (base64) al equipo SUNMI por el JS USDK oficial.
export async function sendEscposToSunmi(b64, _opts, timeoutMs = 8000) {
  let sdk;
  try {
    sdk = await getSunmiSdk();
  } catch {
    throw new Error("No se pudo cargar el SDK de SUNMI (JS USDK).");
  }
  const connected = await waitForConnection(sdk, 4000);
  if (!connected) {
    throw new Error(
      "Sin conexión con el servicio de impresión SUNMI. Instala/abre la app 'JS USDK' (Sunmi App Store) en el equipo.",
    );
  }
  const hex = b64ToHex(b64);
  // sendEscCommand resuelve SOLO con ACK positivo (code===1) del equipo.
  await withTimeout(
    sdk.printer.commandApi.sendEscCommand([hex]),
    timeoutMs,
    "La impresora SUNMI no confirmó la impresión (sin ACK).",
  );
  return { ok: true, via: "sunmi" };
}

// Imprime el ticket en texto por el servicio de impresión del navegador.
export function printPlaintextInBrowser(plaintext) {
  const w = window.open("", "_blank", "width=380,height=640");
  if (!w) throw new Error("El navegador bloqueó la ventana de impresión");
  w.document.write(
    `<pre style="font-family:'Courier New',monospace;font-size:12px;white-space:pre;margin:0;padding:8px">${
      plaintext.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
    }</pre>`,
  );
  w.document.close();
  w.focus();
  w.print();
  return { ok: true, via: "navegador" };
}
