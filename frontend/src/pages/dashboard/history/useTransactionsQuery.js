/**
 * iter83 — useTransactionsQuery
 *
 * Encapsulates ALL data-plane concerns of the History section that used to
 * live inline in MyTransactions.jsx:
 *
 * • Filter state (tab, currency, since, until, min/max amount) and page.
 * • Auto page-reset when any filter changes.
 * • Initial /api/currencies + /api/vip/balances fetches.
 * • The paginated /api/me/transactions fetch and error toast.
 * • The 15-second live-feed poller (paused when hidden/off/off-page-0).
 * • The seen-ref-ids tracking that powers the "N new items" pill.
 * • `downloadExport(kind)` and `clearFilters()` helpers.
 *
 * Behaviour is byte-identical to the pre-refactor version — this hook
 * simply centralises the state so the presentational component can shrink.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

export const PAGE_SIZE = 50;
// Live-feed poll interval — must stay in sync with the client-facing copy
// in i18n (myTransactions.live.*). Bumping this requires a UX review.
export const LIVE_POLL_MS = 15_000;

function buildFilterParams({ tab, currency, since, until, minAmount, maxAmount }) {
  const p = {};
  if (tab !== "all") p.direction = tab;
  if (currency) p.currency = currency;
  if (since) p.since = since;
  if (until) p.until = until;
  if (minAmount !== "") p.min_amount = minAmount;
  if (maxAmount !== "") p.max_amount = maxAmount;
  return p;
}

export function useTransactionsQuery() {
  const { t } = useTranslation();

  // --- Filter state -------------------------------------------------------
  const [tab, setTab] = useState("all");
  const [currency, setCurrency] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [page, setPage] = useState(0);

  // --- Server state -------------------------------------------------------
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ by_currency: {}, conversion_count: 0 });
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [currencies, setCurrencies] = useState([]);
  const [balanceSummary, setBalanceSummary] = useState({ balances: [], total_usdt: 0 });

  // --- Live feed state ----------------------------------------------------
  const [liveEnabled, setLiveEnabled] = useState(true);
  const [newItemsCount, setNewItemsCount] = useState(0);
  // Tracking set stored in a ref so mutations don't cause re-renders.
  const seenRefIdsRef = useRef(new Set());
  const loadRef = useRef(null);

  // Bootstrap: currencies + initial balance summary once on mount.
  useEffect(() => {
    axios.get(`${API}/currencies`, { withCredentials: true })
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalanceSummary(r.data))
      .catch(() => {});
  }, []);

  // Reset to page 0 whenever any filter changes.
  useEffect(() => {
    setPage(0);
  }, [tab, currency, since, until, minAmount, maxAmount]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        ...buildFilterParams({ tab, currency, since, until, minAmount, maxAmount }),
      };
      const r = await axios.get(`${API}/me/transactions`, { params, withCredentials: true });
      setItems(r.data.items);
      setTotals(r.data.totals);
      const totalCount = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(totalCount) ? totalCount : r.data.items.length);
      // Reset "new items" tracking to what we just rendered so subsequent
      // polls only surface records that arrive AFTER this load.
      seenRefIdsRef.current = new Set(r.data.items.map((it) => it.ref_id));
      setNewItemsCount(0);
      // Refresh balance summary alongside — cheap single-doc read on the
      // backend, keeps the top-of-page widget in sync with the ledger.
      axios.get(`${API}/vip/balances`, { withCredentials: true })
        .then((rb) => setBalanceSummary(rb.data))
        .catch(() => {});
    } catch (e) {
      toast.error(e.response?.data?.detail || t("myTransactions.loadError"));
    } finally {
      setLoading(false);
    }
  }, [tab, currency, since, until, minAmount, maxAmount, page, t]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRef.current = load; }, [load]);

  // Live-feed poller. Only runs on page 0 while the user hasn't paused it
  // and the tab is currently visible.
  useEffect(() => {
    if (!liveEnabled || page !== 0) return undefined;
    let cancelled = false;
    const poll = async () => {
      if (document.hidden) return;
      try {
        const params = {
          limit: PAGE_SIZE,
          offset: 0,
          ...buildFilterParams({ tab, currency, since, until, minAmount, maxAmount }),
        };
        const r = await axios.get(`${API}/me/transactions`, { params, withCredentials: true });
        if (cancelled) return;
        const seen = seenRefIdsRef.current;
        const newlyArrived = r.data.items.filter((it) => !seen.has(it.ref_id));
        if (newlyArrived.length > 0) setNewItemsCount(newlyArrived.length);
      } catch {
        // Silently swallow — poll retries every LIVE_POLL_MS.
      }
    };
    const id = setInterval(poll, LIVE_POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [liveEnabled, page, tab, currency, since, until, minAmount, maxAmount]);

  const applyNewItems = useCallback(() => {
    if (loadRef.current) loadRef.current();
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const clearFilters = useCallback(() => {
    setTab("all");
    setCurrency("");
    setSince("");
    setUntil("");
    setMinAmount("");
    setMaxAmount("");
  }, []);

  const downloadExport = useCallback(async (kind) => {
    try {
      const params = new URLSearchParams();
      Object.entries(buildFilterParams({
        tab, currency, since, until, minAmount, maxAmount,
      })).forEach(([k, v]) => params.set(k, String(v)));
      const url = `${API}/me/transactions/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `${t("myTransactions.exportFilename")}_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("myTransactions.exportedToast", { kind: kind.toUpperCase() }));
    } catch {
      toast.error(t("myTransactions.exportError", { kind: kind.toUpperCase() }));
    }
  }, [tab, currency, since, until, minAmount, maxAmount, t]);

  const hasFilters = useMemo(
    () => tab !== "all" || currency !== "" || since !== "" || until !== "" || minAmount !== "" || maxAmount !== "",
    [tab, currency, since, until, minAmount, maxAmount],
  );

  return {
    // filters + setters
    filters: {
      tab, setTab,
      currency, setCurrency,
      since, setSince,
      until, setUntil,
      minAmount, setMinAmount,
      maxAmount, setMaxAmount,
      currencies,
      hasFilters,
      clearFilters,
      downloadExport,
    },
    // page
    page, setPage,
    // server data
    items, totals, total, loading, balanceSummary,
    // live feed
    liveEnabled, setLiveEnabled,
    newItemsCount, applyNewItems,
  };
}
