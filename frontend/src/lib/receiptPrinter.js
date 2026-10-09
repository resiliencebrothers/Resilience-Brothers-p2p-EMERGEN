// iter356 — Transporte de impresión para SUNMI D3 Mini T1730.
//
// El backend genera el flujo ESC/POS (bytes estándar de impresora térmica).
// Aquí decidimos CÓMO llega ese flujo a la impresora según el transporte:
//
//   • "simulacion" — no toca hardware: la UI muestra el ticket y el volcado
//     ESC/POS. 100% verificable sin el equipo.
//   • "sunmi"      — envía el ESC/POS al middleware SUNMI "JS USDK" por un
//     WebSocket local del propio dispositivo (p. ej. ws://127.0.0.1:8080/).
//     *** El formato de trama y el puerto deben confirmarse con el equipo real
//         (ver /app/memory/SUNMI_T1730_INTEGRATION.md). ***
//   • "navegador"  — imprime el ticket en texto por el servicio de impresión
//     de Android/Chromium (window.print). Útil como alternativa.

export const DEFAULT_CONFIG = {
  transport: "simulacion",
  sunmiWsUrl: "ws://127.0.0.1:8080/",
  width: 48, // 48 = 80mm · 32 = 58mm
  openDrawer: true,
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

// Envía ESC/POS (base64) al middleware SUNMI por WebSocket. Resuelve al recibir
// un ACK o al cerrarse correctamente; rechaza ante error o timeout.
export function sendEscposToSunmi(b64, wsUrl, timeoutMs = 6000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let ws;
    const done = (fn, arg) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { ws && ws.close(); } catch { /* noop */ }
      fn(arg);
    };
    const timer = setTimeout(
      () => done(reject, new Error("Tiempo de espera agotado con el servicio SUNMI")),
      timeoutMs,
    );
    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      return done(reject, e);
    }
    ws.onopen = () => {
      // Trama documentada; AJUSTAR al protocolo del JS USDK instalado si difiere.
      ws.send(JSON.stringify({ type: "escpos", data: b64 }));
      // Algunos servicios no responden ACK: resolvemos poco después del envío.
      setTimeout(() => done(resolve, { ok: true, via: "sunmi" }), 400);
    };
    ws.onmessage = () => done(resolve, { ok: true, via: "sunmi" });
    ws.onerror = () =>
      done(reject, new Error("No se pudo conectar con el servicio de impresión SUNMI"));
  });
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
