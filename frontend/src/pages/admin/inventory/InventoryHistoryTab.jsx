import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { CalendarClock, Download, Boxes, Coins, AlertTriangle, ScanLine } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const qty = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });
const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// iter328 (IPV Fase 1) — Corte histórico: reconstruye existencia y valor (CUP)
// del inventario a una fecha de corte desde los movimientos, y valora las
// diferencias de conteo del día al costo de referencia guardado.
export default function InventoryHistoryTab() {
  const { t } = useTranslation();
  const [cutoff, setCutoff] = useState(todayLocal());
  const [start, setStart] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/admin/inventory/cutoff-report`, {
      params: { date: cutoff, ...(start ? { start } : {}) },
      withCredentials: true,
    }).then((r) => setData(r.data))
      .catch((e) => {
        setData(null);
        toast.error(e.response?.data?.detail || t("inventory.history.loadError"));
      })
      .finally(() => setLoading(false));
  }, [cutoff, start, t]);
  useEffect(() => { load(); }, [load]);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const r = await axios.get(`${API}/admin/inventory/cutoff-report.csv`, {
        params: { date: cutoff, ...(start ? { start } : {}) },
        responseType: "blob", withCredentials: true,
      });
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `inventario_corte_${cutoff}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("inventory.export.done"));
    } catch { toast.error(t("inventory.export.error")); }
    finally { setExporting(false); }
  };

  const tot = data?.totals;
  const cur = data?.currency || "CUP";

  return (
    <div className="space-y-5" data-testid="inventory-history-tab">
      {/* Controles de corte */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label className="micro-label text-neutral-500 flex items-center gap-1">
            <CalendarClock className="w-3.5 h-3.5" /> {t("inventory.history.cutoff")}
          </Label>
          <Input type="date" value={cutoff} max={todayLocal()}
            onChange={(e) => setCutoff(e.target.value)}
            data-testid="history-cutoff-input"
            className="bg-[#14122A] border-white/10 text-white rounded-none w-[170px]" />
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("inventory.history.start")}</Label>
          <Input type="date" value={start} max={cutoff}
            onChange={(e) => setStart(e.target.value)}
            data-testid="history-start-input"
            className="bg-[#14122A] border-white/10 text-white rounded-none w-[170px]" />
        </div>
        {start && (
          <Button variant="outline" size="sm" onClick={() => setStart("")}
            data-testid="history-clear-start-btn"
            className="rounded-none border-white/10 text-xs">
            {t("inventory.history.clearStart")}
          </Button>
        )}
        <Button size="sm" disabled={exporting || !data?.products?.length}
          onClick={exportCsv} data-testid="history-export-csv-btn"
          className="ml-auto bg-emerald-700 hover:bg-emerald-600 text-white rounded-none text-xs">
          <Download className="w-3.5 h-3.5 mr-1" /> {t("inventory.history.exportCsv")}
        </Button>
      </div>

      <p className="text-[0.7rem] text-neutral-500 leading-relaxed">
        {t("inventory.history.hint", { cur })}
      </p>

      {/* Resumen */}
      {tot && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="history-summary">
          <Card icon={Boxes} label={t("inventory.history.sumProducts")} value={tot.num_products} />
          <Card icon={ScanLine} label={t("inventory.history.sumUnits")} value={qty(tot.units)} />
          <Card icon={Coins} label={t("inventory.history.sumValue", { cur })} value={fmt(tot.value)} accent />
          <Card icon={Coins} label={t("inventory.history.sumDiffValue", { cur })}
            value={fmt(tot.diff_value)}
            tone={tot.diff_value < 0 ? "neg" : tot.diff_value > 0 ? "pos" : "mut"} />
        </div>
      )}

      {/* Aviso de cobertura parcial */}
      {tot?.partial_count > 0 && (
        <div className="flex items-start gap-2 border border-amber-500/30 bg-amber-500/5 px-3 py-2"
          data-testid="history-partial-warning">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-[0.7rem] text-amber-200/90">
            {t("inventory.history.partialWarn", { n: tot.partial_count })}
            {data?.coverage_from && " " + t("inventory.history.coverageFrom", { date: data.coverage_from })}
          </p>
        </div>
      )}

      {/* Tabla */}
      <div className="overflow-x-auto border border-white/10">
        <table className="w-full text-xs" data-testid="history-table">
          <thead>
            <tr className="bg-white/5 text-neutral-400 uppercase tracking-wider text-[0.6rem]">
              <th className="text-left px-3 py-2">{t("inventory.history.colProduct")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colOpening")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colIn")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colSales")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colMerma")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colConsumo")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colOther")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colAdj")}</th>
              <th className="text-right px-2 py-2 font-semibold">{t("inventory.history.colFinal")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colWac")}</th>
              <th className="text-right px-3 py-2 font-semibold">{t("inventory.history.colValue")}</th>
              <th className="text-right px-2 py-2">{t("inventory.history.colDiff")}</th>
              <th className="text-right px-3 py-2">{t("inventory.history.colDiffValue")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.products || []).map((p) => (
              <tr key={p.product_id} className="border-t border-white/5 hover:bg-white/[0.02]"
                data-testid={`history-row-${p.product_id}`}>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-white">{p.name || "—"}</span>
                    {p.coverage === "parcial" && (
                      <span className="text-[0.55rem] uppercase px-1.5 py-0.5 border border-amber-500/30 text-amber-300"
                        data-testid={`history-partial-${p.product_id}`}>
                        {t("inventory.history.partialTag")}
                      </span>
                    )}
                    {!p.is_active && (
                      <span className="text-[0.55rem] uppercase px-1.5 py-0.5 border border-white/10 text-neutral-500">
                        {t("inventory.history.inactiveTag")}
                      </span>
                    )}
                  </div>
                  {p.category && <span className="text-[0.6rem] text-neutral-500">{p.category}</span>}
                </td>
                <td className="text-right px-2 py-2 text-neutral-400">{qty(p.opening)}</td>
                <td className="text-right px-2 py-2 text-emerald-400/80">{p.entradas ? "+" + qty(p.entradas) : "—"}</td>
                <td className="text-right px-2 py-2 text-neutral-300">{p.ventas ? "−" + qty(p.ventas) : "—"}</td>
                <td className="text-right px-2 py-2 text-neutral-300">{p.merma ? "−" + qty(p.merma) : "—"}</td>
                <td className="text-right px-2 py-2 text-neutral-300">{p.consumo ? "−" + qty(p.consumo) : "—"}</td>
                <td className="text-right px-2 py-2 text-neutral-300">{p.otra_salida ? "−" + qty(p.otra_salida) : "—"}</td>
                <td className="text-right px-2 py-2 text-neutral-300">{p.ajuste_neto ? (p.ajuste_neto > 0 ? "+" : "") + qty(p.ajuste_neto) : "—"}</td>
                <td className="text-right px-2 py-2 font-semibold text-white">{qty(p.final_stock)}</td>
                <td className="text-right px-2 py-2 text-neutral-400">{fmt(p.wac)}</td>
                <td className="text-right px-3 py-2 font-semibold text-[#8B5CF6]">{fmt(p.value)}</td>
                <td className={`text-right px-2 py-2 ${p.count ? (p.count.difference < 0 ? "text-red-400" : p.count.difference > 0 ? "text-emerald-400" : "text-neutral-400") : "text-neutral-600"}`}>
                  {p.count ? (p.count.difference > 0 ? "+" : "") + p.count.difference : "—"}
                </td>
                <td className={`text-right px-3 py-2 ${p.count ? (p.count.difference_value < 0 ? "text-red-400" : p.count.difference_value > 0 ? "text-emerald-400" : "text-neutral-400") : "text-neutral-600"}`}>
                  {p.count ? fmt(p.count.difference_value) : "—"}
                </td>
              </tr>
            ))}
            {!loading && !(data?.products || []).length && (
              <tr><td colSpan={13} className="px-3 py-8 text-center text-neutral-500"
                data-testid="history-empty">{t("inventory.history.empty")}</td></tr>
            )}
            {loading && (
              <tr><td colSpan={13} className="px-3 py-8 text-center text-neutral-500">{t("inventory.history.loading")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Card = ({ icon: Icon, label, value, accent, tone }) => {
  const toneCls = tone === "neg" ? "text-red-400" : tone === "pos" ? "text-emerald-400"
    : accent ? "text-[#8B5CF6]" : "text-white";
  return (
    <div className="border border-white/10 bg-[#14122A] px-3 py-3">
      <div className="flex items-center gap-1.5 text-neutral-500 text-[0.6rem] uppercase tracking-wider">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className={`mt-1 text-lg font-semibold ${toneCls}`}>{value}</div>
    </div>
  );
};
