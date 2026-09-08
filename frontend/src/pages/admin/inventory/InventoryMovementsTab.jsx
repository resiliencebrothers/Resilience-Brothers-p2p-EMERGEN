import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Plus } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

const TYPE_STYLES = {
  entrada: "text-emerald-400",
  venta: "text-amber-300",
  ajuste_pos: "text-sky-300",
  ajuste_neg: "text-red-400",
  precio: "text-fuchsia-300",
};

const selectCls = "w-full h-10 mt-1 bg-[#0a0a0a] border border-white/10 text-sm px-3 text-white";

export default function InventoryMovementsTab() {
  const { t } = useTranslation();
  const [movs, setMovs] = useState([]);
  const [products, setProducts] = useState([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [productFilter, setProductFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const emptyForm = { product_id: "", type: "entrada", quantity: 1, unit_price: "", unit_cost: "", sale_price: "", note: "", photo_url: "" };
  const [form, setForm] = useState(emptyForm);

  // iter219 — solo Entrada y Venta se registran a mano (ajustes retirados);
  // los reversos internos y cambios de precio se muestran con su etiqueta.
  const createTypes = {
    entrada: t("inventory.movements.typeEntrada"),
    venta: t("inventory.movements.typeVenta"),
  };
  const displayLabel = {
    ...createTypes,
    ajuste_pos: t("inventory.movements.typeReverso"),
    ajuste_neg: t("inventory.movements.typeAjusteNeg"),
    precio: t("inventory.movements.typePrecio"),
  };

  const load = useCallback(() => {
    const params = {};
    if (typeFilter) params.type = typeFilter;
    if (productFilter) params.product_id = productFilter;
    axios.get(`${API}/admin/inventory/movements`, { params, withCredentials: true })
      .then((r) => setMovs(r.data)).catch(() => {});
  }, [typeFilter, productFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    axios.get(`${API}/admin/inventory/control`, { withCredentials: true })
      .then((r) => setProducts(r.data)).catch(() => {});
  }, []);

  const onPhotoFile = (file) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("inventory.movements.photoTooBig"));
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, photo_url: reader.result }));
    reader.readAsDataURL(file);
  };

  const save = async () => {
    if (!form.product_id) return toast.error(t("inventory.movements.productRequired"));
    setBusy(true);
    try {
      const payload = {
        product_id: form.product_id,
        type: form.type,
        quantity: parseInt(form.quantity) || 0,
        note: form.note,
        photo_url: form.photo_url,
      };
      if (form.type === "venta" && form.unit_price !== "") payload.unit_price = parseFloat(form.unit_price);
      if (form.type === "entrada") {
        if (form.unit_cost !== "") payload.unit_cost = parseFloat(form.unit_cost);
        if (form.sale_price !== "") payload.sale_price = parseFloat(form.sale_price);
      }
      await axios.post(`${API}/admin/inventory/movements`, payload, { withCredentials: true });
      toast.success(t("inventory.movements.saved"));
      setOpen(false);
      setForm(emptyForm);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("inventory.movements.saveError"));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="inventory-movements">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-2 flex-wrap">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            data-testid="movements-type-filter"
            className="h-10 bg-[#0a0a0a] border border-white/10 text-sm px-3 text-white"
          >
            <option value="">{t("inventory.movements.filterAll")}</option>
            <option value="entrada">{t("inventory.movements.typeEntrada")}</option>
            <option value="venta">{t("inventory.movements.typeVenta")}</option>
            <option value="precio">{t("inventory.movements.typePrecio")}</option>
          </select>
          <select
            value={productFilter}
            onChange={(e) => setProductFilter(e.target.value)}
            data-testid="movements-product-filter"
            className="h-10 max-w-[260px] bg-[#0a0a0a] border border-white/10 text-sm px-3 text-white"
          >
            <option value="">{t("inventory.movements.filterAllProducts")}</option>
            {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}
          </select>
        </div>
        <Button data-testid="add-movement-btn" onClick={() => setOpen(true)} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
          <Plus className="w-4 h-4 mr-1" /> {t("inventory.movements.newBtn")}
        </Button>
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[1000px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colDate")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colType")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colProduct")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.movements.colQty")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.movements.colUnit")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.movements.colTotal")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.movements.colProfit")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colSource")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colUser")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.movements.colNote")}</th>
            </tr>
          </thead>
          <tbody>
            {movs.length === 0 && (
              <tr><td colSpan="10" className="text-center text-neutral-500 py-8">{t("inventory.movements.empty")}</td></tr>
            )}
            {movs.map((m) => (
              <tr key={m.id} className="border-b border-white/5" data-testid={`movement-row-${m.id}`}>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">{new Date(m.created_at).toLocaleString()}</td>
                <td className={`px-4 py-3 text-xs uppercase tracking-wider ${TYPE_STYLES[m.type] || ""}`}>{displayLabel[m.type] || m.type}</td>
                <td className="px-4 py-3">{m.product_name}</td>
                <td className="px-4 py-3 font-mono text-right">{m.type === "precio" ? "—" : m.quantity}</td>
                <td className="px-4 py-3 font-mono text-right text-neutral-400">{fmt(m.type === "entrada" ? m.unit_cost : m.unit_price)}</td>
                <td className="px-4 py-3 font-mono text-right">{m.type === "precio" ? "—" : fmt(m.total)}</td>
                <td className={`px-4 py-3 font-mono text-right ${m.profit > 0 ? "text-emerald-400" : "text-neutral-500"}`}>{m.type === "venta" ? fmt(m.profit) : "—"}</td>
                <td className="px-4 py-3 text-xs text-neutral-500">{m.source === "marketplace" ? t("inventory.movements.sourceMarketplace") : t("inventory.movements.sourceManual")}</td>
                <td className="px-4 py-3 text-xs text-neutral-400" data-testid={`movement-user-${m.id}`}>{m.actor_email || "—"}</td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-[220px]">
                  <div className="flex items-center gap-2">
                    {m.photo_url && (
                      <a href={m.photo_url} target="_blank" rel="noreferrer" data-testid={`movement-photo-${m.id}`}>
                        <img src={m.photo_url} alt="foto" className="h-8 w-8 object-cover border border-white/10" />
                      </a>
                    )}
                    <span className="truncate" title={m.note}>{m.note}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{t("inventory.movements.dialogTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.movements.product")}</Label>
              <select data-testid="movement-product" value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} className={selectCls}>
                <option value="">—</option>
                {products.map((p) => <option key={p.product_id} value={p.product_id}>{`${p.name} (stock ${p.stock})`}</option>)}
              </select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.movements.type")}</Label>
              <select data-testid="movement-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className={selectCls}>
                {Object.keys(createTypes).map((k) => <option key={k} value={k}>{createTypes[k]}</option>)}
              </select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.movements.qty")}</Label>
              <Input data-testid="movement-qty" type="number" min="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
            </div>
            {form.type === "venta" && (
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.movements.unitPrice")}</Label>
                <Input data-testid="movement-unit-price" type="number" step="any" value={form.unit_price} placeholder={t("inventory.movements.defaultFromProduct")} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
            )}
            {form.type === "entrada" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="micro-label text-neutral-500">{t("inventory.movements.unitCost")}</Label>
                  <Input data-testid="movement-unit-cost" type="number" step="any" value={form.unit_cost} placeholder={t("inventory.movements.defaultFromProduct")} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">{t("inventory.movements.salePrice")}</Label>
                  <Input data-testid="movement-sale-price" type="number" step="any" value={form.sale_price} placeholder={t("inventory.movements.salePriceHint")} onChange={(e) => setForm({ ...form, sale_price: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
              </div>
            )}
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.movements.note")}</Label>
              <Input data-testid="movement-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.movements.photo")}</Label>
              <input data-testid="movement-photo-input" type="file" accept="image/*" onChange={(e) => onPhotoFile(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {form.photo_url && (
                <img src={form.photo_url} alt="preview" className="mt-2 h-20 object-cover border border-white/10" />
              )}
            </div>
            <Button data-testid="save-movement-btn" onClick={save} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
              {busy ? "…" : t("inventory.movements.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
