import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Truck, Plus, MapPin, Package, User } from "lucide-react";
import { toast } from "sonner";

// Fase 4 — la Empresa SOLICITA mensajería; Resilience asigna el mensajero.
// La Empresa no elige ni asigna mensajeros.
const STATUS = {
  available: { label: "En espera de mensajero", cls: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
  assigned: { label: "Asignada", cls: "bg-sky-500/10 text-sky-300 border-sky-500/30" },
  accepted: { label: "Aceptada", cls: "bg-sky-500/10 text-sky-300 border-sky-500/30" },
  on_the_way: { label: "En camino", cls: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30" },
  delivered: { label: "Entregada", cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
  confirmed: { label: "Completada", cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
  cancelled: { label: "Cancelada", cls: "bg-neutral-500/10 text-neutral-400 border-neutral-500/30" },
};
const CANCELABLE = ["available", "assigned"];
const emptyForm = {
  receiver_name: "", receiver_phone: "", delivery_address: "", province: "",
  municipality: "", note: "", fromStore: false, product_id: "", origin_store_id: "", quantity: "",
};

export default function CompanyDeliveriesView() {
  const [items, setItems] = useState([]);
  const [products, setProducts] = useState([]);
  const [stores, setStores] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [fee, setFee] = useState(0);
  const clientKeyRef = useRef(null);

  const load = useCallback(() => {
    axios.get(`${API}/company/deliveries`, { withCredentials: true }).then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/company/me`, { withCredentials: true }).then((r) => setFee(Number(r.data?.delivery_fee_usdt || 0))).catch(() => {});
    axios.get(`${API}/company/products`, { withCredentials: true }).then((r) => setProducts(r.data)).catch(() => {});
    axios.get(`${API}/company/stores`, { withCredentials: true }).then((r) => setStores(r.data)).catch(() => {});
  }, [load]);

  const submit = async () => {
    if (!form.receiver_name || form.receiver_name.trim().length < 2) return toast.error("Nombre del destinatario requerido");
    if (!form.receiver_phone) return toast.error("Teléfono del destinatario requerido");
    if (!form.delivery_address || form.delivery_address.trim().length < 5) return toast.error("Dirección de entrega requerida");
    // E34-02 — clave de idempotencia ESTABLE por envío lógico: se genera UNA
    // vez y se conserva en los reintentos (mismo envío ⇒ mismo cargo/reserva).
    if (!clientKeyRef.current) {
      clientKeyRef.current = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
    }
    const body = {
      receiver_name: form.receiver_name.trim(),
      receiver_phone: form.receiver_phone.trim(),
      delivery_address: form.delivery_address.trim(),
      province: form.province || "",
      municipality: form.municipality || "",
      note: form.note || "",
      client_key: clientKeyRef.current,
    };
    if (form.fromStore) {
      if (!form.product_id || !form.origin_store_id || !form.quantity) return toast.error("Elige producto, tienda y cantidad");
      body.product_id = form.product_id;
      body.origin_store_id = form.origin_store_id;
      body.quantity = parseFloat(form.quantity);
    }
    setBusy(true);
    const doPost = () => axios.post(`${API}/company/deliveries`, body, { withCredentials: true });
    try {
      try {
        await doPost();
      } catch (e1) {
        // Sin respuesta del servidor (red): reintenta UNA vez con la MISMA
        // clave → el backend deduplica (no se cobra ni reserva dos veces).
        if (!e1.response) { await doPost(); } else { throw e1; }
      }
      toast.success("Solicitud enviada. Resilience asignará un mensajero.");
      clientKeyRef.current = null;  // nuevo envío ⇒ nueva clave
      setOpen(false); setForm(emptyForm); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo crear la solicitud");
    } finally { setBusy(false); }
  };

  const cancel = async (it) => {
    if (!window.confirm("¿Cancelar esta solicitud de mensajería?")) return;
    try {
      await axios.post(`${API}/company/deliveries/${it.id}/cancel`, {}, { withCredentials: true });
      toast.success("Solicitud cancelada");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "No se pudo cancelar"); }
  };

  return (
    <div className="space-y-6" data-testid="company-deliveries-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Truck className="w-6 h-6 text-[#8B5CF6]" /> Mensajería
          </h2>
          <p className="text-sm text-neutral-500 mt-1">Solicita un envío. Resilience asigna el mensajero (tú no lo eliges).</p>
          <p className="text-xs mt-1" data-testid="company-delivery-fee-note">
            {fee > 0
              ? <span className="text-amber-300">Tarifa por envío: <span className="font-mono">{fee} USDT</span> · se retiene de tu sub-saldo y se reembolsa si cancelas antes de completarse.</span>
              : <span className="text-emerald-400">Mensajería sin costo por ahora.</span>}
          </p>
        </div>
        <Button data-testid="company-delivery-new-btn" onClick={() => { setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> Solicitar envío
        </Button>
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-deliveries-empty">
          Aún no has solicitado envíos. Crea tu primera solicitud de mensajería.
        </p>
      )}

      <div className="space-y-3">
        {items.map((it) => {
          const st = STATUS[it.delivery_status] || STATUS.available;
          return (
            <div key={it.id} className="tactile-card p-4" data-testid={`company-delivery-${it.id}`}>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-sm"><User className="w-4 h-4 text-neutral-600" /> <span className="text-white">{it.receiver_name}</span> <span className="text-neutral-500">· {it.receiver_phone}</span></div>
                  <div className="flex items-start gap-2 text-sm text-neutral-400"><MapPin className="w-4 h-4 mt-0.5 text-neutral-600" /> {it.delivery_address}{it.municipality ? `, ${it.municipality}` : ""}{it.province ? `, ${it.province}` : ""}</div>
                  <div className="flex items-center gap-2 text-sm text-neutral-400"><Package className="w-4 h-4 text-neutral-600" /> {it.package_label}</div>
                  {it.courier_name && <div className="text-xs text-sky-300">Mensajero: {it.courier_name}</div>}
                  {Number(it.fee_usdt || 0) > 0 && (
                    <div className="text-xs text-neutral-500" data-testid={`company-delivery-fee-${it.id}`}>
                      Tarifa: <span className="font-mono text-neutral-300">{it.fee_usdt} USDT</span>
                      {it.fee_status === "held" && <span className="text-amber-300"> · retenida</span>}
                      {it.fee_status === "charged" && <span className="text-emerald-400"> · cobrada</span>}
                      {it.fee_status === "refunded" && <span className="text-neutral-400"> · reembolsada</span>}
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${st.cls}`} data-testid={`company-delivery-status-${it.id}`}>{st.label}</span>
                  {CANCELABLE.includes(it.delivery_status) && (
                    <button data-testid={`company-delivery-cancel-${it.id}`} onClick={() => cancel(it)} className="text-xs text-neutral-400 hover:text-[#EF4444]">Cancelar</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setOpen(false)}>
          <div className="bg-[#1A1730] border border-white/10 rounded-none w-full max-w-lg max-h-[88vh] overflow-y-auto p-6 space-y-3" onClick={(e) => e.stopPropagation()} data-testid="company-delivery-dialog">
            <h3 className="font-display text-xl">Solicitar envío</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Destinatario</Label>
                <Input data-testid="company-delivery-receiver" value={form.receiver_name} onChange={(e) => setForm({ ...form, receiver_name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Teléfono</Label>
                <Input data-testid="company-delivery-phone" value={form.receiver_phone} onChange={(e) => setForm({ ...form, receiver_phone: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Dirección de entrega</Label>
              <Input data-testid="company-delivery-address" value={form.delivery_address} onChange={(e) => setForm({ ...form, delivery_address: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Provincia</Label>
                <Input data-testid="company-delivery-province" value={form.province} onChange={(e) => setForm({ ...form, province: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Municipio</Label>
                <Input data-testid="company-delivery-municipality" value={form.municipality} onChange={(e) => setForm({ ...form, municipality: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Nota / contenido</Label>
              <Textarea data-testid="company-delivery-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="flex items-center gap-3 pt-2 border-t border-white/5">
              <Switch data-testid="company-delivery-fromstore" checked={form.fromStore} onCheckedChange={(v) => setForm({ ...form, fromStore: v })} />
              <span className="text-sm">Despachar un producto desde una tienda (descuenta su stock)</span>
            </div>
            {form.fromStore && (
              <div className="grid grid-cols-1 gap-3 bg-black/20 p-3 border border-white/5">
                <div>
                  <Label className="micro-label text-neutral-500">Producto</Label>
                  <Select value={form.product_id} onValueChange={(v) => setForm({ ...form, product_id: v })}>
                    <SelectTrigger data-testid="company-delivery-product" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder="Selecciona" /></SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      {products.map((p) => <SelectItem key={p.id} value={p.id} data-testid={`company-delivery-product-opt-${p.id}`}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="micro-label text-neutral-500">Tienda origen</Label>
                    <Select value={form.origin_store_id} onValueChange={(v) => setForm({ ...form, origin_store_id: v })}>
                      <SelectTrigger data-testid="company-delivery-store" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder="Selecciona" /></SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                        {stores.map((s) => <SelectItem key={s.id} value={s.id} data-testid={`company-delivery-store-opt-${s.id}`}>{s.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="micro-label text-neutral-500">Cantidad</Label>
                    <Input data-testid="company-delivery-qty" type="number" step="any" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                  </div>
                </div>
              </div>
            )}
            <Button data-testid="company-delivery-save" onClick={submit} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? "…" : (fee > 0 ? `Enviar solicitud · ${fee} USDT` : "Enviar solicitud")}
            </Button>
            {fee > 0 && (
              <p className="text-xs text-neutral-500 text-center">Se retienen {fee} USDT de tu sub-saldo al solicitar. Si cancelas antes de que se complete, se te reembolsan íntegros.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
