/**
 * iter277 — Denominaciones de billetes dinámicas (fábrica + añadidas por el
 * admin). Cache a nivel de módulo para no repetir la petición por componente.
 * S06 — cache REACTIVA: invalidar recarga la configuración y notifica a todos
 * los consumidores montados (los formularios abiertos ven el billete nuevo
 * sin recargar la página).
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";

export const DEFAULT_CASH_DENOMS = {
  CUP: [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
  USD: [100, 50, 20, 10, 5, 2, 1],
};

let cache = null;
const listeners = new Set();

function fetchDenoms() {
  return axios
    .get(`${API}/admin/company-funds/denominations-config`, { withCredentials: true })
    .then((r) => {
      if (r.data && r.data.CUP) {
        cache = r.data;
        listeners.forEach((fn) => fn(cache));
      }
    })
    .catch(() => {});
}

export function invalidateCashDenoms() {
  cache = null;
  fetchDenoms();
}

export function useCashDenoms() {
  const [denoms, setDenoms] = useState(cache || DEFAULT_CASH_DENOMS);
  useEffect(() => {
    listeners.add(setDenoms);
    if (cache) setDenoms(cache);
    else fetchDenoms();
    return () => { listeners.delete(setDenoms); };
  }, []);
  return denoms;
}
