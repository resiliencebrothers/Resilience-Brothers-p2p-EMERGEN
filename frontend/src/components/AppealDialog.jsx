import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { MessageSquare, Send, Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";

/**
 * AppealDialog — self-service appeal for `under_review` clients.
 *
 * Renders a "Enviar apelación" button that opens a modal with:
 *  - textarea for the appeal message (min 10 chars, max 2000)
 *  - list of previous appeals (pending / resolved / rejected) with staff response
 *
 * Endpoints consumed:
 *  - POST /api/appeals            (create)
 *  - GET  /api/appeals/me         (history)
 */
export default function AppealDialog() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/appeals/me`, { withCredentials: true });
      setItems(r.data.items || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo cargar el historial");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const hasPending = items.some((a) => a.status === "pending");

  const submit = async () => {
    const trimmed = message.trim();
    if (trimmed.length < 10) {
      toast.error("Cuéntanos con más detalle (mínimo 10 caracteres).");
      return;
    }
    setSending(true);
    try {
      await axios.post(
        `${API}/appeals`,
        { message: trimmed },
        { withCredentials: true }
      );
      toast.success("Apelación enviada. El staff la revisará pronto.");
      setMessage("");
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail?.code === "APPEAL_ALREADY_PENDING") {
        toast.error("Ya tienes una apelación pendiente. Espera la respuesta del staff.");
        await load();
      } else if (typeof detail === "string") {
        toast.error(detail);
      } else {
        toast.error(detail?.message || "No se pudo enviar la apelación.");
      }
    } finally {
      setSending(false);
    }
  };

  const statusChip = (status) => {
    const config = {
      pending: { icon: Clock, cls: "text-[#EAB308] border-[#EAB308]/40 bg-[#EAB308]/5", label: "PENDIENTE" },
      resolved: { icon: CheckCircle2, cls: "text-[#22C55E] border-[#22C55E]/40 bg-[#22C55E]/5", label: "APROBADA" },
      rejected: { icon: XCircle, cls: "text-[#EF4444] border-[#EF4444]/40 bg-[#EF4444]/5", label: "RECHAZADA" },
    }[status] || { icon: Clock, cls: "text-neutral-400 border-white/10", label: status };
    const Icon = config.icon;
    return (
      <span className={`inline-flex items-center gap-1.5 text-[0.65rem] tracking-wider font-semibold border px-2 py-0.5 uppercase ${config.cls}`}>
        <Icon className="w-3 h-3" /> {config.label}
      </span>
    );
  };

  return (
    <>
      <Button
        data-testid="open-appeal-dialog-btn"
        onClick={() => setOpen(true)}
        variant="outline"
        size="sm"
        className="border-[#EAB308]/40 text-[#EAB308] hover:bg-[#EAB308]/10 mt-3"
      >
        <MessageSquare className="w-3.5 h-3.5 mr-1.5" />
        Enviar apelación al staff
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="appeal-dialog" className="max-w-lg bg-[#0c0c0c] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="text-white">Apelación al staff</DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs leading-relaxed">
              Escribe por qué crees que tu cuenta debe ser reactivada. El staff verá tu mensaje y responderá cuanto antes. Sé claro y aporta contexto (por ejemplo, número correcto, motivo del bloqueo aparente).
            </DialogDescription>
          </DialogHeader>

          {!hasPending && (
            <div className="space-y-2">
              <Textarea
                data-testid="appeal-message-textarea"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ej: Mi teléfono es correcto y no coincide con la lista bloqueada; puedo verificar por WhatsApp."
                rows={5}
                maxLength={2000}
                className="bg-black/40 border-white/10 text-sm text-white"
              />
              <div className="flex items-center justify-between text-[0.65rem] text-neutral-500">
                <span>{message.length}/2000</span>
                <span>{message.trim().length < 10 ? `Faltan ${10 - message.trim().length} caracteres` : "Listo para enviar"}</span>
              </div>
            </div>
          )}

          {hasPending && (
            <div className="border border-[#EAB308]/30 bg-[#EAB308]/5 px-3 py-2.5 text-xs text-[#FEF3C7]">
              Ya tienes una apelación pendiente. El staff la está revisando. Espera la respuesta antes de enviar otra.
            </div>
          )}

          {/* History */}
          <div className="border-t border-white/5 pt-3">
            <div className="micro-label text-neutral-500 text-[0.65rem] mb-2">Historial de apelaciones</div>
            {loading && <div className="text-xs text-neutral-500">Cargando...</div>}
            {!loading && items.length === 0 && (
              <div className="text-xs text-neutral-500 italic">Aún no has enviado ninguna apelación.</div>
            )}
            {!loading && items.length > 0 && (
              <ul className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {items.map((a) => (
                  <li key={a.id} data-testid={`appeal-history-item-${a.id}`} className="border border-white/5 bg-black/30 px-3 py-2 space-y-1">
                    <div className="flex items-center justify-between">
                      {statusChip(a.status)}
                      <span className="text-[0.6rem] text-neutral-500">{a.created_at?.slice(0, 16).replace("T", " ")}</span>
                    </div>
                    <div className="text-xs text-neutral-300 line-clamp-3">{a.message}</div>
                    {a.staff_response && (
                      <div className="text-[0.7rem] text-neutral-400 border-l-2 border-[#EAB308]/60 pl-2 mt-1">
                        <span className="text-[#EAB308] font-semibold">Staff: </span>{a.staff_response}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <DialogFooter className="pt-2">
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              data-testid="appeal-close-btn"
              className="text-neutral-400 hover:text-white"
            >
              Cerrar
            </Button>
            {!hasPending && (
              <Button
                data-testid="appeal-submit-btn"
                onClick={submit}
                disabled={sending || message.trim().length < 10}
                className="bg-[#EAB308] hover:bg-[#EAB308]/90 text-black font-semibold"
              >
                {sending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
                Enviar
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
