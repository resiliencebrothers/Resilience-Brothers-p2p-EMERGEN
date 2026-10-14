/**
 * M02 — regresión del control de vigencia de la carga compartida del panel
 * del mensajero. Reproduce respuestas diferidas y verifica que una respuesta
 * ATRASADA nunca sobrescriba a una más reciente (haciendo «desaparecer» la
 * entrega del último aviso). Lógica pura — no necesita React.
 */
import { createLatestGuard } from "../latestResponseGuard";

function defer() {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return { promise, resolve };
}

// Modela el patrón real de `load`: cada carga reserva un `seq` y solo aplica
// su payload si sigue siendo la última iniciada.
function wireLoad(guard, state, d) {
  const seq = guard.begin();
  return d.promise.then((resp) => {
    if (guard.isLatest(seq)) state.data = resp;
    return resp;
  });
}

describe("createLatestGuard — la carga de /courier/deliveries", () => {
  test("B-antes-de-A: la respuesta atrasada de A no oculta la entrega B del último aviso", async () => {
    const guard = createLatestGuard();
    const state = { data: null };

    const dA = defer(); // aviso A — lista anterior (solo A)
    const dB = defer(); // aviso B — lista nueva (A y B), iniciada DESPUÉS

    const pA = wireLoad(guard, state, dA);
    const pB = wireLoad(guard, state, dB);

    // Resuelve PRIMERO la consulta de B.
    dB.resolve({ available: [{ id: "A" }, { id: "B" }] });
    await pB;
    expect(state.data.available.map((x) => x.id)).toEqual(["A", "B"]);

    // Resuelve DESPUÉS la consulta ATRASADA de A (solo A): debe descartarse.
    dA.resolve({ available: [{ id: "A" }] });
    await pA;
    expect(state.data.available.map((x) => x.id)).toEqual(["A", "B"]);
  });

  test("solapamiento refresco-periódico / apertura: un refresco atrasado no pisa la apertura", async () => {
    const guard = createLatestGuard();
    const state = { data: null };

    const poll = defer(); // refresco periódico EN VUELO (iniciado primero)
    const open = defer(); // apertura de aviso (iniciada DESPUÉS)

    const pPoll = wireLoad(guard, state, poll);
    const pOpen = wireLoad(guard, state, open);

    // La apertura resuelve primero y aplica la reserva.
    open.resolve({ available: [{ id: "RES" }] });
    await pOpen;
    expect(state.data.available.map((x) => x.id)).toEqual(["RES"]);

    // El refresco ATRASADO (iniciado antes) resuelve después con lista vacía:
    // NO debe hacer desaparecer la reserva recién mostrada.
    poll.resolve({ available: [] });
    await pPoll;
    expect(state.data.available.map((x) => x.id)).toEqual(["RES"]);
  });

  test("control positivo: en orden, cada respuesta aplica normalmente", async () => {
    const guard = createLatestGuard();
    const state = { data: null };

    const d1 = defer();
    const p1 = wireLoad(guard, state, d1);
    d1.resolve({ available: [{ id: "A" }] });
    await p1;
    expect(state.data.available.map((x) => x.id)).toEqual(["A"]);

    const d2 = defer();
    const p2 = wireLoad(guard, state, d2);
    d2.resolve({ available: [{ id: "A" }, { id: "B" }] });
    await p2;
    expect(state.data.available.map((x) => x.id)).toEqual(["A", "B"]);
  });
});
