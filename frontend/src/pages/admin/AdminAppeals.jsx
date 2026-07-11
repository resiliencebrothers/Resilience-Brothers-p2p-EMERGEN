import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { MessageSquare, Check, X, Loader2, Inbox, CheckCircle2, XCircle, Clock, Mail } from "lucide-react";

const STATUS_TABS = [
  { key: "pending", label: "Pendientes", icon: Clock },
  { key: "resolved", label: "Aprobadas", icon: CheckCircle2 },
  { key: "rejected", label: "Rechazadas", icon: XCircle },
  { key: "all", label: "Todas", icon: Inbox },
];

/**
 * AdminAppeals — staff queue of self-service client appeals.
 *
 * Endpoints:
 *  - GET  /api/admin/appeals?status=<pending|resolved|rejected>
 *  - POST /api/admin/appeals/{id}/resolve  {response}
 *  - POST /api/admin/appeals/{id}/reject   {response}
 *
 * Requires: role=admin OR (employee + can_manage_blocklist).
 */
export default function AdminAppeals() {
  const [tab, setTab] = useState("pending");
  const [items, setItems] = useState([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // appeal being reviewed
  const [action, setAction] = useState(null);     // "resolve" | "reject"
  const [response, setResponse] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = tab === "all" ? {} : { status: tab };
      const r = await axios.get(`${API}/admin/appeals`, { params, withCredentials: true });
      setItems(r.data.items || []);
      setPendingCount(r.data.pending_count || 0);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar la cola de apelaciones");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const openAction = (appeal, kind) => {
    setSelected(appeal);
    setAction(kind);
    setResponse("");
  };

  const submitAction = async () => {
    const trimmed = response.trim();
    if (!trimmed) {
      toast.error("Escribe una respuesta para el cliente.");
      return;
    }
    setSaving(true);
    try {
      await axios.post(
        `${API}/admin/appeals/${selected.id}/${action}`,
        { response: trimmed },
        { withCredentials: true }
      );
      toast.success(action === "resolve" ? "Apelación aprobada." : "Apelación rechazada.");
      setSelected(null);
      setAction(null);
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo procesar la apelación");
    } finally {
      setSaving(false);
    }
  };

  const statusChip = (status) => {
    const cfg = {
      pending: { icon: Clock, cls: "text-[#8B5CF6] border-[#8B5CF6]/40 bg-[#8B5CF6]/5", label: "PENDIENTE" },
      resolved: { icon: CheckCircle2, cls: "text-[#22C55E] border-[#22C55E]/40 bg-[#22C55E]/5", label: "APROBADA" },
      rejected: { icon: XCircle, cls: "text-[#EF4444] border-[#EF4444]/40 bg-[#EF4444]/5", label: "RECHAZADA" },
    }[status] || { icon: Clock, cls: "text-neutral-400 border-white/10", label: status };
    const Icon = cfg.icon;
    return (
      <span className={`inline-flex items-center gap-1.5 text-[0.65rem] tracking-wider font-semibold border px-2 py-0.5 uppercase ${cfg.cls}`}>
        <Icon className="w-3 h-3" /> {cfg.label}
      </span>
    );
  };

  return (
    <div data-testid="admin-appeals-page" className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl">Apelaciones</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Mensajes de clientes bajo revisión pidiendo reactivación. Resolver aquí
            <span className="text-neutral-500"> no </span>activa la cuenta — usa <span className="text-white font-semibold">Verificar teléfono</span> en Usuarios cuando decidas activar.
          </p>
        </div>
        <div className="text-xs text-neutral-400">
          Pendientes: <span className="text-[#8B5CF6] font-bold text-base">{pendingCount}</span>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-black/40 border border-white/5">
          {STATUS_TABS.map((s) => (
            <TabsTrigger
              key={s.key}
              value={s.key}
              data-testid={`appeals-tab-${s.key}`}
              className="data-[state=active]:bg-[#8B5CF6] data-[state=active]:text-white text-neutral-400"
            >
              <s.icon className="w-3.5 h-3.5 mr-1.5" />
              {s.label}
              {s.key === "pending" && pendingCount > 0 && (
                <span className="ml-1.5 bg-[#EF4444] text-white text-[0.6rem] font-bold px-1.5 py-0.5 rounded-full">
                  {pendingCount}
                </span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={tab} className="mt-4">
          {loading && <div className="text-sm text-neutral-500">Cargando...</div>}
          {!loading && items.length === 0 && (
            <div className="text-sm text-neutral-500 italic border border-white/5 bg-black/20 px-4 py-6 text-center">
              No hay apelaciones en esta cola.
            </div>
          )}
          <ul className="space-y-3">
            {items.map((a) => (
              <li
                key={a.id}
                data-testid={`appeal-row-${a.id}`}
                className="border border-white/5 bg-black/30 px-4 py-3 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    {statusChip(a.status)}
                    <span className="text-sm font-semibold truncate">{a.user_name || a.user_email}</span>
                  </div>
                  <span className="text-[0.65rem] text-neutral-500">{a.created_at?.slice(0, 16).replace("T", " ")}</span>
                </div>
                <div className="text-xs text-neutral-400 flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center gap-1"><Mail className="w-3 h-3" /> {a.user_email}</span>
                  {a.user_phone && <span>📱 {a.user_phone}</span>}
                </div>
                <div className="text-sm text-neutral-200 whitespace-pre-wrap">{a.message}</div>
                {a.staff_response && (
                  <div className="text-xs text-neutral-400 border-l-2 border-[#8B5CF6]/60 pl-3 py-1">
                    <span className="text-[#8B5CF6] font-semibold">Respuesta staff ({a.resolved_by_email}): </span>
                    {a.staff_response}
                  </div>
                )}
                {a.status === "pending" && (
                  <div className="flex gap-2 pt-1">
                    <Button
                      size="sm"
                      data-testid={`appeal-resolve-btn-${a.id}`}
                      onClick={() => openAction(a, "resolve")}
                      className="bg-[#22C55E]/10 border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/20"
                    >
                      <Check className="w-3.5 h-3.5 mr-1" /> Aprobar
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`appeal-reject-btn-${a.id}`}
                      onClick={() => openAction(a, "reject")}
                      className="bg-[#EF4444]/10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/20"
                    >
                      <X className="w-3.5 h-3.5 mr-1" /> Rechazar
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </TabsContent>
      </Tabs>

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent data-testid="appeal-action-dialog" className="bg-[#0c0c0c] border-white/10 text-white max-w-md max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-white">
              {action === "resolve" ? "Aprobar apelación" : "Rechazar apelación"}
            </DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs">
              El cliente recibirá tu respuesta como notificación in-app + push.
              {action === "resolve" && (
                <span className="block mt-2 text-[#8B5CF6]">
                  ⚠️ Aprobar la apelación NO activa la cuenta. Debes ir a <b>Usuarios → Verificar teléfono</b> por separado.
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="border border-white/5 bg-black/40 px-3 py-2 text-xs text-neutral-300 space-y-1">
              <div><span className="text-neutral-500">Cliente:</span> {selected.user_name || selected.user_email}</div>
              <div className="text-neutral-200 pt-1 border-t border-white/5 mt-1">{selected.message}</div>
            </div>
          )}
          <Textarea
            data-testid="appeal-response-textarea"
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            placeholder={action === "resolve"
              ? "Ej: Gracias por tu apelación, en las próximas horas activamos tu cuenta."
              : "Ej: Sigues en la lista bloqueada por reportes previos. Contacta a WhatsApp."}
            rows={4}
            maxLength={1000}
            className="bg-black/40 border-white/10 text-sm text-white"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSelected(null)} className="text-neutral-400 hover:text-white">
              Cancelar
            </Button>
            <Button
              data-testid="appeal-action-confirm-btn"
              onClick={submitAction}
              disabled={saving || !response.trim()}
              className={action === "resolve"
                ? "bg-[#22C55E] hover:bg-[#22C55E]/90 text-black font-semibold"
                : "bg-[#EF4444] hover:bg-[#EF4444]/90 text-white font-semibold"}
            >
              {saving ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <MessageSquare className="w-4 h-4 mr-1.5" />}
              Confirmar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
