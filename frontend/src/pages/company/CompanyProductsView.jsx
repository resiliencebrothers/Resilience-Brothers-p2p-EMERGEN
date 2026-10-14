import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Boxes, Plus, Edit2, Trash2, Package } from "lucide-react";
import { toast } from "sonner";

// Catálogo de la Empresa. Los productos nuevos quedan 'pending' hasta que un
// admin de Resilience los aprueba; una vez aprobados se publican al marketplace.
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
};
const STATUS_LABEL = { pending: "Pendiente", approved: "Aprobado", rejected: "Rechazado" };

const emptyForm = {
  name: "", description: "", image_url: "", price_usd: "", stock: "",
  unit: "unidad", category: "general", is_active: true, available_store_ids: [],
};

export default function CompanyProductsView({ onChanged }) {
  const [items, setItems] = useState([]);
  const [stores, setStores] = useState([]);
  const [commission, setCommission] = useState(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);

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
    if (file.size > 4 * 1024 * 1024) return toast.error("La imagen supera 4 MB");
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
    if (!form.name || form.name.trim().length < 2) return toast.error("El nombre es obligatorio");
    const price = parseFloat(form.price_usd);
    if (!price || price <= 0) return toast.error("El precio debe ser mayor a 0");
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
    };
    try {
      if (editing) {
        await axios.put(`${API}/company/products/${editing.id}`, base, { withCredentials: true });
        toast.success("Producto actualizado");
      } else {
        const payload = { ...base, stock: parseFloat(form.stock) || 0, unit: form.unit };
        await axios.post(`${API}/company/products`, payload, { withCredentials: true });
        toast.success("Producto enviado a aprobación");
      }
      setOpen(false); setEditing(null); setForm(emptyForm);
      load(); onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo guardar el producto");
    } finally { setBusy(false); }
  };

  const remove = async (p) => {
    if (!window.confirm(`¿Eliminar «${p.name}»?`)) return;
    try {
      await axios.delete(`${API}/company/products/${p.id}`, { withCredentials: true });
      toast.success("Producto eliminado");
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "No se pudo eliminar"); }
  };

  return (
    <div className="space-y-6" data-testid="company-products-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Boxes className="w-6 h-6 text-[#8B5CF6]" /> Mis productos
          </h2>
        </div>
        <Button data-testid="company-product-new-btn"
          onClick={() => { setEditing(null); setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> Nuevo producto
        </Button>
      </div>

      {commission !== null && (
        <div className="border-l-4 border-amber-400 bg-amber-500/5 px-4 py-3 text-sm text-neutral-300" data-testid="company-commission-note">
          Resilience aplica una comisión del {commission}% sobre cada venta del marketplace.
        </div>
      )}

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-products-empty">
          Aún no tienes productos. Publica el primero y espera la aprobación del administrador.
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
                  {STATUS_LABEL[p.approval_status] || "Aprobado"}
                </span>
              </div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              {p.approval_status === "rejected" && p.rejection_reason && (
                <div className="text-xs text-red-400 mt-1">Motivo: {p.rejection_reason}</div>
              )}
              <div className="mt-auto pt-3 flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]">{p.price_usd} <span className="text-xs text-neutral-500">USDT</span></div>
                  <div className="text-xs text-neutral-500">Stock: {p.stock}</div>
                  <div className="text-xs text-emerald-400 mt-1">Vendido: {p.sold_qty || 0} · Ganado: {(p.earned_usd || 0).toFixed(2)} USD</div>
                </div>
                <div className="flex gap-2">
                  <button data-testid={`company-product-edit-${p.id}`} onClick={() => { setEditing(p); setForm({ ...emptyForm, ...p, price_usd: String(p.price_usd), available_store_ids: p.available_store_ids || [] }); setOpen(true); }}
                    className="text-neutral-400 hover:text-[#8B5CF6]" title="Editar"><Edit2 className="w-4 h-4" /></button>
                  <button data-testid={`company-product-delete-${p.id}`} onClick={() => remove(p)}
                    className="text-neutral-400 hover:text-[#EF4444]" title="Eliminar"><Trash2 className="w-4 h-4" /></button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? "Editar producto" : "Nuevo producto"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">Nombre</Label>
              <Input data-testid="company-product-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Descripción</Label>
              <Textarea data-testid="company-product-description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Imagen</Label>
              <input data-testid="company-product-image" type="file" accept="image/*" onChange={(e) => onImageFile(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {form.image_url && <img src={form.image_url} alt="preview" className="mt-2 h-24 object-cover border border-white/10" />}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Precio (USDT)</Label>
                <Input data-testid="company-product-price" type="number" step="any" min="0" value={form.price_usd} onChange={(e) => setForm({ ...form, price_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              {!editing && (
                <div>
                  <Label className="micro-label text-neutral-500">Unidad</Label>
                  <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })}>
                    <SelectTrigger data-testid="company-product-unit" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      <SelectItem value="unidad" data-testid="company-product-unit-unidad">Unidad (entero)</SelectItem>
                      <SelectItem value="libra" data-testid="company-product-unit-libra">Libra (decimal)</SelectItem>
                      <SelectItem value="kg" data-testid="company-product-unit-kg">Kg (decimal)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
            {!editing ? (
              <div>
                <Label className="micro-label text-neutral-500">Stock inicial</Label>
                <Input data-testid="company-product-stock" type="number" step={form.unit === "unidad" ? "1" : "any"} min="0" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                <p className="text-xs text-neutral-500 mt-1">Entra como una recepción auditada en el almacén central.</p>
              </div>
            ) : (
              <div className="border-l-4 border-[#8B5CF6]/40 bg-[#8B5CF6]/5 px-3 py-2 text-xs text-neutral-400" data-testid="company-product-stock-note">
                El stock se gestiona en la pestaña <span className="text-[#8B5CF6]">Inventario</span> (recibir, distribuir, devolver o ajustar). Editar aquí no cambia el stock.
              </div>
            )}
            <div>
              <Label className="micro-label text-neutral-500">Categoría</Label>
              <Input data-testid="company-product-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Disponible en tiendas (opcional)</Label>
              {stores.length === 0 ? (
                <p className="text-xs text-neutral-500 mt-1">Crea tiendas para elegir dónde se vende. Si no eliges ninguna, estará disponible en todas.</p>
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
              <span className="text-sm">Producto activo</span>
            </div>
            {!editing && <p className="text-xs text-neutral-500">El producto quedará pendiente hasta que un administrador lo apruebe.</p>}
            <Button data-testid="company-product-save" onClick={save} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? "…" : "Guardar"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
