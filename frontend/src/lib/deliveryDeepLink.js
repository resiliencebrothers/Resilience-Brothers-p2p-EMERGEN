/**
 * M02 — coordinación de la navegación por aviso (deep-link) del panel del
 * mensajero con el control de vigencia de la carga compartida.
 *
 * El guard de vigencia (`createLatestGuard`) ya evita que una respuesta
 * ATRASADA sobrescriba la lista (`setData`). Pero el efecto del aviso decidía
 * pestaña/resaltado con el VALOR DEVUELTO por `load`, que se devuelve incluso
 * cuando la respuesta fue descartada por antigua. Así una respuesta vieja podía
 * dejar al mensajero en una pestaña sin la tarjeta que debía mostrar.
 *
 * Este coordinador resuelve el aviso SOLO con una respuesta que:
 *  1) fue APLICADA (es la última iniciada — la lista vigente), y
 *  2) es POSTERIOR a la apertura del aviso (`seq > sinceSeq`), de modo que
 *     refleja el estado del servidor en/después del momento en que se abrió.
 * Si la respuesta de la propia carga del aviso llega tarde y se descarta, un
 * refresco posterior ya aplicado la resuelve con el estado vigente; el aviso
 * no queda sin resolver porque el id pendiente persiste hasta lograrlo.
 */
import { createLatestGuard } from "./latestResponseGuard";

// Mapea el estado VIGENTE a la navegación del aviso (pestaña + resaltado), o
// marca la entrega como desaparecida. Pura.
export function resolveDeepLinkTarget(data, id) {
  if (!data || !id) return null;
  if ((data.available || []).some((d) => d.id === id)) {
    return { tab: "available", highlight: id };
  }
  if ((data.mine || []).some((d) => d.id === id)) {
    return { tab: "mine", highlight: id };
  }
  if ((data.history || []).some((d) => d.id === id)) {
    return { tab: "history", highlight: id };
  }
  return { gone: true };
}

export function createDeepLinkCoordinator() {
  const guard = createLatestGuard();
  let pendingId = null;
  let sinceSeq = 0;
  return {
    // Reserva el turno de una carga; devuelve su número de secuencia.
    beginLoad() {
      return guard.begin();
    },
    // ¿La respuesta de esa carga sigue siendo la última iniciada?
    isApplied(seq) {
      return guard.isLatest(seq);
    },
    // Nuevo aviso pendiente: fija el umbral (solo respuestas posteriores lo
    // resolverán).
    open(id) {
      pendingId = id;
      sinceSeq = guard.peek();
    },
    pending() {
      return pendingId;
    },
    // Llamar SOLO cuando una respuesta fue APLICADA. Devuelve la acción de
    // navegación (o null si aún no hay una respuesta vigente suficientemente
    // fresca para el aviso pendiente). Al resolver, limpia el pendiente.
    onApplied(data, seq) {
      if (pendingId == null) return null;
      if (seq <= sinceSeq) return null;
      const target = resolveDeepLinkTarget(data, pendingId);
      pendingId = null;
      return target;
    },
  };
}
