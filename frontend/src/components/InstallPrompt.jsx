import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";

/**
 * Install prompt button. Listens for `beforeinstallprompt`, shows a sticky
 * banner so the user can install Resilience Brothers as a PWA.
 * On iOS Safari there's no event, so we show a Safari-specific hint.
 */
export default function InstallPrompt() {
  const [deferred, setDeferred] = useState(null);
  const [show, setShow] = useState(false);
  const [iosHint, setIosHint] = useState(false);

  useEffect(() => {
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
    if (isStandalone) return;
    if (sessionStorage.getItem("rb_install_dismissed") === "1") return;

    const handler = (e) => {
      e.preventDefault();
      setDeferred(e);
      setShow(true);
    };
    window.addEventListener("beforeinstallprompt", handler);

    // iOS detection (Safari has no install event)
    const ua = window.navigator.userAgent;
    const isIos = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
    const isSafari = /^((?!chrome|android).)*safari/i.test(ua);
    if (isIos && isSafari && !isStandalone) {
      // Show iOS hint after a small delay
      const t = setTimeout(() => setIosHint(true), 4000);
      return () => {
        clearTimeout(t);
        window.removeEventListener("beforeinstallprompt", handler);
      };
    }

    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  const install = async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    setDeferred(null);
    setShow(false);
  };

  const dismiss = () => {
    sessionStorage.setItem("rb_install_dismissed", "1");
    setShow(false);
    setIosHint(false);
  };

  if (!show && !iosHint) return null;

  return (
    <div
      data-testid="install-prompt"
      className="fixed bottom-4 left-4 right-4 sm:left-auto sm:bottom-6 sm:right-6 sm:max-w-sm z-50 glass-panel border border-[#EAB308]/40 p-4 shadow-2xl"
    >
      <button
        data-testid="install-dismiss"
        onClick={dismiss}
        className="absolute top-2 right-2 text-neutral-500 hover:text-white"
        aria-label="Cerrar"
      >
        <X className="w-4 h-4" />
      </button>
      <div className="flex items-start gap-3 pr-6">
        <div className="w-10 h-10 bg-[#EAB308] flex items-center justify-center font-display text-black shrink-0">RB</div>
        <div className="min-w-0">
          <div className="micro-label text-[#EAB308] mb-1">INSTALAR APP</div>
          <p className="text-sm text-white leading-snug">
            {iosHint ? (
              <>Toca <span className="font-mono">Compartir</span> → <span className="font-mono">Añadir a pantalla de inicio</span> para usar Resilience como app.</>
            ) : (
              <>Instala Resilience en tu móvil para acceso instantáneo y notificaciones.</>
            )}
          </p>
          {show && !iosHint && (
            <button
              data-testid="install-trigger"
              onClick={install}
              className="mt-3 inline-flex items-center gap-2 bg-[#EAB308] hover:bg-[#FACC15] text-black font-semibold px-4 py-2 text-sm"
            >
              <Download className="w-4 h-4" /> Instalar app
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
