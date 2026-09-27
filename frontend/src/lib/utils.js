import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// DR01 — importes con la precisión real del activo: nunca mostrar como 0
// un importe positivo (cripto hasta 8 decimales, fiat mínimo 2).
export function formatAmount(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });
}
