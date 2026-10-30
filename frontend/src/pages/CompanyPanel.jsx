import { useCallback, useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Building2, Store, Boxes, LayoutDashboard, LogOut, Clock, Warehouse, Wallet, Truck, IdCard, ShieldCheck, Wrench, BadgeCheck, AlertTriangle, RefreshCw, CalendarClock, CalendarCheck } from "lucide-react";
import NotificationBell from "@/components/NotificationBell";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import CompanyStoresView from "@/pages/company/CompanyStoresView";
import CompanyProductsView from "@/pages/company/CompanyProductsView";
import CompanyServicesView from "@/pages/company/CompanyServicesView";
import CompanyBookingsView from "@/pages/company/CompanyBookingsView";
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
  { id: "overview", icon: LayoutDashboard },
  { id: "stores", icon: Store },
  { id: "products", icon: Boxes },
  { id: "services", icon: CalendarClock },
  { id: "bookings", icon: CalendarCheck },
  { id: "inventory", icon: Warehouse },
  { id: "deliveries", icon: Truck },
  { id: "wallet", icon: Wallet },
  { id: "tools", icon: Wrench },
];
// Pantallas comunes de cuenta (verificación de identidad + 2FA). Son requisito
// para retirar/liquidar; antes la Empresa no tenía forma de alcanzarlas.
const ACCOUNT_TABS = [
  { id: "kyc", icon: IdCard },
  { id: "security", icon: ShieldCheck },
];
// EMP-O01 — durante la revisión la Empresa SÍ puede preparar su KYB y su 2FA.
const REVIEW_TABS = [{ id: "overview", icon: Clock, labelKey: "reviewStatus" }, ...ACCOUNT_TABS];
const VALID_IDS = [...TABS, ...ACCOUNT_TABS].map((tb) => tb.id);

