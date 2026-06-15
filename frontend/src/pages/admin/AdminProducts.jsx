import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Plus, Edit2, Trash2 } from "lucide-react";
import { toast } from "sonner";

const empty = { name: "", description: "", image_url: "", price_usd: 0, cost_usd: 0, stock: 0, category: "general", is_active: true };

export default function AdminProducts() {
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
    } catch (e) { toast.error("Error"); }
  };

  const remove = async (id) => {
    if (!window.confirm("¿Eliminar?")) return;
    await axios.delete(`${API}/admin/products/${id}`, { withCredentials: true });
    toast.success("Eliminado"); load();
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
                  <button onClick={() => { setEditing(p); setForm(p); setOpen(true); }} className="text-neutral-400 hover:text-[#EAB308]"><Edit2 className="w-4 h-4" /></button>
                  <button onClick={() => remove(p.id)} className="text-neutral-400 hover:text-[#EF4444]"><Trash2 className="w-4 h-4" /></button>
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
            <div><Label className="micro-label text-neutral-500">URL Imagen</Label><Input value={form.image_url} onChange={e => setForm({ ...form, image_url: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label className="micro-label text-neutral-500">Precio USD (venta)</Label><Input data-testid="prod-price" type="number" step="any" value={form.price_usd} onChange={e => setForm({ ...form, price_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
              <div><Label className="micro-label text-neutral-500">Costo USD (compra)</Label><Input data-testid="prod-cost" type="number" step="any" value={form.cost_usd} onChange={e => setForm({ ...form, cost_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" /></div>
            </div>
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
