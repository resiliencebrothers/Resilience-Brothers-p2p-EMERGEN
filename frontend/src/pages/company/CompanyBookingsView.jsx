import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { CalendarCheck, Check, X, Clock, User, Wallet, TrendingUp, Star, MessageSquare, CornerDownRight, Loader2 } from "lucide-react";
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
  const [earnings, setEarnings] = useState(null);
  const [filter, setFilter] = useState("");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const q = filter ? `?status=${filter}` : "";
    axios.get(`${API}/company/bookings${q}`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
    axios.get(`${API}/company/bookings/earnings`, { withCredentials: true })
      .then((r) => setEarnings(r.data)).catch(() => {});
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
        El cliente ya pagó el total por adelantado (anticipo + resto <span className="text-sky-300">congelado</span>) y queda <span className="text-[#8B5CF6]">retenido</span>.
        Acepta para confirmar el turno; recházalo y se le devuelve TODO automáticamente.
        Si no decides a tiempo, se cancela y reembolsa solo. El importe completo se te libera
        <span className="text-[#8B5CF6]"> después de la fecha de la cita</span>.
      </div>

      {earnings && (
        <div className="tactile-card p-4" data-testid="company-earnings-panel">
          <div className="micro-label text-[#8B5CF6] mb-3 flex items-center gap-1"><Wallet className="w-3.5 h-3.5" /> Ingresos</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">Retenido (pendientes)</div>
              <div className="font-display text-2xl text-amber-300" data-testid="earnings-held">{earnings.held_pending} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">Reservas pendientes de aceptar</div>
            </div>
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">Por liberar</div>
              <div className="font-display text-2xl text-emerald-400" data-testid="earnings-upcoming">{earnings.upcoming_release} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">Citas confirmadas · se libera tras cada cita</div>
            </div>
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">Ya cobrado</div>
              <div className="font-display text-2xl text-sky-300" data-testid="earnings-settled">{earnings.settled_total} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">Citas completadas</div>
            </div>
          </div>
          {earnings.upcoming?.length > 0 && (
            <div className="mt-4">
              <div className="text-xs text-neutral-400 mb-2 flex items-center gap-1"><TrendingUp className="w-3.5 h-3.5 text-emerald-400" /> Próximas liberaciones por fecha de cita</div>
              <ul className="space-y-1.5" data-testid="earnings-schedule">
                {earnings.upcoming.map((u) => (
                  <li key={u.id} className="flex items-center justify-between gap-3 text-sm border-b border-white/5 pb-1.5 last:border-0">
                    <span className="text-neutral-300 truncate">{u.slot_date} · {u.slot_start} · <span className="text-neutral-500">{u.service_title}</span></span>
                    <span className="font-mono text-emerald-300 shrink-0">{u.amount_usdt} USDT</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

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
              {b.remainder_usdt > 0 && ["pending", "accepted", "settled"].includes(b.status) && (
                <div className="text-[0.7rem] text-emerald-300/80 mt-0.5" data-testid={`company-booking-deposit-${b.id}`}>
                  Anticipo {b.deposit_usdt} USDT · resto {b.remainder_usdt} USDT {b.status === "settled" ? "liberado tras la cita" : "congelado hasta la cita"}
                </div>
              )}
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
              Se devolverá al cliente {rejecting?.amount_usdt > 0 ? `${rejecting.amount_usdt} USDT (anticipo + resto congelado)` : "el importe"}. Puedes indicar un motivo (opcional).
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

      <CompanyReviews />
    </div>
  );
}

// ---------- Reseñas de clientes: la empresa responde públicamente ----------
function CompanyReviews() {
  const [reviews, setReviews] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/company/reviews`, { withCredentials: true })
      .then((r) => setReviews(r.data || [])).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (rv) => {
    const text = (drafts[rv.id] ?? "").trim();
    if (!text) return;
    setSavingId(rv.id);
    try {
      await axios.post(`${API}/company/reviews/${rv.id}/response`, { response: text },
        { withCredentials: true });
      toast.success("Respuesta publicada");
      setDrafts((d) => { const n = { ...d }; delete n[rv.id]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setSavingId(null); }
  };

  return (
    <div data-testid="company-reviews-section">
      <h3 className="font-display text-xl flex items-center gap-2 mt-2">
        <MessageSquare className="w-5 h-5 text-[#8B5CF6]" /> Reseñas de clientes
        {reviews.length > 0 && <span className="text-sm text-neutral-500">· {reviews.length}</span>}
      </h3>
      <p className="text-sm text-neutral-400 mt-1 mb-3">Responde públicamente para mostrar atención de calidad.</p>

      {reviews.length === 0 ? (
        <p className="text-neutral-500 text-center py-10 tactile-card" data-testid="company-reviews-empty">
          Aún no tienes reseñas. Aparecerán aquí cuando tus clientes valoren un servicio completado.
        </p>
      ) : (
        <div className="space-y-3">
          {reviews.map((rv) => (
            <div key={rv.id} data-testid={`company-review-${rv.id}`} className="tactile-card p-4">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-0.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Star key={n} className={`w-3.5 h-3.5 ${n <= Math.round(rv.rating) ? "fill-amber-400 text-amber-400" : "text-neutral-600"}`} />
                    ))}
                  </span>
                  <span className="text-xs text-neutral-300">{rv.customer_name}</span>
                </div>
                <span className="text-[0.7rem] text-neutral-500">{rv.service_title}</span>
              </div>
              {rv.comment && <p className="text-sm text-neutral-300 mt-1.5 whitespace-pre-line">{rv.comment}</p>}

              {rv.company_response ? (
                <div className="mt-2.5 ml-3 border-l-2 border-[#8B5CF6]/40 pl-3" data-testid={`company-review-reply-${rv.id}`}>
                  <div className="text-[0.65rem] uppercase tracking-wider text-[#A78BFA] flex items-center gap-1">
                    <CornerDownRight className="w-3 h-3" /> Tu respuesta
                  </div>
                  <p className="text-sm text-neutral-300 mt-0.5 whitespace-pre-line">{rv.company_response}</p>
                  <button data-testid={`company-review-edit-${rv.id}`} onClick={() => setDrafts((d) => ({ ...d, [rv.id]: rv.company_response }))}
                    className="text-[0.7rem] text-neutral-500 hover:text-[#A78BFA] mt-1">Editar respuesta</button>
                </div>
              ) : null}

              {(drafts[rv.id] !== undefined || !rv.company_response) && (
                <div className="mt-2.5 space-y-2">
                  <Textarea data-testid={`company-review-input-${rv.id}`} rows={2}
                    value={drafts[rv.id] ?? ""} onChange={(e) => setDrafts((d) => ({ ...d, [rv.id]: e.target.value }))}
                    placeholder="Escribe una respuesta pública…" className="rounded-none bg-[#0a0a0a] border-white/10" />
                  <Button data-testid={`company-review-save-${rv.id}`} onClick={() => save(rv)} disabled={savingId === rv.id || !(drafts[rv.id] ?? "").trim()}
                    className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none h-9">
                    {savingId === rv.id ? (<><Loader2 className="w-4 h-4 mr-1 animate-spin" /> …</>) : (rv.company_response ? "Guardar cambios" : "Responder")}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
