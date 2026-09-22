import { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * Encapsulates data-fetching + rate math for BalanceConverterCard.
 * Returns balances/rates/currencies + memoized derived state + a
 * `refresh()` helper that reloads balances, rates AND dust eligibility.
 *
 * FX10 (auditoría 22/09/2026) — las tasas se recargan en vivo con el evento
 * SSE `rates_updated` y también en cada `refresh()`: la vista previa nunca
 * se queda con una cotización vieja tras un cambio del operador.
 * FX04 — la elegibilidad del barrido de saldos pequeños viene del ENDPOINT
 * (`GET /vip/dust`, cotización ejecutable), no de la valoración local.
 */
export function useConverterData({ isVip, enabled = true }) {
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [dust, setDust] = useState(null);

  const loadBalances = useCallback(() => {
    if (!enabled) return Promise.resolve();
    return axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});
  }, [enabled]);

  const loadRates = useCallback(() => {
    if (!enabled) return Promise.resolve();
    return axios.get(`${API}/rates`, { withCredentials: true })
      .then((r) => setRates(r.data))
      .catch(() => {});
  }, [enabled]);

  const loadDust = useCallback(() => {
    if (!enabled) return Promise.resolve();
    return axios.get(`${API}/vip/dust`, { withCredentials: true })
      .then((r) => setDust(r.data))
      .catch(() => {});
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    loadBalances();
    loadRates();
    loadDust();
    axios.get(`${API}/currencies`)
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, [enabled, loadBalances, loadRates, loadDust]);

  // FX10 — cualquier alta/edición/borrado de tasa recarga la tabla al
  // instante (el evento solo trae el id; la respuesta autorizada viene de
  // GET /rates según el rol).
  useLiveEvent(enabled ? "rates_updated" : null, loadRates);

  // iter85 — Sort positive balances by USDT equivalent DESC so the
  // largest asset in the account shows first in the converter card.
  const positive = useMemo(
    () => (balances.balances || [])
      .filter((b) => Number(b.amount) > 0)
      .slice()
      .sort((a, b) => Number(b.usdt_equivalent || 0) - Number(a.usdt_equivalent || 0)),
    [balances.balances],
  );

  // Mirrors `services/balances.py::_convert_direct` + iter101 tier-picker
  // for SELF-CONVERSION.
  //
  // iter101.1 — Server now injects `rate_convert` on every rate row —
  // pre-computed against the caller's role — so the client never sees the
  // raw `real_rate` (competitive info stays server-side) while the
  // preview still matches the confirmed conversion byte-for-byte. When
  // `rate_convert` is present we use it; otherwise fall back to the
  // legacy per-role picker (kept for admin/staff who still receive
  // `real_rate` and for offline unit tests).
  const computeRate = useCallback((f, tCode) => {
    if (!f || !tCode || f === tCode) return null;
    const pick = (r) => {
      if (r.rate_convert != null && Number(r.rate_convert) > 0) {
        return Number(r.rate_convert);
      }
      if (isVip) return Number(r.rate_vip || r.rate_normal);
      return Number(r.rate_normal);
    };
    // iter287 — ruta inversa = el cliente ADQUIERE el from_code de la fila:
    // aplica la tasa de VENTA única de la empresa (inyectada por el servidor).
    const pickSell = (r) => {
      if (r.rate_convert_sell != null && Number(r.rate_convert_sell) > 0) {
        return Number(r.rate_convert_sell);
      }
      if (r.rate_sell != null && Number(r.rate_sell) > 0) {
        return Number(r.rate_sell);
      }
      return pick(r);
    };
    const direct = rates.find((r) => r.from_code === f && r.to_code === tCode);
    if (direct) {
      const v = pick(direct);
      if (v > 0) return v;
    }
    const inverse = rates.find((r) => r.from_code === tCode && r.to_code === f);
    if (inverse) {
      const inv = pickSell(inverse);
      if (inv > 0) return 1 / inv;
    }
    return null;
  }, [rates, isVip]);

  // Helper: convert an amount in `code` to its USDT equivalent using the
  // same rate table the backend uses. Prefers the operator's inverse
  // valuation quote (USDT→code) then falls back to code→USDT direct.
  const toUsdt = useCallback((amt, code) => {
    if (amt == null || !code) return null;
    if (code === "USDT") return amt;
    const inverse = rates.find((r) => r.from_code === "USDT" && r.to_code === code);
    if (inverse && inverse.rate_normal > 0) return amt / inverse.rate_normal;
    const direct = rates.find((r) => r.from_code === code && r.to_code === "USDT");
    if (direct && direct.rate_normal > 0) return amt * direct.rate_normal;
    return null;
  }, [rates]);

  const refresh = useCallback(
    () => Promise.all([loadBalances(), loadRates(), loadDust()]),
    [loadBalances, loadRates, loadDust],
  );

  return {
    balances, rates, currencies, positive, dust,
    computeRate, toUsdt,
    refresh,
  };
}
