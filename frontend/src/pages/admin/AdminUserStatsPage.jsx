import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft, User as UserIcon, Wallet, TrendingUp, AlertTriangle,
  ShieldCheck, History, HandCoins, Mail, Phone, IdCard, Percent, Star,
  CheckCircle2, XCircle, Clock, ScrollText,
} from "lucide-react";

const fmtNum = (n, digits = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: digits });

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : "—");

const STATUS_META = {
  active: { label: "Activo", cls: "text-emerald-400" },
  under_review: { label: "En revisión", cls: "text-amber-400" },
  blocked: { label: "Bloqueado", cls: "text-red-400" },
};

const KYC_META = {
  approved:    { label: "Aprobado",   cls: "text-emerald-400", icon: CheckCircle2 },
  pending:     { label: "Pendiente",  cls: "text-amber-400",   icon: Clock },
  rejected:    { label: "Rechazado",  cls: "text-red-400",     icon: XCircle },
  not_started: { label: "Sin iniciar",cls: "text-neutral-500", icon: IdCard },
};

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff",
  admin: "Admin",
};

/**
 * iter55.32 — Admin/staff drill-down for one specific user. Reachable from
 * the "Ver estadísticas" button in AdminUsers row. Uses the new
 * `/api/admin/users/{id}/stats` aggregate endpoint.
 */
