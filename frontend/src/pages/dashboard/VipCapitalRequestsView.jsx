import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { CheckCircle2, XCircle, Clock, HandCoins, Plus, Info } from "lucide-react";

const STATUS_META = {
  pending: { label: "En revisión", cls: "text-amber-400 border-amber-500/40 bg-amber-500/5", icon: Clock },
  disbursed: { label: "Desembolsado", cls: "text-[#8B5CF6] border-[#8B5CF6]/40 bg-[#8B5CF6]/5", icon: HandCoins },
  paid_off: { label: "Devuelto", cls: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5", icon: CheckCircle2 },
  rejected: { label: "Rechazado", cls: "text-red-400 border-red-500/40 bg-red-500/5", icon: XCircle },
};

const fmtNum = (n, d = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

/**
 * iter55.32 — VIP-facing view for capital requests ("Solicitud de Fondos").
 * The VIP client can:
 *   - See all their historical requests
 *   - Create new ones (form dialog)
 *   - See progress of active debts (bar)
 */
export default function VipCapitalRequestsView() {
  const [items, setItems] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USDT");
  const [reason, setReason] = useState("");
  const [estimatedReturnDate, setEstimatedReturnDate] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reqs, cur] = await Promise.all([
        axios.get(`${API}/vip/capital-requests`, { withCredentials: true }),
        axios.get(`${API}/currencies`),
      ]);
      setItems(reqs.data || []);
      setCurrencies((cur.data || []).filter((c) => c.is_active));
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al cargar solicitudes.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    const amt = Number(amount);
    if (isNaN(amt) || amt <= 0) return toast.error("Ingresa un monto válido mayor a 0.");
    if (reason.trim().length < 8) return toast.error("Describe brevemente el motivo (mínimo 8 caracteres).");
    setBusy(true);
    try {
      await axios.post(
        `${API}/vip/capital-requests`,
        {
          amount: amt,
          currency_code: currency,
          reason: reason.trim(),
          estimated_return_date: estimatedReturnDate || null,
        },
        { withCredentials: true },
      );
      toast.success("Solicitud enviada. El equipo la revisará pronto.");
      setOpen(false);
      setAmount(""); setReason(""); setEstimatedReturnDate("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al enviar la solicitud.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="vip-capital-requests-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">/ Solicitud de Fondos</div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="max-w-2xl">
            <h1 className="font-display text-3xl">Capital operativo</h1>
            <p className="text-sm text-neutral-400 mt-2 leading-relaxed">
              Solicita capital de la empresa para operar con tus clientes.
              Si es aprobado, el monto se acredita a tu saldo VIP y se descuenta
              automáticamente un porcentaje de cada orden acumulada que completes
              hasta terminar de devolver el capital.
            </p>
          </div>
          <Button
            data-testid="vip-capital-request-new"
            onClick={() => setOpen(true)}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-11 px-6 uppercase tracking-wider text-xs font-bold"
          >
            <Plus className="w-4 h-4 mr-2" /> Nueva solicitud
          </Button>
        </div>
      </div>

      {/* ADVICE CARD */}
      <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 p-4 flex gap-3">
        <Info className="w-5 h-5 text-[#8B5CF6] shrink-0 mt-0.5" />
        <div className="text-sm text-neutral-300 leading-relaxed">
          El equipo revisa cada solicitud manualmente. Podrás tener varias solicitudes
          activas al mismo tiempo. Recibirás notificación en cuanto sean aprobadas o rechazadas.
        </div>
      </div>

      {/* LIST */}
      {loading ? (
        <div className="text-neutral-500 p-6">Cargando…</div>
      ) : items.length === 0 ? (
        <div className="tactile-card p-10 text-center text-neutral-500" data-testid="vip-cr-empty">
          Aún no has enviado ninguna solicitud de capital.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((cr) => {
            const meta = STATUS_META[cr.status] || STATUS_META.pending;
            const StatusIcon = meta.icon;
            const paidPct = cr.debt_original
              ? Math.round(((cr.debt_original - (cr.debt_remaining || 0)) / cr.debt_original) * 100)
              : 0;
            return (
              <div
                key={cr.id}
                className="tactile-card p-5"
                data-testid={`vip-cr-item-${cr.id}`}
              >
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div className="flex-1 min-w-[240px]">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 flex items-center gap-1 ${meta.cls}`}>
                        <StatusIcon className="w-3 h-3" /> {meta.label}
                      </span>
                      <span className="text-neutral-500 text-xs">
                        {fmtDate(cr.created_at)}
                      </span>
                    </div>
                    <div className="text-sm text-neutral-300 leading-relaxed max-w-xl">
                      {cr.reason}
                    </div>
                    {cr.status === "rejected" && cr.reject_reason && (
                      <div className="mt-2 text-xs text-red-400 border-l-2 border-red-500/50 pl-2">
                        {cr.reject_reason}
                      </div>
                    )}
                    {cr.estimated_return_date && (
                      <div className="mt-2 text-xs text-neutral-500">
                        Fecha estimada de devolución: {cr.estimated_return_date}
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="micro-label text-neutral-500">Monto</div>
                    <div className="font-display text-2xl tabular-nums">
                      {fmtNum(cr.amount, 2)} <span className="text-sm text-neutral-500">{cr.currency_code}</span>
                    </div>
                    {cr.status === "disbursed" && (
                      <>
                        <div className="mt-2 text-xs text-neutral-500">
                          Restante: <span className="text-amber-400 tabular-nums">{fmtNum(cr.debt_remaining, 2)} {cr.currency_code}</span>
                        </div>
                        <div className="mt-1 text-[0.65rem] text-[#8B5CF6]">
                          Descuento {cr.discount_pct}% por orden
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {cr.status === "disbursed" && (
                  <div className="mt-4">
                    <div className="h-1.5 bg-white/5">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${paidPct}%` }}
                      />
                    </div>
                    <div className="text-[0.65rem] text-neutral-500 mt-1 uppercase tracking-widest">
                      {paidPct}% devuelto
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* NEW REQUEST DIALOG */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Nueva solicitud de capital</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">Monto</Label>
                <Input
                  data-testid="vip-cr-amount"
                  type="number"
                  min="0.01" step="0.01"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
                  placeholder="1000.00"
                />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Moneda</Label>
                <Select value={currency} onValueChange={setCurrency}>
                  <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1" data-testid="vip-cr-currency">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    {currencies.map((c) => (
                      <SelectItem key={c.code} value={c.code} data-testid={`vip-cr-cur-${c.code}`}>
                        {c.code} · {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Motivo (mínimo 8 caracteres)</Label>
              <Textarea
                data-testid="vip-cr-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                className="rounded-none bg-[#0a0a0a] border-white/10 mt-1"
                placeholder="Ej: capital para atender pedido grande de cliente en Cuba durante la semana del..."
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Fecha estimada de devolución (opcional)</Label>
              <Input
                data-testid="vip-cr-return-date"
                type="date"
                value={estimatedReturnDate}
                onChange={(e) => setEstimatedReturnDate(e.target.value)}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setOpen(false)} className="rounded-none bg-transparent border border-white/15 text-white">Cancelar</Button>
            <Button
              data-testid="vip-cr-submit"
              onClick={submit}
              disabled={busy}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold"
            >
              Enviar solicitud
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
