import { NavLink, Routes, Route, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LogOut, Coins, TrendingUp, Users, ListChecks, Package, ArrowDownToLine, ArrowLeft, Banknote } from "lucide-react";
import AdminCurrencies from "@/pages/admin/AdminCurrencies";
import AdminRates from "@/pages/admin/AdminRates";
import AdminUsers from "@/pages/admin/AdminUsers";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminOverview from "@/pages/admin/AdminOverview";
import AdminRevenue from "@/pages/admin/AdminRevenue";
import PushToggle from "@/components/PushToggle";

export default function AdminPanel() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const items = [
    { to: "/admin", icon: ListChecks, label: "Resumen", end: true, id: "admin-nav-overview" },
    { to: "/admin/orders", icon: ListChecks, label: "Órdenes", id: "admin-nav-orders" },
    { to: "/admin/withdrawals", icon: ArrowDownToLine, label: "Retiros VIP", id: "admin-nav-withdrawals" },
    { to: "/admin/currencies", icon: Coins, label: "Monedas", id: "admin-nav-currencies" },
    { to: "/admin/rates", icon: TrendingUp, label: "Tasas", id: "admin-nav-rates" },
    { to: "/admin/products", icon: Package, label: "Productos", id: "admin-nav-products" },
    { to: "/admin/users", icon: Users, label: "Usuarios", id: "admin-nav-users" },
    ...(user?.role === "admin" ? [
      { to: "/admin/revenue", icon: Banknote, label: "Ingresos", id: "admin-nav-revenue", highlight: true },
    ] : []),
  ];

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white flex">
      <aside className="hidden lg:flex w-64 border-r border-white/5 flex-col fixed inset-y-0 left-0 z-40 bg-[#0c0c0c]">
        <div className="h-16 border-b border-white/5 flex items-center px-6 gap-3">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 object-contain" />
          <div>
            <div className="font-display text-sm">ADMIN</div>
            <div className="micro-label text-[#EAB308] text-[0.6rem]">Control Room</div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {items.map(it => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              data-testid={it.id}
              className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 text-sm transition-colors ${isActive ? "bg-[#EAB308] text-black font-semibold" : "text-neutral-400 hover:bg-white/5 hover:text-white"}`}
            >
              <it.icon className="w-4 h-4" />
              {it.label}
            </NavLink>
          ))}
          <button
            data-testid="back-to-dashboard"
            onClick={() => navigate("/dashboard")}
            className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-neutral-500 hover:text-white mt-4"
          >
            <ArrowLeft className="w-4 h-4" /> Volver al cliente
          </button>
        </nav>
        <div className="p-4 border-t border-white/5">
          <div className="text-sm font-medium truncate">{user?.name}</div>
          <div className="micro-label text-[#EAB308] mb-3">ADMIN</div>
          <div className="mb-2"><PushToggle /></div>
          <button data-testid="admin-logout" onClick={logout} className="w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 px-3 py-2">
            <LogOut className="w-4 h-4" /> Cerrar Sesión
          </button>
        </div>
      </aside>

      <main className="flex-1 lg:ml-64">
        <div className="lg:hidden sticky top-0 z-30 glass-panel h-14 px-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
            <span className="font-display text-sm">ADMIN</span>
          </div>
          <button onClick={logout}><LogOut className="w-5 h-5" /></button>
        </div>
        <div className="lg:hidden flex overflow-x-auto border-b border-white/5 bg-[#0c0c0c]">
          {items.map(it => (
            <NavLink key={it.to} to={it.to} end={it.end}
              className={({ isActive }) => `flex-shrink-0 px-4 py-3 text-xs uppercase tracking-wider ${isActive ? "text-[#EAB308] border-b-2 border-[#EAB308]" : "text-neutral-500"}`}>
              {it.label}
            </NavLink>
          ))}
        </div>
        <div className="p-6 lg:p-10">
          <Routes>
            <Route index element={<AdminOverview />} />
            <Route path="orders" element={<AdminOrders />} />
            <Route path="withdrawals" element={<AdminWithdrawals />} />
            <Route path="currencies" element={<AdminCurrencies />} />
            <Route path="rates" element={<AdminRates />} />
            <Route path="products" element={<AdminProducts />} />
            <Route path="users" element={<AdminUsers />} />
            {user?.role === "admin" && <Route path="revenue" element={<AdminRevenue />} />}
          </Routes>
        </div>
      </main>
    </div>
  );
}
