import { History, Percent, Star, TrendingUp, Wallet } from "lucide-react";
import { fmtNum } from "./userStatsMeta";

export default function UserStatsKpis({ orders, balanceTotalUsdt }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
      <Kpi
        testid="user-stats-kpi-total-balance"
        icon={Wallet}
        label="Saldo total"
        value={fmtNum(balanceTotalUsdt, 2)}
        sub="USDT equivalente"
      />
      <Kpi
        testid="user-stats-kpi-orders-30d"
        icon={TrendingUp}
        label="Volumen 30 días"
        value={fmtNum(orders.volume_last_30d_usdt, 2)}
        sub={`USDT · ${orders.count_last_30d} órdenes`}
      />
      <Kpi
        testid="user-stats-kpi-total-orders"
        icon={History}
        label="Órdenes totales"
        value={orders.total_lifetime}
        sub={`${orders.success_count || 0} exitosas`}
      />
      <Kpi
        testid="user-stats-kpi-success-rate"
        icon={Percent}
        label="Éxito operativo"
        value={
          <>
            {orders.success_rate_pct ?? 0}<span className="text-lg text-neutral-500">%</span>
          </>
        }
        sub="Aprobadas + completadas"
      />
      <Kpi
        testid="user-stats-kpi-favorite-currency"
        icon={Star}
        label="Moneda favorita"
        value={orders.favorite_currency || "—"}
        sub={orders.favorite_currency_count ? `${orders.favorite_currency_count} apariciones` : "sin datos"}
      />
    </div>
  );
}

function Kpi({ icon: Icon, label, value, sub, testid }) {
  return (
    <div className="tactile-card p-5" data-testid={testid}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-[#8B5CF6]" />
        <div className="micro-label text-neutral-500">{label}</div>
      </div>
      <div className="font-display text-3xl tabular-nums">{value}</div>
      <div className="text-xs text-neutral-500 mt-1">{sub}</div>
    </div>
  );
}
