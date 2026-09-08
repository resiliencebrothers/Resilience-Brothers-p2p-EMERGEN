import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Store, Plus, Edit2, Trash2, Package } from "lucide-react";
import { toast } from "sonner";

// iter217 — Autoservicio VIP: publica y gestiona tus propios productos en el
// marketplace. Los productos nuevos quedan pendientes hasta que un admin los
// apruebe; las ediciones posteriores se reflejan en tiempo real.
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
};

const emptyForm = { name: "", description: "", image_url: "", price_usd: "", stock: 0, category: "general", is_active: true };

export default function MyProductsView() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [commission, setCommission] = useState(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/vip/my-products`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/vendor/commission`, { withCredentials: true })
      .then((r) => setCommission(r.data.commission_pct)).catch(() => {});
  }, [load]);

  const onImageFile = (file) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("myProducts.imageTooBig"));
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, image_url: reader.result }));
    reader.readAsDataURL(file);
  };

  const save = async () => {
    if (!form.name || form.name.trim().length < 2) return toast.error(t("myProducts.nameRequired"));
    const price = parseFloat(form.price_usd);
    if (!price || price <= 0) return toast.error(t("myProducts.priceRequired"));
    setBusy(true);
    const payload = {
      name: form.name.trim(),
      description: form.description,
      image_url: form.image_url,
      price_usd: price,
      stock: parseInt(form.stock) || 0,
      category: form.category || "general",
      is_active: form.is_active,
    };
    try {
      if (editing) {
        await axios.put(`${API}/vip/my-products/${editing.id}`, payload, { withCredentials: true });
        toast.success(t("myProducts.toastUpdated"));
      } else {
        await axios.post(`${API}/vip/my-products`, payload, { withCredentials: true });
        toast.success(t("myProducts.toastCreated"));
      }
      setOpen(false); setEditing(null); setForm(emptyForm);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("myProducts.toastError"));
    } finally { setBusy(false); }
  };

  const remove = async (p) => {
    if (!window.confirm(t("myProducts.confirmDelete", { name: p.name }))) return;
    try {
      await axios.delete(`${API}/vip/my-products/${p.id}`, { withCredentials: true });
      toast.success(t("myProducts.toastDeleted"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("myProducts.toastError")); }
  };

  return (
    <div className="space-y-8" data-testid="my-products-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("myProducts.eyebrow")}</div>
          <h1 className="font-display text-3xl flex items-center gap-3">
            <Store className="w-8 h-8 text-[#8B5CF6]" /> {t("myProducts.title")}
          </h1>
        </div>
        <Button data-testid="my-products-new-btn" onClick={() => { setEditing(null); setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> {t("myProducts.newBtn")}
        </Button>
      </div>

      {commission !== null && (
        <div className="border-l-4 border-amber-400 bg-amber-500/5 px-4 py-3 text-sm text-neutral-300" data-testid="my-products-commission-note">
          {t("myProducts.commissionNote", { pct: commission })}
        </div>
      )}

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="my-products-empty">{t("myProducts.empty")}</p>
      )}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((p) => (
          <div key={p.id} className="tactile-card overflow-hidden flex flex-col" data-testid={`my-product-${p.id}`}>
            <div className="aspect-video bg-[#0a0a0a] overflow-hidden">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center"><Package className="w-12 h-12 text-neutral-700" /></div>
              )}
            </div>
            <div className="p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between gap-2">
                <div className="micro-label text-neutral-500">{p.category}</div>
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[p.approval_status] || ""}`} data-testid={`my-product-status-${p.id}`}>
                  {t(`myProducts.status.${p.approval_status || "approved"}`)}
                </span>
              </div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              {p.approval_status === "rejected" && p.rejection_reason && (
                <div className="text-xs text-red-400 mt-1">{t("myProducts.rejectedReason")}: {p.rejection_reason}</div>
              )}
              <div className="mt-auto pt-3 flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]">{p.price_usd} <span className="text-xs text-neutral-500">USDT</span></div>
                  <div className="text-xs text-neutral-500">{t("myProducts.stockLabel")} {p.stock}</div>
                  <div className="text-xs text-emerald-400 mt-1">
                    {t("myProducts.sold")}: {p.sold_qty || 0} · {t("myProducts.earned")}: {(p.earned_usd || 0).toFixed(2)} USD
                  </div>
                </div>
                <div className="flex gap-2">
                  <button data-testid={`my-product-edit-${p.id}`} onClick={() => { setEditing(p); setForm({ ...p, price_usd: String(p.price_usd) }); setOpen(true); }}
                    className="text-neutral-400 hover:text-[#8B5CF6]" title={t("myProducts.editBtn")}>
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button data-testid={`my-product-delete-${p.id}`} onClick={() => remove(p)}
                    className="text-neutral-400 hover:text-[#EF4444]" title={t("myProducts.deleteBtn")}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? t("myProducts.form.editTitle") : t("myProducts.form.newTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("myProducts.form.name")}</Label>
              <Input data-testid="my-product-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("myProducts.form.description")}</Label>
              <Textarea data-testid="my-product-description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("myProducts.form.image")}</Label>
              <input data-testid="my-product-image" type="file" accept="image/*" onChange={(e) => onImageFile(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {form.image_url && (
                <img src={form.image_url} alt="preview" className="mt-2 h-24 object-cover border border-white/10" />
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("myProducts.form.price")}</Label>
                <Input data-testid="my-product-price" type="number" step="any" min="0" value={form.price_usd} onChange={(e) => setForm({ ...form, price_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("myProducts.form.stock")}</Label>
                <Input data-testid="my-product-stock" type="number" min="0" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("myProducts.form.category")}</Label>
              <Input data-testid="my-product-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="flex items-center gap-3">
              <Switch data-testid="my-product-active" checked={form.is_active} onCheckedChange={(v) => setForm({ ...form, is_active: v })} />
              <span className="text-sm">{t("myProducts.form.active")}</span>
            </div>
            {!editing && <p className="text-xs text-neutral-500">{t("myProducts.form.pendingHint")}</p>}
            <Button data-testid="my-product-save" onClick={save} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? "…" : t("myProducts.form.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
