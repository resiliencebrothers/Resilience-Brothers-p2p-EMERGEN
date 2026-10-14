/**
 * OP02 — regresión del control de VIGENCIA de las cargas administrativas de
 * Entregas (lista + total + error + atención). Modela los callbacks reales de
 * `load` (begin al disparar; aplicar solo si `isLatest` en then/catch) y
 * verifica que una respuesta o error ATRASADO nunca pise el resultado vigente,
 * para filtro, paginación, errores y atención. Lógica pura — sin React.
 */
import { createLatestGuard } from "../latestResponseGuard";

// Mirror de la rama de LISTA de `load`: reserva seq y aplica filas/total o
// vacía en error, solo si sigue siendo la última iniciada.
function listCall(guard, state) {
  const seq = guard.begin();
  return {
    resolve(rows, total) {
      if (!guard.isLatest(seq)) return;
      state.rows = rows;
      state.total = total ?? rows.length;
    },
    reject() {
      if (!guard.isLatest(seq)) return;
      state.rows = [];
      state.total = 0;
    },
  };
}

// Mirror de la rama de ATENCIÓN de `load`.
function attnCall(guard, state) {
  const seq = guard.begin();
  return {
    resolve(att) { if (guard.isLatest(seq)) state.attention = att; },
  };
}

describe("OP02 — vigencia de la lista de entregas admin", () => {
  test("filtro en orden inverso: la respuesta filtrada vigente se mantiene; la anterior sin filtro se descarta", () => {
    const g = createLatestGuard();
    const state = { rows: null, total: 0 };
    const unfiltered = listCall(g, state);   // consulta sin filtro (seq 1)
    const filtered = listCall(g, state);     // "Solo reasignadas" (seq 2)
    // la filtrada responde primero
    filtered.resolve([{ id: "R", reassigned: true }], 1);
    expect(state.rows.map((x) => x.id)).toEqual(["R"]);
    expect(state.total).toBe(1);
    // responde después la anterior sin filtro → descartada
    unfiltered.resolve([{ id: "N" }, { id: "R", reassigned: true }], 2);
    expect(state.rows.map((x) => x.id)).toEqual(["R"]);
    expect(state.total).toBe(1);
  });

  test("paginación: al activar el filtro desde una página posterior, la carga de la página antigua no vacía la primera", () => {
    const g = createLatestGuard();
    const state = { rows: null, total: 0 };
    const oldPage = listCall(g, state);  // carga con page=2 (seq 1)
    const firstPage = listCall(g, state); // tras reset a page=0 (seq 2)
    // la primera página (vigente) responde
    firstPage.resolve([{ id: "A" }], 1);
    expect(state.rows.map((x) => x.id)).toEqual(["A"]);
    // la página antigua responde vacía después → descartada
    oldPage.resolve([], 0);
    expect(state.rows.map((x) => x.id)).toEqual(["A"]);
    expect(state.total).toBe(1);
  });

  test("un ERROR de una petición antigua no borra una respuesta más reciente correcta", () => {
    const g = createLatestGuard();
    const state = { rows: null, total: 0 };
    const oldReq = listCall(g, state);  // seq 1
    const newReq = listCall(g, state);  // seq 2
    newReq.resolve([{ id: "R", reassigned: true }], 1);
    expect(state.rows.map((x) => x.id)).toEqual(["R"]);
    oldReq.reject();  // error atrasado → NO debe vaciar
    expect(state.rows.map((x) => x.id)).toEqual(["R"]);
    expect(state.total).toBe(1);
  });

  test("atención: una respuesta antigua no restaura la tarjeta U1 tras mostrarse U2", () => {
    const g = createLatestGuard();
    const state = { attention: null };
    const r1 = attnCall(g, state);  // U1 (seq 1)
    const r2 = attnCall(g, state);  // U2 (seq 2)
    r2.resolve({ unanswered_reservations: [{ id: "D", assignment_uid: "U2" }] });
    expect(state.attention.unanswered_reservations[0].assignment_uid).toBe("U2");
    r1.resolve({ unanswered_reservations: [{ id: "D", assignment_uid: "U1" }] });
    expect(state.attention.unanswered_reservations[0].assignment_uid).toBe("U2");
  });

  test("control positivo: en orden, cada respuesta aplica normalmente", () => {
    const g = createLatestGuard();
    const state = { rows: null, total: 0 };
    const c1 = listCall(g, state);
    c1.resolve([{ id: "A" }], 1);
    expect(state.rows.map((x) => x.id)).toEqual(["A"]);
    const c2 = listCall(g, state);
    c2.resolve([{ id: "A" }, { id: "B" }], 2);
    expect(state.rows.map((x) => x.id)).toEqual(["A", "B"]);
    expect(state.total).toBe(2);
  });
});
