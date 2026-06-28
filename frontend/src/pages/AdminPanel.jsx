import { NavLink, Routes, Route, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { LogOut, Coins, TrendingUp, Users, ListChecks, Package, ArrowDownToLine, ArrowLeft, Banknote, Shield, Menu, X, Receipt, Inbox, Wallet, Ban, Activity } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import AdminCurrencies from "@/pages/admin/AdminCurrencies";
import AdminRates from "@/pages/admin/AdminRates";
import AdminUsers from "@/pages/admin/AdminUsers";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminOverview from "@/pages/admin/AdminOverview";
import AdminRevenue from "@/pages/admin/AdminRevenue";
import AdminAudit from "@/pages/admin/AdminAudit";
import AdminTransactions from "@/pages/admin/AdminTransactions";
import AdminQueue from "@/pages/admin/AdminQueue";
import AdminCompanyFunds from "@/pages/admin/AdminCompanyFunds";
import AdminBlockedContacts from "@/pages/admin/AdminBlockedContacts";
import AdminHealth from "@/pages/admin/AdminHealth";
import PushToggle from "@/components/PushToggle";
import NotificationBell from "@/components/NotificationBell";

export default function AdminPanel() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isStaff = user?.role === "admin" || user?.role === "employee";

  const items = [
    { to: "/admin", icon: ListChecks, label: "Resumen", end: true, id: "admin-nav-overview" },
    { to: "/admin/queue", icon: Inbox, label: "Mi Cola", id: "admin-nav-queue", highlight: true },
    { to: "/admin/orders", icon: ListChecks, label: "Órdenes", id: "admin-nav-orders" },
    { to: "/admin/withdrawals", icon: ArrowDownToLine, label: "Retiros", id: "admin-nav-withdrawals" },
    { to: "/admin/currencies", icon: Coins, label: "Monedas", id: "admin-nav-currencies" },
    { to: "/admin/rates", icon: TrendingUp, label: "Tasas", id: "admin-nav-rates" },
    { to: "/admin/products", icon: Package, label: "Productos", id: "admin-nav-products" },
    { to: "/admin/users", icon: Users, label: "Usuarios", id: "admin-nav-users" },
    { to: "/admin/blocked-contacts", icon: Ban, label: "Bloqueos", id: "admin-nav-blocked-contacts" },
    { to: "/admin/company-funds", icon: Wallet, label: "Fondo Empresa", id: "admin-nav-company-funds" },
    ...(isStaff ? [
      { to: "/admin/transactions", icon: Receipt, label: "Transacciones", id: "admin-nav-transactions", highlight: true },
    ] : []),
    ...(user?.role === "admin" ? [
      { to: "/admin/revenue", icon: Banknote, label: "Ingresos", id: "admin-nav-revenue", highlight: true },
      { to: "/admin/health", icon: Activity, label: "Salud", id: "admin-nav-health", highlight: true },
      { to: "/admin/audit", icon: Shield, label: "Auditoría", id: "admin-nav-audit" },
    ] : []),
  ];

  const navLinkClass = ({ isActive }) =>
    `flex items-center gap-3 px-3 py-2.5 text-sm transition-colors ${
      isActive
        ? "bg-[#EAB308] text-black font-semibold"
        : "text-neutral-400 hover:bg-white/5 hover:text-white"
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
          {it.label}
          {it.highlight && (
            <span className="ml-auto text-[0.6rem] bg-[#EAB308]/20 text-[#EAB308] px-1.5 py-0.5">ADMIN</span>
          )}
        </NavLink>
      ))}
      <button
        data-testid="back-to-dashboard"
        onClick={() => { onItemClick?.(); navigate("/dashboard"); }}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-neutral-500 hover:text-white mt-4"
      >
        <ArrowLeft className="w-4 h-4" /> Volver al cliente
      </button>
    </>
  );

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-64 border-r border-white/5 flex-col fixed inset-y-0 left-0 z-40 bg-[#0c0c0c]">
        <div className="h-16 border-b border-white/5 flex items-center px-6 gap-3">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 object-contain" />
          <div>
            <div className="font-display text-sm">ADMIN</div>
            <div className="micro-label text-[#EAB308] text-[0.6rem]">Control Room</div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {renderNavLinks()}
        </nav>
        <div className="p-4 border-t border-white/5">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{user?.name}</div>
              <div className="micro-label text-[#EAB308]">{user?.role?.toUpperCase()}</div>
            </div>
            <NotificationBell />
          </div>
          <div className="mb-2"><PushToggle /></div>
          <button data-testid="admin-logout" onClick={logout} className="w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 px-3 py-2">
            <LogOut className="w-4 h-4" /> Cerrar Sesión
          </button>
        </div>
      </aside>

      <main className="flex-1 lg:ml-64">
        {/* Mobile top bar with hamburger menu */}
        <div className="lg:hidden sticky top-0 z-30 glass-panel h-14 px-4 flex items-center justify-between border-b border-white/5">
          <div className="flex items-center gap-2">
            <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
            <span className="font-display text-sm">ADMIN</span>
            <span className="micro-label text-[#EAB308] text-[0.55rem]">{user?.role?.toUpperCase()}</span>
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <button
                data-testid="admin-mobile-menu-trigger"
                className="flex items-center gap-2 border border-[#EAB308]/40 bg-[#EAB308]/10 text-[#EAB308] px-3 py-1.5 text-xs uppercase tracking-wider font-mono"
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
              <div className="h-16 border-b border-white/5 flex items-center justify-between px-5">
                <div className="flex items-center gap-3">
                  <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
                  <div>
                    <div className="font-display text-sm">ADMIN</div>
                    <div className="micro-label text-[#EAB308] text-[0.55rem]">Control Room</div>
                  </div>
                </div>
                <button
                  onClick={() => setMobileOpen(false)}
                  data-testid="admin-mobile-menu-close"
                  className="text-neutral-400 hover:text-white"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
                {renderNavLinks(() => setMobileOpen(false))}
              </nav>
              <div className="p-4 border-t border-white/5">
                <div className="text-sm font-medium truncate">{user?.name}</div>
                <div className="micro-label text-[#EAB308] mb-3">{user?.role?.toUpperCase()}</div>
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
            <Route index element={<AdminOverview />} />
            <Route path="queue" element={<AdminQueue />} />
            <Route path="company-funds" element={<AdminCompanyFunds />} />
            <Route path="orders" element={<AdminOrders />} />
            <Route path="withdrawals" element={<AdminWithdrawals />} />
            <Route path="currencies" element={<AdminCurrencies />} />
            <Route path="rates" element={<AdminRates />} />
            <Route path="products" element={<AdminProducts />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="blocked-contacts" element={<AdminBlockedContacts />} />
            {user?.role === "admin" && <Route path="revenue" element={<AdminRevenue />} />}
            {user?.role === "admin" && <Route path="health" element={<AdminHealth />} />}
            {isStaff && <Route path="transactions" element={<AdminTransactions />} />}
            {user?.role === "admin" && <Route path="audit" element={<AdminAudit />} />}
          </Routes>
        </div>
      </main>
    </div>
  );
}
