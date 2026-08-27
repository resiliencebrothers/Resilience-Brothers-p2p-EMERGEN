/**
 * iter196 — Delivery ledger visible per-user for support.
 *
 * The API already exposes `/api/admin/users/:id/email-events` (up to 50
 * events). Previously this info was only surfaced next to the verification
 * badge for `password` + unverified users, which meant support could not
 * diagnose delivery for verified clients (missing withdrawal / deposit /
 * order emails). This section renders the full delivery ledger for any
 * user so anyone in the team can answer "did the email land?".
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { Mail, RefreshCcw, Send } from "lucide-react";
import { toast } from "sonner";
import { API } from "@/App";

const STATUS_TONE = {
  sent:       "text-emerald-400 border-emerald-500/40 bg-emerald-500/5",
  suppressed: "text-neutral-400 border-white/10 bg-white/5",
  failed:     "text-[#EF4444] border-[#EF4444]/40 bg-[#EF4444]/10",
};

const KIND_LABEL = {
  withdrawal_in_progress: "Retiro en proceso",
  withdrawal_paid:        "Retiro exitoso",
  deposit_received:       "Depósito en proceso",
  deposit_confirmed:      "Depósito exitoso",
  deposit_rejected:       "Depósito rechazado",
  capital_deposit_confirmed: "Dep. capital confirmado",
  capital_deposit_rejected:  "Dep. capital rechazado",
  settlement_confirmed:   "Cobro confirmado",
  settlement_rejected:    "Cobro rechazado",
  capital_request_disbursed: "Solicitud capital aprobada",
  capital_request_rejected:  "Solicitud capital rechazada",
  verification:           "Verificación",
  order_approved:         "Orden aprobada",
  order_rejected:         "Orden rechazada",
  password_reset:         "Recuperar contraseña",
};

export default function EmailLedgerSection({ userId }) {
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [retryingId, setRetryingId] = useState(null);

  const load = () => {
    setLoading(true);
    axios
      .get(`${API}/admin/users/${userId}/email-events`, {
        params: { limit: 25 },
        withCredentials: true,
      })
      .then((r) => setData(r.data))
      .catch(() => setData({ email: "", events: [] }))
      .finally(() => setLoading(false));
    axios
      .get(`${API}/admin/email-health`, { withCredentials: true })
      .then((r) => setHealth(r.data))
      .catch(() => setHealth(null));
  };

  useEffect(load, [userId]);

  const resend = async (ev) => {
    if (!ev.id) return;
    setRetryingId(ev.id);
    try {
      await axios.post(`${API}/admin/email-events/${ev.id}/resend`, {},
        { withCredentials: true });
      toast.success("Reintento enviado — refrescando…");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo reintentar");
    } finally {
      setRetryingId(null);
    }
  };

  const events = data?.events || [];

  return (
    <div className="tactile-card p-5" data-testid="user-stats-email-ledger">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <h2 className="font-display text-xl flex items-center gap-2">
          <Mail className="w-5 h-5 text-[#8B5CF6]" /> Historial de correos enviados
        </h2>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          data-testid="email-ledger-refresh"
          className="text-[0.65rem] uppercase tracking-widest px-3 py-1 border border-white/10 hover:border-white/30 text-neutral-400 hover:text-white transition-all inline-flex items-center gap-1"
        >
          <RefreshCcw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          Refrescar
        </button>
      </div>

      {health && (!health.send_enabled || !health.api_key_set) && (
        <div
          className="mb-4 border border-[#EF4444]/40 bg-[#EF4444]/10 px-4 py-3 text-sm text-[#FCA5A5]"
          data-testid="email-health-warning"
        >
          <strong className="text-[#EF4444]">⚠ El envío real de correos está DESACTIVADO en este servidor.</strong>{" "}
          {!health.api_key_set
            ? "Falta la variable de entorno RESEND_API_KEY — ningún correo puede salir."
            : "La variable de entorno EMAIL_SEND_ENABLED está en false — los correos se registran como \"suppressed\" pero nunca se envían."}{" "}
          Corrige la variable en el panel de despliegue y vuelve a desplegar.
        </div>
      )}
      {health && health.send_enabled && health.api_key_set && (
        <div
          className="mb-4 text-[0.65rem] text-neutral-500 font-mono"
          data-testid="email-health-ok"
        >
          Envío real: <span className="text-emerald-400">ACTIVO</span> · últimos 7 días:{" "}
          <span className="text-emerald-400">{health.counts_7d?.sent ?? 0} enviados</span> ·{" "}
          <span className="text-[#EF4444]">{health.counts_7d?.failed ?? 0} fallidos</span> ·{" "}
          <span className="text-neutral-400">{health.counts_7d?.suppressed ?? 0} suprimidos</span>
        </div>
      )}

      {loading && !data ? (
        <div className="text-sm text-neutral-500">Cargando…</div>
      ) : events.length === 0 ? (
        <div className="text-sm text-neutral-500 py-6 text-center border border-white/5 bg-[#0a0a0a]">
          Aún no le hemos enviado ningún correo (o no hay registros en el ledger).
        </div>
      ) : (
        <div className="space-y-2">
          {events.map((ev, i) => {
            const tone = STATUS_TONE[ev.status] || STATUS_TONE.suppressed;
            const label = KIND_LABEL[ev.kind] || ev.kind || "email";
            const canResend = ev.can_resend && ev.status !== "suppressed";
            const isRetrying = retryingId === ev.id;
            return (
              <div
                key={`${ev.created_at}-${i}`}
                className="border border-white/5 bg-[#0a0a0a] px-3 py-2 flex items-start justify-between gap-3 flex-wrap"
                data-testid={`email-ledger-row-${i}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-neutral-300 truncate" title={ev.subject}>
                    {ev.subject}
                  </div>
                  <div className="text-[0.65rem] text-neutral-500 font-mono mt-1 flex items-center gap-2 flex-wrap">
                    <span className="text-[#8B5CF6]">{label}</span>
                    <span className="text-neutral-600">·</span>
                    <time className="tabular-nums">{new Date(ev.created_at).toLocaleString()}</time>
                    {ev.attempts > 1 && (
                      <>
                        <span className="text-neutral-600">·</span>
                        <span>{ev.attempts} intentos</span>
                      </>
                    )}
                  </div>
                  {ev.status === "failed" && ev.error && (
                    <div className="text-[0.65rem] text-[#EF4444] mt-1 font-mono break-all">
                      {ev.error}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {canResend && (
                    <button
                      type="button"
                      onClick={() => resend(ev)}
                      disabled={isRetrying}
                      data-testid={`email-ledger-resend-${i}`}
                      className={
                        "text-[0.6rem] uppercase tracking-widest px-2 py-1 border font-mono inline-flex items-center gap-1 transition-all " +
                        (ev.status === "failed"
                          ? "border-[#EF4444]/40 hover:border-[#EF4444] hover:bg-[#EF4444]/10 text-[#EF4444]"
                          : "border-white/10 hover:border-white/30 text-neutral-400 hover:text-white")
                      }
                      title="Reenviar este correo (mismo destinatario, mismo cuerpo)"
                    >
                      <Send className={`w-3 h-3 ${isRetrying ? "animate-pulse" : ""}`} />
                      {isRetrying ? "…" : "Reenviar"}
                    </button>
                  )}
                  <span
                    className={`text-[0.6rem] uppercase tracking-widest px-2 py-1 border font-mono ${tone}`}
                    data-testid={`email-ledger-status-${i}`}
                  >
                    {ev.status}
                  </span>
                </div>
              </div>
            );
          })}
          <div className="text-[0.65rem] text-neutral-600 mt-2">
            Mostrando {events.length} evento{events.length === 1 ? "" : "s"} más recientes.{" "}
            <span className="text-neutral-500">
              (<code className="text-neutral-400">sent</code> = Resend aceptó ·{" "}
              <code className="text-neutral-400">suppressed</code> = envío desactivado (dev) ·{" "}
              <code className="text-neutral-400">failed</code> = error, ver detalle)
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
