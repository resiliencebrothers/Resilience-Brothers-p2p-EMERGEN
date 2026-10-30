import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { CalendarCheck, Check, X, Clock, User } from "lucide-react";
import { toast } from "sonner";

// Reservas recibidas por la Empresa (Fase 2). La empresa acepta o rechaza cada
// turno; al rechazar (o si no decide a tiempo) el cliente recibe el reembolso
// automático en USDT. El dinero se libera a la empresa DESPUÉS de la cita.
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  accepted: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
  cancelled: "bg-neutral-500/10 text-neutral-300 border-neutral-500/30",
  expired: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  settled: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};
const STATUS_LABEL = {
  pending: "Pendiente", accepted: "Confirmada", rejected: "Rechazada",
  cancelled: "Cancelada", expired: "No confirmada", settled: "Completada",
};
const FILTERS = [
  { v: "", l: "Todas" }, { v: "pending", l: "Pendientes" },
  { v: "accepted", l: "Confirmadas" }, { v: "settled", l: "Completadas" },
  { v: "rejected", l: "Rechazadas" }, { v: "cancelled", l: "Canceladas" },
  { v: "expired", l: "No confirmadas" },
];

export default function CompanyBookingsView({ onChanged }) {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const q = filter ? `?status=${filter}` : "";
    axios.get(`${API}/company/bookings${q}`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const accept = async (b) => {
    setBusy(true);
    try {
      await axios.post(`${API}/company/bookings/${b.id}/accept`, {}, { withCredentials: true });
      toast.success("Reserva confirmada");
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const doReject = async () => {
    if (!rejecting) return;
    setBusy(true);
    try {
      await axios.post(`${API}/company/bookings/${rejecting.id}/reject`, { reason },
        { withCredentials: true });
      toast.success("Reserva rechazada; se reembolsó al cliente");
      setRejecting(null); setReason("");
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const pendingCount = items.filter((b) => b.status === "pending").length;

  return (
    <div className="space-y-6" data-testid="company-bookings-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <CalendarCheck className="w-6 h-6 text-[#8B5CF6]" /> Reservas recibidas
          {pendingCount > 0 && <span className="text-sm bg-amber-500/15 text-amber-300 px-2 py-0.5 rounded-full">{pendingCount} pendiente{pendingCount > 1 ? "s" : ""}</span>}
        </h2>
      </div>

      <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-neutral-300" data-testid="company-bookings-note">
        El cliente ya pagó el importe, que queda <span className="text-[#8B5CF6]">retenido</span>.
        Acepta para confirmar el turno; recházalo y se le devuelve automáticamente.
        Si no decides a tiempo, se cancela y reembolsa solo. El pago se te libera
        <span className="text-[#8B5CF6]"> después de la fecha de la cita</span>.
      </div>

      <div className="flex gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button key={f.v || "all"} data-testid={`company-bookings-filter-${f.v || "all"}`} onClick={() => setFilter(f.v)}
            className={`px-3 py-1 text-xs uppercase tracking-wider border transition-colors ${filter === f.v ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {f.l}
          </button>
        ))}
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-bookings-empty">
          Aún no tienes reservas{filter ? " con ese filtro" : ""}.
        </p>
      )}

      <div className="space-y-3">
        {items.map((b) => (
          <div key={b.id} data-testid={`company-booking-${b.id}`} className="tactile-card p-4 flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-display text-base truncate">{b.service_title}</span>
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[b.status] || ""}`} data-testid={`company-booking-status-${b.id}`}>
                  {STATUS_LABEL[b.status] || b.status}
                </span>
              </div>
              <div className="text-xs text-neutral-400 mt-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> {b.slot_date} · {b.slot_start}–{b.slot_end}
              </div>
              <div className="text-xs text-neutral-400 mt-0.5 flex items-center gap-1">
                <User className="w-3 h-3" /> {b.customer_name || "Cliente"}
              </div>
              <div className="text-xs text-neutral-500 mt-0.5">
                {b.quantity > 1 ? `${b.quantity}× · ` : ""}{b.amount_usdt > 0 ? `${b.amount_usdt} USDT` : "A presupuestar"}
              </div>
              {b.note && <div className="text-xs text-neutral-400 mt-1 italic">“{b.note}”</div>}
            </div>
            {b.status === "pending" && (
              <div className="flex gap-2">
                <Button data-testid={`company-booking-accept-${b.id}`} onClick={() => accept(b)} disabled={busy}
                  className="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 rounded-none h-9">
                  <Check className="w-4 h-4 mr-1" /> Aceptar
                </Button>
                <Button data-testid={`company-booking-reject-${b.id}`} onClick={() => { setRejecting(b); setReason(""); }} disabled={busy}
                  variant="outline" className="border-white/15 text-neutral-300 hover:text-red-400 rounded-none h-9">
                  <X className="w-4 h-4 mr-1" /> Rechazar
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>

      <Dialog open={!!rejecting} onOpenChange={(v) => !v && setRejecting(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto sm:max-w-md" data-testid="company-booking-reject-dialog">
          <DialogHeader><DialogTitle className="font-display">Rechazar reserva</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-neutral-300">
              Se devolverá al cliente {rejecting?.amount_usdt > 0 ? `${rejecting.amount_usdt} USDT` : "el importe"}. Puedes indicar un motivo (opcional).
            </p>
            <Textarea data-testid="company-booking-reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
              placeholder="Ej: no tenemos disponibilidad ese día" className="rounded-none bg-[#0a0a0a] border-white/10" />
            <div className="flex gap-2">
              <Button data-testid="company-booking-reject-cancel" onClick={() => setRejecting(null)} variant="outline"
                className="flex-1 border-white/15 text-neutral-200 rounded-none h-10">Cancelar</Button>
              <Button data-testid="company-booking-reject-confirm" onClick={doReject} disabled={busy}
                className="flex-1 bg-red-500/80 hover:bg-red-500 text-white font-semibold rounded-none h-10">
                {busy ? "…" : "Rechazar y reembolsar"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
