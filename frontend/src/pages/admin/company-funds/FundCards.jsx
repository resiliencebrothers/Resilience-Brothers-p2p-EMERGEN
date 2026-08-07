/**
 * iter122 — FundCards (redesigned)
 *
 * Professional per-currency treasury cards for the "Fondo Empresa" module.
 * Each card shows:
 *  - Currency chip + wallet icon (header)
 *  - Net available balance (big) + gross custody (subtle)
 *  - Highlighted "Rentabilidad total" block (green/red) with %
 *  - Two-column breakdown of inflows (left) and outflows (right)
 *  - Amber "client balances owed" liability line, if any
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Wallet, TrendingUp, TrendingDown, ArrowDownLeft, ArrowUpRight, AlertTriangle } from "lucide-react";
import ProfitSparkline from "./ProfitSparkline";
import ProfitDetailDialog from "./ProfitDetailDialog";

const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function FundCards({ funds }) {
  const { t } = useTranslation();
  const [detailCurrency, setDetailCurrency] = useState(null);
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
          <FundCard key={f.currency} f={f} t={t} onOpenDetail={setDetailCurrency} />
        ))}
      </div>
      <ProfitDetailDialog
        currency={detailCurrency}
        onClose={() => setDetailCurrency(null)}
      />
    </>
  );
}

/* ------------------------------ subcomponents ------------------------------ */

function KVRow({ label, value, tone = "neutral", testId }) {
  const toneCls = {
    neutral: "text-neutral-400",
    positive: "text-[#22C55E]",
    vip: "text-[#A78BFA]",
    negative: "text-[#F87171]",
    warn: "text-[#F59E0B]",
  }[tone];
  return (
    <div className="flex items-baseline justify-between gap-2 text-[0.68rem] font-mono" data-testid={testId}>
      <span className="text-neutral-500 truncate">{label}</span>
      <span className={`${toneCls} tabular-nums whitespace-nowrap`}>{value}</span>
    </div>
  );
}

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

function InflowsColumn({ f, t }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1 text-[0.55rem] uppercase tracking-widest text-neutral-500 pb-1 border-b border-white/5">
        <ArrowDownLeft className="w-3 h-3 text-[#22C55E]" />
        <span>{t("admin.companyFunds.inflows")}</span>
      </div>
      <KVRow label={t("admin.companyFunds.orders")} value={fmt2(f.inflow)} tone="positive" />
      {(f.inflow_vip_batches ?? 0) > 0 && (
        <KVRow
          label={t("admin.companyFunds.vipBatchesIn")}
          value={fmt2(f.inflow_vip_batches)}
          tone="vip"
          testId={`fund-vip-batches-in-${f.currency}`}
        />
      )}
      {(f.inflow_deposits ?? 0) > 0 && (
        <KVRow
          label={t("admin.companyFunds.depositsIn")}
          value={fmt2(f.inflow_deposits)}
          tone="positive"
          testId={`fund-deposits-in-${f.currency}`}
        />
      )}
      {f.manual_inflow > 0 && (
        <KVRow
          label={t("admin.companyFunds.ownContribution")}
          value={fmt2(f.manual_inflow)}
          tone="positive"
          testId={`fund-manual-in-${f.currency}`}
        />
      )}
    </div>
  );
}

function OutflowsColumn({ f, t }) {
  const legacyClients =
    f.outflow_clients_vip == null &&
    f.outflow_clients_normal == null &&
    (f.outflow_clients ?? 0) > 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1 text-[0.55rem] uppercase tracking-widest text-neutral-500 pb-1 border-b border-white/5">
        <ArrowUpRight className="w-3 h-3 text-[#EF4444]" />
        <span>{t("admin.companyFunds.outflows")}</span>
      </div>
      {(f.outflow_orders ?? 0) > 0 && (
        <KVRow
          label={t("admin.companyFunds.deliveredToClients")}
          value={fmt2(f.outflow_orders)}
          tone="negative"
          testId={`fund-order-out-${f.currency}`}
        />
      )}
      {(f.outflow_clients_vip ?? 0) > 0 && (
        <KVRow
          label={t("admin.companyFunds.vipWithdrawals")}
          value={fmt2(f.outflow_clients_vip)}
          tone="negative"
          testId={`fund-vip-out-${f.currency}`}
        />
      )}
      {(f.outflow_clients_normal ?? 0) > 0 && (
        <KVRow
          label={t("admin.companyFunds.normalWithdrawals")}
          value={fmt2(f.outflow_clients_normal)}
          tone="negative"
          testId={`fund-normal-out-${f.currency}`}
        />
      )}
      {legacyClients && (
        <KVRow
          label={t("admin.companyFunds.clientWithdrawals")}
          value={fmt2(f.outflow_clients)}
          tone="negative"
        />
      )}
      <KVRow
        label={t("admin.companyFunds.companyOutflow")}
        value={fmt2(f.outflow_company)}
        tone="negative"
      />
      {f.manual_outflow > 0 && (
        <KVRow
          label={t("admin.companyFunds.ownOutflow")}
          value={fmt2(f.manual_outflow)}
          tone="negative"
          testId={`fund-manual-out-${f.currency}`}
        />
      )}
    </div>
  );
}

function FundCard({ f, t, onOpenDetail }) {
  const liability = f.client_balances ?? 0;
  const net = f.balance_available ?? f.balance;
  const positive = net >= 0;
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

      {/* Net balance */}
      <div className="mt-3">
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
      </div>

      {/* Profitability */}
      <ProfitBlock f={f} t={t} onOpen={onOpenDetail} />

      {/* Inflows / outflows */}
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2">
        <InflowsColumn f={f} t={t} />
        <OutflowsColumn f={f} t={t} />
      </div>

      {/* Liability row */}
      {liability > 0 && (
        <div
          className="mt-3 px-2.5 py-1.5 border border-[#F59E0B]/25 bg-[#F59E0B]/5 rounded-sm flex items-center justify-between gap-2"
          data-testid={`fund-client-balances-${f.currency}`}
        >
          <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-[#F59E0B]">
            <AlertTriangle className="w-3 h-3" />
            <span>{t("admin.companyFunds.clientBalancesOwed")}</span>
          </div>
          <span className="text-[0.7rem] font-mono text-[#F59E0B] tabular-nums whitespace-nowrap">
            {fmt2(liability)}
          </span>
        </div>
      )}
    </div>
  );
}
