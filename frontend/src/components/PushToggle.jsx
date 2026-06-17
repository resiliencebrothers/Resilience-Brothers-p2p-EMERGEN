import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Bell, BellOff, BellRing } from "lucide-react";
import { toast } from "sonner";

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        setStatus("denied");
        toast.error("Permiso de notificaciones rechazado");
        return;
      }
      const { data } = await axios.get(`${API}/push/vapid-public-key`, { withCredentials: true });
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(data.key),
      });
      await axios.post(`${API}/push/subscribe`, {
        subscription: sub.toJSON(),
        user_agent: navigator.userAgent,
      }, { withCredentials: true });
      setStatus("subscribed");
      toast.success("Notificaciones activadas");
      // Send test notification
      try {
        await axios.post(`${API}/push/test`, {}, { withCredentials: true });
      } catch (err) {
        // eslint-disable-next-line no-console -- benign: first device may not have receivers yet
        console.warn("Push test failed (no devices yet):", err?.response?.status);
      }
    } catch (e) {
      // eslint-disable-next-line no-console -- intentional: surface push setup errors in production
      console.error(e);
      toast.error("Error al activar notificaciones");
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
  const Icon = isOn ? BellRing : status === "denied" ? BellOff : Bell;

  return (
    <button
      data-testid="push-toggle"
      onClick={() => {
        if (status === "denied") {
          toast.error("Las notificaciones están bloqueadas. Habilítalas desde la configuración del navegador.");
          return;
        }
        isOn ? unsubscribe() : subscribe();
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
