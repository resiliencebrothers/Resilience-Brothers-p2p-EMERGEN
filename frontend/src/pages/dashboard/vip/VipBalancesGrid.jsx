import { Coins, History, Eye } from "lucide-react";

/**
 * iter55.29 — Extracted from VipView. Per-currency clickable grid that
 * opens the ledger dialog with the orders that credited each balance.
 */
export function VipBalancesGrid({ balances, ledger, onDrillDown }) {
  const hasBalances = balances.balances.length > 0;
  return (
    <div className="tactile-card p-6" data-testid="vip-balances-card">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-xl flex items-center gap-2">
          <Coins className="w-5 h-5 text-[#8B5CF6]" /> Saldo por moneda
        </h2>
        {ledger.total_orders > 0 && (
          <span
            className="text-xs text-neutral-500 flex items-center gap-1"
            data-testid="ledger-summary"
          >
            <History className="w-3.5 h-3.5" />
            {ledger.total_orders} {ledger.total_orders === 1 ? "orden" : "órdenes"} acreditadas
          </span>
        )}
      </div>
      {!hasBalances ? (
        <p className="text-neutral-500 text-sm">Aún no tienes saldo acumulado. Crea órdenes con entrega &laquo;Acumular en saldo&raquo;.</p>
      ) : (
        <>
          <p className="text-xs text-neutral-500 mb-3">
            Click en una moneda para ver las órdenes que la acreditaron.
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {balances.balances.map((b) => {
              const bucket = ledger.by_currency?.[b.currency];
              const orderCount = bucket?.orders?.length || 0;
              const hasDrillDown = orderCount > 0;
              return (
                <button
                  type="button"
                  key={b.currency}
                  onClick={() => hasDrillDown && onDrillDown(b.currency)}
                  disabled={!hasDrillDown}
                  className={`text-left border border-white/10 p-4 transition-colors ${
                    hasDrillDown
                      ? "hover:border-[#8B5CF6]/60 hover:bg-white/5 cursor-pointer"
                      : "opacity-80 cursor-default"
                  }`}
                  data-testid={`balance-card-${b.currency}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="micro-label text-neutral-500">{b.currency}</span>
                    <span className="text-xs text-neutral-500">≈ {b.usdt_equivalent?.toFixed(2) ?? "—"} USDT</span>
                  </div>
                  <div className="font-display text-2xl text-white">
                    {b.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </div>
                  {hasDrillDown && (
                    <div className="text-[0.65rem] text-[#8B5CF6] mt-2 flex items-center gap-1">
                      <Eye className="w-3 h-3" />
                      {orderCount} {orderCount === 1 ? "orden" : "órdenes"} · ver desglose
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
