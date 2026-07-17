import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import AdminPageHeader from "@/components/AdminPageHeader";
import { Plus, Edit2, Trash2, Lock } from "lucide-react";
import { toast } from "sonner";

const empty = { name: "", description: "", image_url: "", price_usd: 0, cost_usd: 0, stock: 0, category: "general", is_active: true };

export default function AdminProducts() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const canEditPrice = isAdmin || !!user?.can_edit_product_prices;
  const canEditImage = isAdmin || !!user?.can_upload_product_images;
  const canDelete = isAdmin || !!user?.can_delete_products;

  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const load = async () => {
    const r = await axios.get(`${API}/products`);
    setItems(r.data);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    const payload = {
      ...form,
      price_usd: parseFloat(form.price_usd),
      cost_usd: parseFloat(form.cost_usd) || 0,
      stock: parseInt(form.stock),
    };
    try {
      if (editing) await axios.put(`${API}/admin/products/${editing.id}`, payload, { withCredentials: true });
      else await axios.post(`${API}/admin/products`, payload, { withCredentials: true });
      toast.success(t("admin.products.toastSaved"));
      setOpen(false); setEditing(null); setForm(empty); load();
    } catch (e) { toast.error(e.response?.data?.detail || t("admin.products.toastSaveError")); }
  };

  const remove = async (id) => {
    if (!canDelete) {
      toast.error(t("admin.products.toastNoDelete"));
      return;
    }
    if (!window.confirm(t("admin.products.confirmDelete"))) return;
    try {
      await axios.delete(`${API}/admin/products/${id}`, { withCredentials: true });
      toast.success(t("admin.products.toastDeleted")); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.products.toastDeleteError"));
    }
  };

  return (
    <div data-testid="admin-products">
      <AdminPageHeader
        eyebrow={t("admin.products.eyebrow")}
        title={t("admin.products.title")}
        actions={
          <Button data-testid="add-product-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> {t("admin.products.newBtn")}
          </Button>
        }
      />
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map(p => (
          <div key={p.id} className="tactile-card overflow-hidden">
            <div className="aspect-video bg-[#0a0a0a]">{p.image_url && <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />}</div>
            <div className="p-4">
              <div className="micro-label text-neutral-500">{p.category}</div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              <div className="flex items-center justify-between mt-3">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]">${p.price_usd}</div>
                  <div className="text-xs text-neutral-500">{t("admin.products.stock")} {p.stock}</div>
                  {p.cost_usd > 0 && (
                    <div className="text-xs text-[#22C55E] mt-1">{t("admin.products.margin", { value: (p.price_usd - p.cost_usd).toFixed(2) })}</div>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setEditing(p); setForm(p); setOpen(true); }}
                    data-testid={`edit-product-${p.id}`}
                    className="text-neutral-400 hover:text-[#8B5CF6]"
                    title={t("admin.products.editTitleAction")}
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => remove(p.id)}
                    disabled={!canDelete}
                    data-testid={`delete-product-${p.id}`}
                    title={canDelete ? t("admin.products.deleteTitleAction") : t("admin.products.noDeletePerm")}
                    className={`text-neutral-400 ${canDelete ? "hover:text-[#EF4444]" : "opacity-30 cursor-not-allowed"}`}
                  >
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
          <DialogHeader><DialogTitle className="font-display">{editing ? t("admin.products.editTitle") : t("admin.products.newTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label className="micro-label text-neutral-500">{t("admin.products.name")}</Label><Input data-testid="prod-name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div><Label className="micro-label text-neutral-500">{t("admin.products.description")}</Label><Textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div>
              <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                {t("admin.products.imageUrl")} {!canEditImage && <Lock className="w-3 h-3 text-neutral-600" />}
              </Label>
              <Input
                value={form.image_url}
                onChange={e => setForm({ ...form, image_url: e.target.value })}
                disabled={!canEditImage}
                data-testid="prod-image-url"
                title={canEditImage ? "" : t("admin.products.noImageEdit")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              {!canEditImage && (
                <p className="text-[0.65rem] text-neutral-600 mt-1">
                  {t("admin.products.imageNoPerm")}
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                  {t("admin.products.priceSale")} {!canEditPrice && <Lock className="w-3 h-3 text-neutral-600" />}
                </Label>
                <Input
                  data-testid="prod-price"
                  type="number"
                  step="any"
                  value={form.price_usd}
                  onChange={e => setForm({ ...form, price_usd: e.target.value })}
                  disabled={!canEditPrice}
                  title={canEditPrice ? "" : t("admin.products.noPriceEdit")}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
              <div>
                <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                  {t("admin.products.priceCost")} {!canEditPrice && <Lock className="w-3 h-3 text-neutral-600" />}
                </Label>
                <Input
                  data-testid="prod-cost"
                  type="number"
                  step="any"
                  value={form.cost_usd}
                  onChange={e => setForm({ ...form, cost_usd: e.target.value })}
                  disabled={!canEditPrice}
                  title={canEditPrice ? "" : t("admin.products.noPriceEdit")}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
            </div>
            {!canEditPrice && (
              <p className="text-[0.65rem] text-neutral-600 -mt-2">
                {t("admin.products.priceNoPerm")}
              </p>
            )}
            <div><Label className="micro-label text-neutral-500">{t("admin.products.stockLabel")}</Label><Input data-testid="prod-stock" type="number" value={form.stock} onChange={e => setForm({ ...form, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
            <div><Label className="micro-label text-neutral-500">{t("admin.products.category")}</Label><Input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div className="flex items-center gap-3"><Switch checked={form.is_active} onCheckedChange={v => setForm({ ...form, is_active: v })} /><span className="text-sm">{t("admin.products.active")}</span></div>
            <Button data-testid="save-product-btn" onClick={save} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">{t("admin.products.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
