import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import AdminPageHeader from "@/components/AdminPageHeader";
import CurrencyIcon from "@/components/CurrencyIcon";
import { Plus, Edit2, Trash2 } from "lucide-react";
import { toast } from "sonner";

const empty = { code: "", name: "", type: "fiat", symbol: "", country: "", is_active: true, payment_account: "", delivery_methods: null, is_convertible_to: true };

export default function AdminCurrencies() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const DELIVERY_OPTIONS = [
    { value: "transfer", label: t("admin.currencies.deliveryTransfer") },
    { value: "cash", label: t("admin.currencies.deliveryCash") },
    { value: "crypto", label: t("admin.currencies.deliveryCrypto") },
  ];

  const load = async () => {
    const r = await axios.get(`${API}/currencies`);
    setItems(r.data);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      if (editing) await axios.put(`${API}/admin/currencies/${editing.id}`, form, { withCredentials: true });
      else await axios.post(`${API}/admin/currencies`, form, { withCredentials: true });
      toast.success(t("admin.currencies.toastSaved"));
      setOpen(false); setEditing(null); setForm(empty);
      load();
    } catch (e) { toast.error(t("admin.currencies.toastError")); }
  };

  const remove = async (id) => {
    if (!window.confirm(t("admin.currencies.confirmDelete"))) return;
    await axios.delete(`${API}/admin/currencies/${id}`, { withCredentials: true });
    toast.success(t("admin.currencies.toastDeleted")); load();
  };

  const edit = (it) => { setEditing(it); setForm({ ...it }); setOpen(true); };

  return (
    <div data-testid="admin-currencies">
      <AdminPageHeader
        eyebrow={t("admin.currencies.eyebrow")}
        title={t("admin.currencies.title")}
        actions={
          <Button data-testid="add-currency-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> {t("admin.currencies.newBtn")}
          </Button>
        }
      />

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colCode")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colName")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colType")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colCountry")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colAccount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colConvertible")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.currencies.colActive")}</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.map(c => (
              <tr key={c.id} className="border-b border-white/5">
                <td className="px-4 py-3 font-mono font-semibold">
                  <div className="flex items-center gap-2">
                    <CurrencyIcon code={c.code} size="md" />
                    <span data-testid={`currency-code-${c.code}`}>{c.code}</span>
                  </div>
                </td>
                <td className="px-4 py-3">{c.name}</td>
                <td className="px-4 py-3"><span className={`text-xs uppercase border px-2 py-0.5 ${c.type === "crypto" ? "border-[#8B5CF6]/40 text-[#8B5CF6]" : "border-white/20 text-neutral-400"}`}>{c.type}</span></td>
                <td className="px-4 py-3 text-neutral-400">{c.country || "—"}</td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs truncate">{c.payment_account || "—"}</td>
                <td className="px-4 py-3" data-testid={`currency-convertible-${c.code}`}>
                  {c.is_convertible_to === false
                    ? <span className="text-xs text-amber-400 border border-amber-400/40 bg-amber-400/5 px-1.5 py-0.5">{t("admin.currencies.inputOnly")}</span>
                    : <span className="text-xs text-emerald-400">✓</span>}
                </td>
                <td className="px-4 py-3">{c.is_active ? "✓" : "✕"}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => edit(c)} className="text-neutral-400 hover:text-[#8B5CF6] mr-3"><Edit2 className="w-4 h-4" /></button>
                  <button onClick={() => remove(c.id)} className="text-neutral-400 hover:text-[#EF4444]"><Trash2 className="w-4 h-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{editing ? t("admin.currencies.editTitle") : t("admin.currencies.newTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.currencies.code")}</Label>
              <Input
                data-testid="cur-code"
                value={form.code}
                onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono"
              />
              {form.code && form.code !== form.code.trim() && (
                <div
                  data-testid="cur-code-preview"
                  className="mt-1.5 text-[0.7rem] text-[#8B5CF6] font-mono flex items-center gap-1"
                >
                  <span className="opacity-60">{t("admin.currencies.willBeSaved")}</span>
                  <span className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 px-1.5 py-0.5">
                    {form.code.trim()}
                  </span>
                </div>
              )}
              {form.code && form.code === form.code.trim() && (
                <div className="mt-1 text-[0.65rem] text-neutral-600 font-mono">
                  {t("admin.currencies.willBeSavedShort")} <span className="text-neutral-400">{form.code.trim()}</span>
                </div>
              )}
            </div>
            <div><Label className="micro-label text-neutral-500">{t("admin.currencies.name")}</Label><Input data-testid="cur-name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.currencies.type")}</Label>
              <Select value={form.type} onValueChange={v => setForm({ ...form, type: v })}>
                <SelectTrigger className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  <SelectItem value="crypto">Crypto</SelectItem>
                  <SelectItem value="fiat">Fiat</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label className="micro-label text-neutral-500">{t("admin.currencies.country")}</Label><Input value={form.country} onChange={e => setForm({ ...form, country: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div><Label className="micro-label text-neutral-500">{t("admin.currencies.paymentAccount")}</Label><Input value={form.payment_account} onChange={e => setForm({ ...form, payment_account: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div data-testid="cur-delivery-methods">
              <Label className="micro-label text-neutral-500">{t("admin.currencies.deliveryMethods")}</Label>
              <div className="text-xs text-neutral-500 mt-1 mb-2">
                {t("admin.currencies.deliveryHelper")}
              </div>
              <div className="space-y-2 mt-2 bg-[#0a0a0a] border border-white/10 p-3">
                {DELIVERY_OPTIONS.map((opt) => {
                  const checked = Array.isArray(form.delivery_methods)
                    && form.delivery_methods.includes(opt.value);
                  return (
                    <label
                      key={opt.value}
                      className="flex items-center gap-3 cursor-pointer hover:bg-white/5 px-1 py-1"
                      data-testid={`cur-delivery-${opt.value}`}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(v) => {
                          const current = Array.isArray(form.delivery_methods)
                            ? [...form.delivery_methods] : [];
                          const next = v
                            ? [...new Set([...current, opt.value])]
                            : current.filter((m) => m !== opt.value);
                          setForm({ ...form, delivery_methods: next.length ? next : null });
                        }}
                      />
                      <span className="text-sm text-neutral-200">{opt.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
            <div className="flex items-center gap-3"><Switch checked={form.is_active} onCheckedChange={v => setForm({ ...form, is_active: v })} /><span className="text-sm">{t("admin.currencies.active")}</span></div>
            <div className="border border-white/10 bg-[#0a0a0a] p-3">
              <div className="flex items-center gap-3">
                <Switch
                  data-testid="currency-convertible-toggle"
                  checked={form.is_convertible_to !== false}
                  onCheckedChange={v => setForm({ ...form, is_convertible_to: v })}
                />
                <span className="text-sm">{t("admin.currencies.convertibleLabel")}</span>
              </div>
              <div className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
                {t("admin.currencies.convertibleHelper")}
              </div>
            </div>
            <Button data-testid="save-currency-btn" onClick={save} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">{t("admin.currencies.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
