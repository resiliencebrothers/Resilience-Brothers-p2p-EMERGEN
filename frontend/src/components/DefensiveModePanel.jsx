import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ShieldAlert, ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { useNavigate } from "react-router-dom";
import { captureError } from "@/sentry";

export default function DefensiveModePanel() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pendingTotp, setPendingTotp] = useState(null);

  const load = async () => {
    try {
      const r = await axios.get(`${API}/system/defensive-mode`, { withCredentials: true });
      setState(r.data);
    } catch (err) {
      captureError(err, { where: "DefensiveModePanel.load" });
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const requestToggle = (enabled) => {
    if (enabled && !reason.trim()) {
      toast.error("Indica el motivo antes de activar el modo defensivo");
      return;
    }
    setPendingTotp({ enabled, reason: reason.trim() });
  };

  const confirmWithTotp = async (code) => {
    try {
      await axios.post(
        `${API}/admin/defensive-mode/toggle`,
        { enabled: pendingTotp.enabled, reason: pendingTotp.reason, totp_code: code },
        { withCredentials: true },
      );
      toast.success(pendingTotp.enabled ? "Modo defensivo activado" : "Modo defensivo desactivado");
      setPendingTotp(null); setDialogOpen(false); setReason(""); load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail?.message || e.response?.data?.detail || "Error");
    }
  };

  if (loading) return null;
  const enabled = !!state?.enabled;

  return (
    <>
      <div
        data-testid="defensive-mode-panel"
        className={`tactile-card p-5 lg:p-6 border-l-2 ${enabled ? "border-[#EF4444] bg-[#EF4444]/5" : "border-white/10"}`}
      >
        <div className="flex items-start gap-4 flex-wrap">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            {enabled ? (
              <ShieldAlert className="w-7 h-7 text-[#EF4444] shrink-0" />
            ) : (
              <ShieldCheck className="w-7 h-7 text-[#22C55E] shrink-0" />
            )}
            <div className="min-w-0">
              <div className="micro-label text-neutral-500 mb-1">/ Seguridad</div>
              <h2 className="font-display text-lg">
                Modo Defensivo{" "}
                <span className={enabled ? "text-[#EF4444]" : "text-[#22C55E]"}>
                  · {enabled ? "ACTIVO" : "Inactivo"}
                </span>
              </h2>
              {enabled ? (
                <p className="text-xs text-neutral-400 mt-1 leading-relaxed">
                  La plataforma rechaza nuevos registros y congela retiros hasta que lo desactives.
                  Los usuarios ven un banner amarillo.
                </p>
              ) : (
                <p className="text-xs text-neutral-500 mt-1 leading-relaxed">
                  Activa este modo cuando detectes ataques coordinados. Suspende nuevos registros, congela retiros y muestra aviso a los usuarios.
                </p>
              )}
            </div>
          </div>
          {isAdmin && (
            <Button
              data-testid={enabled ? "defensive-mode-disable-btn" : "defensive-mode-enable-btn"}
              onClick={() => {
                if (enabled) requestToggle(false);
                else setDialogOpen(true);
              }}
              className={`rounded-none ${enabled ? "bg-[#EF4444] hover:bg-[#DC2626] text-white" : "bg-white/5 hover:bg-[#EF4444]/20 hover:text-[#EF4444] text-white border border-white/10"}`}
            >
              {enabled ? "Desactivar" : "Activar modo defensivo"}
            </Button>
          )}
        </div>
      </div>

      {/* ENABLE DIALOG — requires reason */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-[#14101F] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2">
              <ShieldAlert className="w-6 h-6 text-[#EF4444]" /> Activar Modo Defensivo
            </DialogTitle>
            <DialogDescription className="text-neutral-400 text-sm">
              Mientras esté activo: <strong className="text-white">se bloquean nuevos registros</strong> (email y Google),
              <strong className="text-white"> se congelan retiros</strong> de clientes (admin sí puede retirar) y
              <strong className="text-white"> los usuarios ven un banner amarillo</strong>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Label className="micro-label text-neutral-500">Motivo (visible en audit log)</Label>
            <Input
              data-testid="defensive-mode-reason-input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ej: ataque coordinado de scammers desde IP X"
              maxLength={500}
              className="rounded-none bg-[#0a0a0a] border-white/10"
            />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setDialogOpen(false)} className="rounded-none">Cancelar</Button>
              <Button
                data-testid="defensive-mode-confirm-enable"
                onClick={() => requestToggle(true)}
                className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none"
              >
                Activar
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingTotp}
        action={pendingTotp?.enabled ? "activar modo defensivo" : "desactivar modo defensivo"}
        onClose={() => setPendingTotp(null)}
        onSubmit={confirmWithTotp}
      />
    </>
  );
}


/** Public banner — shown on every page if defensive mode is enabled. */
export function DefensiveBanner() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    let active = true;
    const fetchState = async () => {
      try {
        const r = await axios.get(`${API}/system/defensive-mode`);
        if (active) setEnabled(!!r.data?.enabled);
      } catch (err) {
        // Non-critical: banner just stays in its previous state if the public endpoint is unreachable
        captureError(err, { where: "DefensiveBanner.poll", level: "warning" });
      }
    };
    fetchState();
    const t = setInterval(fetchState, 60_000); // poll every 60s
    return () => { active = false; clearInterval(t); };
  }, []);

  if (!enabled) return null;
  return (
    <div
      data-testid="defensive-banner"
      role="status"
      className="bg-[#8B5CF6] text-white text-center text-xs sm:text-sm font-semibold py-2 px-4 z-50"
    >
      <Loader2 className="w-3.5 h-3.5 inline-block mr-2 animate-spin" />
      Plataforma en mantenimiento de seguridad. Los retiros y nuevos registros están temporalmente suspendidos. Disculpa las molestias.
    </div>
  );
}
