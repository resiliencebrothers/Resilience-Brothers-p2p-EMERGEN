import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Sparkles, ArrowDown } from "lucide-react";
import { usePwaInstall } from "@/hooks/usePwaInstall";

// Non-sensitive UI preference ("hint already seen" flag — no tokens/PII);
// localStorage is intentional so the hint never re-nags across sessions.
const HINT_KEY = "rb_install_hint_seen";

/**
 * iter114 — One-time onboarding popover for the manual "Instalar app" button.
 * Rendered above the button in the mobile Sheet footer for first-time users
 * (gated by parent via `enabled` prop = `user.onboarding_completed === false`).
 * Once dismissed, persists in localStorage so it never surfaces again.
 */
export default function InstallAppHint({ enabled = true, testid = "install-app-hint" }) {
  const { t } = useTranslation();
  const { canInstall, isIos, isStandalone } = usePwaInstall();
  const [visible, setVisible] = useState(false);

  const dismiss = useCallback(() => {
    try { localStorage.setItem(HINT_KEY, "1"); } catch { /* ignore */ }
    setVisible(false);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (isStandalone) return;
    // Only show if the button itself would render (Android/desktop native prompt available OR iOS instructions).
    if (!canInstall && !isIos) return;
    try {
      if (localStorage.getItem(HINT_KEY) === "1") return;
    } catch { return; }
    setVisible(true);
  }, [enabled, canInstall, isIos, isStandalone]);

  useEffect(() => {
    if (!visible) return;
    // Auto-dismiss the very first time the user taps ANY install-app button
    // (they got the message, we don't need to nag anymore).
    const handler = (e) => {
      const el = e.target?.closest?.("[data-testid$='-install-app']");
      if (el) dismiss();
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, [visible, dismiss]);

  if (!visible) return null;

  return (
    <div
      data-testid={testid}
      role="dialog"
      aria-live="polite"
      className="relative mb-3 bg-gradient-to-br from-[#8B5CF6]/25 to-[#8B5CF6]/5 border border-[#8B5CF6]/50 rounded-lg p-3 text-xs text-white/90 shadow-[0_0_20px_-4px_rgba(139,92,246,0.4)] animate-in fade-in slide-in-from-bottom-2 duration-500"
    >
      <button
        type="button"
        data-testid={`${testid}-close`}
        onClick={dismiss}
        aria-label={t("common.close", "Cerrar")}
        className="absolute top-1.5 right-1.5 text-white/60 hover:text-white transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Sparkles className="w-3.5 h-3.5 text-[#8B5CF6]" />
        <span className="font-semibold text-[#8B5CF6] uppercase tracking-wider text-[0.65rem]">
          {t("pwa.installHint.title", "Nuevo aquí")}
        </span>
      </div>
      <p className="text-white/80 leading-snug mb-2 pr-4">
        {t("pwa.installHint.body", "Instala Resilience en tu pantalla de inicio — se abre como una app nativa, más rápido y sin buscar la URL cada vez.")}
      </p>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1 text-[#8B5CF6]/90 text-[0.65rem]">
          <ArrowDown className="w-3 h-3 animate-bounce" />
          <span>{t("pwa.installHint.arrow", "Toca el botón morado")}</span>
        </div>
        <button
          type="button"
          data-testid={`${testid}-ack`}
          onClick={dismiss}
          className="text-[0.65rem] text-white/70 hover:text-white uppercase tracking-wider font-semibold px-2 py-1 border border-white/20 hover:border-white/40 rounded transition-colors"
        >
          {t("pwa.installHint.ack", "Entendido")}
        </button>
      </div>
    </div>
  );
}
