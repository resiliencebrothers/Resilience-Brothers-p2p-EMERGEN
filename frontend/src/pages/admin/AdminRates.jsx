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
import { Plus, Edit2, Trash2, Lock } from "lucide-react";
import { toast } from "sonner";

const empty = { from_code: "", to_code: "", rate_normal: 0, rate_vip: 0, real_rate: "" };

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

  const buildPayload = () => ({
    ...form,
    rate_normal: parseFloat(form.rate_normal),
    rate_vip: parseFloat(form.rate_vip),
    real_rate: form.real_rate === "" || form.real_rate === null ? null : parseFloat(form.real_rate),
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

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
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
                  <td className="px-4 py-3 font-mono font-semibold">{r.from_code} → {r.to_code}</td>
                  <td className="px-4 py-3 font-mono">{r.rate_normal}</td>
                  <td className="px-4 py-3 font-mono text-[#8B5CF6]">{r.rate_vip}</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E]">{r.real_rate ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-neutral-500">{new Date(r.updated_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    {editable ? (
                      <>
                        <button data-testid={`edit-rate-${r.id}`} onClick={() => { setEditing(r); setForm({ ...r, real_rate: r.real_rate ?? "" }); setOpen(true); }} className="text-neutral-400 hover:text-[#8B5CF6] mr-3"><Edit2 className="w-4 h-4" /></button>
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
