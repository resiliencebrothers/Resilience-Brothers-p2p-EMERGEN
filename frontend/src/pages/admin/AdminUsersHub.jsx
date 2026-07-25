import { useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users, MessageSquare, IdCard, UserCog, HelpCircle, Crown } from "lucide-react";
import AdminUsers from "./AdminUsers";
import AdminAppeals from "./AdminAppeals";
import AdminKYC from "./AdminKYC";
import AdminProfileChangeRequests from "./AdminProfileChangeRequests";
import AdminSupport from "./AdminSupport";
import AdminVipRequests from "./AdminVipRequests";
import { useAuth } from "@/context/AuthContext";

/**
 * iter55.31 — Consolidates 4 admin user-management sections under a single
 * "Usuarios" hub with sticky tabs (list · appeals · KYC · profile-change requests).
 * iter55.33 — tab labels now translatable via i18next.
 * iter107 — adds the "Soporte" tab so support tickets (from `/admin/support`)
 * live next to Apelaciones in the same natural place operators already look —
 * no more confusion between "Apelaciones" (account_status=under_review) and
 * "Support tickets" (client help requests).
 *
 * URL contract:
 *   /admin/users               → tab=list (default)
 *   /admin/users?tab=appeals   → Apelaciones
 *   /admin/users?tab=support   → Soporte
 *   /admin/users?tab=kyc       → KYC verificación
 *   /admin/users?tab=changes   → Cambios de datos
 *
 * Legacy paths `/admin/appeals`, `/admin/kyc`, `/admin/support`,
 * `/admin/profile-change-requests` still work via redirect routes registered
 * in AdminPanel.jsx.
 */
const ALL_TABS = [
  { id: "list",         labelKey: "usersHub.tabs.list",         icon: Users,          Component: AdminUsers,                perm: "users" },
  { id: "appeals",      labelKey: "usersHub.tabs.appeals",      icon: MessageSquare,  Component: AdminAppeals,              perm: "appeals" },
  { id: "support",      labelKey: "usersHub.tabs.support",      icon: HelpCircle,     Component: AdminSupport,              perm: "support" },
  { id: "vip-requests", labelKey: "usersHub.tabs.vipRequests",  icon: Crown,          Component: AdminVipRequests,          perm: "vip_requests" },
  { id: "kyc",          labelKey: "usersHub.tabs.kyc",          icon: IdCard,         Component: AdminKYC,                  perm: "kyc" },
  { id: "changes",      labelKey: "usersHub.tabs.changes",      icon: UserCog,        Component: AdminProfileChangeRequests, perm: "profile_changes" },
];

function hasPerm(user, code) {
  if (!user) return false;
  if (user.role === "admin") return true;
  if (user.role !== "employee") return false;
  const perms = user.allowed_permissions || [];
  return perms.length === 0 || perms.includes(code);
}

export default function AdminUsersHub() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  const TAB_META = useMemo(
    () => ALL_TABS.filter((tt) => hasPerm(user, tt.perm)),
    [user],
  );

  const activeId = params.get("tab") || (TAB_META[0]?.id || "list");
  const active = useMemo(
    () => TAB_META.find((tt) => tt.id === activeId) || TAB_META[0],
    [activeId, TAB_META],
  );
  const ActiveComponent = active?.Component || AdminUsers;

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
