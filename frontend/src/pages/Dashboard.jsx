import { useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LogOut, LayoutDashboard, ArrowLeftRight, ListOrdered, Star, Boxes, Shield } from "lucide-react";
import ExchangeView from "@/pages/dashboard/ExchangeView";
import OrdersView from "@/pages/dashboard/OrdersView";
import VipView from "@/pages/dashboard/VipView";
import MarketplaceView from "@/pages/dashboard/MarketplaceView";
import OverviewView from "@/pages/dashboard/OverviewView";
import PushToggle from "@/components/PushToggle";

export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const isVip = user?.role === "vip" || user?.role === "admin";

  const navItems = [
    { to: "/dashboard", icon: LayoutDashboard, label: "Resumen", end: true, id: "nav-overview" },
    { to: "/dashboard/exchange", icon: ArrowLeftRight, label: "Intercambio", id: "nav-exchange" },
    { to: "/dashboard/orders", icon: ListOrdered, label: "Mis Órdenes", id: "nav-orders" },
    ...(isVip ? [
      { to: "/dashboard/vip", icon: Star, label: "Saldo VIP", id: "nav-vip" },
      { to: "/dashboard/marketplace", icon: Boxes, label: "Marketplace", id: "nav-marketplace" },
    ] : []),
  ];

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white flex">
      {/* SIDEBAR */}
      <aside className="hidden lg:flex w-64 border-r border-white/5 flex-col fixed inset-y-0 left-0 z-40 bg-[#0c0c0c]">
        <div className="h-16 border-b border-white/5 flex items-center px-6 gap-3">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 object-contain" />
          <div>
            <div className="font-display text-sm">RESILIENCE</div>
            <div className="micro-label text-neutral-500 text-[0.6rem]">P2P Console</div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              data-testid={item.id}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 text-sm transition-colors ${
                  isActive ? "bg-[#EAB308] text-black font-semibold" : "text-neutral-400 hover:bg-white/5 hover:text-white"
                }`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
          {(user?.role === "admin" || user?.role === "employee") && (
            <NavLink
              to="/admin"
              data-testid="nav-admin"
              className="flex items-center gap-3 px-3 py-2.5 text-sm transition-colors mt-4 border border-[#EAB308]/40 text-[#EAB308] hover:bg-[#EAB308]/10"
            >
              <Shield className="w-4 h-4" />
              {user?.role === "admin" ? "Panel Admin" : "Panel Equipo"}
            </NavLink>
          )}
        </nav>
        <div className="p-4 border-t border-white/5">
          <div className="flex items-center gap-3 mb-3">
            {user?.picture ? (
              <img src={user.picture} alt="" className="w-9 h-9 rounded-full" />
            ) : (
              <div className="w-9 h-9 bg-neutral-800 rounded-full"></div>
            )}
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{user?.name}</div>
              <div className="micro-label text-neutral-500">
                {user?.role === "vip" ? "VIP" : user?.role === "admin" ? "Admin" : user?.role === "employee" ? "Empleado" : "Cliente"}
              </div>
            </div>
          </div>
          <div className="mb-2"><PushToggle /></div>
          <button
            data-testid="logout-btn"
            onClick={logout}
            className="w-full flex items-center justify-center gap-2 text-sm text-neutral-400 hover:text-white border border-white/10 hover:border-white/30 px-3 py-2 transition-colors"
          >
            <LogOut className="w-4 h-4" /> Cerrar Sesión
          </button>
        </div>
      </aside>

      <main className="flex-1 lg:ml-64">
        {/* Mobile top bar */}
        <div className="lg:hidden sticky top-0 z-30 glass-panel h-14 px-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img src="/branding/logo-300.png" alt="RB" className="h-8 w-8 object-contain" />
            <span className="font-display text-sm">RESILIENCE</span>
          </div>
          <button onClick={logout} className="text-neutral-400" data-testid="logout-mobile-btn">
            <LogOut className="w-5 h-5" />
          </button>
        </div>
        {/* Mobile nav */}
        <div className="lg:hidden flex overflow-x-auto border-b border-white/5 bg-[#0c0c0c]">
          {navItems.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                `flex-shrink-0 px-4 py-3 text-xs uppercase tracking-wider ${isActive ? "text-[#EAB308] border-b-2 border-[#EAB308]" : "text-neutral-500"}`
              }
            >
              {it.label}
            </NavLink>
          ))}
        </div>

        <div className="p-6 lg:p-10">
          <Routes>
            <Route index element={<OverviewView />} />
            <Route path="exchange" element={<ExchangeView />} />
            <Route path="orders" element={<OrdersView />} />
            <Route path="vip" element={<VipView />} />
            <Route path="marketplace" element={<MarketplaceView />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
