import { NavLink, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { LogOut, Coins, TrendingUp, Users, ListChecks, Package, ArrowDownToLine, ArrowLeft, Shield, ShieldAlert, Menu, Receipt, Inbox, Wallet, Ban, Activity, ChevronRight } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import AdminCurrencies from "@/pages/admin/AdminCurrencies";
import AdminRates from "@/pages/admin/AdminRates";
import AdminUsersHub from "@/pages/admin/AdminUsersHub";
import AdminUserStatsPage from "@/pages/admin/AdminUserStatsPage";
import AdminOverviewHub from "@/pages/admin/AdminOverviewHub";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminAuditHub from "@/pages/admin/AdminAuditHub";
import AdminTransactions from "@/pages/admin/AdminTransactions";
import AdminQueue from "@/pages/admin/AdminQueue";
import AdminCompanyFundsHub from "@/pages/admin/AdminCompanyFundsHub";
import AdminBlockedContacts from "@/pages/admin/AdminBlockedContacts";
import AdminHealth from "@/pages/admin/AdminHealth";
import AdminSecurity from "@/pages/admin/AdminSecurity";
import PushToggle from "@/components/PushToggle";
import NotificationBell from "@/components/NotificationBell";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";

export default function AdminPanel() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isStaff = user?.role === "admin" || user?.role === "employee";
  const isAdmin = user?.role === "admin";
  const userPerms = user?.allowed_permissions || [];
  // iter55.16 — Admins pass everything. Employees with an empty list pass
  // everything (backward compat). Employees with a specific list only pass
  // when the code is present.
  const hasPerm = (code) => isAdmin || userPerms.length === 0 || userPerms.includes(code);

  const items = [
    { to: "/admin", icon: ListChecks, label: t("sidebar.admin.overview"), end: true, id: "admin-nav-overview", hasSubsections: true },
    ...(hasPerm("quick_view") ? [
      { to: "/admin/queue", icon: Inbox, label: t("sidebar.admin.queue"), id: "admin-nav-queue", highlight: true },
    ] : []),
    ...(hasPerm("orders") ? [
      { to: "/admin/orders", icon: ListChecks, label: t("sidebar.admin.orders"), id: "admin-nav-orders" },
    ] : []),
    ...(hasPerm("withdrawals") ? [
      { to: "/admin/withdrawals", icon: ArrowDownToLine, label: t("sidebar.admin.withdrawals"), id: "admin-nav-withdrawals" },
    ] : []),
    ...(hasPerm("currencies") ? [
      { to: "/admin/currencies", icon: Coins, label: t("sidebar.admin.currencies"), id: "admin-nav-currencies" },
    ] : []),
    ...(hasPerm("rates") ? [
      { to: "/admin/rates", icon: TrendingUp, label: t("sidebar.admin.rates"), id: "admin-nav-rates" },
    ] : []),
    ...(hasPerm("products") ? [
      { to: "/admin/products", icon: Package, label: t("sidebar.admin.products"), id: "admin-nav-products" },
    ] : []),
    ...(hasPerm("users") || hasPerm("appeals") || hasPerm("kyc") || hasPerm("profile_changes") ? [
      { to: "/admin/users", icon: Users, label: t("sidebar.admin.users"), id: "admin-nav-users",
        highlight: hasPerm("kyc"), hasSubsections: true },
    ] : []),
    ...(hasPerm("blocked_contacts") ? [
      { to: "/admin/blocked-contacts", icon: Ban, label: t("sidebar.admin.blockedContacts"), id: "admin-nav-blocked-contacts" },
    ] : []),
    ...(hasPerm("company_funds") ? [
      { to: "/admin/company-funds", icon: Wallet, label: t("sidebar.admin.companyFunds"), id: "admin-nav-company-funds",
        hasSubsections: user?.role === "admin" },
    ] : []),
    ...(hasPerm("transactions") ? [
      { to: "/admin/transactions", icon: Receipt, label: t("sidebar.admin.transactions"), id: "admin-nav-transactions", highlight: true },
    ] : []),
    ...(user?.role === "admin" ? [
      { to: "/admin/health", icon: Activity, label: t("sidebar.admin.health"), id: "admin-nav-health", highlight: true },
      { to: "/admin/security", icon: ShieldAlert, label: t("sidebar.admin.security"), id: "admin-nav-security", highlight: true },
      { to: "/admin/audit", icon: Shield, label: t("sidebar.admin.audit"), id: "admin-nav-audit",
        hasSubsections: true },
    ] : []),
  ];

  const navLinkClass = ({ isActive }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group relative outline-none focus-visible:ring-2 focus-visible:ring-violet-500 ${
      isActive
        ? "bg-violet-500/10 text-violet-300 before:absolute before:left-0 before:top-[15%] before:bottom-[15%] before:w-[3px] before:bg-violet-500 before:rounded-r-full shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
        : "text-white/60 hover:text-white hover:bg-white/[0.04]"
    }`;

  const renderNavLinks = (onItemClick) => (
    <>
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          data-testid={it.id}
          onClick={onItemClick}
          className={navLinkClass}
        >
          <it.icon className="w-4 h-4" />
          <span className="flex-1">{it.label}</span>
          {it.highlight && (
            <span className="w-1.5 h-1.5 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.8)]" title="Función destacada" />
          )}
          {it.hasSubsections && (
            <ChevronRight
              className="w-3.5 h-3.5 text-white/30 group-hover:text-violet-300 transition-colors"
              aria-label="Contiene subsecciones"
            />
          )}
        </NavLink>
      ))}
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

      <main className="flex-1 lg:ml-64">
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

        <div className="p-6 lg:p-10">
          <Routes>
            <Route index element={<AdminOverviewHub />} />
            <Route path="quick" element={<Navigate to="/admin?tab=quick" replace />} />
            <Route path="queue" element={<AdminQueue />} />
            <Route path="company-funds" element={<AdminCompanyFundsHub />} />
            <Route path="orders" element={<AdminOrders />} />
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
            {user?.role === "admin" && <Route path="audit" element={<AdminAuditHub />} />}
          </Routes>
        </div>
      </main>
    </div>
  );
}
