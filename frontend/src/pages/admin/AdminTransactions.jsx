import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { toast } from "sonner";
import { Pagination } from "@/components/Pagination";
import { Banknote } from "lucide-react";
import { useTranslation } from "react-i18next";

import { TransactionsTotals } from "./transactions/TransactionsTotals";
import { TransactionsFilters } from "./transactions/TransactionsFilters";
import { TransactionsTable } from "./transactions/TransactionsTable";
import { TransactionDetailModal } from "./transactions/TransactionDetailModal";
import { SectionsLegend } from "./transactions/SectionsLegend";
import { ORIGIN_FILTERS, originOf } from "./transactions/originMeta";

const PAGE_SIZE = 50;

export default function AdminTransactions() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ by_currency: {}, total_count: 0 });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);

  // filters
  const [direction, setDirection] = useState("all");
  const [origin, setOrigin] = useState("all");
  const [currency, setCurrency] = useState("");
  const [holder, setHolder] = useState("");
  const [holderInput, setHolderInput] = useState("");
  const [client, setClient] = useState("");
  const [clientInput, setClientInput] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [selected, setSelected] = useState(null);

  // currencies for dropdown
  const [currencies, setCurrencies] = useState([]);

  useEffect(() => {
    axios.get(`${API}/currencies`, { withCredentials: true })
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, []);

  // debounce holder search
  useEffect(() => {
    const t = setTimeout(() => setHolder(holderInput.trim()), 300);
    return () => clearTimeout(t);
  }, [holderInput]);

  // debounce client search
  useEffect(() => {
    const t = setTimeout(() => setClient(clientInput.trim()), 300);
    return () => clearTimeout(t);
  }, [clientInput]);

  // reset page on filter change
  useEffect(() => {
    setPage(0);
  }, [direction, origin, currency, holder, client, since, until, minAmount, maxAmount]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (direction !== "all") params.direction = direction;
      if (ORIGIN_FILTERS[origin]) params.ref_type = ORIGIN_FILTERS[origin];
      if (currency) params.currency = currency;
      if (holder) params.holder = holder;
      if (client) params.client = client;
      if (since) params.since = since;
      if (until) params.until = until;
      if (minAmount !== "") params.min_amount = minAmount;
      if (maxAmount !== "") params.max_amount = maxAmount;
      const r = await axios.get(`${API}/admin/transactions`, { params, withCredentials: true });
      setItems(r.data.items);
      setTotals(r.data.totals);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.items.length);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.transactions.loadError"));
    } finally {
      setLoading(false);
    }
  }, [direction, origin, currency, holder, client, since, until, minAmount, maxAmount, page, t]);
  useEffect(() => { load(); }, [load]);

  const downloadExport = async (kind) => {
    try {
      const params = new URLSearchParams();
      if (direction !== "all") params.set("direction", direction);
      if (ORIGIN_FILTERS[origin]) params.set("ref_type", ORIGIN_FILTERS[origin]);
      if (currency) params.set("currency", currency);
      if (holder) params.set("holder", holder);
      if (client) params.set("client", client);
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      if (minAmount !== "") params.set("min_amount", minAmount);
      if (maxAmount !== "") params.set("max_amount", maxAmount);
      const url = `${API}/admin/transactions/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `transacciones_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("admin.transactions.exported", { kind: kind.toUpperCase() }));
    } catch (e) {
      toast.error(t("admin.transactions.exportError", { kind: kind.toUpperCase() }));
    }
  };

  const clearFilters = () => {
    setDirection("all");
    setOrigin("all");
    setCurrency("");
    setHolderInput("");
    setClientInput("");
    setSince("");
    setUntil("");
    setMinAmount("");
    setMaxAmount("");
  };

  const hasFilters =
    direction !== "all" || origin !== "all" || currency || holderInput || clientInput || since || until ||
    minAmount !== "" || maxAmount !== "";

  const goToSource = (tx) => {
    setSelected(null);
    navigate(originOf(tx.ref_type).route);
  };

  return (
    <div data-testid="admin-transactions" className="space-y-5">
      <div className="mb-2">
        <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-2">
          <Banknote className="w-3.5 h-3.5" /> {t("admin.transactions.eyebrow")}
        </div>
        <h1 className="font-display text-3xl">{t("admin.transactions.title")}</h1>
        <p className="text-neutral-500 text-sm mt-1">
          {t("admin.transactions.subtitle")}
        </p>
      </div>

      <SectionsLegend />

      <TransactionsTotals totalsByCurrency={totals?.by_currency || {}} />

      <TransactionsFilters
        direction={direction} setDirection={setDirection}
        origin={origin} setOrigin={setOrigin}
        currency={currency} setCurrency={setCurrency}
        holderInput={holderInput} setHolderInput={setHolderInput}
        clientInput={clientInput} setClientInput={setClientInput}
        since={since} setSince={setSince}
        until={until} setUntil={setUntil}
        minAmount={minAmount} setMinAmount={setMinAmount}
        maxAmount={maxAmount} setMaxAmount={setMaxAmount}
        currencies={currencies}
        hasFilters={hasFilters}
        onClear={clearFilters}
        onExport={downloadExport}
      />

      <TransactionsTable items={items} loading={loading} onRowClick={setSelected} />

      <Pagination
        page={page}
        total={total}
        pageSize={PAGE_SIZE}
        loading={loading}
        onPageChange={setPage}
        testidPrefix="tx-pagination"
      />

      <TransactionDetailModal
        selected={selected}
        onClose={() => setSelected(null)}
        onNavigate={goToSource}
      />
    </div>
  );
}
