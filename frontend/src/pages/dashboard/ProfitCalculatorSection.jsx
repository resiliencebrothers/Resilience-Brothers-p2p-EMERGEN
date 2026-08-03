// iter116 — VIP-only profitability calculator inside "Activos".
// Pure client-side tool: dual-mode calculator + volume projections. The VIP
// types their OWN prices — no company rates, no transfer % defaults, no
// persistence, no backend calls.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import CalculatorPanel from "@/pages/admin/profitability/CalculatorPanel";
import ProjectionsTable from "@/pages/admin/profitability/ProjectionsTable";

const DEFAULT_CALC = {
  mode: "combined",
  pairId: "", fromCode: "", toCode: "",
  sell: "", buy: "", buyPct: "", sellPct: "",
  qty: "1", opsPerDay: "10", daysPerMonth: "26",
};

export default function ProfitCalculatorSection() {
  const { t } = useTranslation();
  const [calc, setCalc] = useState(DEFAULT_CALC);

  return (
    <div className="space-y-4" data-testid="vip-profit-calculator">
      <p className="text-xs text-neutral-500">{t("assetsView.calcNote")}</p>
      <CalculatorPanel calc={calc} setCalc={setCalc} />
      <ProjectionsTable calc={calc} setCalc={setCalc} />
    </div>
  );
}
