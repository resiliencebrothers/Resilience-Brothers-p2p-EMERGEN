import { useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users, MessageSquare, IdCard, UserCog } from "lucide-react";
import AdminUsers from "./AdminUsers";
import AdminAppeals from "./AdminAppeals";
import AdminKYC from "./AdminKYC";
import AdminProfileChangeRequests from "./AdminProfileChangeRequests";

/**
 * iter55.31 — Consolidates 4 admin user-management sections under a single
 * "Usuarios" hub with sticky tabs (list · appeals · KYC · profile-change requests).
 * iter55.33 — tab labels now translatable via i18next.
 *
 * URL contract:
 *   /admin/users               → tab=list (default)
 *   /admin/users?tab=appeals   → Apelaciones
 *   /admin/users?tab=kyc       → KYC verificación
 *   /admin/users?tab=changes   → Cambios de datos
 *
 * Legacy paths `/admin/appeals`, `/admin/kyc`, `/admin/profile-change-requests`
 * still work via redirect routes registered in AdminPanel.jsx.
 */
const TAB_META = [
  { id: "list",     labelKey: "usersHub.tabs.list",     icon: Users,          Component: AdminUsers },
  { id: "appeals",  labelKey: "usersHub.tabs.appeals",  icon: MessageSquare,  Component: AdminAppeals },
  { id: "kyc",      labelKey: "usersHub.tabs.kyc",      icon: IdCard,         Component: AdminKYC },
  { id: "changes",  labelKey: "usersHub.tabs.changes",  icon: UserCog,        Component: AdminProfileChangeRequests },
];

export default function AdminUsersHub() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const activeId = params.get("tab") || "list";
  const active = useMemo(() => TAB_META.find((tt) => tt.id === activeId) || TAB_META[0], [activeId]);
  const ActiveComponent = active.Component;

  const setTab = (id) => {
    if (id === "list") {
      // Clean URL for the default landing tab
      navigate("/admin/users", { replace: false });
    } else {
      setParams({ tab: id });
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-users-hub">
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 -mt-2 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label={t("admin.hubs.usersAria")}
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
              data-testid={`users-hub-tab-${tt.id}`}
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
      <div data-testid={`users-hub-panel-${activeId}`}>
        <ActiveComponent />
      </div>
    </div>
  );
}
