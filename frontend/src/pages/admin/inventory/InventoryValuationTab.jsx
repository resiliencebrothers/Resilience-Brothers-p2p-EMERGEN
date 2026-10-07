import { useCallback, useEffect, useState, Fragment } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import {
  Download, Layers, Package, Coins, Percent, Snowflake, Flame, Tag,
  ChevronDown, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { fmtUnitsBreakdown, unitAbbr } from "@/utils/units";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const WINDOWS = [30, 60, 90];

const CAP = {
  activo: { key: "capActivo", cls: "text-emerald-400 border-emerald-500/30" },
  lento: { key: "capLento", cls: "text-amber-300 border-amber-500/30" },
  sin_ventas: { key: "capSinVentas", cls: "text-red-400 border-red-500/30" },
  vacio: { key: "capVacio", cls: "text-neutral-500 border-white/10" },
};

// iter321/322 (IPV Fase 2) — valoración del inventario: WAC + detalle de lotes
// (FIFO), margen esperado por lote y cruce de rotación con costo para detectar
// capital inmovilizado en mercancía de baja venta.
export default function InventoryValuationTab() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [exporting, setExporting] = useState(false);
  const [window_, setWindow] = useState(30);
  const [onlyImmob, setOnlyImmob] = useState(false);
  const [applying, setApplying] = useState(null);
  const [clearing, setClearing] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/admin/inventory/valuation`, {
      params: { window: window_ }, withCredentials: true,
    }).then((r) => setData(r.data)).catch(() => setData(null));
  }, [window_]);
  useEffect(() => { load(); }, [load]);
  useLiveEvent("products_changed", load);

  const toggle = (id) => setExpanded((e) => ({ ...e, [id]: !e[id] }));

  const exportCsv = async () => {
    setExporting(true);
    try {
      const r = await axios.get(`${API}/admin/inventory/valuation.csv`, {
        params: { window: window_ }, responseType: "blob", withCredentials: true,
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

  // iter323 — aplicar el precio de liquidación sugerido (libera caja).
  const applyLiquidation = async (pid) => {
    setApplying(pid);
    try {
      const r = await axios.post(`${API}/admin/inventory/products/${pid}/apply-liquidation`,
        {}, { params: { window: window_ }, withCredentials: true });
      toast.success(t("inventory.valuation.liqApplied", { price: fmt(r.data.new_price), pct: r.data.discount_pct }));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("inventory.valuation.liqError")); }
    finally { setApplying(null); }
  };

  // iter324 — retirar la etiqueta de oferta (mantiene el precio rebajado).
  const clearOffer = async (pid) => {
    setClearing(pid);
    try {
      await axios.post(`${API}/admin/inventory/products/${pid}/clear-offer`, {}, { withCredentials: true });
      toast.success(t("inventory.valuation.offerCleared"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("inventory.valuation.liqError")); }
    finally { setClearing(null); }
  };

  if (!data) return <p className="text-neutral-500 text-sm py-8 text-center" data-testid="valuation-loading">…</p>;
  const { products, totals } = data;
  const shown = onlyImmob ? products.filter((p) => p.immobilized) : products;

  const kpi = (testid, Icon, label, value, color, sub) => (
    <div className="tactile-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 micro-label text-neutral-500"><Icon className="w-3.5 h-3.5" /> {label}</div>
      <p className={`font-display text-xl mt-1 ${color || "text-white"}`}>{value}</p>
      {sub && <p className="text-[0.6rem] text-neutral-500 mt-0.5">{sub}</p>}
    </div>
  );

  return (
    <div className="space-y-4" data-testid="valuation-tab">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 className="font-display text-base">{t("inventory.valuation.title")}</h3>
          <p className="text-[0.65rem] text-neutral-500 max-w-[560px] mt-1">{t("inventory.valuation.hint")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center border border-white/10" data-testid="valuation-window">
            {WINDOWS.map((w) => (
              <button key={w} data-testid={`valuation-window-${w}`} onClick={() => setWindow(w)}
                className={`px-2.5 py-1.5 text-xs transition-colors ${window_ === w ? "bg-[#8B5CF6] text-white" : "text-neutral-400 hover:text-white"}`}>
                {t("inventory.valuation.daysN", { n: w })}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" disabled={exporting} data-testid="valuation-csv-btn"
            onClick={exportCsv} className="rounded-none border-white/10 text-xs">
            <Download className="w-3.5 h-3.5 mr-1" /> {t("inventory.valuation.csvBtn")}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {kpi("valuation-total-products", Package, t("inventory.valuation.totProducts"), totals.num_products)}
        {kpi("valuation-total-units", Layers, t("inventory.valuation.totUnits"), fmtUnitsBreakdown(totals.units_by_unit))}
        {kpi("valuation-total-wac", Coins, t("inventory.valuation.totWac"), fmt(totals.value_wac), "text-emerald-400")}
        {kpi("valuation-total-lots", Coins, t("inventory.valuation.totLots"), fmt(totals.value_lots), "text-[#8B5CF6]")}
        {kpi("valuation-total-margin", Percent, t("inventory.valuation.totMargin"), fmt(totals.expected_margin), "text-emerald-300")}
        {kpi("valuation-total-immob", Snowflake, t("inventory.valuation.totImmob"), fmt(totals.immobilized_value), "text-red-400",
          t("inventory.valuation.immobCount", { n: totals.immobilized_count }))}
      </div>

      <div className="flex items-center justify-between flex-wrap gap-2">
        {totals.stock_sin_lote > 0 ? (
          <p className="text-[0.65rem] text-amber-300/80" data-testid="valuation-sin-lote-total">
            {t("inventory.valuation.sinLoteTotal", { n: totals.stock_sin_lote })}
          </p>
        ) : <span />}
        <button data-testid="valuation-only-immob" onClick={() => setOnlyImmob((v) => !v)}
          className={`text-xs px-2.5 py-1.5 border transition-colors ${onlyImmob ? "bg-red-500/10 text-red-300 border-red-500/30" : "border-white/10 text-neutral-400 hover:text-white"}`}>
          <Snowflake className="w-3 h-3 inline mr-1" /> {t("inventory.valuation.onlyImmob")}
        </button>
      </div>

      {onlyImmob && totals.immobilized_count > 0 && (
        <div className="tactile-card p-4 border-l-2 border-red-500/50" data-testid="valuation-liq-summary">
          <p className="text-sm text-neutral-200">
            <Flame className="w-4 h-4 inline mr-1.5 text-red-400" />
            {t("inventory.valuation.liqSummary", {
              cash: fmt(totals.immobilized_value),
              n: totals.immobilized_count,
              recovery: fmt(totals.liquidation_recovery),
            })}
          </p>
        </div>
      )}

      <div className="tactile-card overflow-auto max-h-[60vh]" data-testid="valuation-table">
        <table className="w-full text-sm min-w-[1040px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500 w-8"></th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("inventory.valuation.colProduct")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colStock")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colWac")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colMargin")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colValueWac")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colValueLots")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colSold")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("inventory.valuation.colStatus")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("inventory.valuation.colLots")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan="10" className="text-center text-neutral-500 py-8" data-testid="valuation-empty">{t("inventory.valuation.empty")}</td></tr>
            )}
            {shown.map((p) => {
              const cap = CAP[p.capital_status] || CAP.vacio;
              return (
                <Fragment key={p.product_id}>
                  <tr className={`border-b border-white/5 ${p.immobilized ? "bg-red-500/[0.04]" : ""}`} data-testid={`valuation-row-${p.product_id}`}>
                    <td className="px-3 py-3">
                      <button data-testid={`valuation-expand-${p.product_id}`} onClick={() => toggle(p.product_id)}
                        className="text-neutral-400 hover:text-white" title={t("inventory.valuation.lotsTitle")}>
                        {expanded[p.product_id] ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                      </button>
                    </td>
                    <td className="px-3 py-3">
                      {p.name}
                      {!p.is_active && <span className="ml-2 text-[0.6rem] uppercase text-neutral-500">({t("inventory.control.inactive")})</span>}
                      {p.stock_sin_lote > 0 && (
                        <span className="ml-2 text-[0.6rem] uppercase text-amber-300 border border-amber-500/30 px-1" data-testid={`valuation-sin-lote-${p.product_id}`}>
                          {t("inventory.valuation.sinLote", { n: p.stock_sin_lote })}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-right" data-testid={`valuation-stock-${p.product_id}`}>{p.stock} <span className="text-[0.6rem] text-neutral-500">{unitAbbr(p.unit)}</span></td>
                    <td className="px-3 py-3 font-mono text-right text-neutral-300" data-testid={`valuation-wac-${p.product_id}`}>{fmt(p.wac)}</td>
                    <td className="px-3 py-3 font-mono text-right text-emerald-300">{p.margin_pct_wac != null ? `${fmt(p.margin_pct_wac)}%` : "—"}</td>
                    <td className="px-3 py-3 font-mono text-right text-emerald-400">{fmt(p.inventory_value_wac)}</td>
                    <td className="px-3 py-3 font-mono text-right text-[#8B5CF6]">{fmt(p.inventory_value_lots)}</td>
                    <td className="px-3 py-3 font-mono text-right" title={p.sellout_days != null ? t("inventory.valuation.selloutHint", { n: p.sellout_days }) : ""}>{p.sold_window}</td>
                    <td className="px-3 py-3">
                      <span className={`text-[0.6rem] uppercase tracking-wide px-1.5 py-0.5 border ${cap.cls}`} data-testid={`valuation-status-${p.product_id}`}>
                        {t(`inventory.valuation.${cap.key}`)}
                      </span>
                      {p.on_offer ? (
                        <span className="block mt-1 text-[0.6rem] text-[#C4B5FD]" data-testid={`valuation-offer-badge-${p.product_id}`}>
                          <Tag className="w-2.5 h-2.5 inline mr-0.5" />{t("inventory.valuation.offerTag")} −{p.offer_discount_pct}%
                        </span>
                      ) : p.liquidation && !p.liquidation.loss && p.liquidation.discount_pct > 0 && (
                        <span className="block mt-1 text-[0.6rem] text-red-300 font-mono" data-testid={`valuation-liq-badge-${p.product_id}`}>
                          −{p.liquidation.discount_pct}%
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-right">{p.num_lotes}</td>
                  </tr>
                  {expanded[p.product_id] && (
                    <tr className="bg-[#0a0a0a]/40" data-testid={`valuation-lots-${p.product_id}`}>
                      <td></td>
                      <td colSpan="9" className="px-3 py-3">
                        {p.on_offer ? (
                          <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-3 mb-3 flex items-center justify-between flex-wrap gap-2" data-testid={`valuation-offer-${p.product_id}`}>
                            <span className="text-xs text-[#C4B5FD]">
                              <Tag className="w-3.5 h-3.5 inline mr-1" />
                              {t("inventory.valuation.offerActive", { pct: p.offer_discount_pct })}
                            </span>
                            <Button size="sm" variant="outline" data-testid={`valuation-offer-clear-${p.product_id}`}
                              disabled={clearing === p.product_id} onClick={() => clearOffer(p.product_id)}
                              className="rounded-none border-white/10 text-xs h-8">
                              {clearing === p.product_id ? "…" : t("inventory.valuation.offerClear")}
                            </Button>
                          </div>
                        ) : p.liquidation && (
                          <div className="border border-red-500/20 bg-red-500/5 p-3 mb-3 flex items-center justify-between flex-wrap gap-2" data-testid={`valuation-liq-${p.product_id}`}>
                            <div className="text-xs leading-relaxed">
                              {p.liquidation.loss ? (
                                <span className="text-red-300" data-testid={`valuation-liq-loss-${p.product_id}`}>
                                  <Flame className="w-3.5 h-3.5 inline mr-1" />{t("inventory.valuation.liqLoss")}
                                </span>
                              ) : p.liquidation.discount_pct > 0 ? (
                                <span className="text-neutral-200">
                                  <Flame className="w-3.5 h-3.5 inline mr-1 text-red-400" />
                                  {t("inventory.valuation.liqSuggest", { pct: p.liquidation.discount_pct, from: fmt(p.price_usd), to: fmt(p.liquidation.suggested_price) })}
                                  <span className="block text-[0.65rem] text-neutral-500 mt-0.5">
                                    {t("inventory.valuation.liqFree", { cash: fmt(p.liquidation.cash_to_free), rev: fmt(p.liquidation.estimated_revenue) })}
                                  </span>
                                </span>
                              ) : (
                                <span className="text-neutral-400">{t("inventory.valuation.liqNoRoom")}</span>
                              )}
                            </div>
                            {!p.liquidation.loss && p.liquidation.discount_pct > 0 && (
                              <Button size="sm" data-testid={`valuation-liq-apply-${p.product_id}`} disabled={applying === p.product_id}
                                onClick={() => applyLiquidation(p.product_id)}
                                className="bg-red-500/80 hover:bg-red-500 text-white rounded-none text-xs h-8">
                                {applying === p.product_id ? "…" : t("inventory.valuation.liqApply", { price: fmt(p.liquidation.suggested_price) })}
                              </Button>
                            )}
                          </div>
                        )}
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
                                <th className="text-right">{t("inventory.valuation.lotMargin")}</th>
                                <th className="text-right">{t("inventory.valuation.lotMarginRem")}</th>
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
                                  <td className={`text-right font-mono ${l.margin_unit >= 0 ? "text-emerald-300" : "text-red-400"}`}>{l.margin_pct != null ? `${fmt(l.margin_pct)}%` : "—"}</td>
                                  <td className={`text-right font-mono ${l.remaining_margin >= 0 ? "text-emerald-300" : "text-red-400"}`}>{fmt(l.remaining_margin)}</td>
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
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
