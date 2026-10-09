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

// ── JS USDK oficial de SUNMI (con recuperación de conexión) ───────────────
// El SDK expone `printer.commandApi.sendEscCommand([hex])`, cuya promesa SOLO
// se resuelve ante un ACK positivo (code===1) del equipo; si el socket no está
// conectado rechaza al instante, y si el equipo responde otro código la promesa
// queda colgada → la cortamos con un timeout. Así NUNCA damos éxito ante
// error/sin respuesta/cierre.
//
// SUN-06 — Recuperación del socket: el SDK NO reconecta (init() no recrea un
// socketManager existente). Por eso NO cacheamos una instancia muerta: en cada
// envío comprobamos la conexión y, si está cerrada/fallida, DESCARTAMOS la
// instancia y reconstruimos una nueva, arrancando el servicio (deep link)
// ANTES de abrir la conexión. No reenviamos trabajos automáticamente: un
// reintento es siempre una acción EXPLÍCITA del usuario (la venta ya quedó
// registrada; el ticket pudo imprimirse antes de perderse el ACK).
let _sdkModulePromise = null;   // solo cacheamos el import del módulo (seguro)
let _sdk = null;                // instancia viva actual (null = reconstruir)

async function loadSunmiClass() {
  if (!_sdkModulePromise) _sdkModulePromise = import("sunmi-js-sdk");
  try {
    const mod = await _sdkModulePromise;
    return mod.default || mod;
  } catch (e) {
    _sdkModulePromise = null;   // no cachear un import fallido (recuperable)
    throw e;
  }
}

function isSdkConnected(sdk) {
  const sm = sdk && sdk.socketManager;
  return !!(sm && sm.connected && sm.socket && sm.socket.readyState === 1); // 1 = OPEN
}

function disposeSdk(sdk) {
  try {
    const sm = sdk && sdk.socketManager;
    if (sm && typeof sm.disconnect === "function") sm.disconnect();
    else if (sm && sm.socket && typeof sm.socket.close === "function") sm.socket.close();
  } catch { /* noop */ }
}

function waitForConnection(sdk, timeoutMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      if (isSdkConnected(sdk)) return resolve(true);
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

// Construye una instancia NUEVA y CONECTADA: arranca el servicio ANTES de abrir
// el socket (coordinación), luego init() abre la conexión al servicio ya listo.
async function buildConnectedSdk(timeoutMs) {
  const SUNMI = await loadSunmiClass();
  // Limpia anclas sunmi:// huérfanas de intentos previos (evita ids duplicados).
  document.querySelectorAll("#sunmi-init-link").forEach((n) => n.remove());
  const sdk = new SUNMI();
  // 1) Arranca la app/servicio JS USDK por el deep link y espera (~3s) a que
  //    esté escuchando ANTES de abrir la conexión.
  try { await sdk.launchPrinterService(); } catch { /* el deep link puede no resolver */ }
  // 2) Abre el WebSocket al servicio ya disponible.
  sdk.init();
  // 3) Espera a que la conexión quede ABIERTA.
  const ok = await waitForConnection(sdk, timeoutMs);
  if (!ok) {
    disposeSdk(sdk);
    throw new Error(
      "Sin conexión con el servicio de impresión SUNMI. Instala/abre la app 'JS USDK' (Sunmi App Store) en el equipo.",
    );
  }
  return sdk;
}

// Devuelve una instancia conectada, reutilizándola solo si su socket sigue vivo.
async function ensureConnectedSdk(timeoutMs) {
  if (_sdk && isSdkConnected(_sdk)) return _sdk;
  if (_sdk) { disposeSdk(_sdk); _sdk = null; }   // descartar la instancia muerta
  _sdk = await buildConnectedSdk(timeoutMs);
  return _sdk;
}

// Envía ESC/POS (base64) al equipo SUNMI por el JS USDK oficial.
export async function sendEscposToSunmi(b64, _opts, timeoutMs = 8000) {
  let sdk;
  try {
    sdk = await ensureConnectedSdk(4000);
  } catch (e) {
    _sdk = null;   // asegurar reconstrucción en el PRÓXIMO intento explícito
    throw (e instanceof Error ? e : new Error(String(e)));
  }
  const hex = b64ToHex(b64);
  try {
    // sendEscCommand resuelve SOLO con ACK positivo (code===1) del equipo.
    await withTimeout(
      sdk.printer.commandApi.sendEscCommand([hex]),
      timeoutMs,
      "La impresora SUNMI no confirmó la impresión (sin ACK).",
    );
  } catch (e) {
    // Si el socket cayó durante el envío, descarta la instancia para que el
    // PRÓXIMO intento reconstruya la conexión. NO reenviamos aquí: el ticket
    // pudo imprimirse antes de perderse el ACK; el reintento es explícito.
    if (!isSdkConnected(sdk)) { disposeSdk(sdk); _sdk = null; }
    throw (e instanceof Error ? e : new Error(String(e)));
  }
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
