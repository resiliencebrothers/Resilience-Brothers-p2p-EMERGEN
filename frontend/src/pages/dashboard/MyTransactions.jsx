/**
 * iter83 — MyTransactions
 *
 * Composition-only container. Owns:
 *   • Page chrome (title, subtitle, breadcrumb).
 *   • Live-feed toggle button + "N new items" pill (both derive their
 *     state from useTransactionsQuery).
 *   • Live balance summary widget at the top.
 *   • Direction TAB pills (Todas / Entradas / Salidas / Conversiones).
 *   • Per-currency totals grid.
 *
 * All data-plane concerns (fetching, polling, filter state) live in
 * `useTransactionsQuery`. Filter row and table live in their own files.
 * Behaviour is identical to iter79 — this is a maintenance-only refactor.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pagination } from "@/components/Pagination";
import CurrencyIcon from "@/components/CurrencyIcon";
import { Receipt, ArrowDown, ArrowUp, ArrowRightLeft, Radio, Pause, ChevronRight } from "lucide-react";
import { useTransactionsQuery, PAGE_SIZE } from "@/pages/dashboard/history/useTransactionsQuery";
import TransactionFilters from "@/pages/dashboard/history/TransactionFilters";
import TransactionTable from "@/pages/dashboard/history/TransactionTable";
import AllBalancesDialog from "@/pages/dashboard/history/AllBalancesDialog";

export default function MyTransactions() {
  const { t } = useTranslation();
  const q = useTransactionsQuery();

  const { filters, page, setPage } = q;
  const { tab, setTab } = filters;

  const totalsRows = useMemo(
    () => Object.entries(q.totals?.by_currency || {})
      .map(([code, v]) => ({ code, ...v, net: (v.in || 0) - (v.out || 0) }))
      .sort((a, b) => Math.abs(b.net) - Math.abs(a.net)),
    [q.totals],
  );

  const conversionCount = Number(q.totals?.conversion_count || 0);
  const tabPills = useMemo(() => [
    { key: "all", label: t("myTransactions.tabs.all") },
    { key: "in",  label: t("myTransactions.tabs.in") },
    { key: "out", label: t("myTransactions.tabs.out") },
    { key: "conversion", label: t("myTransactions.tabs.conversion"), badge: conversionCount },
  ], [t, conversionCount]);

  return (
    <div data-testid="my-transactions" className="space-y-5">
      <div className="mb-2 flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-2">
            <Receipt className="w-3.5 h-3.5" /> {t("myTransactions.breadcrumb")}
          </div>
          <h1 className="font-display text-3xl">{t("myTransactions.title")}</h1>
          <p className="text-neutral-500 text-sm mt-1">
            {t("myTransactions.subtitle")}
          </p>
        </div>
        <LiveToggle
          liveEnabled={q.liveEnabled}
          onToggle={() => q.setLiveEnabled((v) => !v)}
          t={t}
        />
      </div>

      {q.newItemsCount > 0 && (
        <button
          type="button"
          onClick={q.applyNewItems}
          data-testid="my-tx-new-items-pill"
          className="mx-auto flex items-center gap-2 px-4 py-2 bg-[#8B5CF6] text-white text-xs uppercase tracking-widest font-mono hover:bg-[#8B5CF6]/90 transition-colors animate-in fade-in slide-in-from-top-2 duration-300"
        >
          <ArrowDown className="w-3.5 h-3.5" />
          {t("myTransactions.live.newItems", { count: q.newItemsCount })}
        </button>
      )}

      <BalanceSummary balanceSummary={q.balanceSummary} t={t} />

      <div className="flex gap-2 flex-wrap" data-testid="my-tx-tabs" role="tablist">
        {tabPills.map((p) => (
          <TabPill key={p.key} pill={p} active={tab === p.key} onClick={() => setTab(p.key)} />
        ))}
      </div>

      {totalsRows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="my-tx-totals">
          {totalsRows.slice(0, 6).map((row) => (
            <TotalCard key={row.code} row={row} t={t} />
          ))}
        </div>
      )}

      <TransactionFilters filters={filters} />

      <TransactionTable items={q.items} loading={q.loading} hasFilters={filters.hasFilters} />

      <Pagination
        page={page}
        total={q.total}
        pageSize={PAGE_SIZE}
        loading={q.loading}
        onPageChange={setPage}
        testidPrefix="my-tx-pagination"
      />
    </div>
  );
}

function LiveToggle({ liveEnabled, onToggle, t }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      data-testid="my-tx-live-toggle"
      className={
        "flex items-center gap-2 border px-3 py-1.5 text-[0.65rem] uppercase tracking-widest font-mono transition-colors "
        + (liveEnabled
          ? "border-[#22C55E]/40 bg-[#22C55E]/5 text-[#22C55E]"
          : "border-white/15 bg-transparent text-neutral-500 hover:border-white/30")
      }
      title={liveEnabled ? t("myTransactions.live.pauseHint") : t("myTransactions.live.resumeHint")}
    >
      {liveEnabled ? (
        <>
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#22C55E] opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#22C55E]" />
          </span>
          <Radio className="w-3 h-3" />
          {t("myTransactions.live.on")}
        </>
      ) : (
        <>
          <Pause className="w-3 h-3" />
          {t("myTransactions.live.off")}
        </>
      )}
    </button>
  );
}

function BalanceSummary({ balanceSummary, t }) {
  const [seeAllOpen, setSeeAllOpen] = useState(false);
  // iter85 — Sort the balance widget by USDT equivalent DESCENDING so the
  // asset with the largest USD value in the account shows up first. This
  // matches the sort order used by AllBalancesDialog for consistency.
  const positiveBalances = useMemo(
    () => (balanceSummary.balances || [])
      .filter((b) => Number(b.amount) > 0)
      .slice()
      .sort((a, b) => Number(b.usdt_equivalent || 0) - Number(a.usdt_equivalent || 0)),
    [balanceSummary],
  );
  if (!positiveBalances.length) return null;
  // iter84 — Show up to 12 tiles inline (was 8) so users with medium
  // portfolios don't need to open the modal at all. Anything beyond 12
  // is behind a "see all" button that opens AllBalancesDialog.
  const INLINE_LIMIT = 12;
  const inlineBalances = positiveBalances.slice(0, INLINE_LIMIT);
  const extraCount = Math.max(0, positiveBalances.length - INLINE_LIMIT);
  return (
    <div className="tactile-card p-5" data-testid="my-tx-balance-summary">
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <div className="micro-label text-neutral-500">
          {t("myTransactions.balanceSummaryLabel")}
        </div>
        <div className="text-right">
          <div className="font-mono text-2xl text-[#8B5CF6]">
            {Number(balanceSummary.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
            <span className="text-sm text-neutral-500 ml-2">USDT</span>
          </div>
          <div className="text-[0.65rem] text-neutral-600">
            {t("myTransactions.balanceSummarySub")}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {inlineBalances.map((b) => (
          <div
            key={b.currency}
            className="border border-white/5 bg-[#0a0a0a] px-3 py-2 flex items-center gap-2"
            data-testid={`my-tx-balance-${b.currency}`}
          >
            <CurrencyIcon code={b.currency} size="md" />
            <div>
              <div className="text-[0.6rem] uppercase tracking-widest text-neutral-500">{b.currency}</div>
              <div className="font-mono text-sm mt-0.5">
                {Number(b.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
              </div>
            </div>
          </div>
        ))}
      </div>
      {/* iter84 — "See all N balances" CTA. Always shown when the wallet
         has ≥ 4 currencies so the user can jump to the full modal even
         when all fit inline; the label changes to reflect the extra count. */}
      {positiveBalances.length >= 4 && (
        <button
          type="button"
          onClick={() => setSeeAllOpen(true)}
          data-testid="my-tx-balance-see-all"
          className="mt-3 flex items-center gap-1 text-xs text-[#8B5CF6] hover:text-[#A78BFA] hover:underline underline-offset-4"
        >
          {extraCount > 0
            ? t("myTransactions.allBalances.seeAllExtra", { count: extraCount })
            : t("myTransactions.allBalances.seeAll", { count: positiveBalances.length })}
          <ChevronRight className="w-3 h-3" />
        </button>
      )}
      <AllBalancesDialog
        open={seeAllOpen}
        onOpenChange={setSeeAllOpen}
        balanceSummary={balanceSummary}
      />
    </div>
  );
}

