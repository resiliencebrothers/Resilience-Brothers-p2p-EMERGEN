import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { UserCircle, Phone, Check, X, RefreshCcw, Clock } from "lucide-react";

/**
 * iter55.20b — Admin panel for pending profile-change requests.
 *
 * Today only phone-change requests need admin approval (email uses OTP
 * self-service; country is instant with KYC-reset). This panel lists every
 * user with `pending_phone_change` set and lets the operator approve or
 * reject each one with a 2FA step-up.
 *
 * Available to admins AND to staff members granted the `profile_changes`
 * permission (iter55.16 catalog).
 */
export default function AdminProfileChangeRequests() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState(null); // {action, userId, reason?}
  const [rejectFor, setRejectFor] = useState(null); // userId in reject dialog
  const [rejectReason, setRejectReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/profile-change-requests`, { withCredentials: true });
      setItems(r.data.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al cargar solicitudes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const askApprove = (userId) => setPendingAction({ action: "approve", userId });

  const askReject = (userId) => {
    setRejectFor(userId);
    setRejectReason("");
  };

  const submitReject = () => {
    if (!rejectReason || rejectReason.trim().length < 3) {
      return toast.error("Motivo requerido (mínimo 3 caracteres)");
    }
    setPendingAction({ action: "reject", userId: rejectFor, reason: rejectReason.trim() });
    setRejectFor(null);
  };

  const confirmWithTotp = async (totpCode) => {
    if (!pendingAction) return;
    const { action, userId, reason } = pendingAction;
    try {
      const url = action === "approve"
        ? `${API}/admin/profile-change-requests/${userId}/approve-phone`
        : `${API}/admin/profile-change-requests/${userId}/reject-phone`;
      const body = action === "approve" ? { totp_code: totpCode } : { reason, totp_code: totpCode };
      await axios.post(url, body, { withCredentials: true });
      toast.success(action === "approve"
        ? "Cambio de teléfono aprobado"
        : "Cambio de teléfono rechazado");
      setPendingAction(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || "Error al procesar");
      }
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-profile-change-requests">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl">Solicitudes de cambio de datos</h1>
          <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
            Clientes que pidieron cambiar su número de teléfono. Verifica que
            realmente contactaron al equipo antes de aprobar.
          </p>
        </div>
        <Button
          onClick={load}
          disabled={loading}
          data-testid="profile-changes-refresh"
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-9 px-3 font-mono text-xs uppercase tracking-wider"
        >
          <RefreshCcw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} /> Refrescar
        </Button>
      </div>

      {loading && (
        <div className="text-xs text-neutral-500 p-6" data-testid="profile-changes-loading">
          Cargando...
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="tactile-card p-10 text-center" data-testid="profile-changes-empty">
          <UserCircle className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
          <p className="text-sm text-neutral-500">No hay solicitudes pendientes.</p>
        </div>
      )}

      {!loading && items.length > 0 && (
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a] border-b border-white/10">
              <tr>
                <th className="text-left px-4 py-3 micro-label text-neutral-500">Cliente</th>
                <th className="text-left px-4 py-3 micro-label text-neutral-500">País</th>
                <th className="text-left px-4 py-3 micro-label text-neutral-500">Teléfono actual</th>
                <th className="text-left px-4 py-3 micro-label text-neutral-500">Teléfono nuevo</th>
                <th className="text-left px-4 py-3 micro-label text-neutral-500">Solicitado</th>
                <th className="text-right px-4 py-3 micro-label text-neutral-500">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.user_id} className="border-b border-white/5 hover:bg-white/[0.02]"
                    data-testid={`profile-change-row-${it.user_id}`}>
                  <td className="px-4 py-3">
                    <div className="text-sm text-white">{it.name || "—"}</div>
                    <div className="text-[0.65rem] text-neutral-500">{it.email}</div>
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-300">{it.country || "—"}</td>
                  <td className="px-4 py-3 text-xs font-mono text-neutral-400">
                    {it.current_phone || "—"}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-[#8B5CF6]">
                    <span className="flex items-center gap-1">
                      <Phone className="w-3 h-3" /> {it.new_phone}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[0.7rem] text-neutral-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {it.requested_at ? new Date(it.requested_at).toLocaleString("es") : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 justify-end">
                      <Button
                        onClick={() => askApprove(it.user_id)}
                        data-testid={`profile-change-approve-${it.user_id}`}
                        className="rounded-none bg-[#22C55E] hover:bg-[#22C55E]/90 text-black h-8 px-3 font-mono text-[0.65rem] uppercase tracking-wider"
                      >
                        <Check className="w-3 h-3 mr-1" /> Aprobar
                      </Button>
                      <Button
                        onClick={() => askReject(it.user_id)}
                        data-testid={`profile-change-reject-${it.user_id}`}
                        className="rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-8 px-3 font-mono text-[0.65rem] uppercase tracking-wider"
                      >
                        <X className="w-3 h-3 mr-1" /> Rechazar
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Reject reason dialog — collects the mandatory reason before 2FA */}
      <Dialog open={!!rejectFor} onOpenChange={(v) => !v && setRejectFor(null)}>
        <DialogContent className="bg-[#141322] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
                       data-testid="profile-change-reject-dialog">
          <DialogHeader>
            <DialogTitle className="font-display text-xl">Rechazar cambio</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-neutral-400 leading-relaxed">
              El cliente recibirá una notificación con el motivo. Sé claro para
              evitar tickets de soporte.
            </p>
            <Textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
              data-testid="profile-change-reject-reason"
              placeholder="Ej. Documento de respaldo no coincide con el titular de la cuenta."
              className="rounded-none bg-[#0a0a0a] border-white/10"
            />
            <div className="flex gap-2">
              <Button onClick={() => setRejectFor(null)}
                      className="flex-1 rounded-none bg-transparent border border-white/15 text-white h-10 font-mono uppercase tracking-wider text-xs">
                Cancelar
              </Button>
              <Button onClick={submitReject}
                      data-testid="profile-change-reject-continue"
                      className="flex-1 rounded-none bg-[#EF4444] hover:bg-[#EF4444]/90 text-white h-10 font-mono uppercase tracking-wider text-xs">
                Continuar
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingAction}
        title={pendingAction?.action === "approve"
          ? "Confirmar aprobación"
          : "Confirmar rechazo"}
        description="Esta acción modifica datos sensibles del cliente. Ingresa tu código 2FA para continuar."
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}
