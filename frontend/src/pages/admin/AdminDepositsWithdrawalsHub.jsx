import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { ArrowDownToLine, PiggyBank, HandCoins } from "lucide-react";
import { API } from "@/App";
import AdminPageHeader from "@/components/AdminPageHeader";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import AdminWithdrawals from "./AdminWithdrawals";
import AdminDeposits from "./vip/AdminDeposits";
import AdminCapitalRequests from "./AdminCapitalRequests";

/**
 * iter163 — "Depósitos y Retiros" hub. Unifies the money-out queue
 * (withdrawals) with the money-in queues, all gated by the `withdrawals`
 * permission so one designated staff member handles both directions.
 * iter166 — capital deposits retired (unified into client deposits);
 * capital REQUESTS moved here from Company Funds.
 * iter171 — badge counts refresh debounced via useLiveRefresh so a burst
 * of deposit_created / new_withdrawal / ledger_changed events does not
 * spawn dozens of concurrent /pending-count fetches.
 *
 * URL contract:
 *   /admin/withdrawals                → tab=withdrawals (default)
 *   /admin/withdrawals?tab=deposits   → client deposits queue
 *   /admin/withdrawals?tab=requests   → VIP capital requests queue
 */
const TABS = [
  { id: "withdrawals", labelKey: "depositsWithdrawalsHub.tabs.withdrawals", icon: ArrowDownToLine, countKey: "withdrawals_pending" },
  { id: "deposits",    labelKey: "depositsWithdrawalsHub.tabs.deposits",    icon: PiggyBank,        countKey: "deposits_pending" },
  { id: "requests",    labelKey: "depositsWithdrawalsHub.tabs.requests",    icon: HandCoins,        countKey: "requests_pending" },
];

const HUB_BADGE_EVENTS = ["deposit_created", "new_withdrawal", "ledger_changed"];

export default function AdminDepositsWithdrawalsHub() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [counts, setCounts] = useState(null);

  const activeId = params.get("tab") || "withdrawals";
  const active = TABS.find((tt) => tt.id === activeId) || TABS[0];

  const loadCounts = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/deposits-hub/pending-count`, {
        withCredentials: true,
        timeout: 20000,
      });
      setCounts(r.data);
    } catch { /* badges are best-effort */ }
  }, []);

  useEffect(() => { loadCounts(); }, [loadCounts]);
  useLiveRefresh(loadCounts, HUB_BADGE_EVENTS);

  const setTab = (id) => {
    if (id === "withdrawals") setParams({});
    else setParams({ tab: id });
  };

  return (
    <div className="space-y-4" data-testid="admin-deposits-withdrawals-hub">
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 -mt-2 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label={t("depositsWithdrawalsHub.aria")}
        data-testid="deposits-withdrawals-hub-tabs"
      >
        {TABS.map((tt) => {
          const Icon = tt.icon;
          const isActive = tt.id === active.id;
          const count = counts?.[tt.countKey] || 0;
          return (
            <button
              key={tt.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(tt.id)}
              data-testid={`deposits-withdrawals-hub-tab-${tt.id}`}
              className={
                "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap " +
                "transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500 " +
                (isActive
                  ? "text-violet-300 after:absolute after:left-3 after:right-3 after:-bottom-[7px] after:h-[2px] after:bg-violet-500 after:rounded-full"
                  : "text-white/50 hover:text-white hover:bg-white/[0.03] rounded-md")
              }
            >
              <Icon className="w-4 h-4" />
              {t(tt.labelKey)}
              {count > 0 && (
                <span
                  data-testid={`deposits-withdrawals-hub-count-${tt.id}`}
                  className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-[0.6rem] font-bold border border-amber-500/50 bg-amber-500/10 text-amber-400"
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {active.id === "withdrawals" && <AdminWithdrawals />}

      {active.id === "deposits" && (
        <div className="space-y-4">
          <AdminPageHeader
            eyebrow={t("depositsWithdrawalsHub.eyebrow")}
            title={t("depositsWithdrawalsHub.tabs.deposits")}
            subtitle={t("depositsWithdrawalsHub.depositsSubtitle")}
            testid="deposits-tab-header"
          />
          <AdminDeposits onChanged={loadCounts} />
        </div>
      )}

      {active.id === "requests" && <AdminCapitalRequests />}
    </div>
  );
}
