import { useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Wallet, Banknote, HandCoins } from "lucide-react";
import AdminCompanyFunds from "./AdminCompanyFunds";
import AdminRevenue from "./AdminRevenue";
import AdminCapitalRequests from "./AdminCapitalRequests";

/**
 * iter55.31 — Consolidates "Fondos de la Empresa" (treasury view) and
 * "Ingresos" (commissions revenue report) under a single hub with tabs.
 * Both views live in the same mental space for the finance operator so
 * grouping them cuts sidebar clutter (same pattern as UsersHub and
 * OverviewHub introduced in earlier iterations).
 *
 * URL contract:
 *   /admin/company-funds                → tab=funds (default) → AdminCompanyFunds
 *   /admin/company-funds?tab=revenue    → AdminRevenue
 *
 * Legacy `/admin/revenue` still works via redirect in AdminPanel.jsx.
 */
const TAB_META = [
  { id: "funds",    labelKey: "companyFundsHub.tabs.funds",    icon: Wallet,    Component: AdminCompanyFunds },
  { id: "revenue",  labelKey: "companyFundsHub.tabs.revenue",  icon: Banknote,  Component: AdminRevenue },
  { id: "requests", labelKey: "companyFundsHub.tabs.requests", icon: HandCoins, Component: AdminCapitalRequests },
];

export default function AdminCompanyFundsHub() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const activeId = params.get("tab") || "funds";
  const active = useMemo(() => TAB_META.find((tt) => tt.id === activeId) || TAB_META[0], [activeId]);
  const ActiveComponent = active.Component;

  const setTab = (id) => {
    if (id === "funds") {
      navigate("/admin/company-funds", { replace: false });
    } else {
      setParams({ tab: id });
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-company-funds-hub">
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 -mt-2 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label="Fondos de la Empresa"
      >
        {TAB_META.map((tt) => {
          const Icon = tt.icon;
          const isActive = tt.id === activeId;
          return (
            <button
              key={tt.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(tt.id)}
              data-testid={`company-funds-hub-tab-${tt.id}`}
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
            </button>
          );
        })}
      </nav>
      <div data-testid={`company-funds-hub-panel-${activeId}`}>
        <ActiveComponent />
      </div>
    </div>
  );
}
