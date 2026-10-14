/**
 * M02-UI — arbitración entre la navegación AUTOMÁTICA por reservas (iter208:
 * abrir «Disponibles» cuando hay entregas reservadas para el mensajero) y la
 * navegación EXPLÍCITA del aviso (deep-link a una entrega concreta).
 *
 * La misma aplicación de la lista que resuelve un aviso hacia otra pestaña
 * (p. ej. «Mis entregas») puede subir `reservedCount` de 0 a 1 y disparar el
 * efecto de reservas, que haría `setTab("available")` pisando la selección del
 * aviso. La selección explícita del aviso debe tener PRIORIDAD durante su
 * apertura y la aplicación de la respuesta que la resuelve.
 *
 * Mecanismo: cada vez que un aviso fija pestaña, se incrementa un «token» de
 * navegación. El efecto de reservas sólo abre «Disponibles» si ese token no ha
 * avanzado respecto al último visto por el efecto — es decir, si NO acaba de
 * resolverse un aviso en esta misma aplicación. Tras consumir el token (en un
 * efecto de sincronización por render), la apertura automática vuelve a actuar
 * para reservas posteriores independientes.
 *
 * @param {number} reservedCount  entregas reservadas para el mensajero
 * @param {number} navToken       token actual (sube al fijar pestaña un aviso)
 * @param {number} navTokenSeen   último token visto por el efecto de reservas
 * @returns {boolean} si debe abrirse automáticamente «Disponibles»
 */
export function shouldAutoOpenReserved(reservedCount, navToken, navTokenSeen) {
  if (navToken !== navTokenSeen) return false; // aviso explícito recién resuelto
  return reservedCount > 0;
}
