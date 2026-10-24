import { Package, ShoppingBag, Coins, TrendingUp, Trophy, Clock, XCircle, Receipt } from "lucide-react";
import { fmtNum } from "./userStatsMeta";

const UNIT_ABBR = { unidad: "u", libra: "lb", kg: "kg" };
const unitAbbr = (u) => UNIT_ABBR[u] || "u";

/**
 * Ventas de una cuenta Empresa: KPIs de ventas entregadas + ingresos,
 * desglose por estado y el ranking de productos más vendidos. Alimentado por
 * el bloque `sales` de /admin/users/{id}/stats (solo rol empresa).
 */
export default function VendorSalesSection({ sales }) {
  const top = sales.top_products || [];
  const avgTicket = sales.delivered_count > 0 ? sales.gross_usdt / sales.delivered_count : 0;
  return (
    <div className="space-y-4" data-testid="user-stats-sales-section">
      <div className="flex items-center gap-2">
        <ShoppingBag className="w-4 h-4 text-[#8B5CF6]" />
        <h2 className="font-display text-lg">Ventas de la empresa</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <SalesKpi
          testid="user-stats-sales-delivered"
          icon={Package}
          label="Ventas entregadas"
          value={sales.delivered_count}
          sub={`${sales.total_count} canjes en total`}
        />
        <SalesKpi
          testid="user-stats-sales-gross"
          icon={Coins}
          label="Ingreso bruto"
          value={fmtNum(sales.gross_usdt, 2)}
          sub="USDT · ventas entregadas"
        />
        <SalesKpi
          testid="user-stats-sales-net"
          icon={Coins}
          label="Ingreso neto"
          value={fmtNum(sales.net_usdt, 2)}
          sub="USDT · acreditado al saldo"
        />
        <SalesKpi
          testid="user-stats-sales-avg-ticket"
          icon={Receipt}
          label="Ticket promedio"
          value={fmtNum(avgTicket, 2)}
          sub="USDT · ingreso ÷ ventas"
        />
        <SalesKpi
          testid="user-stats-sales-30d"
          icon={TrendingUp}
          label="Ventas 30 días"
          value={sales.count_last_30d}
          sub={`${fmtNum(sales.gross_last_30d_usdt, 2)} USDT en bruto`}
        />
      </div>

      <div className="flex flex-wrap gap-3">
        <span
          data-testid="user-stats-sales-pending"
          className="inline-flex items-center gap-1.5 text-xs text-amber-400 border border-amber-500/30 bg-amber-500/5 px-3 py-1.5"
        >
          <Clock className="w-3.5 h-3.5" /> {sales.pending_count} pendientes / en proceso
        </span>
        <span
          data-testid="user-stats-sales-rejected"
          className="inline-flex items-center gap-1.5 text-xs text-red-400 border border-red-500/30 bg-red-500/5 px-3 py-1.5"
        >
          <XCircle className="w-3.5 h-3.5" /> {sales.rejected_count} rechazadas
        </span>
      </div>

      <div className="tactile-card overflow-x-auto" data-testid="user-stats-top-products">
        <div className="flex items-center gap-2 px-4 pt-4 pb-2">
          <Trophy className="w-4 h-4 text-amber-400" />
          <div className="micro-label text-neutral-500">Productos más vendidos</div>
        </div>
        {top.length === 0 ? (
          <div className="px-4 py-6 text-sm text-neutral-500" data-testid="user-stats-top-products-empty">
            Aún no hay ventas entregadas para esta empresa.
          </div>
        ) : (
          <table className="w-full text-sm min-w-[560px]">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500 w-8">#</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Producto</th>
                <th className="px-4 py-3 micro-label text-neutral-500 text-right">Unidades</th>
                <th className="px-4 py-3 micro-label text-neutral-500 text-right">Pedidos</th>
                <th className="px-4 py-3 micro-label text-neutral-500 text-right">Ingresos</th>
              </tr>
            </thead>
            <tbody>
              {top.map((p, i) => (
                <tr
                  key={p.product_id || i}
                  className="border-b border-white/5"
                  data-testid={`top-product-row-${i}`}
                >
                  <td className="px-4 py-3 text-neutral-500 tabular-nums">{i + 1}</td>
                  <td className="px-4 py-3 flex items-center gap-2">
                    <Package className="w-3.5 h-3.5 text-neutral-500 shrink-0" />
                    <span>{p.product_name || "—"}</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums font-mono">
                    {fmtNum(p.quantity_sold, 3)} {unitAbbr(p.unit)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums font-mono">{p.orders}</td>
                  <td className="px-4 py-3 text-right tabular-nums font-mono text-emerald-400">
                    {fmtNum(p.revenue_usdt, 2)} USDT
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function SalesKpi({ icon: Icon, label, value, sub, testid }) {
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
