/**
 * SUN-06 — Recuperación del socket del transporte SUNMI (JS USDK).
 *
 * Mockea el SDK real (`sunmi-js-sdk`) replicando su contrato: `init()` solo crea
 * el socketManager si no existe (NO reconecta), el socketManager expone
 * `connected`/`socket.readyState`/`disconnect()`, y
 * `printer.commandApi.sendEscCommand([hex])` resuelve con ACK (code===1).
 *
 * El estado del "servicio" se controla con `globalThis.__sunmi.serviceUp`:
 * una instancia nueva conecta solo si el servicio está disponible al hacer init().
 */
jest.mock("sunmi-js-sdk", () => {
  class FakeSocketManager {
    constructor() {
      const up = !!(globalThis.__sunmi && globalThis.__sunmi.serviceUp);
      this.connected = up;
      this.socket = {
        readyState: up ? 1 : 0, // 1 = OPEN, 0 = CONNECTING
        close() { this.readyState = 3; },
      };
    }
    disconnect() { this.connected = false; this.socket.readyState = 3; }
  }
  class FakeSUNMI {
    constructor() {
      this.socketManager = null;
      this.printer = null;
      (globalThis.__sunmi.instances = globalThis.__sunmi.instances || []).push(this);
    }
    launchPrinterService() { return Promise.resolve(true); }
    init() {
      if (this.socketManager) return; // el SDK real NO recrea uno existente
      const sm = new FakeSocketManager();
      this.socketManager = sm;
      this.printer = {
        commandApi: {
          sendEscCommand() {
            globalThis.__sunmi.sendCalls = (globalThis.__sunmi.sendCalls || 0) + 1;
            const b = globalThis.__sunmi.sendBehavior;
            if (b === "reject") return Promise.reject(new Error("Socket not connected"));
            if (b === "hang") return new Promise(() => {});
            return Promise.resolve({ code: 1 }); // ACK positivo
          },
        },
      };
    }
  }
  return { __esModule: true, default: FakeSUNMI };
});

function freshModule() {
  jest.resetModules();
  globalThis.__sunmi = { serviceUp: false, sendBehavior: "ack", sendCalls: 0, instances: [] };
  return require("../receiptPrinter");
}

describe("SUN-06 recuperación del socket SUNMI", () => {
  test("servicio apagado al abrir la página → un nuevo intento recupera sin recargar", async () => {
    const mod = freshModule();
    // Servicio apagado: el primer envío debe FALLAR-CERRADO (sin falso éxito).
    await expect(mod.sendEscposToSunmi("AAAA")).rejects.toThrow(/Sin conexión/i);
    // El servicio ya está disponible: el siguiente intento reconstruye y conecta.
    globalThis.__sunmi.serviceUp = true;
    const res = await mod.sendEscposToSunmi("AAAA");
    expect(res.ok).toBe(true);
    // Se reconstruyó una instancia NUEVA (no se reutilizó la muerta).
    expect(globalThis.__sunmi.instances.length).toBe(2);
    expect(globalThis.__sunmi.sendCalls).toBe(1); // solo el envío exitoso llamó
  }, 20000);

  test("caída tras un envío correcto → el siguiente intento reconstruye y obtiene ACK", async () => {
    const mod = freshModule();
    globalThis.__sunmi.serviceUp = true;
    const r1 = await mod.sendEscposToSunmi("AAAA");
    expect(r1.ok).toBe(true);
    expect(globalThis.__sunmi.instances.length).toBe(1);
    // Simula la caída del socket vivo (servicio sigue disponible luego).
    const live = globalThis.__sunmi.instances[0];
    live.socketManager.connected = false;
    live.socketManager.socket.readyState = 3; // CLOSED
    const r2 = await mod.sendEscposToSunmi("AAAA");
    expect(r2.ok).toBe(true);
    // Descartó el socket muerto y construyó uno nuevo (no reutilizó el cerrado).
    expect(globalThis.__sunmi.instances.length).toBe(2);
  }, 20000);

  test("sin ACK (promesa colgada) → falla por timeout y NO reenvía en silencio", async () => {
    const mod = freshModule();
    globalThis.__sunmi.serviceUp = true;
    globalThis.__sunmi.sendBehavior = "hang"; // el equipo nunca confirma
    await expect(mod.sendEscposToSunmi("AAAA", undefined, 400)).rejects.toThrow(/ACK|confirm/i);
    // Se intentó UNA sola vez: el reintento debe ser explícito del usuario.
    expect(globalThis.__sunmi.sendCalls).toBe(1);
  }, 20000);
});
