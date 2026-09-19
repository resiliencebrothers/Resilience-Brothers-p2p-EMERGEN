/**
 * iter277 — Denominaciones de billetes dinámicas (fábrica + añadidas por el
 * admin). Cache a nivel de módulo para no repetir la petición por componente.
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";

export const DEFAULT_CASH_DENOMS = {
  CUP: [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
  USD: [100, 50, 20, 10, 5, 2, 1],
};

let cache = null;

export function invalidateCashDenoms() {
  cache = null;
}

export function useCashDenoms() {
  const [denoms, setDenoms] = useState(cache || DEFAULT_CASH_DENOMS);
  useEffect(() => {
    if (cache) { setDenoms(cache); return; }
    axios
      .get(`${API}/admin/company-funds/denominations-config`, { withCredentials: true })
      .then((r) => {
        if (r.data && r.data.CUP) { cache = r.data; setDenoms(r.data); }
      })
      .catch(() => {});
  }, []);
  return denoms;
}
