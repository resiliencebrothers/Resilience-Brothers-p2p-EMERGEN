/**
 * Single source of truth for client-side order/withdrawal status semantics.
 *
 * iter55.25 (Feb 2026) showed the danger of duplicating these sets: the
 * dashboard counter and the /orders table both had their own IN_FLIGHT
 * definitions and drifted, causing "Pendientes: 2" while the table showed 1.
 * This module fixes that once — every consumer imports from here.
 *
 * Semantics reminder:
 *   • orders.approved      = "Confirmado" (staff validated + paid) → NOT pending
 *   • withdrawals.approved = "En progreso" (cash retiro approved but not paid) → still pending
 */

/** Order statuses that are still "in flight" for the client (Pendiente). */
export const ORDER_IN_FLIGHT = Object.freeze(
  new Set(["pending", "requires_double_approval"]),
);

/** Order statuses that count as "Completada" (successful terminal). */
export const ORDER_COMPLETED = Object.freeze(
  new Set(["approved", "completed", "delivered"]),
);

/** Withdrawal statuses that are still "in flight" for the client (Pendiente). */
export const WITHDRAWAL_IN_FLIGHT = Object.freeze(
  new Set(["pending", "approved", "requires_double_approval"]),
);

/** Withdrawal statuses that count as "Completada" (paid out). */
export const WITHDRAWAL_COMPLETED = Object.freeze(new Set(["paid"]));

/** Convenience map for the /orders filter pills. */
export const ORDER_FILTER_STATUSES = Object.freeze({
  all: null, // null → no filter
  pending: [...ORDER_IN_FLIGHT],
  completed: [...ORDER_COMPLETED],
  rejected: ["rejected"],
});
