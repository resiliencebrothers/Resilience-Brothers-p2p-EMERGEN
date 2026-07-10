import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";

/**
 * Reusable 2FA step-up prompt for high-risk admin actions.
 *
 * Usage:
 *   const [pending, setPending] = useState(null); // payload waiting for TOTP
 *   <TotpPromptDialog
 *     open={!!pending}
 *     title="Confirmar acción de admin"
 *     description="Esta es una acción sensible. Ingresa tu código 2FA para continuar."
 *     onCancel={() => setPending(null)}
 *     onConfirm={(code) => doAction({ ...pending, totp_code: code })}
 *   />
 *
 * The parent component is responsible for closing the dialog
 * (`onCancel`) after a successful `onConfirm` so the user can
 * retry on invalid codes (which keeps the modal open).
 */
export default function TotpPromptDialog({
  open,
  title = "Verificación 2FA requerida",
  description = "Ingresa tu código de Google Authenticator para confirmar esta acción.",
  onConfirm,
  onCancel,
  busy = false,
}) {
  const navigate = useNavigate();
  const [code, setCode] = useState("");

  useEffect(() => {
    if (!open) setCode("");
  }, [open]);

  const handleSubmit = () => {
    const trimmed = code.trim();
    if (trimmed.length < 6) {
      toast.error("Ingresa un código de 6 dígitos o un código de recuperación");
      return;
    }
    onConfirm(trimmed);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel?.(); }}>
      <DialogContent
        data-testid="totp-prompt-dialog"
        className="bg-[#141414] border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-[#EAB308]" /> {title}
          </DialogTitle>
          <DialogDescription className="text-neutral-400">
            {description}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="micro-label text-[#EAB308]">Código 2FA</Label>
            <Input
              data-testid="totp-prompt-input"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
              placeholder="123456 o XXXXX-XXXXX"
              maxLength={11}
              autoFocus
              autoComplete="one-time-code"
              inputMode="text"
              className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono text-center text-lg tracking-wider"
            />
            <p className="text-[0.65rem] text-neutral-500 mt-1">
              Código de 6 dígitos de tu app autenticadora o un código de recuperación.{" "}
              <button
                type="button"
                onClick={() => navigate("/dashboard/security")}
                className="text-[#EAB308] hover:underline"
              >
                Configurar 2FA
              </button>
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Button
              data-testid="totp-prompt-cancel"
              variant="ghost"
              onClick={onCancel}
              className="rounded-none border border-white/10 hover:bg-white/5"
            >
              Cancelar
            </Button>
            <Button
              data-testid="totp-prompt-confirm"
              onClick={handleSubmit}
              disabled={busy}
              className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none"
            >
              {busy ? "Verificando..." : "Confirmar"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Helper to map a 2FA error response to a user-friendly toast.
 * Returns `true` if the error WAS a 2FA error (so the caller can keep the dialog open).
 */
export function handleTotpError(error, navigate) {
  const detail = error?.response?.data?.detail;
  const code = typeof detail === "object" ? detail?.code : null;
  if (error?.response?.status === 412 && code === "TOTP_SETUP_REQUIRED") {
    toast.error("Debes configurar 2FA antes de realizar esta acción");
    setTimeout(() => navigate?.("/dashboard/security"), 1500);
    return true;
  }
  if (code === "TOTP_INVALID" || code === "TOTP_CODE_REQUIRED") {
    toast.error(detail?.message || "Código 2FA inválido");
    return true;
  }
  return false;
}
