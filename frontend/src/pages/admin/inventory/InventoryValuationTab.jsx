import { useCallback, useEffect, useState, Fragment } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import { Download, Layers, Package, Coins, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// iter321 (IPV Fase 2) — valoración del inventario: costo promedio ponderado
// (WAC) + detalle de lotes (FIFO sobre la existencia actual).
export default function InventoryValuationTab() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [exporting, setExporting] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/admin/inventory/valuation`, { withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null));
  }, []);
  useEffect(() => { load(); }, [load]);
  useLiveEvent("products_changed", load);

  const toggle = (id) => setExpanded((e) => ({ ...e, [id]: !e[id] }));

  const exportCsv = async () => {
    setExporting(true);
    try {
      const r = await axios.get(`${API}/admin/inventory/valuation.csv`, {
        responseType: "blob", withCredentials: true,
      });
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `inventario_valoracion_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("inventory.export.done"));
    } catch { toast.error(t("inventory.export.error")); }
    finally { setExporting(false); }
  };

  if (!data) return <p className="text-neutral-500 text-sm py-8 text-center" data-testid="valuation-loading">…</p>;
  const { products, totals } = data;

  const kpi = (testid, Icon, label, value, color) => (
    <div className="tactile-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 micro-label text-neutral-500"><Icon className="w-3.5 h-3.5" /> {label}</div>
      <p className={`font-display text-2xl mt-1 ${color || "text-white"}`}>{value}</p>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="valuation-tab">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 className="font-display text-base">{t("inventory.valuation.title")}</h3>
          <p className="text-[0.65rem] text-neutral-500 max-w-[560px] mt-1">{t("inventory.valuation.hint")}</p>
        </div>
        <Button variant="outline" size="sm" disabled={exporting} data-testid="valuation-csv-btn"
          onClick={exportCsv} className="rounded-none border-white/10 text-xs">
          <Download className="w-3.5 h-3.5 mr-1" /> {t("inventory.valuation.csvBtn")}
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpi("valuation-total-products", Package, t("inventory.valuation.totProducts"), totals.num_products)}
        {kpi("valuation-total-units", Layers, t("inventory.valuation.totUnits"), totals.units)}
        {kpi("valuation-total-wac", Coins, t("inventory.valuation.totWac"), fmt(totals.value_wac), "text-emerald-400")}
        {kpi("valuation-total-lots", Coins, t("inventory.valuation.totLots"), fmt(totals.value_lots), "text-[#8B5CF6]")}
      </div>
      {totals.stock_sin_lote > 0 && (
        <p className="text-[0.65rem] text-amber-300/80" data-testid="valuation-sin-lote-total">
          {t("inventory.valuation.sinLoteTotal", { n: totals.stock_sin_lote })}
        </p>
      )}

      <div className="tactile-card overflow-auto max-h-[60vh]" data-testid="valuation-table">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500 w-8"></th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.valuation.colProduct")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colStock")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colWac")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colValueWac")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colValueLots")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colLots")}</th>
            </tr>
          </thead>
          <tbody>
            {products.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8" data-testid="valuation-empty">{t("inventory.valuation.empty")}</td></tr>
            )}
            {products.map((p) => (
              <Fragment key={p.product_id}>
                <tr className="border-b border-white/5" data-testid={`valuation-row-${p.product_id}`}>
                  <td className="px-4 py-3">
                    <button data-testid={`valuation-expand-${p.product_id}`} onClick={() => toggle(p.product_id)}
                      className="text-neutral-400 hover:text-white" title={t("inventory.valuation.lotsTitle")}>
                      {expanded[p.product_id] ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    {p.name}
                    {!p.is_active && <span className="ml-2 text-[0.6rem] uppercase text-neutral-500">({t("inventory.control.inactive")})</span>}
                    {p.stock_sin_lote > 0 && (
                      <span className="ml-2 text-[0.6rem] uppercase text-amber-300 border border-amber-500/30 px-1" data-testid={`valuation-sin-lote-${p.product_id}`}>
                        {t("inventory.valuation.sinLote", { n: p.stock_sin_lote })}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-right">{p.stock}</td>
                  <td className="px-4 py-3 font-mono text-right text-neutral-300" data-testid={`valuation-wac-${p.product_id}`}>{fmt(p.wac)}</td>
                  <td className="px-4 py-3 font-mono text-right text-emerald-400">{fmt(p.inventory_value_wac)}</td>
                  <td className="px-4 py-3 font-mono text-right text-[#8B5CF6]">{fmt(p.inventory_value_lots)}</td>
                  <td className="px-4 py-3 font-mono text-right">{p.num_lotes}</td>
                </tr>
                {expanded[p.product_id] && (
                  <tr className="bg-[#0a0a0a]/40" data-testid={`valuation-lots-${p.product_id}`}>
                    <td></td>
                    <td colSpan="6" className="px-4 py-3">
                      {p.lots.length === 0 ? (
                        <p className="text-xs text-neutral-500">{t("inventory.valuation.noLots")}</p>
                      ) : (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left micro-label text-neutral-500 border-b border-white/10">
                              <th className="py-1.5">{t("inventory.valuation.lotDate")}</th>
                              <th>{t("inventory.valuation.lotSource")}</th>
                              <th className="text-right">{t("inventory.valuation.lotCost")}</th>
                              <th className="text-right">{t("inventory.valuation.lotQty")}</th>
                              <th className="text-right">{t("inventory.valuation.lotRemaining")}</th>
                              <th className="text-right">{t("inventory.valuation.lotValue")}</th>
                              <th className="text-right">{t("inventory.valuation.lotAge")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {p.lots.map((l) => (
                              <tr key={l.id} className={`border-b border-white/5 ${l.remaining === 0 ? "text-neutral-600" : ""}`} data-testid={`valuation-lot-row-${l.id}`}>
                                <td className="py-1.5">{(l.received_at || "").slice(0, 10)}</td>
                                <td className="text-neutral-400">{l.source === "alta" ? t("inventory.valuation.srcAlta") : t("inventory.valuation.srcManual")}</td>
                                <td className="text-right font-mono">{fmt(l.unit_cost)}</td>
                                <td className="text-right font-mono">{l.qty}</td>
                                <td className="text-right font-mono text-[#8B5CF6]">{l.remaining}</td>
                                <td className="text-right font-mono">{fmt(l.remaining_value)}</td>
                                <td className="text-right font-mono text-neutral-500">{l.age_days != null ? t("inventory.valuation.days", { n: l.age_days }) : "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