export default function CompanyPanel() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [kyb, setKyb] = useState(null);

  const seg = location.pathname.split("/")[2] || "overview";
  const tab = VALID_IDS.includes(seg) ? seg : "overview";
  const go = (id) => navigate(id === "overview" ? "/company" : `/company/${id}`);
  const tabLabel = (tItem) => t(`company.panel.tabs.${tItem.labelKey || tItem.id}`);

  const active = user?.account_status === "active";

  const loadSummary = useCallback(() => {
    if (!active) return;
    axios.get(`${API}/company/me`, { withCredentials: true })
      .then((r) => setSummary(r.data)).catch(() => {});
  }, [active]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  // Insignia "Empresa verificada" + aviso de KYB rechazado: reflejan el
  // estado del expediente KYB (verified = aprobado; rejected/needs_more_info
  // = requiere corrección y reenvío).
  useEffect(() => {
    axios.get(`${API}/kyc/my-status`, { withCredentials: true })
      .then((r) => setKyb(r.data))
      .catch(() => {});
  }, [tab]);

  const kybVerified = kyb?.status === "verified";
  const kybNeedsAction = kyb?.status === "rejected" || kyb?.status === "needs_more_info";
  const kybReasons = kyb?.verification?.rejection_reasons || [];
  const kybNotes = kyb?.verification?.review_notes || "";

  if (user && user.role !== "empresa") {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-[#14101F] text-white">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#14101F]/90 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <Building2 className="w-6 h-6 text-[#8B5CF6] shrink-0" />
            <div className="min-w-0">
              <div className="micro-label text-[#8B5CF6] leading-none whitespace-nowrap">{t("company.panel.headerLabel")}</div>
              <div className="font-display text-base leading-tight truncate" data-testid="company-name">{user?.name}</div>
            </div>
            {kybVerified && (
              <span data-testid="company-verified-badge"
                title={t("company.panel.verifiedBadgeTitle")}
                className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1 border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 text-[11px] font-semibold uppercase tracking-wide rounded-full">
                <BadgeCheck className="w-3.5 h-3.5" /> {t("company.panel.verifiedBadge")}
              </span>
            )}
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
        {/* Aviso de KYB rechazado / con correcciones — visible en todo el panel
            (excepto en la propia pestaña de Verificación, que ya detalla los
            motivos y ofrece el formulario de reenvío). */}
        {kybNeedsAction && tab !== "kyc" && (
          <div
            data-testid="company-kyb-rejected-banner"
            className="mb-6 border border-[#EF4444]/40 bg-[#EF4444]/5 p-5 flex flex-col sm:flex-row sm:items-start gap-4"
          >
            <AlertTriangle className="w-6 h-6 text-[#EF4444] shrink-0" />
            <div className="flex-1 min-w-0">
              <h3 className="font-display text-lg text-[#FEE2E2]" data-testid="company-kyb-rejected-title">
                {kyb?.status === "rejected"
                  ? t("company.panel.kyb.rejectedTitle")
                  : t("company.panel.kyb.needsInfoTitle")}
              </h3>
              <p className="text-sm text-neutral-400 mt-1">
                {t("company.panel.kyb.body")}
              </p>
              {kybReasons.length > 0 && (
                <ul className="mt-3 text-xs text-neutral-300 space-y-1 list-disc pl-5" data-testid="company-kyb-rejected-reasons">
                  {kybReasons.map((r) => (<li key={r}>{r}</li>))}
                </ul>
              )}
              {kybNotes && (
                <p className="mt-2 text-xs text-neutral-400 italic" data-testid="company-kyb-rejected-notes">
                  {t("company.panel.kyb.teamNote")} {kybNotes}
                </p>
              )}
            </div>
            <Button
              data-testid="company-kyb-resubmit-btn"
              onClick={() => go("kyc")}
              className="bg-[#EF4444] hover:bg-[#EF4444]/90 text-white rounded-none shrink-0 self-start"
            >
              <RefreshCw className="w-4 h-4 mr-2" /> {t("company.panel.kyb.resubmit")}
            </Button>
          </div>
        )}
        {!active ? (
          <div className="space-y-6">
            <nav className="flex gap-1 border-b border-white/10 overflow-x-auto scrollbar-none"
              data-testid="company-review-nav">
              {REVIEW_TABS.map((tItem) => (
                <button key={tItem.id} data-testid={`company-tab-${tItem.id}`}
                  onClick={() => go(tItem.id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                    tab === tItem.id
                      ? "border-[#8B5CF6] text-white"
                      : "border-transparent text-white/50 hover:text-white"
                  }`}>
                  <tItem.icon className="w-4 h-4" /> {tabLabel(tItem)}
                </button>
              ))}
            </nav>
            {tab === "kyc" ? (
              <CompanyKYCView />
            ) : tab === "security" ? (
              <SecuritySettings embedded />
            ) : (
              <div className="tactile-card p-8 text-center max-w-xl mx-auto" data-testid="company-pending-banner">
                <Clock className="w-12 h-12 text-amber-400 mx-auto mb-4" />
                <h1 className="font-display text-2xl mb-2">{t("company.panel.pending.title")}</h1>
                <p className="text-neutral-400 text-sm">
                  {t("company.panel.pending.body")}
                </p>
                <p className="text-neutral-400 text-sm mt-4">{t("company.panel.pending.prep")}</p>
                <div className="flex flex-wrap gap-3 justify-center mt-2">
                  <button onClick={() => go("kyc")} data-testid="company-pending-goto-kyc"
                    className="text-[#8B5CF6] underline underline-offset-2 hover:text-[#A78BFA]">
                    {t("company.panel.pending.kybLink")}
                  </button>
                  <button onClick={() => go("security")} data-testid="company-pending-goto-security"
                    className="text-[#8B5CF6] underline underline-offset-2 hover:text-[#A78BFA]">
                    {t("company.panel.pending.securityLink")}
                  </button>
                </div>
              </div>
            )}
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
                  <tItem.icon className="w-4 h-4" /> {tabLabel(tItem)}
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
                  <tItem.icon className="w-4 h-4" /> {tabLabel(tItem)}
                </button>
              ))}
            </nav>

            {tab === "overview" && (
              <div className="space-y-6" data-testid="company-overview">
                <h1 className="font-display text-3xl">{t("company.panel.overview.title")}</h1>
                <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  <button onClick={() => go("stores")} className="tactile-card p-6 text-left hover:border-[#8B5CF6]/40 transition-colors" data-testid="company-stat-stores">
                    <Store className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.stores_count ?? "—"}</div>
                    <div className="micro-label text-neutral-500 mt-1">{t("company.panel.overview.stores")}</div>
                  </button>
                  <button onClick={() => go("products")} className="tactile-card p-6 text-left hover:border-[#8B5CF6]/40 transition-colors" data-testid="company-stat-products">
                    <Boxes className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.products_count ?? "—"}</div>
                    <div className="micro-label text-neutral-500 mt-1">{t("company.panel.overview.products")}</div>
                  </button>
                  <button onClick={() => go("services")} className="tactile-card p-6 text-left hover:border-[#8B5CF6]/40 transition-colors" data-testid="company-stat-services">
                    <CalendarClock className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.services_count ?? "—"}</div>
                    <div className="micro-label text-neutral-500 mt-1">{t("company.panel.overview.services")}</div>
                  </button>
                  <div className="tactile-card p-6" data-testid="company-stat-commission">
                    <Building2 className="w-7 h-7 text-[#8B5CF6] mb-3" />
                    <div className="font-display text-3xl">{summary?.commission_pct ?? "—"}%</div>
                    <div className="micro-label text-neutral-500 mt-1">{t("company.panel.overview.commission")}</div>
                  </div>
                </div>
                <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-neutral-300">
                  {t("company.panel.overview.info")}
                </div>
              </div>
            )}

            {tab === "stores" && <CompanyStoresView onChanged={loadSummary} />}
            {tab === "products" && <CompanyProductsView onChanged={loadSummary} />}
            {tab === "services" && <CompanyServicesView onChanged={loadSummary} />}
            {tab === "bookings" && <CompanyBookingsView onChanged={loadSummary} />}
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
