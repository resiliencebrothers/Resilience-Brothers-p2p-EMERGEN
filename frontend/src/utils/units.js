// iter335 (IPV Fase 4) — unidades de medida + venta por fracción.
// "unidad" = venta por pieza (cantidades enteras). "libra"/"kg" = venta por
// fracción (decimales, 3 posiciones). Las abreviaturas u/lb/kg son universales.
export const UNIT_OPTIONS = ["unidad", "libra", "kg"];

const ABBR = { unidad: "u", libra: "lb", kg: "kg" };

export const unitAbbr = (u) => ABBR[u] || "u";

export const isFractionUnit = (u) => u === "libra" || u === "kg";

// Formatea una cantidad respetando la unidad: entero para "unidad", hasta 3
// decimales para fracciones, y añade la abreviatura (lb/kg) cuando aplica.
export const fmtQty = (n, unit) => {
  const v = Number(n ?? 0);
  const s = v.toLocaleString(undefined, {
    maximumFractionDigits: isFractionUnit(unit) ? 3 : 0,
  });
  return isFractionUnit(unit) ? `${s} ${unitAbbr(unit)}` : s;
};

// Paso del <input type="number"> según la unidad.
export const qtyStep = (unit) => (isFractionUnit(unit) ? "0.001" : "1");

// H12 — Desglosa un mapa {unidad: n, libra: n, kg: n} en texto legible:
// "120 u · 45.5 lb · 12 kg". Las cantidades físicas NO se suman entre unidades
// distintas, así que el total se presenta agregado por unidad. El orden es
// canónico (unidad → libra → kg) para que todas las pantallas coincidan.
const _UNIT_ORDER = { unidad: 0, libra: 1, kg: 2 };
export const fmtUnitsBreakdown = (byUnit) => {
  const entries = Object.entries(byUnit || {});
  if (!entries.length) return "0";
  entries.sort(
    ([a], [b]) =>
      (_UNIT_ORDER[a] ?? 99) - (_UNIT_ORDER[b] ?? 99) || a.localeCompare(b),
  );
  return entries
    .map(([u, v]) => {
      const n = Number(v ?? 0).toLocaleString(undefined, {
        maximumFractionDigits: isFractionUnit(u) ? 3 : 0,
      });
      return `${n} ${unitAbbr(u)}`;
    })
    .join(" · ");
};

// Normaliza el texto de un input de cantidad: solo dígitos para "unidad";
// dígitos + un punto decimal para fracciones.
export const sanitizeQty = (raw, unit) => {
  if (isFractionUnit(unit)) {
    let s = String(raw).replace(/[^0-9.]/g, "");
    const i = s.indexOf(".");
    if (i !== -1) s = s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, "");
    return s;
  }
  return String(raw).replace(/[^0-9]/g, "");
};
