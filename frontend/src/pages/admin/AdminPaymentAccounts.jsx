import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import { Plus, Edit2, Trash2, Download } from "lucide-react";
import { toast } from "sonner";

const empty = { currency_code: "", label: "", account_details: "", network: "", min_amount: "", max_amount: "", is_active: true };

// iter151 — Common network / method values suggested to the admin as a
// datalist so we avoid typos like "bep 20" vs "BEP20" that could confuse
// the client. Freeform so admins can still write anything (SEPA, SWIFT,
// Wise, custom bank name, etc.).
const COMMON_NETWORKS = [
  "BEP20", "TRC20", "ERC20", "Polygon", "Arbitrum", "Optimism", "Solana",
  "Avalanche C-Chain", "Bitcoin", "Lightning", "TON",
  "SEPA", "SWIFT", "ACH", "Zelle", "Wire",
];

export default function AdminPaymentAccounts() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [pendingTotp, setPendingTotp] = useState(null);

  const load = async () => {
    const [a, c] = await Promise.all([
      axios.get(`${API}/admin/payment-accounts`, { withCredentials: true }),
      axios.get(`${API}/currencies`),
    ]);
    setAccounts(a.data);
    setCurrencies(c.data);
  };
  useEffect(() => { load(); }, []);

  const buildPayload = () => ({
    currency_code: form.currency_code,
    label: form.label.trim(),
    account_details: form.account_details.trim(),
    network: form.network.trim() || null,
    min_amount: parseFloat(form.min_amount) || 0,
    max_amount: form.max_amount === "" || form.max_amount == null ? null : parseFloat(form.max_amount),
    is_active: !!form.is_active,
  });

  const save = () => {
    if (!form.currency_code || !form.label.trim() || !form.account_details.trim()) {
      toast.error(t("admin.paymentAccounts.toastError"));
      return;
    }
    setPendingTotp(buildPayload());
  };

  const confirmWithTotp = async (code) => {
    const payload = { ...pendingTotp, totp_code: code };
    try {
      if (editing) {
        await axios.put(`${API}/admin/payment-accounts/${editing.id}`, payload, { withCredentials: true });
      } else {
        await axios.post(`${API}/admin/payment-accounts`, payload, { withCredentials: true });
      }
      toast.success(t("admin.paymentAccounts.toastSaved"));
      setPendingTotp(null);
      setOpen(false); setEditing(null); setForm(empty);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.paymentAccounts.toastError"));
      }
    }
  };

  const remove = async (id) => {
    if (!window.confirm(t("admin.paymentAccounts.confirmDelete"))) return;
    try {
      await axios.delete(`${API}/admin/payment-accounts/${id}`, { withCredentials: true });
      toast.success(t("admin.paymentAccounts.toastDeleted"));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.paymentAccounts.toastError"));
    }
  };

  const openEdit = (a) => {
    setEditing(a);
    setForm({
      currency_code: a.currency_code,
      label: a.label,
      account_details: a.account_details,
      network: a.network || "",
      min_amount: a.min_amount ?? "",
      max_amount: a.max_amount ?? "",
      is_active: a.is_active !== false,
    });
    setOpen(true);
  };

  const fmt = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString());

  return (
    <div data-testid="admin-payment-accounts">
      <AdminPageHeader
        eyebrow={t("admin.paymentAccounts.eyebrow")}
        title={t("admin.paymentAccounts.title")}
        actions={
          <Button data-testid="add-account-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> {t("admin.paymentAccounts.newBtn")}
          </Button>
        }
      />

      <p className="text-xs text-neutral-500 mb-4 max-w-3xl">{t("admin.paymentAccounts.helper")}</p>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.colCurrency")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.colLabel")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.colDetails")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.colMin")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.colMax")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.colActive")}</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {accounts.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-neutral-500 text-xs" data-testid="accounts-empty">
                  {t("admin.paymentAccounts.empty")}
                </td>
              </tr>
            )}
            {accounts.map((a) => (
              <tr key={a.id} className={`border-b border-white/5 ${a.is_active === false ? "opacity-50" : ""}`} data-testid={`account-row-${a.id}`}>
                <td className="px-4 py-3 font-mono text-white">{a.currency_code}</td>
                <td className="px-4 py-3 text-white">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span>{a.label}</span>
                    {a.network ? (
                      <span
                        className="text-[0.6rem] font-mono px-1.5 py-0.5 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#A78BFA] uppercase tracking-widest"
                        data-testid={`account-network-badge-${a.id}`}
                      >
                        {a.network}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs">
                  <span className="line-clamp-2 whitespace-pre-wrap">{a.account_details}</span>
                </td>
                <td className="px-4 py-3 font-mono text-[#8B5CF6] text-right">{fmt(a.min_amount)}</td>
                <td className="px-4 py-3 font-mono text-neutral-400 text-right">{fmt(a.max_amount)}</td>
                <td className="px-4 py-3 text-xs">
                  {a.is_active !== false
                    ? <span className="text-emerald-400">✓</span>
                    : <span className="text-neutral-500">—</span>}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button data-testid={`edit-account-${a.id}`} onClick={() => openEdit(a)} className="text-neutral-400 hover:text-[#8B5CF6] mr-3"><Edit2 className="w-4 h-4" /></button>
                  <button data-testid={`delete-account-${a.id}`} onClick={() => remove(a.id)} className="text-neutral-400 hover:text-[#EF4444]"><Trash2 className="w-4 h-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <DailyTotalsSection accounts={accounts} />

      <Dialog open={open} onOpenChange={setOpen}>        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">
              {editing ? t("admin.paymentAccounts.editTitle") : t("admin.paymentAccounts.newTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.currencyLabel")}</Label>
              <Select value={form.currency_code} onValueChange={(v) => setForm({ ...form, currency_code: v })}>
                <SelectTrigger data-testid="account-currency" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder={t("admin.paymentAccounts.select")} /></SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  {currencies.map((c) => <SelectItem key={c.id} value={c.code}>{c.code} — {c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.labelLabel")}</Label>
              <Input data-testid="account-label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder={t("admin.paymentAccounts.labelPh")} maxLength={80} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.networkLabel")}</Label>
              <Input
                data-testid="account-network"
                value={form.network}
                onChange={(e) => setForm({ ...form, network: e.target.value })}
                placeholder={t("admin.paymentAccounts.networkPh")}
                list="pa-network-suggestions"
                maxLength={30}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono uppercase text-sm"
              />
              <datalist id="pa-network-suggestions">
                {COMMON_NETWORKS.map((n) => <option key={n} value={n} />)}
              </datalist>
              <p className="text-[0.65rem] text-neutral-500 mt-1">{t("admin.paymentAccounts.networkHint")}</p>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.detailsLabel")}</Label>
              <Textarea data-testid="account-details" value={form.account_details} onChange={(e) => setForm({ ...form, account_details: e.target.value })} placeholder={t("admin.paymentAccounts.detailsPh")} rows={6} maxLength={1500} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono text-xs" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.minLabel")}</Label>
                <Input data-testid="account-min" type="number" step="any" min="0" value={form.min_amount} onChange={(e) => setForm({ ...form, min_amount: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.maxLabel")}</Label>
                <Input data-testid="account-max" type="number" step="any" min="0" value={form.max_amount} onChange={(e) => setForm({ ...form, max_amount: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
            </div>
            <div className="flex items-center justify-between border border-white/10 px-3 py-2">
              <Label className="micro-label text-neutral-500">{t("admin.paymentAccounts.activeLabel")}</Label>
              <Switch data-testid="account-active" checked={!!form.is_active} onCheckedChange={(v) => setForm({ ...form, is_active: v })} />
            </div>
            <Button data-testid="save-account-btn" onClick={save} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
              {t("admin.paymentAccounts.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingTotp}
        title={t("admin.paymentAccounts.totpTitle")}
        description={t("admin.paymentAccounts.totpDescription")}
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingTotp(null)}
      />
    </div>
  );
}

const RANGE_OPTIONS = [7, 14, 30];

function DailyTotalsSection({ accounts }) {
  const { t } = useTranslation();
  const [days, setDays] = useState(14);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [accFilter, setAccFilter] = useState("all");

  const exportTotals = async (kind) => {
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (accFilter !== "all") params.set("account", accFilter);
      const url = `${API}/admin/payment-accounts/daily-totals/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `conciliacion_cuentas_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("admin.paymentAccounts.exportOk", { kind: kind.toUpperCase() }));
    } catch {
      toast.error(t("admin.paymentAccounts.exportError", { kind: kind.toUpperCase() }));
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    axios.get(`${API}/admin/payment-accounts/daily-totals`, {
      params: { days }, withCredentials: true,
    })
      .then((r) => { if (!cancelled) setRows(r.data?.rows || []); })
      .catch(() => { if (!cancelled) setRows([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  const visible = accFilter === "all" ? rows : rows.filter((r) => r.account_id === accFilter);
  const fmt = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2 });
  let lastDate = null;

  return (
    <div className="mt-8" data-testid="daily-totals-section">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-2">
        <div>
          <h2 className="font-display text-lg text-white">{t("admin.paymentAccounts.totalsTitle")}</h2>
          <p className="text-xs text-neutral-500 max-w-2xl mt-1">{t("admin.paymentAccounts.totalsHelper")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={accFilter} onValueChange={setAccFilter}>
            <SelectTrigger data-testid="totals-account-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-8 w-56 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.paymentAccounts.totalsAllAccounts")}</SelectItem>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={a.id}>{a.currency_code} · {a.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {RANGE_OPTIONS.map((d) => (
            <button
              key={d}
              data-testid={`totals-range-${d}`}
              onClick={() => setDays(d)}
              className={`micro-label px-3 py-1.5 border transition-colors ${
                days === d
                  ? "bg-[#8B5CF6] text-white border-[#8B5CF6]"
                  : "border-white/10 text-neutral-400 hover:text-white"
              }`}
            >
              {t("admin.paymentAccounts.totalsDays", { n: d })}
            </button>
          ))}
          <button
            data-testid="totals-export-csv"
            onClick={() => exportTotals("csv")}
            className="micro-label px-3 py-1.5 border border-white/10 text-neutral-300 hover:text-white hover:border-[#8B5CF6] transition-colors flex items-center gap-1.5"
          >
            <Download className="w-3 h-3" /> CSV
          </button>
          <button
            data-testid="totals-export-pdf"
            onClick={() => exportTotals("pdf")}
            className="micro-label px-3 py-1.5 border border-white/10 text-neutral-300 hover:text-white hover:border-[#8B5CF6] transition-colors flex items-center gap-1.5"
          >
            <Download className="w-3 h-3" /> PDF
          </button>
        </div>
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.totalsColDate")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.paymentAccounts.totalsColAccount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.totalsColConfirmed")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.totalsColPending")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.totalsColTotal")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("admin.paymentAccounts.totalsColOps")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-neutral-500 text-xs">{t("common.loading")}</td></tr>
            )}
            {!loading && visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-neutral-500 text-xs" data-testid="totals-empty">
                  {t("admin.paymentAccounts.totalsEmpty")}
                </td>
              </tr>
            )}
            {!loading && visible.map((r) => {
              const showDate = r.date !== lastDate;
              lastDate = r.date;
              return (
                <tr
                  key={`${r.date}-${r.account_id}`}
                  className={`border-b border-white/5 ${showDate ? "border-t border-t-white/10" : ""}`}
                  data-testid={`totals-row-${r.date}-${r.account_id}`}
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-white">{showDate ? r.date : ""}</td>
                  <td className="px-4 py-2.5 text-xs text-neutral-300">
                    {r.label}
                    <span className="text-[0.6rem] text-neutral-500 ml-1 font-mono">{r.currency_code}</span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-emerald-400 text-right">{fmt(r.confirmed)}</td>
                  <td className="px-4 py-2.5 font-mono text-amber-400 text-right">{r.pending > 0 ? fmt(r.pending) : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-white text-right font-semibold">{fmt(r.total)}</td>
                  <td className="px-4 py-2.5 font-mono text-neutral-500 text-right text-xs">
                    {r.count_confirmed + r.count_pending}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
