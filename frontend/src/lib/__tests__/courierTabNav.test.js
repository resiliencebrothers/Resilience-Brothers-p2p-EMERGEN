/**
 * M02-UI — prueba de "integración" de la navegación del panel del mensajero:
 * ejecuta en orden los DOS efectos que el componente dispara tras aplicar una
 * lista —la resolución del aviso (deep-link) y la apertura automática de
 * «Disponibles» por reservas— usando las piezas puras reales
 * (`createDeepLinkCoordinator`, `resolveDeepLinkTarget`, `shouldAutoOpenReserved`)
 * y el ciclo real del token de navegación. Las pruebas puras del coordinador
 * (`deliveryDeepLink.test.js`) no ejercen el efecto de reservas y por eso no
 * detectaban que éste pisara la pestaña del aviso.
 */
import { createDeepLinkCoordinator } from "../deliveryDeepLink";
import { shouldAutoOpenReserved } from "../courierTabNav";

// Mini-máquina que reproduce fielmente la secuencia del componente:
//  - al aplicar una respuesta VIGENTE: setData + resolución del aviso (y token
//    de navegación explícita si fija pestaña);
//  - efecto de reservas (solo si cambió reservedCount) ANTES del efecto de
//    sincronización del token (que corre en cada render).
//  - una respuesta DESCARTADA (no vigente) no hace setData → no hay render.
function makeHarness() {
  const coord = createDeepLinkCoordinator();
  const state = {
    tab: "mine", highlight: null, data: null,
    navToken: 0, navTokenSeen: 0, prevReserved: 0,
  };
  function render(resp) {
    const reserved = (resp.available || []).filter((d) => d.reserved_for_me).length;
    if (reserved !== state.prevReserved) {
      if (shouldAutoOpenReserved(reserved, state.navToken, state.navTokenSeen)) {
        state.tab = "available";
      }
    }
    state.prevReserved = reserved;
    state.navTokenSeen = state.navToken; // efecto de sync (cada render)
  }
  return {
    state,
    open(id) { coord.open(id); },
    begin() { return coord.beginLoad(); },
    resolve(seq, resp) {
      if (!coord.isApplied(seq)) return; // descartada: sin setData, sin render
      state.data = resp;
      const target = coord.onApplied(resp, seq);
      if (target) {
        if (target.gone) {
          state.highlight = null;
        } else {
          state.navToken += 1;
          state.tab = target.tab;
          state.highlight = target.highlight;
        }
      }
      render(resp);
    },
    applyLoad(resp) { this.resolve(this.begin(), resp); },
  };
}

function selectedVisible(state) {
  if (!state.highlight) return true;
  return (state.data?.[state.tab] || []).some((d) => d.id === state.highlight);
}

describe("M02-UI — la apertura automática de Disponibles no oculta el aviso", () => {
  test("a) primera carga con A reservada y B aceptada, aviso de B → Mis entregas / B", () => {
    const h = makeHarness();
    h.open("B");
    h.applyLoad({
      available: [{ id: "A", reserved_for_me: true }],
      mine: [{ id: "B" }], history: [],
    });
    expect(h.state.tab).toBe("mine");
    expect(h.state.highlight).toBe("B");
    expect(selectedVisible(h.state)).toBe(true);
  });

  test("b) sin aviso, nueva reserva A → se abre Disponibles (iter208 intacto)", () => {
    const h = makeHarness();
    h.applyLoad({ available: [], mine: [{ id: "X" }], history: [] });
    expect(h.state.tab).toBe("mine");
    h.applyLoad({
      available: [{ id: "A", reserved_for_me: true }],
      mine: [{ id: "X" }], history: [],
    });
    expect(h.state.tab).toBe("available");
  });

  test("c) panel ya cargado, reservas sin cambio, aviso de B → B visible", () => {
    const h = makeHarness();
    h.applyLoad({ available: [], mine: [{ id: "B" }], history: [] });
    h.open("B");
    h.applyLoad({ available: [], mine: [{ id: "B" }], history: [] });
    expect(h.state.tab).toBe("mine");
    expect(h.state.highlight).toBe("B");
    expect(selectedVisible(h.state)).toBe(true);
  });

  test("d) aviso + refresco en orden INVERSO: vigencia + selección correcta", () => {
    const h = makeHarness();
    h.open("B");
    const sOwn = h.begin();   // carga propia del aviso (estado viejo: B en Disponibles)
    const sRefresh = h.begin(); // refresco posterior (B en Mis entregas + A reservada)
    // el refresco (vigente) resuelve primero
    h.resolve(sRefresh, {
      available: [{ id: "A", reserved_for_me: true }],
      mine: [{ id: "B" }], history: [],
    });
    expect(h.state.tab).toBe("mine");
    expect(h.state.highlight).toBe("B");
    // la carga propia, ya descartada, no cambia nada
    h.resolve(sOwn, { available: [{ id: "B" }], mine: [], history: [] });
    expect(h.state.tab).toBe("mine");
    expect(selectedVisible(h.state)).toBe(true);
  });

  test("la prioridad del aviso es SOLO durante su resolución: reservas posteriores reabren Disponibles", () => {
    const h = makeHarness();
    h.open("B");
    h.applyLoad({
      available: [{ id: "A", reserved_for_me: true }],
      mine: [{ id: "B" }], history: [],
    });
    expect(h.state.tab).toBe("mine"); // el aviso ganó su aplicación
    // más tarde llega OTRA reserva (cambio independiente de reservedCount)
    h.applyLoad({
      available: [
        { id: "A", reserved_for_me: true },
        { id: "C", reserved_for_me: true },
      ],
      mine: [{ id: "B" }], history: [],
    });
    expect(h.state.tab).toBe("available");
  });
});
