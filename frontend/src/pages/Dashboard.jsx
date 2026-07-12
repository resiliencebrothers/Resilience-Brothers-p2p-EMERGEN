import { useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LogOut, LayoutDashboard, ArrowLeftRight, ListOrdered, Star, Boxes, Shield, Menu, Receipt, UserCircle } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import ExchangeView from "@/pages/dashboard/ExchangeView";
import OrdersView from "@/pages/dashboard/OrdersView";
import VipView from "@/pages/dashboard/VipView";
import MarketplaceView from "@/pages/dashboard/MarketplaceView";
import OverviewView from "@/pages/dashboard/OverviewView";
import MyTransactions from "@/pages/dashboard/MyTransactions";
import SecuritySettings from "@/pages/dashboard/SecuritySettings";
import KYCView from "@/pages/dashboard/KYCView";
import ProfileView from "@/pages/dashboard/ProfileView";
import NotificationsView from "@/pages/dashboard/NotificationsView";
import OnboardingDialog from "@/components/OnboardingDialog";
import NotificationBell from "@/components/NotificationBell";
import AppealDialog from "@/components/AppealDialog";

const ROLE_LABELS = {
  normal: "Cliente",
  vip: "VIP",
  admin: "Admin",
  employee: "Staff Member",
};

export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const isStaff = user?.role === "admin" || user?.role === "employee";
  // iter14: any non-staff client (normal + vip) may see balance & withdraw panel.
  const isClient = user && !isStaff;
  const [mobileOpen, setMobileOpen] = useState(false);
  // Onboarding shows ONLY for users explicitly marked as not-onboarded (legacy users have the field missing and are treated as completed).
  const [showOnboarding, setShowOnboarding] = useState(user?.onboarding_completed === false);

  // iter55.26 — "Mi Perfil" leads the sidebar (owner request, 11 Feb 2026).
  // Verificación y Seguridad quedan AGRUPADAS dentro de Mi Perfil como
  // tabs internos (ver ProfileSectionTabs) — ya no aparecen en el sidebar.
  const navItems = [
    { to: "/dashboard/profile", icon: UserCircle, label: "Mi Perfil", id: "nav-profile" },
    { to: "/dashboard", icon: LayoutDashboard, label: "Resumen", end: true, id: "nav-overview" },
    { to: "/dashboard/exchange", icon: ArrowLeftRight, label: "Intercambio", id: "nav-exchange" },
    { to: "/dashboard/orders", icon: ListOrdered, label: "Mis Órdenes", id: "nav-orders" },
    { to: "/dashboard/transactions", icon: Receipt, label: "Mi Historial", id: "nav-transactions" },
    ...(isClient ? [
      { to: "/dashboard/vip", icon: Star, label: "Saldo y Retiros", id: "nav-vip" },
      { to: "/dashboard/marketplace", icon: Boxes, label: "Marketplace", id: "nav-marketplace" },
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
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          data-testid={item.id}
          onClick={onItemClick}
          className={navLinkClass}
        >
          <item.icon className="w-4 h-4" />
          {item.label}
        </NavLink>
      ))}
      {isStaff && (
        <button
          data-testid="nav-admin"
          onClick={() => { onItemClick?.(); navigate("/admin"); }}
          className="w-full flex items-center gap-3 px-3 py-2.5 text-sm transition-colors mt-4 border border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10"
        >
          <Shield className="w-4 h-4" />
          {user?.role === "admin" ? "Panel Admin" : "Panel Equipo"}
        </button>
      )}
    </>
  );

  const renderUserFooter = (logoutTestid) => (
    <div className="p-4 border-t border-white/5 shrink-0">
      <div className="flex items-center gap-2 mb-3">
        {user?.picture ? (
          <img src={user.picture} alt="" className="w-9 h-9 rounded-full" />
        ) : (
          <div className="w-9 h-9 bg-neutral-800 rounded-full"></div>
        )}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium truncate">{user?.name}</div>
          <div className="micro-label text-neutral-500">
            {ROLE_LABELS[user?.role] || "Cliente"}
          </div>
        </div>
        <NotificationBell />
      </div>
      <button
        data-testid={logoutTestid}
        onClick={logout}
        className="w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 hover:border-white/30 px-3 py-2 transition-colors"
      >
        <LogOut className="w-4 h-4" /> Cerrar Sesión
      </button>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#14101F] text-white flex">
      <OnboardingDialog open={showOnboarding} onClose={() => setShowOnboarding(false)} />
      {/* DESKTOP SIDEBAR */}
      <aside className="hidden lg:flex w-64 border-r border-white/5 flex-col fixed inset-y-0 left-0 z-40 bg-[#0c0c0c]">
        <div className="h-16 border-b border-white/5 flex items-center px-6 gap-3 shrink-0">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 object-contain" />
          <div>
            <div className="font-display text-sm">RESILIENCE</div>
            <div className="micro-label text-neutral-500 text-[0.6rem]">P2P Console</div>
          </div>
        </div>
        <nav className="flex-1 min-h-0 p-4 space-y-1 overflow-y-auto">{renderNavLinks()}</nav>
        {renderUserFooter("logout-btn")}
      </aside>

      <main className="flex-1 lg:ml-64">
        {/* MOBILE TOP BAR with hamburger */}
        <div className="lg:hidden sticky top-0 z-30 glass-panel h-14 px-4 flex items-center justify-between border-b border-white/5">
          <div className="flex items-center gap-2">
            <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
            <span className="font-display text-sm">RESILIENCE</span>
            {isStaff && (
              <span className="micro-label text-[#8B5CF6] text-[0.55rem]">{user?.role?.toUpperCase()}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <button
                data-testid="dashboard-mobile-menu-trigger"
                className="flex items-center gap-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] px-3 py-1.5 text-xs uppercase tracking-wider font-mono"
              >
                <Menu className="w-4 h-4" /> Menú
              </button>
            </SheetTrigger>
            <SheetContent
              side="right"
              data-testid="dashboard-mobile-menu"
              className="w-72 bg-[#0c0c0c] border-l border-white/10 text-white p-0 flex flex-col"
            >
              <VisuallyHidden><SheetTitle>Menú de navegación</SheetTitle></VisuallyHidden>
              <div className="h-16 border-b border-white/5 flex items-center px-5 shrink-0">
                <div className="flex items-center gap-3">
                  <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
                  <div>
                    <div className="font-display text-sm">RESILIENCE</div>
                    <div className="micro-label text-neutral-500 text-[0.55rem]">P2P Console</div>
                  </div>
                </div>
                {/* Close button provided by SheetContent (top-right X). */}
              </div>
              <nav className="flex-1 min-h-0 p-4 space-y-1 overflow-y-auto">
                {renderNavLinks(() => setMobileOpen(false))}
              </nav>
              {renderUserFooter("logout-mobile-btn")}
            </SheetContent>
          </Sheet>
          </div>
        </div>

        <div className="p-6 lg:p-10">
          {user?.account_status === "under_review" && user?.role !== "admin" && user?.role !== "employee" && (
            <div
              data-testid="under-review-banner"
              className="mb-6 border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-[#FEF3C7] flex items-start gap-3"
            >
              <span className="text-2xl leading-none">⚠️</span>
              <div>
                <div className="font-semibold text-[#8B5CF6] uppercase tracking-wider text-xs mb-1">Cuenta bajo revisión</div>
                <p className="text-neutral-300 text-xs leading-relaxed">
                  Tu cuenta aún no está activa. Un miembro del staff debe verificar tu teléfono antes de que puedas operar (intercambios, retiros y canjes están temporalmente deshabilitados).
                  Si llevas más de 24h esperando, contacta a soporte por WhatsApp.
                </p>
                <AppealDialog />
              </div>
            </div>
          )}
          {user?.account_status === "blocked" && user?.role !== "admin" && user?.role !== "employee" && (
            <div
              data-testid="account-blocked-banner"
              className="mb-6 border-l-4 border-[#EF4444] bg-[#EF4444]/5 px-4 py-3 text-sm text-[#FECACA] flex items-start gap-3"
            >
              <span className="text-2xl leading-none">🚫</span>
              <div>
                <div className="font-semibold text-[#EF4444] uppercase tracking-wider text-xs mb-1">Cuenta bloqueada</div>
                <p className="text-neutral-300 text-xs leading-relaxed">
                  Tu cuenta ha sido bloqueada por el equipo. Si crees que es un error, contacta a soporte.
                </p>
              </div>
            </div>
          )}
          <Routes>
            <Route index element={<OverviewView />} />
            <Route path="exchange" element={<ExchangeView />} />
            <Route path="orders" element={<OrdersView />} />
            <Route path="transactions" element={<MyTransactions />} />
            <Route path="kyc" element={<KYCView />} />
            <Route path="security" element={<SecuritySettings />} />
            <Route path="profile" element={<ProfileView />} />
            <Route path="notifications" element={<NotificationsView />} />
            <Route path="vip" element={<VipView />} />
            <Route path="marketplace" element={<MarketplaceView />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
