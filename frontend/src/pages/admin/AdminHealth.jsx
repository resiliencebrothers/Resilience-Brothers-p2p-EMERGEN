import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, Database, ExternalLink, ServerCog,
  ShieldAlert, ShieldCheck, TrendingUp, Users, Inbox, Bug,
  CloudOff, CloudCheck, Clock, ShieldX,
} from "lucide-react";
import { Button } from "@/components/ui/button";

/* -------------------- micro-components -------------------- */

const StatCard = ({ icon: Icon, label, value, sub, tone = "default", testid, action }) => {
  const toneClass = {
    default: "border-white/10",
    danger: "border-red-500/40 bg-red-500/5",
    warn: "border-amber-500/40 bg-amber-500/5",
    ok: "border-emerald-500/30 bg-emerald-500/5",
  }[tone];
  return (
    <div data-testid={testid} className={`p-5 border ${toneClass} space-y-1`}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-neutral-400">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="font-display text-3xl text-white">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
};

const Section = ({ title, children, action }) => (
  <section className="space-y-4">
    <div className="flex items-end justify-between">
      <h2 className="font-display text-lg text-[#EAB308]">{title}</h2>
      {action}
    </div>
    {children}
  </section>
);

/* -------------------- main page -------------------- */

export default function AdminHealth() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/health/summary`, { withCredentials: true });
      setData(r.data);
      setRefreshedAt(new Date());
    } catch (e) {
      toast.error(e?.response?.data?.detail || "No se pudo cargar el dashboard");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
    const id = setInterval(load, 60_000); // auto-refresh cada minuto
    return () => clearInterval(id);
  }, []);

  if (loading && !data) {
    return (
      <div data-testid="admin-health-loading" className="text-neutral-400">
        Cargando dashboard de salud...
      </div>
    );
  }
  if (!data) return null;

  const s = data;
  const peakHour = (s.throughput.hourly_24h || []).reduce(
    (best, cur) => (cur.count > best.count ? cur : best),
    { hour: "—", count: 0 },
  );

  return (
    <div data-testid="admin-health-page" className="space-y-10 max-w-7xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-white">Dashboard de Salud</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Una sola vista del estado operativo. Actualiza cada 60 s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {refreshedAt && (
            <span className="text-xs text-neutral-500">
              Actualizado: {refreshedAt.toLocaleTimeString()}
            </span>
          )}
          <Button
            data-testid="admin-health-refresh"
            onClick={load}
            disabled={loading}
            variant="outline"
            className="border-white/10 hover:bg-white/5"
          >
            {loading ? "..." : "Recargar"}
          </Button>
        </div>
      </div>

      {/* Alertas críticas */}
      {(s.defensive_mode.enabled || s.negative_margin.count > 0) && (
        <Section title="Alertas activas">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {s.defensive_mode.enabled && (
              <StatCard
                testid="health-defensive-on"
                icon={ShieldAlert}
                label="Modo defensivo ACTIVO"
                value="Plataforma cerrada"
                sub={`Activado por ${s.defensive_mode.enabled_by_email || "—"}. Razón: ${
                  s.defensive_mode.reason || "(sin razón)"
                }`}
                tone="danger"
              />
            )}
            {s.negative_margin.count > 0 && (
              <StatCard
                testid="health-negative-margin"
                icon={AlertTriangle}
                label="Órdenes con margen negativo"
                value={s.negative_margin.count}
                sub={`Top: ${s.negative_margin.items[0]?.pair || "—"} → pérdida ${
                  s.negative_margin.items[0]?.loss_amount?.toLocaleString() || "0"
                } ${s.negative_margin.items[0]?.loss_currency || ""}`}
                tone="warn"
                action={
                  <a
                    href="/admin/orders"
                    className="text-xs text-[#EAB308] hover:underline inline-flex items-center gap-1"
                    data-testid="health-go-to-orders"
                  >
                    Revisar órdenes <ExternalLink className="w-3 h-3" />
                  </a>
                }
              />
            )}
          </div>
        </Section>
      )}

      {/* Estado de servicios */}
      <Section title="Servicios externos">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <StatCard
            testid="health-sentry"
            icon={Bug}
            label="Sentry (monitoring)"
            value={s.sentry.enabled ? "ACTIVO" : "OFF"}
            sub={
              s.sentry.enabled
                ? `${s.sentry.local_errors_recent} errores locales (últ. 2k líneas) · env=${s.sentry.environment}`
                : "Configura SENTRY_DSN para activar"
            }
            tone={s.sentry.enabled ? "ok" : "default"}
            action={
              s.sentry.enabled && (
                <a
                  href={s.sentry.deep_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-[#EAB308] hover:underline inline-flex items-center gap-1"
                  data-testid="health-open-sentry"
                >
                  Abrir Sentry <ExternalLink className="w-3 h-3" />
                </a>
              )
            }
          />
          <StatCard
            testid="health-storage"
            icon={s.storage.enabled ? CloudCheck : CloudOff}
            label="Object Storage"
            value={s.storage.enabled ? s.storage.provider.toUpperCase() : "OFF"}
            sub={
              s.storage.enabled
                ? `${s.storage.object_count} archivos · ${s.storage.size_gb} GB · ~$${s.storage.monthly_cost_usd}/mes`
                : "Configura STORAGE_PROVIDER + creds para activar"
            }
            tone={s.storage.enabled ? "ok" : "default"}
          />
          <StatCard
            testid="health-defensive-card"
            icon={s.defensive_mode.enabled ? ShieldAlert : ShieldCheck}
            label="Modo defensivo"
            value={s.defensive_mode.enabled ? "ACTIVO" : "OFF"}
            sub={
              s.defensive_mode.enabled
                ? `Activado: ${s.defensive_mode.enabled_at?.slice(0, 19) || "—"}`
                : "Plataforma operando normalmente"
            }
            tone={s.defensive_mode.enabled ? "danger" : "ok"}
          />
        </div>
        {s.storage.enabled && s.storage.by_folder?.length > 0 && (
          <div className="border border-white/5 p-4 mt-4" data-testid="health-storage-folders">
            <div className="text-xs uppercase tracking-wider text-neutral-400 mb-3">
              Desglose por carpeta
            </div>
            <div className="space-y-2">
              {s.storage.by_folder.map((f) => (
                <div key={f.folder} className="flex items-center justify-between text-sm">
                  <span className="text-neutral-300 font-mono">{f.folder}/</span>
                  <span className="text-neutral-500">
                    {f.count} archivos · {f.size_mb} MB
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Throughput */}
      <Section title="Volumen P2P">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            testid="health-orders-1h"
            icon={Activity}
            label="Última hora"
            value={s.throughput.orders_last_1h}
            sub="órdenes nuevas"
          />
          <StatCard
            testid="health-orders-24h"
            icon={TrendingUp}
            label="Últ. 24 h"
            value={s.throughput.orders_last_24h}
            sub={`pico: ${peakHour.hour} (${peakHour.count})`}
          />
          <StatCard
            testid="health-orders-7d"
            icon={Activity}
            label="Últ. 7 días"
            value={s.throughput.orders_last_7d}
            sub="órdenes nuevas"
          />
          <StatCard
            testid="health-orders-total"
            icon={Database}
            label="Total histórico"
            value={s.platform.orders_total.toLocaleString()}
            sub={`${s.platform.orders_approved} aprob. · ${s.platform.orders_rejected} rech.`}
          />
        </div>
      </Section>

      {/* Colas de trabajo */}
      <Section title="Colas pendientes">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard
            testid="health-queue-orders"
            icon={Inbox}
            label="Órdenes pendientes"
            value={s.queues.pending_orders}
            tone={s.queues.pending_orders > 10 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-double"
            icon={ShieldAlert}
            label="Doble aprobación"
            value={s.queues.pending_double_approval}
            tone={s.queues.pending_double_approval > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-withdrawals"
            icon={Inbox}
            label="Retiros pendientes"
            value={s.queues.pending_withdrawals}
            tone={s.queues.pending_withdrawals > 5 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-phone"
            icon={Users}
            label="Verificar teléfono"
            value={s.queues.pending_phone_verifications}
            tone={s.queues.pending_phone_verifications > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-blocklist"
            icon={ShieldCheck}
            label="Bloqueados"
            value={s.queues.blocked_contacts}
            sub="anti-scam list"
          />
        </div>
      </Section>

      {/* Plataforma */}
      <Section title="Usuarios">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            testid="health-users-total"
            icon={Users}
            label="Total"
            value={s.platform.users_total}
          />
          <StatCard
            testid="health-users-active"
            icon={Users}
            label="Activos"
            value={s.platform.users_active}
            tone="ok"
          />
          <StatCard
            testid="health-users-review"
            icon={Users}
            label="En revisión"
            value={s.platform.users_under_review}
            tone={s.platform.users_under_review > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-users-blocked"
            icon={ShieldAlert}
            label="Bloqueados"
            value={s.platform.users_blocked}
            tone={s.platform.users_blocked > 0 ? "danger" : "default"}
          />
        </div>
      </Section>

      {/* Anti-scam analytics (iter46) */}
      {s.anti_scam && !s.anti_scam.error && (
        <Section title="Anti-fraude · revisión de cuentas">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard
              testid="health-antiscam-queue"
              icon={ShieldX}
              label="Bajo revisión ahora"
              value={s.anti_scam.users_under_review}
              sub="cola de phone-verify"
              tone={s.anti_scam.users_under_review > 5 ? "warn" : "default"}
            />
            <StatCard
              testid="health-antiscam-avg-hours"
              icon={Clock}
              label="Tiempo medio resolución"
              value={
                s.anti_scam.avg_resolution_hours == null
                  ? "—"
                  : `${s.anti_scam.avg_resolution_hours} h`
              }
              sub={
                s.anti_scam.avg_resolution_hours == null
                  ? "sin casos resueltos aún"
                  : `${s.anti_scam.resolved_count} casos resueltos`
              }
              tone={
                s.anti_scam.avg_resolution_hours != null
                && s.anti_scam.avg_resolution_hours > 24
                  ? "warn"
                  : "default"
              }
            />
            <StatCard
              testid="health-antiscam-oldest"
              icon={AlertTriangle}
              label="Ticket más antiguo"
              value={
                s.anti_scam.oldest_pending_hours == null
                  ? "—"
                  : `${s.anti_scam.oldest_pending_hours} h`
              }
              sub="lleva esperando"
              tone={
                s.anti_scam.oldest_pending_hours != null
                && s.anti_scam.oldest_pending_hours > 48
                  ? "danger"
                  : s.anti_scam.oldest_pending_hours != null
                    && s.anti_scam.oldest_pending_hours > 24
                    ? "warn"
                    : "default"
              }
            />
            <StatCard
              testid="health-antiscam-resolved"
              icon={ShieldCheck}
              label="Resueltos histórico"
              value={s.anti_scam.resolved_count}
              sub="contribuyen al promedio"
              tone="ok"
            />
          </div>
        </Section>
      )}

      {/* Tabla margen negativo */}
      {s.negative_margin.count > 0 && (
        <Section title={`Órdenes con margen negativo (${s.negative_margin.count})`}>
          <div className="border border-white/10 overflow-x-auto">
            <table className="w-full text-sm" data-testid="health-margin-table">
              <thead className="bg-white/5 text-xs uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="text-left p-3">ID</th>
                  <th className="text-left p-3">Cliente</th>
                  <th className="text-left p-3">Par</th>
                  <th className="text-right p-3">Pérdida</th>
                  <th className="text-right p-3">% pérdida</th>
                  <th className="text-left p-3">Estado</th>
                </tr>
              </thead>
              <tbody>
                {s.negative_margin.items.map((it) => (
                  <tr key={it.id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="p-3 text-neutral-500 font-mono text-xs">{it.id.slice(0, 8)}</td>
                    <td className="p-3 text-neutral-300">{it.user_name}</td>
                    <td className="p-3 font-mono text-xs">{it.pair}</td>
                    <td className="p-3 text-right text-red-400 font-medium">
                      {it.loss_amount.toLocaleString()} {it.loss_currency}
                    </td>
                    <td className="p-3 text-right text-red-400">{it.loss_pct}%</td>
                    <td className="p-3 text-neutral-500 text-xs">{it.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {s.negative_margin.count > 20 && (
            <p className="text-xs text-neutral-500">
              Mostrando los primeros 20. Total: {s.negative_margin.count}.
            </p>
          )}
        </Section>
      )}

      <p className="text-xs text-neutral-600 text-right">
        Snapshot generado: {new Date(s.generated_at).toLocaleString()}
      </p>
    </div>
  );
}
