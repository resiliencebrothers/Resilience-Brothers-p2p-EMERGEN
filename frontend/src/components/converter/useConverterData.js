import { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";

/**
 * Encapsulates data-fetching + rate math for BalanceConverterCard.
 * Returns balances/rates/currencies + memoized derived state + a
 * `refresh()` helper that reloads only the user's balances.
 *
 * Employees are opted out at the top level of BalanceConverterCard,
 * so this hook always fetches.
 */
export function useConverterData({ isVip, enabled = true }) {
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);

  const loadBalances = useCallback(() => {
    if (!enabled) return Promise.resolve();
    return axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    loadBalances();
    axios.get(`${API}/rates`).then((r) => setRates(r.data)).catch(() => {});
    axios.get(`${API}/currencies`)
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, [enabled, loadBalances]);

  // iter85 — Sort positive balances by USDT equivalent DESC so the
  // largest asset in the account shows first in the converter card.
  const positive = useMemo(
    () => (balances.balances || [])
      .filter((b) => Number(b.amount) > 0)
      .slice()
      .sort((a, b) => Number(b.usdt_equivalent || 0) - Number(a.usdt_equivalent || 0)),
    [balances.balances],
  );

  // Mirrors `services/balances.py::_convert_direct` (inverse-first).
  const computeRate = useCallback((f, tCode) => {
    if (!f || !tCode || f === tCode) return null;
    const pick = (r) => Number(isVip ? (r.rate_vip || r.rate_normal) : r.rate_normal);
    const direct = rates.find((r) => r.from_code === f && r.to_code === tCode);
    if (direct) {
      const v = pick(direct);
      if (v > 0) return v;
    }
    const inverse = rates.find((r) => r.from_code === tCode && r.to_code === f);
    if (inverse) {
      const inv = pick(inverse);
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

  return {
    balances, rates, currencies, positive,
    computeRate, toUsdt,
    refresh: loadBalances,
  };
}
