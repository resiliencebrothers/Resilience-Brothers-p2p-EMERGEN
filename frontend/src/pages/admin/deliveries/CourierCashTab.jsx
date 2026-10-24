import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Banknote, AlertTriangle } from "lucide-react";

// Mejora #1 auditoría — Efectivo en tránsito por mensajero: pendiente de
// rendición por moneda + registro de entregas de caja y rendiciones.

const KIND_COLOR = {
  issued: "text-[#8B5CF6]",
  collected: "text-amber-300",
  delivered_to_recipient: "text-[#22C55E]",
  returned: "text-[#22C55E]",
};

export default function CourierCashTab() {
  const { t } = useTranslation();
  const [summary, setSummary] = useState([]);
  const [events, setEvents] = useState([]);
  const [couriers, setCouriers] = useState([]);
  const [options, setOptions] = useState({ currencies: [], accounts: {} });
  const newOpKey = () => (crypto?.randomUUID ? crypto.randomUUID() : `op_${Date.now()}_${Math.random().toString(36).slice(2)}`);
  const [opKey, setOpKey] = useState(newOpKey());
  const [form, setForm] = useState({
    courier_id: "", kind: "issued", currency: "CUP", amount: "",
    account_id: "", note: "", discrepancy_note: "",
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/admin/courier-cash/summary`, { withCredentials: true })
      .then((r) => setSummary(r.data.couriers || [])).catch(() => {});
    axios.get(`${API}/admin/courier-cash`, { withCredentials: true })
      .then((r) => setEvents(r.data || [])).catch(() => {});
    axios.get(`${API}/admin/couriers`, { withCredentials: true })
      .then((r) => setCouriers(r.data || [])).catch(() => {});
    axios.get(`${API}/admin/courier-cash/options`, { withCredentials: true })
      .then((r) => setOptions({
        currencies: r.data.currencies || [],
        accounts: r.data.accounts || {},
      })).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const accountsForCurrency = options.accounts[form.currency] || [];

  const submit = async () => {
    if (!form.courier_id || !form.amount || !form.currency.trim() || !form.account_id) {
      toast.error(t("admin.cash.formErr"));
      return;
    }
    setBusy(true);
    try {
      await axios.post(`${API}/admin/courier-cash`,
        { ...form, operation_id: opKey }, { withCredentials: true });
      toast.success(t("admin.cash.registered"));
      setForm({ ...form, amount: "", note: "", discrepancy_note: "" });
      setOpKey(newOpKey());  // EF03 — nueva clave tras un registro exitoso
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="courier-cash-tab">
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
            onValueChange={(v) => setForm({ ...form, currency: v, account_id: "" })}
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
      </div>

      {/* Pendiente de rendición por mensajero y moneda */}
      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[820px]" data-testid="cash-summary-table">
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
            {summary.map((s) => (
              <tr key={`${s.courier_id}-${s.currency}`} className="border-b border-white/5" data-testid={`cash-row-${s.courier_id}-${s.currency}`}>
                <td className="px-3 py-3 text-xs">{s.courier_name || s.courier_id}</td>
                <td className="px-3 py-3 font-mono text-xs">{s.currency}</td>
                <td className="px-3 py-3 font-mono text-xs">{s.issued}</td>
                <td className="px-3 py-3 font-mono text-xs">{s.collected}</td>
                <td className="px-3 py-3 font-mono text-xs">{s.delivered_to_recipient}</td>
                <td className="px-3 py-3 font-mono text-xs">{s.returned}</td>
                <td className={`px-3 py-3 font-mono text-sm font-semibold ${
                  s.pending > 0 ? "text-amber-300" : s.pending < 0 ? "text-[#EF4444]" : "text-[#22C55E]"
                }`} data-testid={`cash-pending-${s.courier_id}-${s.currency}`}>
                  {s.pending}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {summary.some((s) => s.pending < 0) && (
          <div className="px-3 py-2 text-[0.65rem] text-[#EF4444] border-t border-white/5">
            {t("admin.cash.negativeHint")}
          </div>
        )}
      </div>

      {/* Últimos movimientos */}
      <div className="tactile-card p-4 space-y-2" data-testid="cash-events-list">
        <div className="micro-label text-neutral-500">{t("admin.cash.eventsTitle")}</div>
        {events.length === 0 && (
          <p className="text-neutral-500 text-xs py-4 text-center">{t("admin.cash.empty")}</p>
        )}
        {events.map((ev) => (
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
            {ev.note && <span className="text-neutral-500 italic">· {ev.note}</span>}
            <span className="text-neutral-600 font-mono text-[0.65rem] ml-auto">
              {new Date(ev.at).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
