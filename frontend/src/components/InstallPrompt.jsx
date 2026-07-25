import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, X } from "lucide-react";
import { usePwaInstall } from "@/hooks/usePwaInstall";

/**
 * Auto install prompt banner. Uses the shared usePwaInstall hook so it
 * stays in sync with the manual <InstallAppButton>. Dismiss is persisted
 * for 7 days in localStorage — after that the banner reappears on the
 * next `beforeinstallprompt`.
 */
export default function InstallPrompt() {
  const { t } = useTranslation();
  const { canInstall, isIos, isStandalone, isDismissed, install, dismiss } = usePwaInstall();
  const [iosHint, setIosHint] = useState(false);

  useEffect(() => {
    if (isStandalone || isDismissed || !isIos || canInstall) return;
    const timer = setTimeout(() => setIosHint(true), 4000);
    return () => clearTimeout(timer);
  }, [isStandalone, isDismissed, isIos, canInstall]);

  if (isStandalone || isDismissed) return null;
  if (!canInstall && !iosHint) return null;

  const handleInstall = async () => {
    await install();
  };
  const handleDismiss = () => {
    dismiss();
    setIosHint(false);
  };

  return (
    <div
      data-testid="install-prompt"
      className="fixed bottom-4 left-4 right-4 sm:left-auto sm:bottom-6 sm:right-6 sm:max-w-sm z-50 glass-panel border border-[#8B5CF6]/40 p-4 shadow-2xl"
    >
      <button
        data-testid="install-dismiss"
        onClick={handleDismiss}
        className="absolute top-2 right-2 text-neutral-500 hover:text-white"
        aria-label={t("common.close", "Cerrar")}
      >
        <X className="w-4 h-4" />
      </button>
      <div className="flex items-start gap-3 pr-6">
        <div className="w-10 h-10 bg-[#8B5CF6] flex items-center justify-center font-display text-white shrink-0">RB</div>
        <div className="min-w-0">
          <div className="micro-label text-[#8B5CF6] mb-1">{t("pwa.banner.label", "INSTALAR APP")}</div>
          <p className="text-sm text-white leading-snug">
            {canInstall ? (
              t("pwa.banner.body", "Instala Resilience en tu móvil para acceso instantáneo y notificaciones.")
            ) : (
              <>
                {t("pwa.banner.iosBody", "Toca")}{" "}
                <span className="font-mono">{t("pwa.iosHelp.share", "Compartir")}</span>{" "}→{" "}
                <span className="font-mono">{t("pwa.iosHelp.addToHome", "Añadir a inicio")}</span>{" "}
                {t("pwa.banner.iosBodyEnd", "para usar Resilience como app.")}
              </>
            )}
          </p>
          {canInstall && (
            <button
              data-testid="install-trigger"
              onClick={handleInstall}
              className="mt-3 inline-flex items-center gap-2 bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold px-4 py-2 text-sm"
            >
              <Download className="w-4 h-4" /> {t("pwa.installApp", "Instalar app")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
