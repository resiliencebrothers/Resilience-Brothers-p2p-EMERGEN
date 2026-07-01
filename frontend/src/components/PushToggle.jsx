import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Bell, BellOff, BellRing } from "lucide-react";
import { toast } from "sonner";
import { captureError } from "@/sentry";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
  return out;
}

export default function PushToggle() {
  const [status, setStatus] = useState("loading"); // loading | unsupported | denied | subscribed | unsubscribed
  const [busy, setBusy] = useState(false);

  // One-shot subscription status detection on mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setStatus("unsupported");
      return;
    }
    if (Notification.permission === "denied") {
      setStatus("denied");
      return;
    }
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setStatus(sub ? "subscribed" : "unsubscribed"))
      .catch(() => setStatus("unsubscribed"));
  }, []);

  const subscribe = async () => {
    setBusy(true);
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        toast.error("Tu navegador no soporta notificaciones push");
        setStatus("unsupported");
        return;
      }
      // Some Android browsers only fire the permission prompt if the call
      // originates from a user gesture. This function is invoked via onClick
      // so we're OK, but we still guard against a stale "denied" state.
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        setStatus(perm === "denied" ? "denied" : "unsubscribed");
        toast.error(
          perm === "denied"
            ? "Bloqueaste las notificaciones. Habilítalas en ajustes del navegador."
            : "Permiso de notificaciones no otorgado"
        );
        return;
      }
      let vapidKey;
      try {
        const { data } = await axios.get(
          `${API}/push/vapid-public-key`,
          { withCredentials: true }
        );
        vapidKey = data?.key;
      } catch {
        toast.error("No se pudo obtener la clave VAPID del servidor");
        return;
      }
      if (!vapidKey) {
        toast.error("Servidor sin VAPID configurada. Contacta al administrador.");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      let sub;
      try {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidKey),
        });
      } catch (err) {
        // Common Android error surface — expose the *actual* browser error so
        // the operator can distinguish permission vs. network vs. invalid key.
        const name = err?.name || "Error";
        const msg = err?.message || "desconocido";
        captureError(err, { where: "PushToggle.subscribe.pushManager" });
        if (name === "NotAllowedError") {
          toast.error("Permiso rechazado por el navegador. Revisa ajustes del sitio.");
        } else if (name === "NotSupportedError") {
          toast.error("Push no soportado. Prueba en Chrome/Firefox actualizado.");
        } else if (name === "AbortError") {
          toast.error("Suscripción cancelada. Intenta de nuevo.");
        } else if (name === "InvalidAccessError" || name === "InvalidStateError") {
          toast.error("Clave VAPID inválida. Contacta al administrador.");
        } else {
          toast.error(`Error de push (${name}): ${msg.slice(0, 80)}`);
        }
        return;
      }
      try {
        await axios.post(`${API}/push/subscribe`, {
          subscription: sub.toJSON(),
          user_agent: navigator.userAgent,
        }, { withCredentials: true });
      } catch (err) {
        toast.error("El servidor rechazó la suscripción. Contacta al administrador.");
        // best-effort cleanup: undo the browser subscription so the user can retry
        try { await sub.unsubscribe(); } catch { /* ignore */ }
        captureError(err, { where: "PushToggle.subscribe.serverPost" });
        return;
      }
      setStatus("subscribed");
      toast.success("Notificaciones activadas");
      // Send test notification — non-fatal
      try {
        await axios.post(`${API}/push/test`, {}, { withCredentials: true });
      } catch (err) {
        captureError(err, {
          where: "PushToggle.testNotification",
          status: err?.response?.status,
          level: "info",
        });
      }
    } catch (e) {
      // Catch-all for anything unexpected (e.g. serviceWorker.ready timeout)
      captureError(e, { where: "PushToggle.subscribe.outer" });
      toast.error(`Error inesperado: ${e?.message?.slice(0, 80) || "reintentar"}`);
    } finally {
      setBusy(false);
    }
  };

  const unsubscribe = async () => {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await axios.post(`${API}/push/unsubscribe`, { endpoint: sub.endpoint }, { withCredentials: true });
        await sub.unsubscribe();
      }
      setStatus("unsubscribed");
      toast.success("Notificaciones desactivadas");
    } catch (e) {
      toast.error("Error");
    } finally {
      setBusy(false);
    }
  };

  if (status === "unsupported") return null;

  const isOn = status === "subscribed";
  let Icon = Bell;
  if (isOn) Icon = BellRing;
  else if (status === "denied") Icon = BellOff;

  return (
    <button
      data-testid="push-toggle"
      onClick={() => {
        if (status === "denied") {
          toast.error("Las notificaciones están bloqueadas. Habilítalas desde la configuración del navegador.");
          return;
        }
        if (isOn) {
          unsubscribe();
        } else {
          subscribe();
        }
      }}
      disabled={busy}
      title={isOn ? "Desactivar notificaciones" : "Activar notificaciones"}
      className={`flex items-center gap-2 px-3 py-2 text-sm border transition-colors ${
        isOn
          ? "border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10"
          : "border-white/10 text-neutral-400 hover:border-[#EAB308] hover:text-[#EAB308]"
      }`}
    >
      <Icon className="w-4 h-4" />
      <span className="hidden sm:inline">{isOn ? "Notificaciones" : "Activar avisos"}</span>
    </button>
  );
}
