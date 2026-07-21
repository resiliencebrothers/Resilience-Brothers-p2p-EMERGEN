import { Coins, History, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import CurrencyIcon from "@/components/CurrencyIcon";

/**
 * iter55.29 — Extracted from VipView. Per-currency clickable grid that
 * opens the ledger dialog with the orders that credited each balance.
 */
export function VipBalancesGrid({ balances, ledger, onDrillDown }) {
  const { t } = useTranslation();
  const hasBalances = balances.balances.length > 0;
  // iter85 — Sort the grid by USDT equivalent DESC so the largest asset
  // in the account shows up first (consistent with History's widget).
  const sortedBalances = hasBalances
    ? balances.balances.slice().sort(
      (a, b) => Number(b.usdt_equivalent || 0) - Number(a.usdt_equivalent || 0),
    )
    : [];
  return (
    <div className="tactile-card p-6" data-testid="vip-balances-card">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-xl flex items-center gap-2">
          <Coins className="w-5 h-5 text-[#8B5CF6]" /> {t("vipView.balanceByCurrency")}
        </h2>
        {ledger.total_orders > 0 && (
          <span
            className="text-xs text-neutral-500 flex items-center gap-1"
            data-testid="ledger-summary"
          >
            <History className="w-3.5 h-3.5" />
            {t("vipView.ordersCredited", { count: ledger.total_orders })}
          </span>
        )}
      </div>
      {!hasBalances ? (
        <p className="text-neutral-500 text-sm">{t("vipView.emptyBalances")}</p>
      ) : (
        <>
          <p className="text-xs text-neutral-500 mb-3">
            {t("vipView.clickToDrilldown")}
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sortedBalances.map((b) => {
              const bucket = ledger.by_currency?.[b.currency];
              const orderCount = bucket?.orders?.length || 0;
              const hasDrillDown = orderCount > 0;
              return (
                <button
                  type="button"
                  key={b.currency}
                  onClick={() => hasDrillDown && onDrillDown(b.currency)}
                  disabled={!hasDrillDown}
                  className={`relative flex flex-col items-start w-full bg-[#1A1730] border border-white/5 rounded-xl p-5 text-left transition-all duration-200 ease-out focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14101F] ${
                    hasDrillDown
                      ? "cursor-pointer hover:-translate-y-0.5 hover:bg-[#181628] hover:border-violet-500/40 hover:shadow-[0_8px_20px_-12px_rgba(139,92,246,0.25)]"
                      : "opacity-80 cursor-default"
                  }`}
                  data-testid={`balance-card-${b.currency}`}
                >
                  {hasDrillDown && (
                    <div className="absolute top-4 right-4 w-2 h-2 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.6)]" />
                  )}
                  <div className="flex items-center justify-between w-full mb-1">
                    <span className="flex items-center gap-2">
                      <CurrencyIcon code={b.currency} size="md" />
                      <span className="text-[11px] font-semibold tracking-[0.2em] text-white/50 uppercase">{b.currency}</span>
                    </span>
                    <span className="text-xs text-neutral-500 font-mono tabular-nums">≈ {b.usdt_equivalent?.toFixed(2) ?? "—"} USDT</span>
                  </div>
                  <div className="font-mono tabular-nums text-2xl text-white tracking-tight">
                    {b.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </div>
                  {hasDrillDown && (
                    <div className="text-[0.65rem] text-violet-400 mt-2 flex items-center gap-1">
                      <Eye className="w-3 h-3" />
                      {t("vipView.ordersDrilldown", { count: orderCount })}
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
