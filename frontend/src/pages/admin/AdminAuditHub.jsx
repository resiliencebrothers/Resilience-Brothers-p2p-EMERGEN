import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Shield, User, FileText } from "lucide-react";
import AdminAudit from "@/pages/admin/AdminAudit";
import AdminAuditByUser from "@/pages/admin/audit/AdminAuditByUser";
import MonthlyAuditReport from "@/pages/admin/audit/MonthlyAuditReport";
import AdminPageHeader from "@/components/AdminPageHeader";

/**
 * iter55.35 — Consolidates the platform's audit surfaces under a single
 * page. Three tabs:
 *   - Global   (default; existing AdminAudit filter+list+export)
 *   - Por usuario (per-user forensic timeline; reuses audit-trail endpoint)
 *   - Reporte mensual (executive KPIs — was inline inside AdminAudit)
 *
 * Grouping rationale: the operator asked to "tener los mismos temas en un
 * solo lugar" — same topics, one place. Deep-link support:
 *   /admin/audit                  → Global tab
 *   /admin/audit?tab=by-user      → Por usuario
 *   /admin/audit?tab=by-user&user_id=X → Por usuario pre-loaded
 *   /admin/audit?tab=monthly      → Reporte mensual
 */
const TAB_META = [
  { id: "global",  labelKey: "auditHub.tabs.global",  icon: Shield,   Component: () => <AdminAudit hideMonthly /> },
  { id: "by-user", labelKey: "auditHub.tabs.byUser",  icon: User,     Component: AdminAuditByUser },
  { id: "monthly", labelKey: "auditHub.tabs.monthly", icon: FileText, Component: MonthlyAuditReport },
];

export default function AdminAuditHub() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const activeId = params.get("tab") || "global";
  const active = useMemo(
    () => TAB_META.find((tt) => tt.id === activeId) || TAB_META[0],
    [activeId],
  );
  const ActiveComponent = active.Component;

  const setTab = (id) => {
    if (id === "global") {
      // Keep the URL clean for the default tab
      setParams({}, { replace: false });
    } else {
      setParams({ tab: id }, { replace: false });
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-audit-hub">
      <AdminPageHeader
        eyebrow={t("admin.audit.eyebrow")}
        title={t("admin.audit.title")}
        subtitle={t("admin.audit.subtitle")}
        icon={Shield}
      />
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label={t("admin.hubs.auditAria")}
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
              data-testid={`audit-hub-tab-${tt.id}`}
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
      <div data-testid={`audit-hub-panel-${activeId}`}>
        <ActiveComponent />
      </div>
    </div>
  );
}
