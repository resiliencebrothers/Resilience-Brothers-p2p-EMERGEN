import { useCallback, useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Building2, Store, Boxes, LayoutDashboard, LogOut, Clock, Warehouse, Wallet, Truck, IdCard, ShieldCheck, Wrench } from "lucide-react";
import NotificationBell from "@/components/NotificationBell";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import CompanyStoresView from "@/pages/company/CompanyStoresView";
import CompanyProductsView from "@/pages/company/CompanyProductsView";
import CompanyInventoryView from "@/pages/company/CompanyInventoryView";
import CompanyWalletView from "@/pages/company/CompanyWalletView";
import CompanyDeliveriesView from "@/pages/company/CompanyDeliveriesView";
import CompanyKYCView from "@/pages/company/CompanyKYCView";
import SecuritySettings from "@/pages/dashboard/SecuritySettings";
import ToolsPanel from "@/pages/dashboard/tools/ToolsPanel";

// Panel independiente para cuentas Empresa (rol business). Mientras la cuenta
// está en revisión, solo se muestra el aviso de aprobación pendiente.
// Las pestañas se manejan por URL (/company/<tab>) para que los CTA de
// verificación (banner, step-up 2FA) puedan dirigir directamente a las
// pantallas comunes de Verificación/Seguridad dentro del panel Empresa.
const TABS = [
  { id: "overview", label: "Resumen", icon: LayoutDashboard },
  { id: "stores", label: "Tiendas", icon: Store },
  { id: "products", label: "Productos", icon: Boxes },
  { id: "inventory", label: "Inventario", icon: Warehouse },
  { id: "deliveries", label: "Mensajería", icon: Truck },
  { id: "wallet", label: "Saldo", icon: Wallet },
  { id: "tools", label: "Herramientas", icon: Wrench },
];
// Pantallas comunes de cuenta (verificación de identidad + 2FA). Son requisito
// para retirar/liquidar; antes la Empresa no tenía forma de alcanzarlas.
const ACCOUNT_TABS = [
  { id: "kyc", label: "Verificación", icon: IdCard },
  { id: "security", label: "Seguridad", icon: ShieldCheck },
];
const VALID_IDS = [...TABS, ...ACCOUNT_TABS].map((tb) => tb.id);

export default function CompanyPanel() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);

  const seg = location.pathname.split("/")[2] || "overview";
  const tab = VALID_IDS.includes(seg) ? seg : "overview";
  const go = (id) => navigate(id === "overview" ? "/company" : `/company/${id}`);

  const active = user?.account_status === "active";

  const loadSummary = useCallback(() => {
    if (!active) return;
    axios.get(`${API}/company/me`, { withCredentials: true })
      .then((r) => setSummary(r.data)).catch(() => {});
  }, [active]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  if (user && user.role !== "empresa") {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-[#14101F] text-white">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#14101F]/90 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Building2 className="w-6 h-6 text-[#8B5CF6]" />
            <div>
              <div className="micro-label text-[#8B5CF6] leading-none">Panel Empresa</div>
              <div className="font-display text-base leading-tight" data-testid="company-name">{user?.name}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <CompactLanguageSwitcher />
            <ThemeToggle />
            <Button data-testid="company-logout" variant="ghost" onClick={logout}
              className="text-neutral-400 hover:text-white rounded-none">
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {!active ? (
          <div className="tactile-card p-8 text-center max-w-xl mx-auto" data-testid="company-pending-banner">
            <Clock className="w-12 h-12 text-amber-400 mx-auto mb-4" />
            <h1 className="font-display text-2xl mb-2">Tu cuenta Empresa está en revisión</h1>
            <p className="text-neutral-400 text-sm">
              Un administrador de Resilience revisará tu solicitud y activará tu
              cuenta pronto. Recibirás una notificación cuando puedas empezar a
              gestionar tus tiendas y publicar productos.
            </p>
          </div>
        ) : (
          <>
            <nav className="flex gap-1 mb-8 border-b border-white/10 overflow-x-auto scrollbar-none">
              {TABS.map((tItem) => (
                <button key={tItem.id} data-testid={`company-tab-${tItem.id}`}
                  onClick={() => go(tItem.id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                    tab === tItem.id
                      ? "border-[#8B5CF6] text-white"
                      : "border-transparent text-white/50 hover:text-white"
                  }`}>
                  <tItem.icon className="w-4 h-4" /> {tItem.label}
                </button>
              ))}
              <span className="w-px bg-white/10 my-2 mx-1 shrink-0" aria-hidden />
              {ACCOUNT_TABS.map((tItem) => (
                <button key={tItem.id} data-testid={`company-tab-${tItem.id}`}
                  onClick={() => go(tItem.id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                    tab === tItem.id
                      ? "border-[#8B5CF6] text-white"
                      : "border-transparent text-white/50 hover:text-white"
                  }`}>
                  <tItem.icon className="w-4 h-4" /> {tItem.label}
                </button>
              ))}
            </nav>

            {tab === "overview" && (
              <div className="space-y-6" data-testid="company-overview">
                <h1 className="font-display text-3xl">Resumen</h1>
                <div className="grid sm:grid-cols-3 gap-4">
                  <button onClick={() => go("stores")} className="tactile-card p-6 text-left hover:border-[#8B5CF6]/40 transition-colors" data-testid="company-stat-stores">
                    <Store className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.stores_count ?? "—"}</div>
                    <div className="micro-label text-neutral-500 mt-1">Tiendas</div>
                  </button>
                  <button onClick={() => go("products")} className="tactile-card p-6 text-left hover:border-[#8B5CF6]/40 transition-colors" data-testid="company-stat-products">
                    <Boxes className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.products_count ?? "—"}</div>
                    <div className="micro-label text-neutral-500 mt-1">Productos</div>
                  </button>
                  <div className="tactile-card p-6" data-testid="company-stat-commission">
                    <Building2 className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.commission_pct ?? "—"}%</div>
                    <div className="micro-label text-neutral-500 mt-1">Comisión marketplace</div>
                  </div>
                </div>
                <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-neutral-300">
                  Gestiona tus tiendas y publica productos al marketplace. Los
                  productos nuevos requieren aprobación del administrador antes de
                  aparecer en la tienda.
                </div>
              </div>
            )}

            {tab === "stores" && <CompanyStoresView onChanged={loadSummary} />}
            {tab === "products" && <CompanyProductsView onChanged={loadSummary} />}
            {tab === "inventory" && <CompanyInventoryView />}
            {tab === "deliveries" && <CompanyDeliveriesView />}
            {tab === "wallet" && <CompanyWalletView />}
            {tab === "tools" && <ToolsPanel />}
            {tab === "kyc" && <CompanyKYCView />}
            {tab === "security" && <SecuritySettings embedded />}
          </>
        )}
      </main>
    </div>
  );
}
