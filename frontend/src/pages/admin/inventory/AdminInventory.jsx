import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import AdminPageHeader from "@/components/AdminPageHeader";
import { Button } from "@/components/ui/button";
import { ClipboardList, Download, FileSpreadsheet, Tags } from "lucide-react";
import { toast } from "sonner";
import InventoryControlTab from "./InventoryControlTab";
import InventoryMovementsTab from "./InventoryMovementsTab";
import InventoryDashboardTab from "./InventoryDashboardTab";
import InventoryScanTab from "./InventoryScanTab";
import InventoryCloseTab from "./InventoryCloseTab";
import InventoryStoresTab from "./InventoryStoresTab";
import LabelsDialog from "./LabelsDialog";

// iter217 — Control de flujo de inventario de la tienda física (réplica del
// Excel del operador: Control Inventario + Movimientos + Dashboard).
const TABS = ["control", "scan", "movements", "close", "stores", "dashboard"];

export default function AdminInventory() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("control");
  const [exporting, setExporting] = useState(false);
  const [labelsOpen, setLabelsOpen] = useState(false);

  // iter220 — descarga CSV/Excel para los archivos contables del operador.
  const download = async (path, filename) => {
    setExporting(true);
    try {
      const r = await axios.get(`${API}${path}`, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("inventory.export.done"));
    } catch {
      toast.error(t("inventory.export.error"));
    } finally { setExporting(false); }
  };

  const ts = new Date().toISOString().slice(0, 10);

  return (
    <div data-testid="admin-inventory">
      <AdminPageHeader
        eyebrow={t("inventory.eyebrow")}
        title={t("inventory.title")}
        icon={ClipboardList}
      />
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <div className="flex gap-2 flex-wrap">
          {TABS.map((k) => (
            <button
              key={k}
              data-testid={`inventory-tab-${k}`}
              onClick={() => setTab(k)}
              className={`px-4 py-2 text-xs uppercase tracking-wider border transition-colors ${
                tab === k
                  ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10"
                  : "border-white/10 text-neutral-400 hover:text-white"
              }`}
            >
              {t(`inventory.tabs.${k}`)}
            </button>
          ))}
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" data-testid="labels-open-btn"
            onClick={() => setLabelsOpen(true)}
            className="rounded-none border-white/10 text-xs">
            <Tags className="w-3.5 h-3.5 mr-1" /> {t("inventory.labels.btn")}
          </Button>
          <Button variant="outline" size="sm" disabled={exporting} data-testid="export-control-csv-btn"
            onClick={() => download("/admin/inventory/export.csv?dataset=control", `inventario_control_${ts}.csv`)}
            className="rounded-none border-white/10 text-xs">
            <Download className="w-3.5 h-3.5 mr-1" /> {t("inventory.export.controlCsv")}
          </Button>
          <Button variant="outline" size="sm" disabled={exporting} data-testid="export-movements-csv-btn"
            onClick={() => download("/admin/inventory/export.csv?dataset=movements", `inventario_movimientos_${ts}.csv`)}
            className="rounded-none border-white/10 text-xs">
            <Download className="w-3.5 h-3.5 mr-1" /> {t("inventory.export.movementsCsv")}
          </Button>
          <Button size="sm" disabled={exporting} data-testid="export-xlsx-btn"
            onClick={() => download("/admin/inventory/export.xlsx", `inventario_${ts}.xlsx`)}
            className="bg-emerald-700 hover:bg-emerald-600 text-white rounded-none text-xs">
            <FileSpreadsheet className="w-3.5 h-3.5 mr-1" /> {t("inventory.export.fullXlsx")}
          </Button>
        </div>
      </div>
      {tab === "control" && <InventoryControlTab />}
      {tab === "scan" && <InventoryScanTab />}
      {tab === "movements" && <InventoryMovementsTab />}
      {tab === "close" && <InventoryCloseTab />}
      {tab === "stores" && <InventoryStoresTab />}
      {tab === "dashboard" && <InventoryDashboardTab />}
      <LabelsDialog open={labelsOpen} onOpenChange={setLabelsOpen} />
    </div>
  );
}
