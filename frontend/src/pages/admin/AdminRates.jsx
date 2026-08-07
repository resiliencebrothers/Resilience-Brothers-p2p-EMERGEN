import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import SpreadCalculator from "@/components/SpreadCalculator";
import AdminPageHeader from "@/components/AdminPageHeader";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Plus, Edit2, Trash2, Lock } from "lucide-react";
import { toast } from "sonner";

const empty = { from_code: "", to_code: "", rate_normal: 0, rate_vip: 0, real_rate: "", tiers: [] };

const newTierKey = () => Math.random().toString(36).slice(2, 10);

export default function AdminRates() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === "admin";
  const allowedCurrencies = currentUser?.allowed_currencies || [];
  const isScoped = !isAdmin && allowedCurrencies.length > 0;

  const canEditRate = (r) =>
    isAdmin || !isScoped || allowedCurrencies.includes(r.from_code) || allowedCurrencies.includes(r.to_code);

  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [pendingTotp, setPendingTotp] = useState(null);

  const load = async () => {
    const [r, c] = await Promise.all([axios.get(`${API}/rates`), axios.get(`${API}/currencies`)]);
    setRates(r.data); setCurrencies(c.data);
  };
  useEffect(() => { load(); }, []);
  // iter97 — live sync for other admins editing rates in parallel.
  useLiveEvent("rates_updated", load);

  const buildPayload = () => ({
    ...form,
    rate_normal: parseFloat(form.rate_normal),
    rate_vip: parseFloat(form.rate_vip),
    real_rate: form.real_rate === "" || form.real_rate === null ? null : parseFloat(form.real_rate),
    tiers: (form.tiers || [])
      .filter(tr => tr.min_amount !== "" && tr.rate_normal !== "" && tr.rate_vip !== "")
      .map(tr => ({
        min_amount: parseFloat(tr.min_amount),
        rate_normal: parseFloat(tr.rate_normal),
        rate_vip: parseFloat(tr.rate_vip),
        real_rate: tr.real_rate === "" || tr.real_rate == null ? null : parseFloat(tr.real_rate),
      })),
  });

  const save = async () => {
    const payload = buildPayload();
    try {
      if (editing) {
        setPendingTotp(payload);
        return;
      }
      await axios.post(`${API}/admin/rates`, payload, { withCredentials: true });
      toast.success(t("admin.rates.toastSaved"));
      setOpen(false); setEditing(null); setForm(empty); load();
    } catch (e) {
      toast.error(t("admin.rates.toastError"));
    }
  };

  const confirmEditWithTotp = async (code) => {
    try {
      await axios.put(
        `${API}/admin/rates/${editing.id}`,
        { ...pendingTotp, totp_code: code },
        { withCredentials: true }
      );
      toast.success(t("admin.rates.toastUpdated"));
      setPendingTotp(null);
      setOpen(false); setEditing(null); setForm(empty); load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || t("admin.rates.toastError"));
    }
  };

  const remove = async (id) => {
    if (!window.confirm(t("admin.rates.confirmDelete"))) return;
    await axios.delete(`${API}/admin/rates/${id}`, { withCredentials: true });
    toast.success(t("admin.rates.toastDeleted")); load();
  };

  return (
    <div data-testid="admin-rates">
      <AdminPageHeader
        eyebrow={t("admin.rates.eyebrow")}
        title={t("admin.rates.title")}
        actions={
          <Button data-testid="add-rate-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> {t("admin.rates.newBtn")}
          </Button>
        }
      />

      <SpreadCalculator rates={rates} />

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.rates.colPair")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.rates.colNormal")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.rates.colVip")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.rates.colReal")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.rates.colUpdated")}</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rates.map(r => {
              const editable = canEditRate(r);
              return (
                <tr key={r.id} className={`border-b border-white/5 ${editable ? "" : "opacity-60"}`} data-testid={`rate-row-${r.id}`}>
                  <td className="px-4 py-3">
                    <CurrencyPairIcon from={r.from_code} to={r.to_code} size="md" showLabel />
                    {(r.tiers?.length || 0) > 0 && (
                      <div className="text-[0.6rem] text-[#A78BFA] font-mono mt-1" data-testid={`rate-tiers-badge-${r.id}`}>
                        {t("admin.rates.tiersBadge", { count: r.tiers.length })}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono">{r.rate_normal}</td>
                  <td className="px-4 py-3 font-mono text-[#8B5CF6]">{r.rate_vip}</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E]">{r.real_rate ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-neutral-500">{new Date(r.updated_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    {editable ? (
                      <>
                        <button data-testid={`edit-rate-${r.id}`} onClick={() => { setEditing(r); setForm({ ...r, real_rate: r.real_rate ?? "", tiers: (r.tiers || []).map(tr => ({ _key: newTierKey(), min_amount: tr.min_amount ?? "", rate_normal: tr.rate_normal ?? "", rate_vip: tr.rate_vip ?? "", real_rate: tr.real_rate ?? "" })) }); setOpen(true); }} className="text-neutral-400 hover:text-[#8B5CF6] mr-3"><Edit2 className="w-4 h-4" /></button>
                        <button data-testid={`delete-rate-${r.id}`} onClick={() => remove(r.id)} className="text-neutral-400 hover:text-[#EF4444]"><Trash2 className="w-4 h-4" /></button>
                      </>
                    ) : (
                      <span title={t("admin.rates.outOfScope")} className="inline-flex items-center gap-1 text-neutral-600 text-xs">
                        <Lock className="w-3 h-3" /> {t("admin.rates.noAccess")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{editing ? t("admin.rates.editTitle") : t("admin.rates.newTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.rates.from")}</Label>
              <Select value={form.from_code} onValueChange={v => setForm({ ...form, from_code: v })}>
                <SelectTrigger className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder={t("admin.rates.select")} /></SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  {currencies.map(c => <SelectItem key={c.id} value={c.code}>{c.code}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.rates.to")}</Label>
              <Select value={form.to_code} onValueChange={v => setForm({ ...form, to_code: v })}>
                <SelectTrigger className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder={t("admin.rates.select")} /></SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  {currencies.map(c => <SelectItem key={c.id} value={c.code}>{c.code}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div><Label className="micro-label text-neutral-500">{t("admin.rates.rateNormalLabel")}</Label><Input data-testid="rate-normal" type="number" step="any" value={form.rate_normal} onChange={e => setForm({ ...form, rate_normal: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
            <div><Label className="micro-label text-neutral-500">{t("admin.rates.rateVipLabel")}</Label><Input data-testid="rate-vip" type="number" step="any" value={form.rate_vip} onChange={e => setForm({ ...form, rate_vip: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.rates.realRateLabel")}</Label>
              <Input data-testid="rate-real" type="number" step="any" value={form.real_rate} onChange={e => setForm({ ...form, real_rate: e.target.value })} placeholder={t("admin.rates.realRatePh")} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              <p className="text-[0.65rem] text-neutral-500 mt-1">{t("admin.rates.realRateHelper")}</p>
            </div>
            <TierEditor tiers={form.tiers || []} onChange={(tiers) => setForm({ ...form, tiers })} t={t} />
            <Button data-testid="save-rate-btn" onClick={save} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">{t("admin.rates.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingTotp}
        title={t("admin.rates.totpTitle")}
        description={t("admin.rates.totpDescription")}
        onConfirm={confirmEditWithTotp}
        onCancel={() => setPendingTotp(null)}
      />
    </div>
  );
}

function TierEditor({ tiers, onChange, t }) {
  const update = (key, field, v) => onChange(tiers.map(tr => (tr._key === key ? { ...tr, [field]: v } : tr)));
  const remove = (key) => onChange(tiers.filter(tr => tr._key !== key));
  const add = () => onChange([...tiers, { _key: newTierKey(), min_amount: "", rate_normal: "", rate_vip: "", real_rate: "" }]);
  const inputCls = "rounded-none bg-[#0a0a0a] border-white/10 font-mono h-8 text-xs px-2";
  return (
    <div className="border border-white/10 p-3 space-y-2" data-testid="rate-tier-editor">
      <div className="flex items-center justify-between">
        <Label className="micro-label text-neutral-500">{t("admin.rates.tiersTitle")}</Label>
        <button type="button" data-testid="add-tier-btn" onClick={add} className="text-xs text-[#8B5CF6] hover:text-[#A78BFA] flex items-center gap-1">
          <Plus className="w-3 h-3" /> {t("admin.rates.addTier")}
        </button>
      </div>
      <p className="text-[0.65rem] text-neutral-500 leading-relaxed">{t("admin.rates.tiersHelper")}</p>
      {tiers.length > 0 && (
        <div className="grid grid-cols-[1fr_1fr_1fr_1fr_24px] gap-1 text-[0.6rem] micro-label text-neutral-600">
          <span>{t("admin.rates.tierMin")}</span>
          <span>{t("admin.rates.tierNormal")}</span>
          <span>{t("admin.rates.tierVip")}</span>
          <span>{t("admin.rates.tierReal")}</span>
          <span />
        </div>
      )}
      {tiers.map((tier, i) => (
        <div key={tier._key} className="grid grid-cols-[1fr_1fr_1fr_1fr_24px] gap-1 items-center">
          <Input data-testid={`tier-min-${i}`} type="number" step="any" value={tier.min_amount} onChange={e => update(tier._key, "min_amount", e.target.value)} className={inputCls} />
          <Input data-testid={`tier-normal-${i}`} type="number" step="any" value={tier.rate_normal} onChange={e => update(tier._key, "rate_normal", e.target.value)} className={inputCls} />
          <Input data-testid={`tier-vip-${i}`} type="number" step="any" value={tier.rate_vip} onChange={e => update(tier._key, "rate_vip", e.target.value)} className={inputCls} />
          <Input data-testid={`tier-real-${i}`} type="number" step="any" value={tier.real_rate} onChange={e => update(tier._key, "real_rate", e.target.value)} className={inputCls} />
          <button type="button" data-testid={`tier-remove-${i}`} onClick={() => remove(tier._key)} className="text-neutral-500 hover:text-[#EF4444] flex justify-center">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
