import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft, User as UserIcon, Wallet, TrendingUp, AlertTriangle,
  ShieldCheck, History, HandCoins,
} from "lucide-react";

const fmtNum = (n, digits = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: digits });

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : "—");

const STATUS_META = {
  active: { label: "Activo", cls: "text-emerald-400" },
  under_review: { label: "En revisión", cls: "text-amber-400" },
  blocked: { label: "Bloqueado", cls: "text-red-400" },
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
        toast.error(e.response?.data?.detail || "No se pudieron cargar las estadísticas.");
        if (e.response?.status === 404) navigate("/admin/users");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [userId, navigate]);

  if (loading) {
    return <div className="p-6 text-neutral-500" data-testid="user-stats-loading">Cargando…</div>;
  }
  if (!data) return null;

  const { user, balances, balance_total_usdt, orders, capital, net_position } = data;
  const status = STATUS_META[user.account_status] || STATUS_META.active;
  const netDirection = net_position.direction;

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

      {/* KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
          <div className="text-xs text-neutral-500 mt-1">Desde el alta</div>
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
