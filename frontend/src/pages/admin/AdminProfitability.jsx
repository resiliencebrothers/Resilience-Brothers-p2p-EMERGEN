// iter113 — Profitability calculator tab (Fondo de Empresa hub).
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Percent, Plus, FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import AdminPageHeader from "@/components/AdminPageHeader";
import CalculatorPanel from "./profitability/CalculatorPanel";
import ProjectionsTable from "./profitability/ProjectionsTable";
import PairsSummaryTable from "./profitability/PairsSummaryTable";
import OperationsTable from "./profitability/OperationsTable";
import OperationDialog from "./profitability/OperationDialog";
import SettingsDialog from "./profitability/SettingsDialog";
import ProfitabilityPdfDialog from "./profitability/ProfitabilityPdfDialog";
import { useProfitability } from "./profitability/useProfitability";

export default function AdminProfitability() {
  const { t } = useTranslation();
  const p = useProfitability();
  const [pdfOpen, setPdfOpen] = useState(false);

  return (
    <div className="space-y-6" data-testid="admin-profitability">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AdminPageHeader
          eyebrow={t("profitability.eyebrow")}
          title={t("profitability.title")}
          subtitle={t("profitability.subtitle")}
        />
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setPdfOpen(true)} data-testid="profit-pdf-btn">
            <FileDown className="w-4 h-4 mr-1.5" />
            {t("profitability.pdf.btn")}
          </Button>
          <Button variant="outline" onClick={() => p.setSettingsOpen(true)} data-testid="profit-settings-btn">
            <Percent className="w-4 h-4 mr-1.5" />
            {t("profitability.settingsBtn")}
          </Button>
          <Button onClick={() => p.setOpDialogOpen(true)} data-testid="profit-add-op-btn">
            <Plus className="w-4 h-4 mr-1.5" />
            {t("profitability.logBtn")}
          </Button>
        </div>
      </div>

      <CalculatorPanel rates={p.rates} calc={p.calc} setCalc={p.setCalc} pctFor={p.pctFor} />
      <ProjectionsTable calc={p.calc} setCalc={p.setCalc} />
      <PairsSummaryTable rates={p.rates} pctFor={p.pctFor} onLoadToCalc={p.loadPairIntoCalc} />
      <OperationsTable items={p.operations} totals={p.totals} onDelete={p.deleteOperation} />

      <OperationDialog
        open={p.opDialogOpen}
        onOpenChange={p.setOpDialogOpen}
        currencies={p.currencies}
        pctFor={p.pctFor}
        onCreate={p.createOperation}
      />
      <SettingsDialog
        open={p.settingsOpen}
        onOpenChange={p.setSettingsOpen}
        currencies={p.currencies}
        settings={p.settings}
        onSave={p.saveSettings}
      />
      <ProfitabilityPdfDialog open={pdfOpen} onOpenChange={setPdfOpen} />
    </div>
  );
}
