import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Banknote, AlertTriangle, Download, Scale, Clock, ChevronDown,
  ChevronLeft, ChevronRight, Calculator,
} from "lucide-react";

// Efectivo en tránsito por mensajero: conciliación por moneda, panel de
// custodias con alertas, registro con desglose de billetes e historial.

const KIND_COLOR = {
  issued: "text-[#8B5CF6]",
  collected: "text-amber-300",
  delivered_to_recipient: "text-[#22C55E]",
  returned: "text-[#22C55E]",
};
const STALE_DAYS = 3;
const PAGE_SIZE = 25;

const daysSince = (iso) => {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
};

export default function CourierCashTab() {
  const { t } = useTranslation();
  const [summary, setSummary] = useState([]);
  const [reconcile, setReconcile] = useState([]);
  const [events, setEvents] = useState({ items: [], total: 0 });
  const [couriers, setCouriers] = useState([]);
  const [options, setOptions] = useState({ currencies: [], accounts: {}, denominations: {} });
  const newOpKey = () => (crypto?.randomUUID ? crypto.randomUUID() : `op_${Date.now()}_${Math.random().toString(36).slice(2)}`);
  const [opKey, setOpKey] = useState(newOpKey());
  const [form, setForm] = useState({
    courier_id: "", kind: "issued", currency: "CUP", amount: "",
    account_id: "", note: "", discrepancy_note: "",
  });
  const [denoms, setDenoms] = useState({});
  const [showDenoms, setShowDenoms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState({ courier_id: "", currency: "", kind: "" });
  const [page, setPage] = useState(0);

  // Arqueo físico por denominación: cruza el conteo real contra lo esperado.
  const [arqCourier, setArqCourier] = useState("");
  const [arqCurrency, setArqCurrency] = useState("");
  const [arqExp, setArqExp] = useState(null);
  const [arqCounts, setArqCounts] = useState({});
  const [arqNote, setArqNote] = useState("");
  const [arqBusy, setArqBusy] = useState(false);
  const [arqHistory, setArqHistory] = useState([]);
  const [arqResult, setArqResult] = useState(null);

  const loadTop = useCallback(() => {
    axios.get(`${API}/admin/courier-cash/summary`, { withCredentials: true })
      .then((r) => setSummary(r.data.couriers || [])).catch(() => {});
    axios.get(`${API}/admin/courier-cash/reconciliation`, { withCredentials: true })
      .then((r) => setReconcile(r.data.rows || [])).catch(() => {});
    axios.get(`${API}/admin/couriers`, { withCredentials: true })
      .then((r) => setCouriers(r.data || [])).catch(() => {});
    axios.get(`${API}/admin/courier-cash/options`, { withCredentials: true })
      .then((r) => setOptions({
        currencies: r.data.currencies || [],
        accounts: r.data.accounts || {},
        denominations: r.data.denominations || {},
      })).catch(() => {});
  }, []);

  const eventParams = useMemo(() => {
    const p = { skip: page * PAGE_SIZE, limit: PAGE_SIZE };
    if (filters.courier_id) p.courier_id = filters.courier_id;
    if (filters.currency) p.currency = filters.currency;
    if (filters.kind) p.kind = filters.kind;
    return p;
  }, [filters, page]);

  const loadEvents = useCallback(() => {
    axios.get(`${API}/admin/courier-cash`, { params: eventParams, withCredentials: true })
      .then((r) => setEvents(r.data || { items: [], total: 0 })).catch(() => {});
  }, [eventParams]);

  useEffect(() => { loadTop(); }, [loadTop]);
  useEffect(() => { loadEvents(); }, [loadEvents]);

  const loadArqueo = useCallback(() => {
    if (!arqCourier || !arqCurrency) { setArqExp(null); setArqHistory([]); return; }
    axios.get(`${API}/admin/courier-cash/arqueo/expected`, {
      params: { courier_id: arqCourier, currency: arqCurrency },
      withCredentials: true,
    }).then((r) => setArqExp(r.data)).catch(() => setArqExp(null));
    axios.get(`${API}/admin/courier-cash/arqueo/history`, {
      params: { courier_id: arqCourier, currency: arqCurrency, limit: 5 },
      withCredentials: true,
    }).then((r) => setArqHistory(r.data.items || [])).catch(() => setArqHistory([]));
  }, [arqCourier, arqCurrency]);

  useEffect(() => {
    loadArqueo();
    setArqCounts({});
    setArqResult(null);
  }, [loadArqueo]);

  const arqDenoms = (arqExp?.denominations && arqExp.denominations.length
    ? arqExp.denominations
    : options.denominations[arqCurrency] || []);
  const arqCountedTotal = useMemo(
    () => arqDenoms.reduce((s, d) => s + Number(d) * (Number(arqCounts[d]) || 0), 0),
    [arqCounts, arqDenoms]);
  const arqExpectedTotal = arqExp?.expected_total ?? 0;
  const arqPending = arqExp?.pending ?? 0;
  const arqTotalDiff = Math.round((arqCountedTotal - arqExpectedTotal) * 100) / 100;
  const arqPendingDiff = Math.round((arqCountedTotal - arqPending) * 100) / 100;

  const submitArqueo = async () => {
    if (!arqCourier || !arqCurrency) {
      toast.error(t("admin.cash.arqueo.selectPrompt"));
      return;
    }
    setArqBusy(true);
    try {
      const counted = Object.fromEntries(
        Object.entries(arqCounts).filter(([, q]) => Number(q) > 0)
          .map(([d, q]) => [d, Number(q)]));
      const r = await axios.post(`${API}/admin/courier-cash/arqueo`, {
        courier_id: arqCourier, currency: arqCurrency, counted, note: arqNote,
      }, { withCredentials: true });
      setArqResult(r.data);
      toast.success(t("admin.cash.arqueo.saved"));
      setArqNote("");
      loadArqueo();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setArqBusy(false);
    }
  };

  const exportArqueoCsv = () => {
    const qs = new URLSearchParams();
    if (arqCourier) qs.set("courier_id", arqCourier);
    if (arqCurrency) qs.set("currency", arqCurrency);
    window.open(`${API}/admin/courier-cash/arqueo/export.csv?${qs.toString()}`, "_blank");
  };

  const accountsForCurrency = options.accounts[form.currency] || [];
  const denomList = options.denominations[form.currency] || [];
  const denomSum = useMemo(
    () => Object.entries(denoms).reduce(
      (s, [d, q]) => s + Number(d) * (Number(q) || 0), 0),
    [denoms]);
  const amountNum = Number(form.amount) || 0;
  const denomsEntered = Object.values(denoms).some((q) => Number(q) > 0);
  const denomsMatch = !denomsEntered || Math.abs(denomSum - amountNum) < 0.01;

  const resetForm = () => {
    setForm((f) => ({ ...f, amount: "", note: "", discrepancy_note: "" }));
    setDenoms({});
  };

  const submit = async () => {
    if (!form.courier_id || !form.amount || !form.currency.trim() || !form.account_id) {
      toast.error(t("admin.cash.formErr"));
      return;
    }
    if (denomsEntered && !denomsMatch) {
      toast.error(t("admin.cash.denomsMismatchErr"));
      return;
    }
    setBusy(true);
    try {
      const payload = { ...form, operation_id: opKey };
      if (denomsEntered) {
        payload.denominations = Object.fromEntries(
          Object.entries(denoms).filter(([, q]) => Number(q) > 0)
            .map(([d, q]) => [d, Number(q)]));
      }
      await axios.post(`${API}/admin/courier-cash`, payload, { withCredentials: true });
      toast.success(t("admin.cash.registered"));
      resetForm();
      setOpKey(newOpKey());
      loadTop();
      loadEvents();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  const exportCsv = () => {
    const qs = new URLSearchParams();
    if (filters.courier_id) qs.set("courier_id", filters.courier_id);
    if (filters.currency) qs.set("currency", filters.currency);
    if (filters.kind) qs.set("kind", filters.kind);
    window.open(`${API}/admin/courier-cash/export.csv?${qs.toString()}`, "_blank");
  };

  const totalPages = Math.max(1, Math.ceil(events.total / PAGE_SIZE));

  return (
    <div className="space-y-6" data-testid="courier-cash-tab">
      {/* Conciliación por moneda */}
      <div className="space-y-2" data-testid="cash-reconciliation">
        <div className="micro-label text-neutral-500 flex items-center gap-2">
          <Scale className="w-4 h-4 text-sky-300" /> {t("admin.cash.reconcileTitle")}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {reconcile.length === 0 && (
            <div className="text-neutral-500 text-xs py-3">{t("admin.cash.empty")}</div>
          )}
          {reconcile.map((r) => (
            <div key={r.currency} className="tactile-card p-4" data-testid={`reconcile-${r.currency}`}>
              <div className="flex items-baseline justify-between mb-2">
                <span className="font-display text-lg">{r.currency}</span>
                <span className="font-mono text-sm text-neutral-400">
                  {t("admin.cash.colTotal")}: <b className="text-white">{r.total.toLocaleString()}</b>
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <ReconCell label={t("admin.cash.colBox")} value={r.box} tone="text-white" testid={`recon-box-${r.currency}`} />
                <ReconCell label={t("admin.cash.colTransit")} value={r.in_transit} tone="text-[#8B5CF6]" testid={`recon-transit-${r.currency}`} />
                <ReconCell label={t("admin.cash.colUnconfirmed")} value={r.collected_unconfirmed} tone={r.collected_unconfirmed > 0 ? "text-amber-300" : "text-neutral-500"} testid={`recon-unconf-${r.currency}`} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Registro manual: caja → mensajero / rendición recibida */}
      <div className="tactile-card p-4 space-y-3">
        <div className="micro-label text-neutral-500 flex items-center gap-2">
          <Banknote className="w-4 h-4 text-[#8B5CF6]" /> {t("admin.cash.registerTitle")}
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-2">
          <Select value={form.courier_id} onValueChange={(v) => setForm({ ...form, courier_id: v })}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10 col-span-2" data-testid="cash-courier-select">
              <SelectValue placeholder={t("admin.deliveries.colCourier")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {couriers.map((c) => (
                <SelectItem key={c.user_id} value={c.user_id}>{c.name || c.email}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v })}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="cash-kind-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              <SelectItem value="issued">{t("admin.cash.kindIssued")}</SelectItem>
              <SelectItem value="returned">{t("admin.cash.kindReturned")}</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={form.currency}
            onValueChange={(v) => { setForm({ ...form, currency: v, account_id: "" }); setDenoms({}); }}
          >
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10 font-mono" data-testid="cash-currency-select">
              <SelectValue placeholder={t("admin.cash.currencyPh")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              {options.currencies.map((cur) => (
                <SelectItem key={cur} value={cur}>{cur}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            placeholder={t("admin.cash.amountPh")}
            inputMode="decimal"
            data-testid="cash-amount-input"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 font-mono"
          />
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="cash-submit-btn"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-10 disabled:opacity-40"
          >
            {busy ? "…" : t("admin.cash.submitBtn")}
          </Button>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
          <Select
            value={form.account_id}
            onValueChange={(v) => setForm({ ...form, account_id: v })}
          >
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="cash-account-select">
              <SelectValue placeholder={form.kind === "issued" ? t("admin.cash.accountFromPh") : t("admin.cash.accountToPh")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {accountsForCurrency.length === 0 && (
                <div className="px-3 py-2 text-xs text-neutral-500">{t("admin.cash.noAccounts")}</div>
              )}
              {accountsForCurrency.map((a) => (
                <SelectItem key={a.id} value={a.id}>{a.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
            placeholder={t("admin.cash.notePh")}
            data-testid="cash-note-input"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs"
          />
          <Input
            value={form.discrepancy_note}
            onChange={(e) => setForm({ ...form, discrepancy_note: e.target.value })}
            placeholder={t("admin.cash.discrepancyPh")}
            data-testid="cash-discrepancy-input"
            className="rounded-none bg-[#0a0a0a] border-amber-400/30 h-9 text-xs placeholder:text-amber-300/50"
          />
        </div>

        {/* Desglose de billetes (opcional) */}
        <div className="border-t border-white/5 pt-2">
          <button
            type="button"
            onClick={() => setShowDenoms((s) => !s)}
            data-testid="cash-denoms-toggle"
            className="text-xs text-neutral-400 flex items-center gap-1 hover:text-white"
          >
            <ChevronDown className={`w-3 h-3 transition-transform ${showDenoms ? "rotate-180" : ""}`} />
            {t("admin.cash.denomsTitle")}
          </button>
          {showDenoms && (
            <div className="mt-2 space-y-2" data-testid="cash-denoms-panel">
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
                {denomList.map((d) => (
                  <div key={d} className="flex items-center gap-1">
                    <span className="font-mono text-[0.65rem] text-neutral-500 w-10 text-right">{d.toLocaleString()}</span>
                    <Input
                      value={denoms[d] || ""}
                      onChange={(e) => setDenoms({ ...denoms, [d]: e.target.value.replace(/[^0-9]/g, "") })}
                      inputMode="numeric"
                      data-testid={`cash-denom-${d}`}
                      className="rounded-none bg-[#0a0a0a] border-white/10 h-8 text-xs font-mono px-1"
                    />
                  </div>
                ))}
              </div>
              <div className="text-xs flex items-center gap-2" data-testid="cash-denoms-sum">
                <span className="text-neutral-500">{t("admin.cash.denomsSum")}:</span>
                <span className="font-mono">{denomSum.toLocaleString()} {form.currency}</span>
                {denomsEntered && (
                  <span className={denomsMatch ? "text-[#22C55E]" : "text-[#EF4444]"}>
                    {denomsMatch ? t("admin.cash.denomsMatch") : `≠ ${amountNum.toLocaleString()}`}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Panel de custodias: pendiente por mensajero y moneda, con alertas */}
      <div className="tactile-card overflow-x-auto" data-testid="cash-custody-panel">
        <div className="micro-label text-neutral-500 px-3 pt-3 flex items-center gap-2">
          <Banknote className="w-4 h-4 text-amber-300" /> {t("admin.cash.custodyTitle")}
        </div>
        <table className="w-full text-sm min-w-[900px]" data-testid="cash-summary-table">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colCourier")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colCurrency")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colIssued")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colCollected")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colDelivered")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colReturned")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.cash.colPending")}</th>
            </tr>
          </thead>
          <tbody>
            {summary.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.cash.empty")}</td></tr>
            )}
            {summary.map((s) => {
              const age = daysSince(s.oldest_at);
              const stale = s.pending > 0 && age >= STALE_DAYS;
              return (
                <tr key={`${s.courier_id}-${s.currency}`} className="border-b border-white/5" data-testid={`cash-row-${s.courier_id}-${s.currency}`}>
                  <td className="px-3 py-3 text-xs">{s.courier_name || s.courier_id}</td>
                  <td className="px-3 py-3 font-mono text-xs">{s.currency}</td>
                  <td className="px-3 py-3 font-mono text-xs">{Number(s.issued).toLocaleString()}</td>
                  <td className="px-3 py-3 font-mono text-xs">{Number(s.collected).toLocaleString()}</td>
                  <td className="px-3 py-3 font-mono text-xs">{Number(s.delivered_to_recipient).toLocaleString()}</td>
                  <td className="px-3 py-3 font-mono text-xs">{Number(s.returned).toLocaleString()}</td>
                  <td className={`px-3 py-3 font-mono text-sm font-semibold ${
                    s.pending > 0 ? "text-amber-300" : s.pending < 0 ? "text-[#EF4444]" : "text-[#22C55E]"
                  }`} data-testid={`cash-pending-${s.courier_id}-${s.currency}`}>
                    <span className="inline-flex items-center gap-1.5">
                      {Number(s.pending).toLocaleString()}
                      {stale && (
                        <span className="inline-flex items-center gap-0.5 text-[0.6rem] text-[#EF4444] border border-[#EF4444]/40 px-1 rounded-sm" data-testid={`cash-stale-${s.courier_id}-${s.currency}`} title={t("admin.cash.staleTitle")}>
                          <Clock className="w-2.5 h-2.5" /> {age}d
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {summary.some((s) => s.pending < 0) && (
          <div className="px-3 py-2 text-[0.65rem] text-[#EF4444] border-t border-white/5">
            {t("admin.cash.negativeHint")}
          </div>
        )}
      </div>

      {/* Arqueo físico por denominación: cruza el conteo real contra lo esperado */}
      <div className="tactile-card p-4 space-y-3" data-testid="arqueo-card">
        <div className="flex items-center justify-between gap-2">
          <div className="micro-label text-neutral-500 flex items-center gap-2">
            <Calculator className="w-4 h-4 text-sky-300" /> {t("admin.cash.arqueo.title")}
          </div>
          {arqCourier && arqCurrency && (
            <button
              onClick={exportArqueoCsv}
              data-testid="arqueo-export-btn"
              className="inline-flex items-center gap-1.5 text-[0.7rem] text-sky-300 hover:text-sky-200 border border-sky-400/30 hover:border-sky-400/60 px-2.5 py-1 transition-colors"
            >
              <Download className="w-3 h-3" /> {t("admin.cash.arqueo.exportBtn")}
            </button>
          )}
        </div>
        <p className="text-xs text-neutral-500">{t("admin.cash.arqueo.help")}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Select value={arqCourier} onValueChange={setArqCourier}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="arqueo-courier-select">
              <SelectValue placeholder={t("admin.deliveries.colCourier")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {couriers.map((c) => (
                <SelectItem key={c.user_id} value={c.user_id}>{c.name || c.email}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={arqCurrency} onValueChange={setArqCurrency}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10 font-mono" data-testid="arqueo-currency-select">
              <SelectValue placeholder={t("admin.cash.currencyPh")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              {options.currencies.map((cur) => (
                <SelectItem key={cur} value={cur}>{cur}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {(!arqCourier || !arqCurrency) && (
          <div className="text-xs text-neutral-500 py-2" data-testid="arqueo-select-prompt">
            {t("admin.cash.arqueo.selectPrompt")}
          </div>
        )}

        {arqCourier && arqCurrency && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[480px]" data-testid="arqueo-table">
                <thead className="border-b border-white/10 bg-[#0a0a0a]">
                  <tr className="text-left">
                    <th className="px-3 py-2 micro-label text-neutral-500">{t("admin.cash.arqueo.colDenom")}</th>
                    <th className="px-3 py-2 micro-label text-neutral-500 text-right">{t("admin.cash.arqueo.colExpected")}</th>
                    <th className="px-3 py-2 micro-label text-neutral-500 text-right">{t("admin.cash.arqueo.colCounted")}</th>
                    <th className="px-3 py-2 micro-label text-neutral-500 text-right">{t("admin.cash.arqueo.colDiff")}</th>
                  </tr>
                </thead>
                <tbody>
                  {arqDenoms.map((d) => {
                    const exp = Number(arqExp?.expected?.[d] || 0);
                    const cnt = Number(arqCounts[d]) || 0;
                    const diff = cnt - exp;
                    return (
                      <tr key={d} className="border-b border-white/5" data-testid={`arqueo-row-${d}`}>
                        <td className="px-3 py-1.5 font-mono text-xs">{Number(d).toLocaleString()}</td>
                        <td className="px-3 py-1.5 font-mono text-xs text-right text-neutral-400" data-testid={`arqueo-expected-${d}`}>{exp}</td>
                        <td className="px-3 py-1.5 text-right">
                          <Input
                            value={arqCounts[d] || ""}
                            onChange={(e) => setArqCounts({ ...arqCounts, [d]: e.target.value.replace(/[^0-9]/g, "") })}
                            inputMode="numeric"
                            data-testid={`arqueo-count-${d}`}
                            className="rounded-none bg-[#0a0a0a] border-white/10 h-8 text-xs font-mono px-1 w-20 ml-auto text-right"
                          />
                        </td>
                        <td className={`px-3 py-1.5 font-mono text-xs text-right ${diff === 0 ? "text-neutral-600" : diff < 0 ? "text-[#EF4444]" : "text-amber-300"}`} data-testid={`arqueo-diff-${d}`}>
                          {diff > 0 ? `+${diff}` : diff}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
              <ReconCell label={t("admin.cash.arqueo.countedTotal")} value={arqCountedTotal} tone="text-white" testid="arqueo-counted-total" />
              <ReconCell label={t("admin.cash.arqueo.expectedTotal")} value={arqExpectedTotal} tone="text-neutral-400" testid="arqueo-expected-total" />
              <ReconCell label={t("admin.cash.arqueo.pending")} value={arqPending} tone="text-[#8B5CF6]" testid="arqueo-pending" />
              <div data-testid="arqueo-pending-diff">
                <div className="micro-label text-neutral-500 text-[0.6rem]">{t("admin.cash.arqueo.pendingDiff")}</div>
                <div className={`font-mono text-sm ${arqPendingDiff === 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
                  {arqPendingDiff > 0 ? `+${arqPendingDiff.toLocaleString()}` : arqPendingDiff.toLocaleString()}
                </div>
              </div>
            </div>
            {arqExp && arqExp.untracked > 0 && (
              <div className="text-[0.65rem] text-amber-300/80" data-testid="arqueo-untracked-hint">
                {t("admin.cash.arqueo.untrackedHint", { amount: arqExp.untracked.toLocaleString(), currency: arqCurrency })}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={arqNote}
                onChange={(e) => setArqNote(e.target.value)}
                placeholder={t("admin.cash.arqueo.notePh")}
                data-testid="arqueo-note-input"
                className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs flex-1 min-w-[180px]"
              />
              <Button
                onClick={submitArqueo}
                disabled={arqBusy}
                data-testid="arqueo-submit-btn"
                className="rounded-none bg-sky-500 hover:bg-sky-400 text-white h-9 text-xs disabled:opacity-40"
              >
                {arqBusy ? "…" : t("admin.cash.arqueo.saveBtn")}
              </Button>
            </div>

            {arqResult && (
              <div className={`text-xs px-3 py-2 border ${arqResult.total_diff === 0 && arqResult.pending_diff === 0 ? "border-[#22C55E]/40 text-[#22C55E]" : "border-[#EF4444]/40 text-[#EF4444]"}`} data-testid="arqueo-result">
                {arqResult.total_diff === 0 && arqResult.pending_diff === 0
                  ? t("admin.cash.arqueo.noDiff")
                  : t("admin.cash.arqueo.diffSummary", {
                    pendingDiff: arqResult.pending_diff.toLocaleString(),
                    currency: arqResult.currency,
                  })}
              </div>
            )}

            {arqHistory.length > 0 && (
              <div className="border-t border-white/5 pt-2" data-testid="arqueo-history">
                <div className="micro-label text-neutral-500 mb-1">{t("admin.cash.arqueo.historyTitle")}</div>
                <div className="space-y-1">
                  {arqHistory.map((a) => (
                    <div key={a.id} className="flex flex-wrap items-baseline gap-x-3 text-[0.7rem] text-neutral-400" data-testid={`arqueo-hist-${a.id}`}>
                      <span className="font-mono">{new Date(a.at).toLocaleString()}</span>
                      <span className="font-mono text-white">{a.counted_total.toLocaleString()} {a.currency}</span>
                      <span className={a.pending_diff === 0 ? "text-[#22C55E]" : "text-[#EF4444]"}>
                        {t("admin.cash.arqueo.pendingDiff")}: {a.pending_diff > 0 ? `+${a.pending_diff}` : a.pending_diff}
                      </span>
                      {a.by_name && <span className="text-neutral-500">· {a.by_name}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Historial paginado, filtrable y exportable */}
      <div className="tactile-card p-4 space-y-3" data-testid="cash-events-list">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <div className="micro-label text-neutral-500">{t("admin.cash.eventsTitle")}</div>
          <Button onClick={exportCsv} data-testid="cash-export-btn"
            className="rounded-none bg-transparent border border-white/15 hover:bg-white/5 text-white h-8 text-xs">
            <Download className="w-3.5 h-3.5 mr-1" /> {t("admin.cash.exportBtn")}
          </Button>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
          <Select value={filters.courier_id || "all"} onValueChange={(v) => { setPage(0); setFilters({ ...filters, courier_id: v === "all" ? "" : v }); }}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs" data-testid="cash-filter-courier">
              <SelectValue placeholder={t("admin.deliveries.colCourier")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              <SelectItem value="all">{t("admin.cash.filterAll")}</SelectItem>
              {couriers.map((c) => (
                <SelectItem key={c.user_id} value={c.user_id}>{c.name || c.email}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={filters.currency || "all"} onValueChange={(v) => { setPage(0); setFilters({ ...filters, currency: v === "all" ? "" : v }); }}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs font-mono" data-testid="cash-filter-currency">
              <SelectValue placeholder={t("admin.cash.colCurrency")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              <SelectItem value="all">{t("admin.cash.filterAll")}</SelectItem>
              {options.currencies.map((cur) => (
                <SelectItem key={cur} value={cur}>{cur}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={filters.kind || "all"} onValueChange={(v) => { setPage(0); setFilters({ ...filters, kind: v === "all" ? "" : v }); }}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs" data-testid="cash-filter-kind">
              <SelectValue placeholder={t("admin.cash.colType")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              <SelectItem value="all">{t("admin.cash.filterAll")}</SelectItem>
              <SelectItem value="issued">{t("admin.cash.kind.issued", "issued")}</SelectItem>
              <SelectItem value="returned">{t("admin.cash.kind.returned", "returned")}</SelectItem>
              <SelectItem value="collected">{t("admin.cash.kind.collected", "collected")}</SelectItem>
              <SelectItem value="delivered_to_recipient">{t("admin.cash.kind.delivered_to_recipient", "delivered")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {events.items.length === 0 && (
          <p className="text-neutral-500 text-xs py-4 text-center">{t("admin.cash.empty")}</p>
        )}
        {events.items.map((ev) => {
          const denomStr = ev.denominations
            ? Object.entries(ev.denominations).map(([d, q]) => `${Number(d).toLocaleString()}×${q}`).join("  ")
            : "";
          return (
            <div key={ev.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs border-l-2 border-white/10 pl-2 py-1" data-testid={`cash-event-${ev.id}`}>
              <span className={`font-mono uppercase text-[0.65rem] ${KIND_COLOR[ev.kind] || ""}`}>
                {t(`admin.cash.kind.${ev.kind}`, ev.kind)}
              </span>
              <span className="font-mono">{ev.amount} {ev.currency}</span>
              <span className="text-neutral-400">{ev.courier_name}</span>
              {ev.discrepancy && (
                <span className="text-amber-300 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> {t("admin.cash.discrepancyTag")}
                </span>
              )}
              {denomStr && <span className="text-sky-300/70 font-mono text-[0.6rem]">🧾 {denomStr}</span>}
              {ev.note && <span className="text-neutral-500 italic">· {ev.note}</span>}
              <span className="text-neutral-400 font-mono text-[0.65rem] ml-auto">
                {new Date(ev.at).toLocaleString()}
              </span>
            </div>
          );
        })}

        {/* Paginación */}
        <div className="flex items-center justify-between pt-2 border-t border-white/5 text-xs">
          <span className="text-neutral-500" data-testid="cash-events-count">
            {t("admin.cash.totalEvents", { count: events.total })}
          </span>
          <div className="flex items-center gap-2">
            <Button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
              data-testid="cash-prev-page"
              className="rounded-none bg-transparent border border-white/15 hover:bg-white/5 text-white h-7 w-7 p-0 disabled:opacity-30">
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="font-mono text-neutral-400" data-testid="cash-page-indicator">{page + 1} / {totalPages}</span>
            <Button onClick={() => setPage((p) => (p + 1 < totalPages ? p + 1 : p))} disabled={page + 1 >= totalPages}
              data-testid="cash-next-page"
              className="rounded-none bg-transparent border border-white/15 hover:bg-white/5 text-white h-7 w-7 p-0 disabled:opacity-30">
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReconCell({ label, value, tone, testid }) {
  return (
    <div data-testid={testid}>
      <div className="micro-label text-neutral-500 text-[0.6rem]">{label}</div>
      <div className={`font-mono text-sm ${tone}`}>{(value ?? 0).toLocaleString()}</div>
    </div>
  );
}