export default function AdminUserStatsPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  // iter55.34 — audit trail (loaded in parallel, non-blocking)
  const [trail, setTrail] = useState(null);
  const [trailDays, setTrailDays] = useState(30);
  const [trailLoading, setTrailLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await axios.get(`${API}/admin/users/${userId}/stats`, {
          withCredentials: true,
        });
        if (!cancelled) setData(r.data);
      } catch (e) {
        const status = e.response?.status;
        const detail = e.response?.data?.detail;
        if (status === 403) {
          toast.error(typeof detail === "string"
            ? detail
            : "Acceso restringido — pídele a un admin el permiso 'Estadísticas de usuario'.");
        } else if (status === 404) {
          toast.error(typeof detail === "string" ? detail : "Usuario no encontrado.");
        } else {
          toast.error(typeof detail === "string" ? detail : "No se pudieron cargar las estadísticas.");
        }
        navigate("/admin/users");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [userId, navigate]);

  // iter55.34 — audit trail fetch. Runs in parallel with the stats block
  // so the main page renders even if this call is slow.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setTrailLoading(true);
      try {
        const r = await axios.get(
          `${API}/admin/users/${userId}/audit-trail`,
          { params: { days: trailDays, limit: 100 }, withCredentials: true },
        );
        if (!cancelled) setTrail(r.data);
      } catch (e) {
        // Same permission gate as the stats endpoint — if the stats call
        // succeeded, this one should too. Silently no-op on 403.
        if (e.response?.status !== 403 && !cancelled) {
          setTrail({ entries: [], total: 0, window_days: trailDays });
        }
      } finally {
        if (!cancelled) setTrailLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [userId, trailDays]);

  if (loading) {
    return <div className="p-6 text-neutral-500" data-testid="user-stats-loading">Cargando…</div>;
  }
  if (!data) return null;

  const { user, kyc, balances, balance_total_usdt, orders, capital, net_position } = data;
  const status = STATUS_META[user.account_status] || STATUS_META.active;
  const netDirection = net_position.direction;
  const kycMeta = KYC_META[kyc?.status || "not_started"] || KYC_META.not_started;
  const KycIcon = kycMeta.icon;

  return (
    <div className="space-y-6" data-testid="admin-user-stats-page">
      <div>
        <button
          onClick={() => navigate("/admin/users")}
          data-testid="user-stats-back-btn"
          className="text-xs uppercase tracking-widest text-neutral-500 hover:text-[#8B5CF6] flex items-center gap-2 mb-3"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Volver a Usuarios
        </button>
        <div className="micro-label text-[#8B5CF6] mb-2">/ Estadísticas del usuario</div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-3xl">{user.name || "(sin nombre)"}</h1>
            <div className="text-sm text-neutral-400 mt-1">
              {user.email}
              {user.phone ? ` · ${user.phone}` : ""}
            </div>
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="border border-white/10 px-2 py-0.5 uppercase tracking-widest text-white/70">
                {ROLE_LABELS[user.role] || user.role}
              </span>
              <span className={`border border-white/10 px-2 py-0.5 uppercase tracking-widest ${status.cls}`}>
                {status.label}
              </span>
              <span className="text-neutral-600">alta {fmtDate(user.created_at)}</span>
            </div>
          </div>
          <UserIcon className="w-12 h-12 text-[#8B5CF6]/40" />
        </div>
      </div>

      {/* NET POSITION HERO */}
      <div className="tactile-card p-6" data-testid="user-stats-net-position">
        <div className="micro-label text-neutral-500 mb-2">Posición neta empresa ↔ cliente</div>
        {netDirection === "platform_owes_client" && (
          <>
            <div className="font-display text-4xl text-emerald-400 tabular-nums">
              +{fmtNum(net_position.net_usdt, 2)} USDT
            </div>
            <div className="text-sm text-neutral-400 mt-1">
              La empresa <strong className="text-emerald-400">le debe</strong> este monto al cliente
              (saldo acumulado {fmtNum(net_position.platform_owes_client_usdt, 2)} USDT − deuda pendiente {fmtNum(net_position.client_owes_platform_usdt, 2)} USDT).
            </div>
          </>
        )}
        {netDirection === "client_owes_platform" && (
          <>
            <div className="font-display text-4xl text-red-400 tabular-nums">
              −{fmtNum(Math.abs(net_position.net_usdt), 2)} USDT
            </div>
            <div className="text-sm text-neutral-400 mt-1">
              El cliente <strong className="text-red-400">le debe</strong> este monto a la empresa
              (deuda por capital operativo {fmtNum(net_position.client_owes_platform_usdt, 2)} USDT − saldo acumulado {fmtNum(net_position.platform_owes_client_usdt, 2)} USDT).
            </div>
          </>
        )}
        {netDirection === "even" && (
          <>
            <div className="font-display text-4xl text-neutral-400 tabular-nums">
              0.00 USDT
            </div>
            <div className="text-sm text-neutral-500 mt-1">
              Cuentas equilibradas — sin saldo pendiente en ningún sentido.
            </div>
          </>
        )}
      </div>

      {/* PERSONAL INFO + KYC (iter55.33) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="user-stats-personal">
        <div className="tactile-card p-5 lg:col-span-2">
          <div className="micro-label text-neutral-500 mb-3">Datos personales</div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="flex items-center gap-2">
              <Mail className="w-4 h-4 text-neutral-500 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-xs text-neutral-500">Email</div>
                <div className="truncate">{user.email}</div>
                {user.email_verified ? (
                  <div className="text-[0.65rem] text-emerald-400 mt-0.5">✓ Verificado</div>
                ) : (
                  <div className="text-[0.65rem] text-amber-400 mt-0.5">⧗ No verificado</div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Phone className="w-4 h-4 text-neutral-500 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-xs text-neutral-500">Teléfono</div>
                <div className="truncate font-mono">{user.phone || "— sin registrar —"}</div>
                {user.phone && (
                  user.phone_verified ? (
                    <div className="text-[0.65rem] text-emerald-400 mt-0.5">✓ Verificado</div>
                  ) : (
                    <div className="text-[0.65rem] text-amber-400 mt-0.5">⧗ Pendiente</div>
                  )
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-neutral-500 shrink-0" />
              <div>
                <div className="text-xs text-neutral-500">Autenticación 2FA</div>
                <div>
                  {user.twofa_enabled ? (
                    <span className="text-emerald-400 text-xs">✓ Activada</span>
                  ) : (
                    <span className="text-amber-400 text-xs">⧗ Desactivada</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <UserIcon className="w-4 h-4 text-neutral-500 shrink-0" />
              <div>
                <div className="text-xs text-neutral-500">Rol</div>
                <div>{ROLE_LABELS[user.role] || user.role}</div>
              </div>
            </div>
          </div>
        </div>
        <div className="tactile-card p-5" data-testid="user-stats-kyc">
          <div className="micro-label text-neutral-500 mb-3 flex items-center gap-2">
            <IdCard className="w-3.5 h-3.5" /> Verificación KYC
          </div>
          <div className={`flex items-center gap-2 ${kycMeta.cls}`}>
            <KycIcon className="w-5 h-5" />
            <span className="font-display text-xl">{kycMeta.label}</span>
          </div>
          {kyc?.submitted_at && (
            <div className="text-xs text-neutral-500 mt-3">
              Enviado: {fmtDate(kyc.submitted_at)}
            </div>
          )}
          {kyc?.reviewed_at && (
            <div className="text-xs text-neutral-500 mt-1">
              Revisado: {fmtDate(kyc.reviewed_at)}
            </div>
          )}
          {kyc?.reviewer_notes && (
            <div className="text-xs text-neutral-400 mt-2 border-l-2 border-white/10 pl-2 italic">
              {kyc.reviewer_notes}
            </div>
          )}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="tactile-card p-5" data-testid="user-stats-kpi-total-balance">
          <div className="flex items-center gap-2 mb-2">
            <Wallet className="w-4 h-4 text-[#8B5CF6]" />
            <div className="micro-label text-neutral-500">Saldo total</div>
          </div>
          <div className="font-display text-3xl tabular-nums">{fmtNum(balance_total_usdt, 2)}</div>
          <div className="text-xs text-neutral-500 mt-1">USDT equivalente</div>
        </div>
        <div className="tactile-card p-5" data-testid="user-stats-kpi-orders-30d">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-[#8B5CF6]" />
            <div className="micro-label text-neutral-500">Volumen 30 días</div>
          </div>
          <div className="font-display text-3xl tabular-nums">
            {fmtNum(orders.volume_last_30d_usdt, 2)}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            USDT · {orders.count_last_30d} órdenes
          </div>
        </div>
        <div className="tactile-card p-5" data-testid="user-stats-kpi-total-orders">
          <div className="flex items-center gap-2 mb-2">
            <History className="w-4 h-4 text-[#8B5CF6]" />
            <div className="micro-label text-neutral-500">Órdenes totales</div>
          </div>
          <div className="font-display text-3xl tabular-nums">{orders.total_lifetime}</div>
          <div className="text-xs text-neutral-500 mt-1">
            {orders.success_count || 0} exitosas
          </div>
        </div>
        <div className="tactile-card p-5" data-testid="user-stats-kpi-success-rate">
          <div className="flex items-center gap-2 mb-2">
            <Percent className="w-4 h-4 text-[#8B5CF6]" />
            <div className="micro-label text-neutral-500">Éxito operativo</div>
          </div>
          <div className="font-display text-3xl tabular-nums">
            {orders.success_rate_pct ?? 0}<span className="text-lg text-neutral-500">%</span>
          </div>
          <div className="text-xs text-neutral-500 mt-1">Aprobadas + completadas</div>
        </div>
        <div className="tactile-card p-5" data-testid="user-stats-kpi-favorite-currency">
          <div className="flex items-center gap-2 mb-2">
            <Star className="w-4 h-4 text-[#8B5CF6]" />
            <div className="micro-label text-neutral-500">Moneda favorita</div>
          </div>
          <div className="font-display text-3xl tabular-nums">
            {orders.favorite_currency || "—"}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {orders.favorite_currency_count
              ? `${orders.favorite_currency_count} apariciones`
              : "sin datos"}
          </div>
        </div>
      </div>

      {/* BALANCE BREAKDOWN */}
      <div className="tactile-card p-5">
        <h2 className="font-display text-xl mb-4 flex items-center gap-2">
          <Wallet className="w-5 h-5 text-[#8B5CF6]" /> Saldo por moneda
        </h2>
        {Object.keys(balances || {}).length === 0 ? (
          <div className="text-sm text-neutral-500">Sin saldo acumulado en ninguna moneda.</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="user-stats-balances-grid">
            {Object.entries(balances).map(([code, amount]) => (
              <div
                key={code}
                className="border border-white/10 p-3"
                data-testid={`user-stats-balance-${code}`}
              >
                <div className="micro-label text-neutral-500">{code}</div>
                <div className="font-display text-2xl tabular-nums mt-1">
                  {fmtNum(amount, 4)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CAPITAL DEBTS */}
      <div className="tactile-card p-5" data-testid="user-stats-capital-section">
        <h2 className="font-display text-xl mb-4 flex items-center gap-2">
          <HandCoins className="w-5 h-5 text-[#8B5CF6]" /> Solicitudes de capital activas
        </h2>
        {capital.active_requests.length === 0 ? (
          <div className="text-sm text-neutral-500">
            Este cliente no tiene deudas de capital operativo pendientes.
          </div>
        ) : (
          <>
            <div className="text-sm text-neutral-400 mb-4">
              Total pendiente:{" "}
              <span className="text-red-400 tabular-nums">
                {fmtNum(capital.total_debt_usdt, 2)} USDT
              </span>
            </div>
            <div className="space-y-3">
              {capital.active_requests.map((cr) => {
                const paidPct = cr.debt_original
                  ? Math.round(((cr.debt_original - cr.debt_remaining) / cr.debt_original) * 100)
                  : 0;
                return (
                  <div
                    key={cr.id}
                    className="border border-white/10 p-4"
                    data-testid={`user-stats-capital-${cr.id}`}
                  >
                    <div className="flex items-start justify-between flex-wrap gap-2">
                      <div>
                        <div className="font-mono text-sm">
                          {fmtNum(cr.debt_remaining, 2)} / {fmtNum(cr.debt_original, 2)} {cr.currency_code}
                        </div>
                        <div className="text-xs text-neutral-500 mt-1">
                          {cr.reason} · Desembolsado {fmtDate(cr.disbursed_at)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-neutral-500">Descuento por orden</div>
                        <div className="font-mono text-[#8B5CF6]">{cr.discount_pct}%</div>
                      </div>
                    </div>
                    <div className="mt-3 h-1.5 bg-white/5">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${paidPct}%` }}
                      />
                    </div>
                    <div className="text-[0.65rem] text-neutral-500 mt-1 uppercase tracking-widest">
                      {paidPct}% devuelto
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* AUDIT TRAIL (iter55.34) */}
      <div className="tactile-card p-5" data-testid="user-stats-audit-trail">
        <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
          <h2 className="font-display text-xl flex items-center gap-2">
            <ScrollText className="w-5 h-5 text-[#8B5CF6]" /> Historial de cambios
          </h2>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex gap-1" role="tablist" aria-label="Ventana temporal">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setTrailDays(d)}
                  data-testid={`audit-trail-window-${d}`}
                  className={
                    "text-[0.65rem] uppercase tracking-widest px-3 py-1 border transition-all " +
                    (trailDays === d
                      ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-[#8B5CF6]"
                      : "border-white/10 text-neutral-500 hover:text-white hover:border-white/20")
                  }
                >
                  {d}d
                </button>
              ))}
            </div>
            <button
              onClick={() => navigate(`/admin/audit?tab=by-user&user_id=${userId}`)}
              data-testid="audit-trail-open-in-audit"
              className="text-[0.65rem] uppercase tracking-widest px-3 py-1 border border-emerald-500/40 hover:border-emerald-500 hover:bg-emerald-500/10 text-emerald-400 transition-all"
              title="Abrir esta trazabilidad en el módulo global de Auditoría"
            >
              Abrir en Auditoría →
            </button>
          </div>
        </div>
        {trailLoading && !trail ? (
          <div className="text-sm text-neutral-500">Cargando historial…</div>
        ) : !trail || trail.entries.length === 0 ? (
          <div className="text-sm text-neutral-500 py-6 text-center border border-white/5 bg-[#0a0a0a]">
            Sin cambios registrados en los últimos {trailDays} días.
          </div>
        ) : (
          <>
            <div className="text-xs text-neutral-500 mb-3">
              {trail.total} evento{trail.total === 1 ? "" : "s"} en los últimos {trail.window_days} días
              {trail.entries.length === 100 ? " (mostrando los 100 más recientes)" : ""}
            </div>
            <ol className="relative border-l border-white/10 ml-2 space-y-4">
              {trail.entries.map((e) => {
                const isAdminActor = e.actor_role === "admin";
                const dotCls = isAdminActor ? "bg-[#8B5CF6]" : "bg-emerald-500";
                return (
                  <li
                    key={e.id}
                    className="ml-4"
                    data-testid={`audit-trail-entry-${e.id}`}
                  >
                    <span className={`absolute -left-[5px] w-2.5 h-2.5 rounded-full ${dotCls}`} />
                    <div className="flex items-baseline justify-between gap-2 flex-wrap">
                      <div className="font-medium text-sm">
                        {e.summary || e.action}
                      </div>
                      <time className="text-[0.65rem] text-neutral-500 whitespace-nowrap tabular-nums">
                        {new Date(e.created_at).toLocaleString()}
                      </time>
                    </div>
                    <div className="text-xs text-neutral-500 mt-1 flex items-center gap-2 flex-wrap">
                      <span className={isAdminActor ? "text-[#8B5CF6]" : "text-emerald-400"}>
                        {e.actor_name || e.actor_email || "sistema"}
                      </span>
                      <span className="text-neutral-600">·</span>
                      <span className="font-mono text-[0.65rem] uppercase tracking-widest text-neutral-500">
                        {e.action}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </div>

      {/* QUICK ACTIONS */}
      <div className="flex gap-2 flex-wrap">
        <Button
          onClick={() => navigate("/admin/users")}
          className="rounded-none bg-transparent border border-white/15 text-white hover:bg-white/5"
          data-testid="user-stats-goto-users-btn"
        >
          <ArrowLeft className="w-4 h-4 mr-2" /> Lista de usuarios
        </Button>
        <Button
          onClick={() => navigate("/admin/company-funds?tab=requests")}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
          data-testid="user-stats-goto-requests-btn"
        >
          <ShieldCheck className="w-4 h-4 mr-2" /> Ver todas las solicitudes de capital
        </Button>
      </div>

      {net_position.net_usdt < 0 && (
        <div className="border-l-4 border-amber-500 bg-amber-500/5 p-4 flex gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-200/90">
            Este cliente <strong>tiene deuda pendiente</strong> con la empresa. Sus próximas
            órdenes acumuladas se descontarán automáticamente según el porcentaje configurado
            en cada solicitud hasta cerrar el balance.
          </div>
        </div>
      )}
    </div>
  );
}
