/**
 * iter122/268 — FundCards (redesigned)
 *
 * Professional per-currency treasury cards for the "Fondo Empresa" module.
 * Each card shows:
 *  - Currency chip + wallet icon (header)
 *  - Net available balance (big) + gross custody (subtle) → per-account breakdown
 *  - Highlighted "Rentabilidad total" block (green/red) with %
 *  - iter268: dynamic inflow/outflow tile — tap opens the per-currency
 *    dashboard (FundDetailDialog) with the full detail
 *  - Amber "client balances owed" tile → tap opens the same dashboard with
 *    the per-client breakdown of what is owed
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Wallet, TrendingUp, TrendingDown, ArrowDownLeft, ArrowUpRight,
  AlertTriangle, Layers, ChevronRight,
} from "lucide-react";
import ProfitSparkline from "./ProfitSparkline";
import ProfitDetailDialog from "./ProfitDetailDialog";
import AccountBreakdownDialog from "./AccountBreakdownDialog";
import FundDetailDialog from "./FundDetailDialog";

const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function FundCards({ funds }) {
  const { t } = useTranslation();
  const [detailCurrency, setDetailCurrency] = useState(null);
  const [breakdownCurrency, setBreakdownCurrency] = useState(null);
  const [dashFund, setDashFund] = useState(null);
  if (funds.length === 0) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4" data-testid="fund-cards">
        <div className="col-span-full text-neutral-500 text-sm">
          {t("admin.companyFunds.empty")}
        </div>
      </div>
    );
  }
  return (
    <>
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
        data-testid="fund-cards"
      >
        {funds.map((f) => (
          <FundCard
            key={f.currency}
            f={f}
            t={t}
            onOpenDetail={setDetailCurrency}
            onOpenBreakdown={setBreakdownCurrency}
            onOpenDashboard={setDashFund}
          />
        ))}
      </div>
      <ProfitDetailDialog
        currency={detailCurrency}
        onClose={() => setDetailCurrency(null)}
      />
      <AccountBreakdownDialog
        currency={breakdownCurrency}
        onClose={() => setBreakdownCurrency(null)}
      />
      <FundDetailDialog fund={dashFund} onClose={() => setDashFund(null)} />
    </>
  );
}

/* ------------------------------ subcomponents ------------------------------ */

