import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Plus, Edit2, Trash2, Lock } from "lucide-react";
import { toast } from "sonner";

const empty = { name: "", description: "", image_url: "", price_usd: 0, cost_usd: 0, stock: 0, category: "general", is_active: true };

export default function AdminProducts() {
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
      toast.success("Guardado");
      setOpen(false); setEditing(null); setForm(empty); load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error al guardar"); }
  };

  const remove = async (id) => {
    if (!canDelete) {
      toast.error("No tienes permiso para eliminar productos");
      return;
    }
    if (!window.confirm("¿Eliminar?")) return;
    try {
      await axios.delete(`${API}/admin/products/${id}`, { withCredentials: true });
      toast.success("Eliminado"); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al eliminar");
    }
  };

  return (
    <div data-testid="admin-products">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="micro-label text-[#EAB308] mb-2">/ Marketplace</div>
          <h1 className="font-display text-3xl">Productos</h1>
        </div>
        <Button data-testid="add-product-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">
          <Plus className="w-4 h-4 mr-1" /> Nuevo
        </Button>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map(p => (
          <div key={p.id} className="tactile-card overflow-hidden">
            <div className="aspect-video bg-[#0a0a0a]">{p.image_url && <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />}</div>
            <div className="p-4">
              <div className="micro-label text-neutral-500">{p.category}</div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              <div className="flex items-center justify-between mt-3">
                <div>
                  <div className="font-display text-xl text-[#EAB308]">${p.price_usd}</div>
                  <div className="text-xs text-neutral-500">Stock: {p.stock}</div>
                  {p.cost_usd > 0 && (
                    <div className="text-xs text-[#22C55E] mt-1">Margen: ${(p.price_usd - p.cost_usd).toFixed(2)}/u</div>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setEditing(p); setForm(p); setOpen(true); }}
                    data-testid={`edit-product-${p.id}`}
                    className="text-neutral-400 hover:text-[#EAB308]"
                    title="Editar producto"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => remove(p.id)}
                    disabled={!canDelete}
                    data-testid={`delete-product-${p.id}`}
                    title={canDelete ? "Eliminar producto" : "No tienes permiso para eliminar productos"}
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
        <DialogContent className="bg-[#141414] border-white/10 text-white rounded-none">
          <DialogHeader><DialogTitle className="font-display">{editing ? "Editar" : "Nuevo"} Producto</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label className="micro-label text-neutral-500">Nombre</Label><Input data-testid="prod-name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div><Label className="micro-label text-neutral-500">Descripción</Label><Textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div>
              <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                URL Imagen {!canEditImage && <Lock className="w-3 h-3 text-neutral-600" />}
              </Label>
              <Input
                value={form.image_url}
                onChange={e => setForm({ ...form, image_url: e.target.value })}
                disabled={!canEditImage}
                data-testid="prod-image-url"
                title={canEditImage ? "" : "No tienes permiso para cambiar imágenes"}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              {!canEditImage && (
                <p className="text-[0.65rem] text-neutral-600 mt-1">
                  Permiso requerido — pídele a un admin que active &quot;Imágenes&quot; en tu cuenta.
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                  Precio USD (venta) {!canEditPrice && <Lock className="w-3 h-3 text-neutral-600" />}
                </Label>
                <Input
                  data-testid="prod-price"
                  type="number"
                  step="any"
                  value={form.price_usd}
                  onChange={e => setForm({ ...form, price_usd: e.target.value })}
                  disabled={!canEditPrice}
                  title={canEditPrice ? "" : "No tienes permiso para modificar precios"}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
              <div>
                <Label className="micro-label text-neutral-500 flex items-center gap-1.5">
                  Costo USD (compra) {!canEditPrice && <Lock className="w-3 h-3 text-neutral-600" />}
                </Label>
                <Input
                  data-testid="prod-cost"
                  type="number"
                  step="any"
                  value={form.cost_usd}
                  onChange={e => setForm({ ...form, cost_usd: e.target.value })}
                  disabled={!canEditPrice}
                  title={canEditPrice ? "" : "No tienes permiso para modificar precios"}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
            </div>
            {!canEditPrice && (
              <p className="text-[0.65rem] text-neutral-600 -mt-2">
                Permiso requerido — pídele a un admin que active &quot;Precios&quot; en tu cuenta.
              </p>
            )}
            <div><Label className="micro-label text-neutral-500">Stock</Label><Input data-testid="prod-stock" type="number" value={form.stock} onChange={e => setForm({ ...form, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
            <div><Label className="micro-label text-neutral-500">Categoría</Label><Input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div className="flex items-center gap-3"><Switch checked={form.is_active} onCheckedChange={v => setForm({ ...form, is_active: v })} /><span className="text-sm">Activo</span></div>
            <Button data-testid="save-product-btn" onClick={save} className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">Guardar</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