function TabPill({ pill, active, onClick }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      data-testid={`my-tx-tab-${pill.key}`}
      className={
        "text-xs uppercase tracking-wider border px-4 py-2 rounded-none transition-colors flex items-center gap-2 "
        + (active
          ? "bg-[#8B5CF6] text-white border-[#8B5CF6]"
          : "border-white/15 text-neutral-400 hover:border-[#8B5CF6]/60 hover:text-white")
      }
    >
      {pill.key === "in" && <ArrowDown className="w-3 h-3" />}
      {pill.key === "out" && <ArrowUp className="w-3 h-3" />}
      {pill.key === "conversion" && <ArrowRightLeft className="w-3 h-3" />}
      <span>{pill.label}</span>
      {pill.key === "conversion" && pill.badge > 0 && (
        <span
          className={
            "font-mono text-[0.65rem] px-1.5 py-0.5 rounded-full "
            + (active ? "bg-white/20 text-white" : "bg-[#8B5CF6]/15 text-[#8B5CF6]")
          }
          data-testid="my-tx-tab-conversion-count"
        >
          {pill.badge}
        </span>
      )}
    </button>
  );
}

function TotalCard({ row, t }) {
  return (
    <div className="tactile-card p-4">
      <div className="micro-label text-neutral-500 mb-1 flex items-center gap-2">
        <CurrencyIcon code={row.code} size="sm" />
        <span>{row.code}</span>
      </div>
      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-400 flex items-center gap-1">
            <ArrowDown className="w-3 h-3 text-[#22C55E]" /> {t("myTransactions.in")}
          </span>
          <span className="font-mono text-[#22C55E]">+{row.in.toLocaleString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-400 flex items-center gap-1">
            <ArrowUp className="w-3 h-3 text-[#EF4444]" /> {t("myTransactions.out")}
          </span>
          <span className="font-mono text-[#EF4444]">-{row.out.toLocaleString()}</span>
        </div>
        <div className="flex justify-between border-t border-white/5 pt-1 mt-1">
          <span className="text-neutral-300 text-xs">{t("myTransactions.net")}</span>
          <span className={`font-mono font-bold ${row.net >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
            {row.net >= 0 ? "+" : ""}{row.net.toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}
