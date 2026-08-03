/**
 * HistorySectionTabs — shared sub-navigation for the unified "Mis Órdenes"
 * hub (órdenes + transacciones). Also hosts the quick-action buttons that
 * replaced the removed sidebar entries: Intercambio (all clients),
 * Envío por Lotes + Solicitud de Fondos (VIP only).
 */
import { NavLink, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { ListOrdered, Receipt, ArrowLeftRight, Layers, HandCoins } from "lucide-react";

export default function HistorySectionTabs() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isVip = user?.role === "vip";
  const isStaff = user?.role === "admin" || user?.role === "employee";

  const TABS = [
    { to: "/dashboard/orders", icon: ListOrdered, label: t("historyHub.ordersTab"), testid: "history-tab-orders" },
    { to: "/dashboard/transactions", icon: Receipt, label: t("historyHub.txTab"), testid: "history-tab-transactions" },
  ];

  const ACTIONS = [
    { to: "/dashboard/exchange", icon: ArrowLeftRight, label: t("dashboard.newExchange"), testid: "history-action-exchange", primary: true },
    ...(isVip ? [
      { to: "/dashboard/batches", icon: Layers, label: t("sidebar.client.batches"), testid: "history-action-batches" },
      { to: "/dashboard/capital-requests", icon: HandCoins, label: t("sidebar.client.capitalRequests"), testid: "history-action-capital" },
    ] : []),
  ];

  return (
    <div className="mb-6" data-testid="history-section-tabs">
      <div className="text-[11px] font-semibold tracking-[0.22em] text-violet-400 uppercase mb-2">
        {t("historyHub.breadcrumb")}
      </div>
      <nav
        className="flex items-center gap-1 border-b border-white/10 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label={t("historyHub.breadcrumb")}
      >
        {TABS.map(({ to, icon: Icon, label, testid }) => (
          <NavLink
            key={to}
            to={to}
            end
            role="tab"
            data-testid={testid}
            className={({ isActive }) =>
              "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap " +
              "transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500 " +
              (isActive
                ? "text-violet-300 after:absolute after:left-3 after:right-3 after:-bottom-[1px] after:h-[2px] after:bg-violet-500 after:rounded-full"
                : "text-white/50 hover:text-white hover:bg-white/[0.03] rounded-md")
            }
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      {!isStaff && (
        <div className="flex flex-wrap gap-2 mt-4" data-testid="history-actions">
          {ACTIONS.map((a) => (
            <Link
              key={a.to}
              to={a.to}
              data-testid={a.testid}
              className={
                a.primary
                  ? "inline-flex items-center gap-2 bg-[#8B5CF6] hover:bg-[#7C3AED] text-white px-4 py-2 font-mono text-xs uppercase tracking-wider transition-colors"
                  : "inline-flex items-center gap-2 border border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 px-4 py-2 font-mono text-xs uppercase tracking-wider transition-colors"
              }
            >
              <a.icon className="w-4 h-4" /> {a.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