function ProfitBlock({ f, t, onOpen }) {
  const p = Number(f.profit_total || 0);
  const pct = Number(f.profit_pct || 0);
  const hasData = p !== 0 || Number(f.outflow_orders || 0) > 0 || Number(f.inflow_vip_batches || 0) > 0;
  const pos = p >= 0;
  const Icon = pos ? TrendingUp : TrendingDown;
  const bg = pos ? "bg-[#22C55E]/10" : "bg-[#EF4444]/10";
  const border = pos ? "border-[#22C55E]/25" : "border-[#EF4444]/25";
  const color = pos ? "text-[#22C55E]" : "text-[#EF4444]";
  const clickable = hasData && !!onOpen;
  return (
    <button
      type="button"
      onClick={clickable ? () => onOpen(f.currency) : undefined}
      disabled={!clickable}
      className={`mt-3 px-3 py-2 border ${border} ${bg} rounded-sm block w-full text-left transition-colors ${
        clickable ? "cursor-pointer hover:border-[#22C55E]/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#22C55E]/60" : "cursor-default"
      }`}
      data-testid={`fund-profit-${f.currency}`}
      aria-label={clickable ? t("admin.companyFunds.profitClickHint") : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-neutral-400">
          <Icon className={`w-3 h-3 ${color}`} />
          <span>{t("admin.companyFunds.profitTotal")}</span>
        </div>
        {hasData && (
          <span className={`text-[0.65rem] font-mono ${color} tabular-nums`} data-testid={`fund-profit-pct-${f.currency}`}>
            {pos ? "+" : ""}{pct.toFixed(2)}%
          </span>
        )}
      </div>
      <div className={`font-display text-lg mt-1 ${color} tabular-nums`}>
        {hasData ? `${pos ? "+" : ""}${fmt2(p)}` : "—"}
      </div>
      {hasData && (
        <ProfitSparkline values={f.profit_30d || []} positive={pos} />
      )}
      {hasData && clickable && (
        <div className="text-[0.55rem] text-neutral-500 mt-1 flex items-center gap-1">
          <span>{t("admin.companyFunds.profitClickHint")}</span>
        </div>
      )}
      {!hasData && (
        <div className="text-[0.6rem] text-neutral-600 mt-0.5">
          {t("admin.companyFunds.noProfitData")}
        </div>
      )}
    </button>
  );
}

function FundCard({ f, t, onOpenDetail, onOpenBreakdown, onOpenDashboard }) {
  const liability = f.client_balances ?? 0;
  const net = f.balance_available ?? f.balance;
  const positive = net >= 0;
  const inTotal = (f.inflow || 0) + (f.inflow_vip_batches || 0) + (f.inflow_deposits || 0) + (f.manual_inflow || 0);
  const outTotal = (f.outflow_orders || 0) + (f.outflow_clients || 0) + (f.outflow_company || 0) + (f.manual_outflow || 0);
  return (
    <div
      className="tactile-card p-5 flex flex-col relative overflow-hidden group hover:border-[#8B5CF6]/30 transition-colors"
      data-testid={`fund-${f.currency}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 px-2 py-0.5 border border-white/10 bg-white/[0.03] rounded-sm">
          <Wallet className="w-3 h-3 text-[#8B5CF6]" />
          <span className="text-[0.65rem] font-mono uppercase tracking-widest text-neutral-200">
            {f.currency}
          </span>
        </div>
        <div className={`w-1.5 h-1.5 rounded-full ${positive ? "bg-[#22C55E]" : "bg-[#EF4444]"} shadow-[0_0_8px_currentColor]`} />
      </div>

      {/* Net balance — click opens per-account breakdown (iter194) */}
      <button
        type="button"
        onClick={() => onOpenBreakdown(f.currency)}
        data-testid={`fund-open-breakdown-${f.currency}`}
        aria-label={t("admin.companyFunds.breakdownHint")}
        className="mt-3 text-left w-full group/bal focus:outline-none focus-visible:ring-1 focus-visible:ring-[#8B5CF6]/60"
      >
        <div className="text-[0.55rem] uppercase tracking-widest text-neutral-500">
          {t("admin.companyFunds.availableBalance")}
        </div>
        <div
          className={`font-display text-3xl mt-0.5 tabular-nums ${
            positive ? "text-[#22C55E]" : "text-[#EF4444]"
          }`}
          data-testid={`fund-balance-${f.currency}`}
        >
          {fmt2(net)}
        </div>
        {liability > 0 && (
          <div
            className="text-[0.65rem] text-neutral-500 font-mono mt-0.5"
            data-testid={`fund-gross-${f.currency}`}
          >
            {t("admin.companyFunds.grossCustody")}: <span className="text-neutral-300">{fmt2(f.balance)}</span>
          </div>
        )}
        <div className="text-[0.55rem] text-neutral-500 mt-1 flex items-center gap-1 group-hover/bal:text-[#8B5CF6] transition-colors">
          <Layers className="w-2.5 h-2.5" />
          <span>{t("admin.companyFunds.breakdownHint")}</span>
        </div>
      </button>

      {/* Profitability */}
      <ProfitBlock f={f} t={t} onOpen={onOpenDetail} />

      {/* iter268 — dynamic inflow/outflow tile → per-currency dashboard */}
      <button
        type="button"
        onClick={() => onOpenDashboard(f)}
        data-testid={`fund-open-dashboard-${f.currency}`}
        aria-label={t("admin.companyFunds.dashboardHint")}
        className="mt-3 px-3 py-2 border border-white/10 bg-white/[0.02] rounded-sm block w-full text-left transition-colors cursor-pointer hover:border-[#8B5CF6]/50 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#8B5CF6]/60"
      >
        <div className="grid grid-cols-2 gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-[0.55rem] uppercase tracking-widest text-neutral-500">
              <ArrowDownLeft className="w-3 h-3 text-[#22C55E]" />
              <span>{t("admin.companyFunds.inflows")}</span>
            </div>
            <div className="font-mono text-[0.85rem] text-[#22C55E] tabular-nums mt-0.5 truncate" data-testid={`fund-in-total-${f.currency}`}>
              {fmt2(inTotal)}
            </div>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-[0.55rem] uppercase tracking-widest text-neutral-500">
              <ArrowUpRight className="w-3 h-3 text-[#EF4444]" />
              <span>{t("admin.companyFunds.outflows")}</span>
            </div>
            <div className="font-mono text-[0.85rem] text-[#F87171] tabular-nums mt-0.5 truncate" data-testid={`fund-out-total-${f.currency}`}>
              {fmt2(outTotal)}
            </div>
          </div>
        </div>
        <div className="text-[0.55rem] text-neutral-500 mt-1.5 flex items-center gap-1 hover:text-[#8B5CF6]">
          <ChevronRight className="w-2.5 h-2.5" />
          <span>{t("admin.companyFunds.dashboardHint")}</span>
        </div>
      </button>

      {/* Liability tile — tap opens the dashboard with the per-client list */}
      {liability > 0 && (
        <button
          type="button"
          onClick={() => onOpenDashboard(f)}
          className="mt-3 px-2.5 py-1.5 border border-[#F59E0B]/25 bg-[#F59E0B]/5 rounded-sm flex items-center justify-between gap-2 w-full text-left cursor-pointer transition-colors hover:border-[#F59E0B]/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#F59E0B]/60"
          data-testid={`fund-client-balances-${f.currency}`}
          aria-label={t("admin.companyFunds.clientBreakdownTitle")}
        >
          <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-[#F59E0B]">
            <AlertTriangle className="w-3 h-3" />
            <span>{t("admin.companyFunds.clientBalancesOwed")}</span>
          </div>
          <span className="text-[0.7rem] font-mono text-[#F59E0B] tabular-nums whitespace-nowrap flex items-center gap-1">
            {fmt2(liability)}
            <ChevronRight className="w-3 h-3" />
          </span>
        </button>
      )}
    </div>
  );
}
