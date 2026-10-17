import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Wallet, Calculator, Wrench } from "lucide-react";
import CashBoxView from "@/pages/dashboard/cashbox/CashBoxView";
import ProfitCalculatorSection from "@/pages/dashboard/ProfitCalculatorSection";

// Herramientas — módulos operativos financieros (Caja de efectivo +
// Rentabilidad) que no tocan los balances operativos de la plataforma pero
// facilitan el negocio del cliente. Compartido por VIP (dashboard) y Empresa.
const SUBTABS = [
  { id: "cashbox", icon: Wallet },
  { id: "profitability", icon: Calculator },
];

export default function ToolsPanel({ heading = true }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("cashbox");

  return (
    <div className="space-y-6" data-testid="tools-panel">
      {heading && (
        <div>
          <div className="micro-label text-[#8B5CF6] flex items-center gap-2">
            <Wrench className="w-3.5 h-3.5" /> {t("tools.eyebrow")}
          </div>
          <h1 className="font-display text-3xl mt-1">{t("tools.title")}</h1>
          <p className="text-sm text-neutral-400 mt-1 max-w-2xl">{t("tools.subtitle")}</p>
        </div>
      )}

      <div className="flex gap-1 flex-wrap border-b border-white/10">
        {SUBTABS.map((s) => (
          <button
            key={s.id}
            data-testid={`tools-subtab-${s.id}`}
            onClick={() => setTab(s.id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
              tab === s.id
                ? "border-[#8B5CF6] text-white"
                : "border-transparent text-white/50 hover:text-white"
            }`}
          >
            <s.icon className="w-4 h-4" /> {t(`tools.tabs.${s.id}`)}
          </button>
        ))}
      </div>

      {tab === "cashbox" && (
        <div data-testid="tools-cashbox-panel">
          <CashBoxView />
        </div>
      )}
      {tab === "profitability" && (
        <div data-testid="tools-profitability-panel">
          <ProfitCalculatorSection />
        </div>
      )}
    </div>
  );
}
