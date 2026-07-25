import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Share, Plus, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { usePwaInstall } from "@/hooks/usePwaInstall";

/**
 * Manual "Install app" button — always visible in the client sidebar footer
 * (and admin footer). Complements the auto-triggered <InstallPrompt> banner
 * for users who dismissed it or who are on iOS where the native prompt
 * never fires.
 *
 * Behaviour:
 *   - Chrome/Edge Android/desktop: fires the deferred `beforeinstallprompt`
 *     event when clicked.
 *   - iOS Safari: opens a dialog with visual "Share → Add to Home Screen"
 *     instructions (no native API available).
 *   - Hidden entirely when the PWA is already running in standalone mode.
 */
export default function InstallAppButton({ testid = "install-app-button", compact = false }) {
  const { t } = useTranslation();
  const { canInstall, isIos, isStandalone, install } = usePwaInstall();
  const [showIosHelp, setShowIosHelp] = useState(false);

  if (isStandalone) return null;
  // Hide entirely if neither the native prompt is available nor iOS.
  // This avoids showing a button that does nothing on desktop Firefox etc.
  if (!canInstall && !isIos) return null;

  const handleClick = async () => {
    if (canInstall) {
      await install();
      return;
    }
    if (isIos) {
      setShowIosHelp(true);
    }
  };

  return (
    <>
      <button
        type="button"
        data-testid={testid}
        onClick={handleClick}
        className={
          compact
            ? "flex items-center justify-center gap-2 w-full text-xs text-[#8B5CF6] hover:text-white hover:bg-[#8B5CF6] border border-[#8B5CF6]/40 hover:border-[#8B5CF6] px-3 py-2 transition-colors font-semibold uppercase tracking-wider"
            : "flex items-center justify-center gap-2 w-full text-sm text-[#8B5CF6] hover:text-white hover:bg-[#8B5CF6] border border-[#8B5CF6]/40 hover:border-[#8B5CF6] px-3 py-2 transition-colors font-semibold"
        }
      >
        <Download className="w-4 h-4" />
        {t("pwa.installApp", "Instalar app")}
      </button>

      <Dialog open={showIosHelp} onOpenChange={setShowIosHelp}>
        <DialogContent data-testid="install-ios-help-dialog" className="max-w-sm max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Download className="w-5 h-5 text-[#8B5CF6]" />
              {t("pwa.iosHelp.title", "Instalar en iPhone / iPad")}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t("pwa.iosHelp.description", "Instrucciones para instalar la app en dispositivos Apple.")}
            </DialogDescription>
          </DialogHeader>
          <ol className="space-y-4 text-sm text-neutral-200 mt-2">
            <li className="flex items-start gap-3">
              <span className="w-6 h-6 shrink-0 bg-[#8B5CF6]/20 text-[#8B5CF6] font-bold flex items-center justify-center rounded-full text-xs">1</span>
              <span>
                {t("pwa.iosHelp.step1", "Toca el botón")}{" "}
                <span className="inline-flex items-center gap-1 bg-white/10 px-2 py-0.5 rounded font-mono text-xs">
                  <Share className="w-3 h-3" /> {t("pwa.iosHelp.share", "Compartir")}
                </span>{" "}
                {t("pwa.iosHelp.step1cont", "en la barra de Safari.")}
              </span>
            </li>
            <li className="flex items-start gap-3">
              <span className="w-6 h-6 shrink-0 bg-[#8B5CF6]/20 text-[#8B5CF6] font-bold flex items-center justify-center rounded-full text-xs">2</span>
              <span>
                {t("pwa.iosHelp.step2", "Desliza y selecciona")}{" "}
                <span className="inline-flex items-center gap-1 bg-white/10 px-2 py-0.5 rounded font-mono text-xs">
                  <Plus className="w-3 h-3" /> {t("pwa.iosHelp.addToHome", "Añadir a inicio")}
                </span>.
              </span>
            </li>
            <li className="flex items-start gap-3">
              <span className="w-6 h-6 shrink-0 bg-[#8B5CF6]/20 text-[#8B5CF6] font-bold flex items-center justify-center rounded-full text-xs">3</span>
              <span>{t("pwa.iosHelp.step3", "Toca «Añadir» y encontrarás Resilience en tu pantalla de inicio como una app nativa.")}</span>
            </li>
          </ol>
          <button
            type="button"
            onClick={() => setShowIosHelp(false)}
            data-testid="install-ios-help-close"
            className="mt-4 w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 hover:border-white/30 px-3 py-2 transition-colors"
          >
            <X className="w-4 h-4" /> {t("common.close", "Cerrar")}
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}
