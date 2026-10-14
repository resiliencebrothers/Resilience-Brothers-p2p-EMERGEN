/**
 * M02 — regresión del flujo COMPLETO de carga + navegación por aviso del panel
 * del mensajero. A diferencia de `latestResponseGuard.test.js` (que solo prueba
 * la protección de `data`), aquí se ejecuta la SELECCIÓN DE PESTAÑA: una
 * respuesta descartada por antigua no debe decidir pestaña, resaltado ni aviso
 * de "entrega desaparecida". Lógica pura — no necesita React.
 */
import {
  createDeepLinkCoordinator,
  resolveDeepLinkTarget,
} from "../deliveryDeepLink";

function defer() {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return { promise, resolve };
}

// Modela `load` del componente: reserva un seq; al resolver aplica la lista
// solo si es la última iniciada y, en ese caso, resuelve el aviso pendiente.
function makeLoad(coord, nav, d) {
  const seq = coord.beginLoad();
  return d.promise.then((resp) => {
    if (coord.isApplied(seq)) {
      nav.data = resp;
      const target = coord.onApplied(resp, seq);
      if (target) nav.lastTarget = target;
    }
    return resp;
  });
}

const AVAIL_B = { available: [{ id: "B" }], mine: [], history: [] };
const MINE_B = { available: [], mine: [{ id: "B" }], history: [] };

describe("resolveDeepLinkTarget — mapeo del estado vigente a navegación", () => {
  test("disponibles / mis entregas / historial / desaparecida", () => {
    expect(resolveDeepLinkTarget(AVAIL_B, "B")).toEqual({ tab: "available", highlight: "B" });
    expect(resolveDeepLinkTarget(MINE_B, "B")).toEqual({ tab: "mine", highlight: "B" });
    expect(resolveDeepLinkTarget({ history: [{ id: "B" }] }, "B")).toEqual({ tab: "history", highlight: "B" });
    expect(resolveDeepLinkTarget({ available: [], mine: [], history: [] }, "B")).toEqual({ gone: true });
  });
});

describe("createDeepLinkCoordinator — navegación del aviso vs respuestas solapadas", () => {
  test("apertura primero / refresco después, orden INVERSO: el refresco (vigente) decide la pestaña; la respuesta antigua del aviso NO", async () => {
    const coord = createDeepLinkCoordinator();
    const nav = { data: null, lastTarget: null };

    coord.open("B");                      // abre el aviso de B
    const dB = defer();                   // carga propia del aviso: estado VIEJO (B en Disponibles)
    const pB = makeLoad(coord, nav, dB);
    const dR = defer();                   // refresco posterior: estado NUEVO (B en Mis entregas)
    const pR = makeLoad(coord, nav, dR);

    // Resuelve PRIMERO el refresco → es la lista vigente, decide la pestaña.
    dR.resolve(MINE_B);
    await pR;
    expect(nav.lastTarget).toEqual({ tab: "mine", highlight: "B" });

    // Resuelve DESPUÉS la consulta ANTIGUA del aviso (B en Disponibles):
    // descartada, no cambia ni la lista ni la navegación.
    dB.resolve(AVAIL_B);
    await pB;
    expect(nav.lastTarget).toEqual({ tab: "mine", highlight: "B" });
    expect(nav.data.mine.map((x) => x.id)).toEqual(["B"]);
  });

  test("la carga propia del aviso llega primero pero es SUPERADA: no resuelve con ella; el refresco vigente sí", async () => {
    const coord = createDeepLinkCoordinator();
    const nav = { data: null, lastTarget: null };

    coord.open("B");
    const dB = defer();                   // seq 1 (propia del aviso)
    const pB = makeLoad(coord, nav, dB);
    const dR = defer();                   // seq 2 (refresco posterior)
    const pR = makeLoad(coord, nav, dR);

    // La propia del aviso resuelve primero PERO ya fue superada por el refresco.
    dB.resolve(AVAIL_B);
    await pB;
    expect(nav.lastTarget).toBeNull();    // una respuesta descartada no decide nada

    // El refresco vigente resuelve el aviso contra el estado real.
    dR.resolve(MINE_B);
    await pR;
    expect(nav.lastTarget).toEqual({ tab: "mine", highlight: "B" });
  });

  test("un refresco iniciado ANTES de abrir el aviso no lo resuelve; la carga del aviso sí", async () => {
    const coord = createDeepLinkCoordinator();
    const nav = { data: null, lastTarget: null };

    const dPre = defer();                 // refresco EN VUELO previo al aviso (seq 1)
    const pPre = makeLoad(coord, nav, dPre);
    coord.open("B");                      // umbral: solo respuestas posteriores

    dPre.resolve(AVAIL_B);                // aplicada, pero PREVIA al aviso
    await pPre;
    expect(nav.lastTarget).toBeNull();

    const dB = defer();                   // carga propia del aviso (seq 2)
    const pB = makeLoad(coord, nav, dB);
    dB.resolve(AVAIL_B);
    await pB;
    expect(nav.lastTarget).toEqual({ tab: "available", highlight: "B" });
  });

  test("control positivo: carga única del aviso resuelve y navega", async () => {
    const coord = createDeepLinkCoordinator();
    const nav = { data: null, lastTarget: null };
    coord.open("B");
    const d = defer();
    const p = makeLoad(coord, nav, d);
    d.resolve(MINE_B);
    await p;
    expect(nav.lastTarget).toEqual({ tab: "mine", highlight: "B" });
  });

  test("entrega realmente desaparecida tras carga fresca → se informa, sin pestaña", async () => {
    const coord = createDeepLinkCoordinator();
    const nav = { data: null, lastTarget: null };
    coord.open("B");
    const d = defer();
    const p = makeLoad(coord, nav, d);
    d.resolve({ available: [], mine: [], history: [] });
    await p;
    expect(nav.lastTarget).toEqual({ gone: true });
  });
});
