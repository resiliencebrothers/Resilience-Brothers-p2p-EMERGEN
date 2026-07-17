import { useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LayoutDashboard, Zap } from "lucide-react";
import AdminOverview from "./AdminOverview";
import AdminQuickDashboard from "./AdminQuickDashboard";

/**
 * iter55.35 — Consolidates "Resumen" (full stats + settings) and "Vista rápida"
 * (mobile-first "is there work now?") under a single Resumen hub with tabs.
 * Both views answer "how is the platform doing right now?" from different
 * angles, so grouping them cuts sidebar clutter.
 *
 * URL contract:
 *   /admin              → tab=general (default) → AdminOverview
 *   /admin?tab=quick    → AdminQuickDashboard
 *
 * Legacy `/admin/quick` still works via redirect route in AdminPanel.jsx.
 */
const TAB_META = [
  { id: "general", labelKey: "overviewHub.tabs.general", icon: LayoutDashboard, Component: AdminOverview },
  { id: "quick",   labelKey: "overviewHub.tabs.quick",   icon: Zap,             Component: AdminQuickDashboard },
];

export default function AdminOverviewHub() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const activeId = params.get("tab") || "general";
  const active = useMemo(() => TAB_META.find((tt) => tt.id === activeId) || TAB_META[0], [activeId]);
  const ActiveComponent = active.Component;

  const setTab = (id) => {
    if (id === "general") {
      navigate("/admin", { replace: false });
    } else {
      setParams({ tab: id });
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-overview-hub">
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 -mt-2 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label={t("admin.hubs.overviewAria")}
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
              data-testid={`overview-hub-tab-${tt.id}`}
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
      <div data-testid={`overview-hub-panel-${activeId}`}>
        <ActiveComponent />
      </div>
    </div>
  );
}
