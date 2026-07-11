import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Plus, Edit2, Trash2 } from "lucide-react";
import { toast } from "sonner";

const empty = { code: "", name: "", type: "fiat", symbol: "", country: "", is_active: true, payment_account: "", delivery_methods: null };

const DELIVERY_OPTIONS = [
  { value: "transfer", label: "Transferencia bancaria" },
  { value: "cash", label: "Efectivo (a domicilio)" },
  { value: "crypto", label: "Cripto (wallet)" },
];

export default function AdminCurrencies() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const load = async () => {
    const r = await axios.get(`${API}/currencies`);
    setItems(r.data);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      if (editing) await axios.put(`${API}/admin/currencies/${editing.id}`, form, { withCredentials: true });
      else await axios.post(`${API}/admin/currencies`, form, { withCredentials: true });
      toast.success("Guardado");
      setOpen(false); setEditing(null); setForm(empty);
      load();
    } catch (e) { toast.error("Error"); }
  };

  const remove = async (id) => {
    if (!window.confirm("¿Eliminar moneda?")) return;
    await axios.delete(`${API}/admin/currencies/${id}`, { withCredentials: true });
    toast.success("Eliminada"); load();
  };

  const edit = (it) => { setEditing(it); setForm({ ...it }); setOpen(true); };

  return (
    <div data-testid="admin-currencies">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">/ Monedas</div>
          <h1 className="font-display text-3xl">Cripto & Fiat</h1>
        </div>
        <Button data-testid="add-currency-btn" onClick={() => { setEditing(null); setForm(empty); setOpen(true); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
          <Plus className="w-4 h-4 mr-1" /> Nueva moneda
        </Button>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Código</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Nombre</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Tipo</th>
              <th className="px-4 py-3 micro-label text-neutral-500">País</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Cuenta destino</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Activa</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.map(c => (
              <tr key={c.id} className="border-b border-white/5">
                <td className="px-4 py-3 font-mono font-semibold">{c.code}</td>
                <td className="px-4 py-3">{c.name}</td>
                <td className="px-4 py-3"><span className={`text-xs uppercase border px-2 py-0.5 ${c.type === "crypto" ? "border-[#8B5CF6]/40 text-[#8B5CF6]" : "border-white/20 text-neutral-400"}`}>{c.type}</span></td>
                <td className="px-4 py-3 text-neutral-400">{c.country || "—"}</td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs truncate">{c.payment_account || "—"}</td>
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
          <DialogHeader><DialogTitle className="font-display">{editing ? "Editar" : "Nueva"} Moneda</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">Código (USDT, USD, CUP...)</Label>
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
                  <span className="opacity-60">Se guardará como:</span>
                  <span className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 px-1.5 py-0.5">
                    {form.code.trim()}
                  </span>
                </div>
              )}
              {form.code && form.code === form.code.trim() && (
                <div className="mt-1 text-[0.65rem] text-neutral-600 font-mono">
                  ↳ se guardará como <span className="text-neutral-400">{form.code.trim()}</span>
                </div>
              )}
            </div>
            <div><Label className="micro-label text-neutral-500">Nombre</Label><Input data-testid="cur-name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div>
              <Label className="micro-label text-neutral-500">Tipo</Label>
              <Select value={form.type} onValueChange={v => setForm({ ...form, type: v })}>
                <SelectTrigger className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  <SelectItem value="crypto">Crypto</SelectItem>
                  <SelectItem value="fiat">Fiat</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label className="micro-label text-neutral-500">País</Label><Input value={form.country} onChange={e => setForm({ ...form, country: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div><Label className="micro-label text-neutral-500">Cuenta destino (Zelle, wallet, banco)</Label><Input value={form.payment_account} onChange={e => setForm({ ...form, payment_account: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" /></div>
            <div data-testid="cur-delivery-methods">
              <Label className="micro-label text-neutral-500">Métodos de entrega permitidos</Label>
              <div className="text-xs text-neutral-500 mt-1 mb-2">
                Si dejas todos en blanco, el sistema detecta automáticamente por el nombre (transferencia/efectivo/wallet).
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
            <div className="flex items-center gap-3"><Switch checked={form.is_active} onCheckedChange={v => setForm({ ...form, is_active: v })} /><span className="text-sm">Activa</span></div>
            <Button data-testid="save-currency-btn" onClick={save} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">Guardar</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
