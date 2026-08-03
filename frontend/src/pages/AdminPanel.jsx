import { NavLink, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { LogOut, Coins, TrendingUp, Users, ListChecks, Package, ArrowDownToLine, ArrowLeft, Shield, ShieldAlert, Menu, Receipt, Inbox, Wallet, Ban, Activity, ChevronRight, ChevronDown, HelpCircle, Layers, Gift } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import AdminCurrencies from "@/pages/admin/AdminCurrencies";
import AdminRates from "@/pages/admin/AdminRates";
import AdminUsersHub from "@/pages/admin/AdminUsersHub";
import AdminUserStatsPage from "@/pages/admin/AdminUserStatsPage";
import AdminOverviewHub from "@/pages/admin/AdminOverviewHub";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminVipBatches from "@/pages/admin/AdminVipBatches";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminAuditHub from "@/pages/admin/AdminAuditHub";
import AdminTransactions from "@/pages/admin/AdminTransactions";
import AdminQueue from "@/pages/admin/AdminQueue";
import AdminCompanyFundsHub from "@/pages/admin/AdminCompanyFundsHub";
import AdminBlockedContacts from "@/pages/admin/AdminBlockedContacts";
import AdminHealth from "@/pages/admin/AdminHealth";
import AdminSecurity from "@/pages/admin/AdminSecurity";
import AdminSupport from "@/pages/admin/AdminSupport";
import AdminReferrals from "@/pages/admin/AdminReferrals";
import PushToggle from "@/components/PushToggle";
import NotificationBell from "@/components/NotificationBell";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";
import { useSupportUnreadCount } from "@/hooks/useSupportUnreadCount";

export default function AdminPanel() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isStaff = user?.role === "admin" || user?.role === "employee";
  const isAdmin = user?.role === "admin";
  // iter107.2 — Memoise so useMemo hooks below have a stable identity.
  const userPerms = useMemo(
    () => user?.allowed_permissions || [],
    [user?.allowed_permissions],
  );
  // iter55.16 — Admins pass everything. Employees with an empty list pass
  // everything (backward compat). Employees with a specific list only pass
  // when the code is present.
  const hasPerm = (code) => isAdmin || userPerms.length === 0 || userPerms.includes(code);

  // iter107.1 — Live count of unread client support tickets, used as a
  // red pill next to the "Usuarios" sidebar entry so staff notice new
  // help requests without opening the section.
  const { unread: supportUnread } = useSupportUnreadCount();

  // iter107.2 — Memoise the sidebar item tree so `useMemo` hooks that
  // depend on it (`groupIds`, `initialOpen`) don't rebuild on every
  // render. `hasPerm` is inlined so ESLint can statically verify deps.
  const items = useMemo(() => {
    const has = (code) => isAdmin || userPerms.length === 0 || userPerms.includes(code);
    return [
      { to: "/admin", icon: ListChecks, label: t("sidebar.admin.overview"), end: true, id: "admin-nav-overview", hasSubsections: true },
      ...(has("quick_view") ? [
        { to: "/admin/queue", icon: Inbox, label: t("sidebar.admin.queue"), id: "admin-nav-queue", highlight: true },
      ] : []),
      ...(has("orders") ? [
        {
          to: "/admin/orders", icon: ListChecks, label: t("sidebar.admin.orders"),
          id: "admin-nav-orders",
          children: [
            { to: "/admin/vip-batches", icon: Layers, label: t("sidebar.admin.vipBatches"), id: "admin-nav-vip-batches", highlight: true },
          ],
        },
      ] : []),
      ...(has("withdrawals") ? [
        { to: "/admin/withdrawals", icon: ArrowDownToLine, label: t("sidebar.admin.withdrawals"), id: "admin-nav-withdrawals" },
      ] : []),
      // iter102.1 — Monedas + Tasas agrupadas: la Rate table es una vista
      // secundaria del catálogo de monedas, no una sección independiente.
      ...(has("currencies") || has("rates") ? [
        {
          to: "/admin/currencies", icon: Coins, label: t("sidebar.admin.currencies"),
          id: "admin-nav-currencies",
          children: [
            ...(has("rates") ? [
              { to: "/admin/rates", icon: TrendingUp, label: t("sidebar.admin.rates"), id: "admin-nav-rates" },
            ] : []),
          ],
        },
      ] : []),
      ...(has("products") ? [
        { to: "/admin/products", icon: Package, label: t("sidebar.admin.products"), id: "admin-nav-products" },
      ] : []),
      // iter102.1 — Usuarios agrupa Soporte + Bloqueos: los tres son
      // vinculantes (tickets salen de un usuario, bloqueos aplican a
      // teléfonos/emails asociados a usuarios).
      ...(has("users") || has("appeals") || has("kyc")
         || has("profile_changes") || has("support")
         || has("blocked_contacts") ? [
        {
          to: "/admin/users", icon: Users, label: t("sidebar.admin.users"),
          id: "admin-nav-users",
          highlight: has("kyc"),
          // iter107.1 — Show a red pill with the pending support ticket
          // count so staff see queued client help right from the sidebar.
          badge: has("support") && supportUnread > 0 ? supportUnread : null,
          children: [
            ...(has("support") ? [
              { to: "/admin/support", icon: HelpCircle, label: t("sidebar.admin.support"), id: "admin-nav-support" },
            ] : []),
            ...(has("blocked_contacts") ? [
              { to: "/admin/blocked-contacts", icon: Ban, label: t("sidebar.admin.blockedContacts"), id: "admin-nav-blocked-contacts" },
            ] : []),
          ],
        },
      ] : []),
      ...((has("company_funds") || has("profitability")) ? [
        { to: "/admin/company-funds", icon: Wallet, label: t("sidebar.admin.companyFunds"), id: "admin-nav-company-funds",
          hasSubsections: user?.role === "admin" },
      ] : []),
      ...(has("transactions") ? [
        { to: "/admin/transactions", icon: Receipt, label: t("sidebar.admin.transactions"), id: "admin-nav-transactions", highlight: true },
      ] : []),
      // iter112 — Referral leaderboard + bonus config.
      ...(has("users") ? [
        { to: "/admin/referrals", icon: Gift, label: t("sidebar.admin.referrals"), id: "admin-nav-referrals" },
      ] : []),
      // iter102.1 — Seguridad agrupa Salud + Auditoría: todas son vistas
      // de monitoreo con requisitos de acceso admin puro.
      ...(user?.role === "admin" ? [
        {
          to: "/admin/security", icon: ShieldAlert, label: t("sidebar.admin.security"),
          id: "admin-nav-security", highlight: true,
          children: [
            { to: "/admin/health", icon: Activity, label: t("sidebar.admin.health"), id: "admin-nav-health", highlight: true },
            { to: "/admin/audit", icon: Shield, label: t("sidebar.admin.audit"), id: "admin-nav-audit" },
          ],
        },
      ] : []),
    ];
  }, [t, isAdmin, userPerms, user?.role, supportUnread]);

  const navLinkClass = ({ isActive }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group relative outline-none focus-visible:ring-2 focus-visible:ring-violet-500 ${
      isActive
        ? "bg-violet-500/10 text-violet-300 before:absolute before:left-0 before:top-[15%] before:bottom-[15%] before:w-[3px] before:bg-violet-500 before:rounded-r-full shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
        : "text-white/60 hover:text-white hover:bg-white/[0.04]"
    }`;

  // iter102.1 — Nested-group expand state. A group auto-opens when the
  // current URL matches the parent or any child so the user always sees
  // where they are; manual clicks toggle from there.
  const location = useLocation();
  const groupIds = useMemo(
    () => items.filter((it) => it.children?.length).map((it) => it.id),
    [items],
  );
  const initialOpen = useMemo(() => {
    const map = {};
    for (const it of items) {
      if (!it.children?.length) continue;
      const active = location.pathname === it.to
        || location.pathname.startsWith(it.to + "/")
        || it.children.some((c) =>
             location.pathname === c.to || location.pathname.startsWith(c.to + "/"));
      map[it.id] = active;
    }
    return map;
  }, [location.pathname, items]);
  const [openGroups, setOpenGroups] = useState(initialOpen);
  // Merge auto-open changes as the route changes (without collapsing groups
  // the user manually opened).
  const openState = { ...initialOpen, ...openGroups };
  const toggleGroup = (id) => setOpenGroups((prev) => ({ ...prev, [id]: !openState[id] }));

  const renderNavItem = (it, onItemClick, indent = false) => {
    const hasChildren = !!it.children?.length;
    const isOpen = hasChildren && openState[it.id];
    return (
      <div key={it.to}>
        <div className={`flex items-stretch ${indent ? "pl-6" : ""}`}>
          <NavLink
            to={it.to}
            end={it.end}
            data-testid={it.id}
            onClick={onItemClick}
            className={navLinkClass}
            style={hasChildren ? { flex: 1 } : undefined}
          >
            <it.icon className="w-4 h-4" />
            <span className="flex-1">{it.label}</span>
            {it.badge != null && it.badge > 0 && (
              <span
                data-testid={`${it.id}-badge`}
                title={`${it.badge} sin leer`}
                className="min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center text-[0.65rem] font-mono font-semibold bg-[#EF4444] text-white rounded-full shadow-[0_0_8px_rgba(239,68,68,0.5)] animate-pulse"
              >
                {it.badge > 99 ? "99+" : it.badge}
              </span>
            )}
            {it.highlight && (
              <span className="w-1.5 h-1.5 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.8)]" title="Función destacada" />
            )}
            {it.hasSubsections && !hasChildren && (
              <ChevronRight
                className="w-3.5 h-3.5 text-white/30 group-hover:text-violet-300 transition-colors"
                aria-label="Contiene subsecciones"
              />
            )}
          </NavLink>
          {hasChildren && (
            <button
              type="button"
              data-testid={`${it.id}-toggle`}
              onClick={(e) => { e.preventDefault(); toggleGroup(it.id); }}
              aria-label={isOpen ? "Colapsar grupo" : "Expandir grupo"}
              className="px-2 text-white/40 hover:text-violet-300 transition-colors rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-violet-500"
            >
              <ChevronDown
                className={`w-4 h-4 transition-transform ${isOpen ? "rotate-0" : "-rotate-90"}`}
              />
            </button>
          )}
        </div>
        {hasChildren && isOpen && (
          <div className="mt-0.5 space-y-0.5">
            {it.children.map((child) => renderNavItem(child, onItemClick, true))}
          </div>
        )}
      </div>
    );
  };

  const renderNavLinks = (onItemClick) => (
    <>
      {items.map((it) => renderNavItem(it, onItemClick))}
      <button
        data-testid="back-to-dashboard"
        onClick={() => { onItemClick?.(); navigate("/dashboard"); }}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-neutral-500 hover:text-white mt-4"
      >
        <ArrowLeft className="w-4 h-4" /> {t("sidebar.admin.backToClient")}
      </button>
    </>
  );

  return (
    <div className="min-h-screen bg-[#14101F] text-white flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-64 border-r border-white/5 flex-col fixed inset-y-0 left-0 z-40 bg-[#0c0c0c]">
        <div className="h-16 border-b border-white/5 flex items-center px-6 gap-3 shrink-0">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 object-contain" />
          <div>
            <div className="font-display text-sm">ADMIN</div>
            <div className="micro-label text-[#8B5CF6] text-[0.6rem]">Control Room</div>
          </div>
        </div>
        <nav className="flex-1 min-h-0 p-4 space-y-1 overflow-y-auto">
          {renderNavLinks()}
        </nav>
        <div className="p-4 border-t border-white/5 shrink-0">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{user?.name}</div>
              <div className="micro-label text-[#8B5CF6]">{user?.role?.toUpperCase()}</div>
            </div>
            <NotificationBell />
          </div>
          <div className="mb-2"><PushToggle /></div>
          <div className="flex items-center gap-2">
            <CompactLanguageSwitcher testid="admin-lang-switcher" />
            <button data-testid="admin-logout" onClick={logout} className="flex-1 flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 hover:border-white/30 px-3 py-2 transition-colors">
              <LogOut className="w-4 h-4" /> {t("common.logout")}
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 lg:ml-64 min-w-0 overflow-x-hidden">
        {/* Mobile top bar with hamburger menu */}
        <div className="lg:hidden sticky top-0 z-30 glass-panel h-14 px-4 flex items-center justify-between border-b border-white/5">
          <div className="flex items-center gap-2">
            <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
            <span className="font-display text-sm">ADMIN</span>
            <span className="micro-label text-[#8B5CF6] text-[0.55rem]">{user?.role?.toUpperCase()}</span>
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <button
                data-testid="admin-mobile-menu-trigger"
                className="flex items-center gap-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] px-3 py-1.5 text-xs uppercase tracking-wider font-mono"
              >
                <Menu className="w-4 h-4" /> Menú
              </button>
            </SheetTrigger>
            <SheetContent
              side="right"
              data-testid="admin-mobile-menu"
              className="w-72 bg-[#0c0c0c] border-l border-white/10 text-white p-0 flex flex-col"
            >
              <VisuallyHidden><SheetTitle>Menú de navegación admin</SheetTitle></VisuallyHidden>
              <div className="h-16 border-b border-white/5 flex items-center px-5 shrink-0">
                <div className="flex items-center gap-3">
                  <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
                  <div>
                    <div className="font-display text-sm">ADMIN</div>
                    <div className="micro-label text-[#8B5CF6] text-[0.55rem]">Control Room</div>
                  </div>
                </div>
                {/* Close button provided by SheetContent (top-right X). */}
              </div>
              <nav className="flex-1 min-h-0 p-4 space-y-1 overflow-y-auto">
                {renderNavLinks(() => setMobileOpen(false))}
              </nav>
              <div className="p-4 border-t border-white/5 shrink-0">
                <div className="text-sm font-medium truncate">{user?.name}</div>
                <div className="micro-label text-[#8B5CF6] mb-3">{user?.role?.toUpperCase()}</div>
                <div className="mb-2"><PushToggle /></div>
                <button
                  data-testid="admin-mobile-logout"
                  onClick={logout}
                  className="w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 px-3 py-2"
                >
                  <LogOut className="w-4 h-4" /> Cerrar Sesión
                </button>
              </div>
            </SheetContent>
          </Sheet>
          </div>
        </div>

        <div className="p-4 sm:p-6 lg:p-10">
          <Routes>
            <Route index element={<AdminOverviewHub />} />
            <Route path="quick" element={<Navigate to="/admin?tab=quick" replace />} />
            <Route path="queue" element={<AdminQueue />} />
            <Route path="company-funds" element={<AdminCompanyFundsHub />} />
            <Route path="orders" element={<AdminOrders />} />
            <Route path="vip-batches" element={<AdminVipBatches />} />
            <Route path="withdrawals" element={<AdminWithdrawals />} />
            <Route path="currencies" element={<AdminCurrencies />} />
            <Route path="rates" element={<AdminRates />} />
            <Route path="products" element={<AdminProducts />} />
            <Route path="users" element={<AdminUsersHub />} />
            <Route path="users/:userId/stats" element={<AdminUserStatsPage />} />
            <Route path="blocked-contacts" element={<AdminBlockedContacts />} />
            {/* iter55.31 — legacy routes redirect into the consolidated hub. */}
            <Route path="appeals" element={<Navigate to="/admin/users?tab=appeals" replace />} />
            <Route path="kyc" element={<Navigate to="/admin/users?tab=kyc" replace />} />
            <Route path="profile-change-requests" element={<Navigate to="/admin/users?tab=changes" replace />} />
            <Route path="security" element={<AdminSecurity />} />
            {user?.role === "admin" && <Route path="revenue" element={<Navigate to="/admin/company-funds?tab=revenue" replace />} />}
            {user?.role === "admin" && <Route path="capital-requests" element={<Navigate to="/admin/company-funds?tab=requests" replace />} />}
            {user?.role === "admin" && <Route path="health" element={<AdminHealth />} />}
            {isStaff && <Route path="transactions" element={<AdminTransactions />} />}
            {isStaff && <Route path="support" element={<AdminSupport />} />}
            {hasPerm("users") && <Route path="referrals" element={<AdminReferrals />} />}
            {user?.role === "admin" && <Route path="audit" element={<AdminAuditHub />} />}
          </Routes>
        </div>
      </main>
    </div>
  );
}
