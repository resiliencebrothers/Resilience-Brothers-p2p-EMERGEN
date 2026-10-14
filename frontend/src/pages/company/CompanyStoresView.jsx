import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Store, Plus, Edit2, Trash2, MapPin } from "lucide-react";
import { toast } from "sonner";

// Tiendas (sucursales) de la Empresa. Una Empresa puede tener varias (1:N).
const emptyForm = {
  name: "", address: "", municipality: "", province: "", phone: "", hours: "", active: true,
};

export default function CompanyStoresView({ onChanged }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/company/stores`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.name || form.name.trim().length < 2) return toast.error("El nombre es obligatorio");
    if (!form.address || form.address.trim().length < 5) return toast.error("La dirección es obligatoria");
    setBusy(true);
    const payload = {
      name: form.name.trim(),
      address: form.address.trim(),
      municipality: form.municipality || "",
      province: form.province || "",
      phone: form.phone || "",
      hours: form.hours || "",
      active: form.active,
    };
    try {
      if (editing) {
        await axios.put(`${API}/company/stores/${editing.id}`, payload, { withCredentials: true });
        toast.success("Tienda actualizada");
      } else {
        await axios.post(`${API}/company/stores`, payload, { withCredentials: true });
        toast.success("Tienda creada");
      }
      setOpen(false); setEditing(null); setForm(emptyForm);
      load(); onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo guardar la tienda");
    } finally { setBusy(false); }
  };

  const remove = async (s) => {
    if (!window.confirm(`¿Eliminar la tienda «${s.name}»?`)) return;
    try {
      await axios.delete(`${API}/company/stores/${s.id}`, { withCredentials: true });
      toast.success("Tienda eliminada");
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "No se pudo eliminar"); }
  };

  return (
    <div className="space-y-6" data-testid="company-stores-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Store className="w-6 h-6 text-[#8B5CF6]" /> Mis tiendas
          </h2>
        </div>
        <Button data-testid="company-store-new-btn"
          onClick={() => { setEditing(null); setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> Nueva tienda
        </Button>
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-stores-empty">
          Aún no tienes tiendas. Crea la primera para empezar a distribuir tu inventario.
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((s) => (
          <div key={s.id} className="tactile-card p-4 flex flex-col" data-testid={`company-store-${s.id}`}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-display text-lg">{s.name}</h3>
              <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${s.active ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-neutral-500/10 text-neutral-400 border-neutral-500/30"}`}>
                {s.active ? "Activa" : "Inactiva"}
              </span>
            </div>
            <div className="text-sm text-neutral-400 mt-2 flex items-start gap-2">
              <MapPin className="w-4 h-4 mt-0.5 text-neutral-600" />
              <span>{s.address}{s.municipality ? `, ${s.municipality}` : ""}{s.province ? `, ${s.province}` : ""}</span>
            </div>
            {s.phone && <div className="text-xs text-neutral-500 mt-1">Tel: {s.phone}</div>}
            {s.hours && <div className="text-xs text-neutral-500 mt-1">Horario: {s.hours}</div>}
            <div className="mt-auto pt-3 flex gap-3 justify-end">
              <button data-testid={`company-store-edit-${s.id}`} onClick={() => { setEditing(s); setForm({ ...emptyForm, ...s }); setOpen(true); }}
                className="text-neutral-400 hover:text-[#8B5CF6]" title="Editar"><Edit2 className="w-4 h-4" /></button>
              <button data-testid={`company-store-delete-${s.id}`} onClick={() => remove(s)}
                className="text-neutral-400 hover:text-[#EF4444]" title="Eliminar"><Trash2 className="w-4 h-4" /></button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? "Editar tienda" : "Nueva tienda"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">Nombre</Label>
              <Input data-testid="company-store-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Dirección</Label>
              <Input data-testid="company-store-address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Municipio</Label>
                <Input data-testid="company-store-municipality" value={form.municipality} onChange={(e) => setForm({ ...form, municipality: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Provincia</Label>
                <Input data-testid="company-store-province" value={form.province} onChange={(e) => setForm({ ...form, province: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Teléfono</Label>
                <Input data-testid="company-store-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Horario</Label>
                <Input data-testid="company-store-hours" value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Switch data-testid="company-store-active" checked={form.active} onCheckedChange={(v) => setForm({ ...form, active: v })} />
              <span className="text-sm">Tienda activa</span>
            </div>
            <Button data-testid="company-store-save" onClick={save} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? "…" : "Guardar"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
