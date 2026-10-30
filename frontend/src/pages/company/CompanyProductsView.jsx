import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Boxes, Plus, Edit2, Trash2, Package, Tag } from "lucide-react";
import { toast } from "sonner";

// Catálogo de la Empresa. Los productos nuevos quedan 'pending' hasta que un
// admin de Resilience los aprueba; una vez aprobados se publican al marketplace.
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
};

const emptyForm = {
  name: "", description: "", image_url: "", price_usd: "", stock: "",
  unit: "unidad", min_stock: "", category: "general", is_active: true, available_store_ids: [],
};

export default function CompanyProductsView({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [stores, setStores] = useState([]);
  const [commission, setCommission] = useState(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  // Oferta/rebaja sobre un producto YA aprobado.
  const [offerFor, setOfferFor] = useState(null);
  const [offerPrice, setOfferPrice] = useState("");
  const [offerEnd, setOfferEnd] = useState("");
  const [offerBusy, setOfferBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/company/products`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/company/stores`, { withCredentials: true })
      .then((r) => setStores(r.data)).catch(() => {});
    axios.get(`${API}/company/me`, { withCredentials: true })
      .then((r) => setCommission(r.data.commission_pct)).catch(() => {});
  }, [load]);

  const onImageFile = (file) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("company.products.imageTooLarge"));
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, image_url: reader.result }));
    reader.readAsDataURL(file);
  };

  const toggleStore = (sid) => setForm((f) => ({
    ...f,
    available_store_ids: f.available_store_ids.includes(sid)
      ? f.available_store_ids.filter((x) => x !== sid)
      : [...f.available_store_ids, sid],
  }));

  const save = async () => {
    if (!form.name || form.name.trim().length < 2) return toast.error(t("company.products.nameRequired"));
    const price = parseFloat(form.price_usd);
    if (!price || price <= 0) return toast.error(t("company.products.priceInvalid"));
    setBusy(true);
    // F2-04 — el stock NO es metadato. En edición se envían SOLO metadatos; el
    // stock se gestiona en la pestaña Inventario (recibir/ajustar auditados),
    // para no sobrescribir el stock vigente ni perder decimales.
    const base = {
      name: form.name.trim(),
      description: form.description,
      image_url: form.image_url,
      price_usd: price,
      category: form.category || "general",
      is_active: form.is_active,
      available_store_ids: form.available_store_ids || [],
      min_stock: parseFloat(form.min_stock) || 0,
    };
    try {
      if (editing) {
        await axios.put(`${API}/company/products/${editing.id}`, base, { withCredentials: true });
        toast.success(t("company.products.updated"));
      } else {
        const payload = { ...base, stock: parseFloat(form.stock) || 0, unit: form.unit };
        await axios.post(`${API}/company/products`, payload, { withCredentials: true });
        toast.success(t("company.products.sentApproval"));
      }
      setOpen(false); setEditing(null); setForm(emptyForm);
      load(); onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("company.products.saveFailed"));
    } finally { setBusy(false); }
  };

  const remove = async (p) => {
    if (!window.confirm(t("company.products.confirmDelete", { name: p.name }))) return;
    try {
      await axios.delete(`${API}/company/products/${p.id}`, { withCredentials: true });
      toast.success(t("company.products.deleted"));
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.products.deleteFailed")); }
  };

  const openOffer = (p) => {
    setOfferFor(p);
    setOfferPrice("");
    setOfferEnd(p.offer_ends_at ? String(p.offer_ends_at).slice(0, 10) : "");
  };

  const saveOffer = async () => {
    if (!offerFor) return;
    const price = parseFloat(offerPrice);
    if (!price || price <= 0) return toast.error(t("company.products.offerPriceRequired"));
    if (price >= Number(offerFor.price_usd)) return toast.error(t("company.products.offerPriceTooHigh"));
    setOfferBusy(true);
    try {
      await axios.post(`${API}/company/products/${offerFor.id}/offer`,
        { discount_price: price, ends_at: offerEnd || null }, { withCredentials: true });
      toast.success(t("company.products.offerActivated"));
      setOfferFor(null); load(); onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("company.products.offerFailed"));
    } finally { setOfferBusy(false); }
  };

  const removeOffer = async (p) => {
    try {
      await axios.delete(`${API}/company/products/${p.id}/offer`, { withCredentials: true });
      toast.success(t("company.products.offerRemoved"));
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.products.offerRemoveFailed")); }
  };

  return (
    <div className="space-y-6" data-testid="company-products-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("company.products.sectionLabel")}</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Boxes className="w-6 h-6 text-[#8B5CF6]" /> {t("company.products.title")}
          </h2>
        </div>
        <Button data-testid="company-product-new-btn"
          onClick={() => { setEditing(null); setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> {t("company.products.newBtn")}
        </Button>
      </div>

      {commission !== null && (
        <div className="border-l-4 border-amber-400 bg-amber-500/5 px-4 py-3 text-sm text-neutral-300" data-testid="company-commission-note">
          {t("company.products.commissionNote", { pct: commission })}
        </div>
      )}

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-products-empty">
          {t("company.products.empty")}
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((p) => (
          <div key={p.id} className="tactile-card overflow-hidden flex flex-col" data-testid={`company-product-${p.id}`}>
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
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[p.approval_status] || ""}`} data-testid={`company-product-status-${p.id}`}>
                  {t(`company.products.status.${p.approval_status}`, { defaultValue: t("company.products.status.approved") })}
                </span>
              </div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              {p.on_offer && (
                <span data-testid={`company-product-offer-badge-${p.id}`}
                  className="inline-flex items-center gap-1 self-start mt-1 text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30">
                  <Tag className="w-3 h-3" /> {t("company.products.offerBadge", { pct: Number(p.offer_discount_pct || 0).toFixed(0) })}
                </span>
              )}
              {p.approval_status === "rejected" && p.rejection_reason && (
                <div className="text-xs text-red-400 mt-1">{t("company.products.rejectionPrefix")} {p.rejection_reason}</div>
              )}
              <div className="mt-auto pt-3 flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6] flex items-baseline gap-2">
                    {p.price_usd} <span className="text-xs text-neutral-500">USDT</span>
                    {p.on_offer && p.offer_original_price > 0 && (
                      <span className="text-xs text-neutral-500 line-through">{p.offer_original_price}</span>
                    )}
                  </div>
                  <div className="text-xs text-neutral-500">{t("company.products.stockPrefix")} {p.stock}</div>
                  <div className="text-xs text-emerald-400 mt-1">{t("company.products.soldPrefix")} {p.sold_qty || 0} · {t("company.products.earnedPrefix")} {Number(p.earned_usdt ?? p.earned_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 6 })} USDT</div>
                </div>
                <div className="flex gap-2">
                  {p.approval_status === "approved" && (
                    p.on_offer ? (
                      <button data-testid={`company-product-offer-remove-${p.id}`} onClick={() => removeOffer(p)}
                        className="text-[#EF4444] hover:opacity-80" title={t("company.products.removeOfferTitle")}><Tag className="w-4 h-4" /></button>
                    ) : (
                      <button data-testid={`company-product-offer-${p.id}`} onClick={() => openOffer(p)}
                        className="text-neutral-400 hover:text-[#EF4444]" title={t("company.products.putOfferTitle")}><Tag className="w-4 h-4" /></button>
                    )
                  )}
                  <button data-testid={`company-product-edit-${p.id}`} onClick={() => { setEditing(p); setForm({ ...emptyForm, ...p, price_usd: String(p.price_usd), available_store_ids: p.available_store_ids || [] }); setOpen(true); }}
                    className="text-neutral-400 hover:text-[#8B5CF6]" title={t("company.products.editTitle")}><Edit2 className="w-4 h-4" /></button>
                  <button data-testid={`company-product-delete-${p.id}`} onClick={() => remove(p)}
                    className="text-neutral-400 hover:text-[#EF4444]" title={t("company.products.deleteTitle")}><Trash2 className="w-4 h-4" /></button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? t("company.products.dialogEditTitle") : t("company.products.dialogNewTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.nameLabel")}</Label>
              <Input data-testid="company-product-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.descLabel")}</Label>
              <Textarea data-testid="company-product-description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.imageLabel")}</Label>
              <input data-testid="company-product-image" type="file" accept="image/*" onChange={(e) => onImageFile(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {form.image_url && <img src={form.image_url} alt="preview" className="mt-2 h-24 object-cover border border-white/10" />}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("company.products.priceLabel")}</Label>
                <Input data-testid="company-product-price" type="number" step="any" min="0" value={form.price_usd} onChange={(e) => setForm({ ...form, price_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              {!editing && (
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.products.unitLabel")}</Label>
                  <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })}>
                    <SelectTrigger data-testid="company-product-unit" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      <SelectItem value="unidad" data-testid="company-product-unit-unidad">{t("company.products.unitUnidad")}</SelectItem>
                      <SelectItem value="libra" data-testid="company-product-unit-libra">{t("company.products.unitLibra")}</SelectItem>
                      <SelectItem value="kg" data-testid="company-product-unit-kg">{t("company.products.unitKg")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
            {!editing ? (
              <div>
                <Label className="micro-label text-neutral-500">{t("company.products.stockLabel")}</Label>
                <Input data-testid="company-product-stock" type="number" step={form.unit === "unidad" ? "1" : "any"} min="0" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                <p className="text-xs text-neutral-500 mt-1">{t("company.products.stockHint")}</p>
              </div>
            ) : (
              <div className="border-l-4 border-[#8B5CF6]/40 bg-[#8B5CF6]/5 px-3 py-2 text-xs text-neutral-400" data-testid="company-product-stock-note">
                {t("company.products.stockEditNotePre")}<span className="text-[#8B5CF6]">{t("company.products.stockEditNoteBold")}</span>{t("company.products.stockEditNotePost")}
              </div>
            )}
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.categoryLabel")}</Label>
              <Input data-testid="company-product-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.minStockLabel")}</Label>
              <Input data-testid="company-product-min-stock" type="number" step="any" min="0" value={form.min_stock ?? ""} onChange={(e) => setForm({ ...form, min_stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              <p className="text-xs text-neutral-500 mt-1">{t("company.products.minStockHint")}</p>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.products.storesLabel")}</Label>
              {stores.length === 0 ? (
                <p className="text-xs text-neutral-500 mt-1">{t("company.products.noStoresHint")}</p>
              ) : (
                <div className="mt-2 space-y-2 max-h-40 overflow-y-auto">
                  {stores.map((s) => (
                    <label key={s.id} htmlFor={`store-opt-${s.id}`} className="flex items-center gap-2 text-sm text-neutral-300 cursor-pointer">
                      <Checkbox id={`store-opt-${s.id}`} data-testid={`company-product-store-${s.id}`}
                        checked={form.available_store_ids.includes(s.id)} onCheckedChange={() => toggleStore(s.id)}
                        className="border-white/30 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:border-[#8B5CF6]" />
                      {s.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Switch data-testid="company-product-active" checked={form.is_active} onCheckedChange={(v) => setForm({ ...form, is_active: v })} />
              <span className="text-sm">{t("company.products.activeLabel")}</span>
            </div>
            {!editing && <p className="text-xs text-neutral-500">{t("company.products.pendingHint")}</p>}
            <Button data-testid="company-product-save" onClick={save} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? t("company.products.saving") : t("company.products.saveBtn")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!offerFor} onOpenChange={(v) => !v && setOfferFor(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="company-offer-dialog">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <Tag className="w-5 h-5 text-[#EF4444]" /> {t("company.products.offerDialogTitle")}
            </DialogTitle>
          </DialogHeader>
          {offerFor && (
            <div className="space-y-4">
              <div className="text-sm text-neutral-400">
                «{offerFor.name}» — {t("company.products.offerCurrentPriceLabel")} <span className="text-[#8B5CF6] font-mono">{offerFor.price_usd} USDT</span>.
                {" "}{t("company.products.offerExplainPre")}<strong className="text-neutral-200">{t("company.products.offerExplainBold")}</strong>{t("company.products.offerExplainPost")}
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.products.offerPriceLabel")}</Label>
                <Input data-testid="company-offer-price" type="number" step="any" min="0" value={offerPrice}
                  onChange={(e) => setOfferPrice(e.target.value)}
                  placeholder={t("company.products.offerPricePlaceholder", { price: offerFor.price_usd })}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                {parseFloat(offerPrice) > 0 && parseFloat(offerPrice) < Number(offerFor.price_usd) && (
                  <p className="text-xs text-emerald-400 mt-1" data-testid="company-offer-pct-preview">
                    {t("company.products.offerPctPreview", { pct: Math.round((1 - parseFloat(offerPrice) / Number(offerFor.price_usd)) * 100) })}
                  </p>
                )}
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.products.offerEndLabel")}</Label>
                <Input data-testid="company-offer-end" type="date" value={offerEnd}
                  onChange={(e) => setOfferEnd(e.target.value)}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                <p className="text-xs text-neutral-500 mt-1">{t("company.products.offerEndHint")}</p>
              </div>
              <Button data-testid="company-offer-save" onClick={saveOffer} disabled={offerBusy}
                className="w-full bg-[#EF4444] hover:bg-[#dc2626] text-white font-bold rounded-none h-11">
                {offerBusy ? t("company.products.saving") : t("company.products.offerSaveBtn")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
