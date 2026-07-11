import { Button } from "@/components/ui/button";
import { Mail } from "lucide-react";

export function AuthSuccessPanel({ message, mode, resending, onResend, onClose }) {
  return (
    <div className="py-4 text-center" data-testid="auth-success-state">
      <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-[#22C55E]/10 flex items-center justify-center">
        <Mail className="w-6 h-6 text-[#22C55E]" />
      </div>
      <p className="text-sm text-neutral-300 mb-5">{message}</p>
      {mode !== "forgot" && (
        <button
          type="button"
          data-testid="auth-resend-verification-btn"
          onClick={onResend}
          disabled={resending}
          className="block mx-auto mb-4 text-xs text-[#8B5CF6] hover:text-[#A78BFA] underline underline-offset-4 disabled:opacity-50"
        >
          {resending ? "Reenviando..." : "¿No recibiste el correo? Reenviar"}
        </button>
      )}
      <Button
        onClick={onClose}
        className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
      >
        Entendido
      </Button>
    </div>
  );
}
