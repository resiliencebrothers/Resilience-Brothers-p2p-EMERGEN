/**
 * M02 — guard de "solo la última petición gana".
 *
 * El panel del mensajero usa una misma carga (`/courier/deliveries`) para el
 * deep-link de un aviso, el refresco periódico y los eventos en vivo. Esas
 * peticiones se solapan y sus respuestas pueden llegar en cualquier orden.
 * Sin control de vigencia, una respuesta ATRASADA (p. ej. la del aviso A, con
 * una lista anterior donde B aún no existe) podía ejecutar su `setData`
 * DESPUÉS de una más reciente y hacer «desaparecer» la entrega del último
 * aviso seleccionado.
 *
 * Cada llamada reserva un número de secuencia con `begin()`; al resolver, solo
 * aplica su resultado si `isLatest(seq)` sigue siendo cierto (es decir, si
 * ninguna petición posterior la ha reemplazado).
 */
export function createLatestGuard() {
  let current = 0;
  return {
    begin() {
      current += 1;
      return current;
    },
    isLatest(seq) {
      return seq === current;
    },
  };
}
