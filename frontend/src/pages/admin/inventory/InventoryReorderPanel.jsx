import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { PackagePlus, RefreshCw, AlertOctagon } from "lucide-react";
import { fmtQty } from "@/utils/units";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// iter333 (IPV Fase 3) — Alerta de reposición: lista de compra sugerida con
// productos en/bajo su mínimo y la cantidad para volver al nivel objetivo.
export default function InventoryReorderPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/admin/inventory/reorder`, { withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const totals = data?.totals;
  const rows = data?.products || [];

  return (
    <div className="space-y-4" data-testid="inventory-reorder-panel">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="font-display text-lg flex items-center gap-2">
          <PackagePlus className="w-4 h-4 text-[#8B5CF6]" /> {t("inventory.reorder.title")}
        </h3>
        <Button data-testid="reorder-refresh-btn" onClick={load} disabled={loading}
          size="sm" variant="outline" className="ml-auto rounded-none border-white/10 text-xs">
          <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />
          {t("inventory.reorder.refresh")}
        </Button>
      </div>
      <p className="text-[0.7rem] text-neutral-500">{t("inventory.reorder.hint")}</p>

      {totals && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="reorder-summary">
          <Card label={t("inventory.reorder.numProducts")} value={totals.num_products} tone="amber" />
          <Card label={t("inventory.reorder.outOfStock")} value={totals.out_of_stock} tone="red" />
          <Card label={t("inventory.reorder.suggestedUnits")} value={fmt(totals.suggested_units)} />
          <Card label={t("inventory.reorder.restockCost")} value={fmt(totals.restock_cost)} />
        </div>
      )}

      <div className="tactile-card overflow-auto max-h-[45vh]" data-testid="reorder-table">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.reorder.colProduct")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.reorder.colStock")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.reorder.colMin")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.reorder.colTarget")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.reorder.colSuggested")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.reorder.colCost")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (<tr><td colSpan="6" className="text-center text-neutral-500 py-8">…</td></tr>)}
            {!loading && rows.length === 0 && (
              <tr><td colSpan="6" className="text-center text-neutral-500 py-8" data-testid="reorder-empty">{t("inventory.reorder.empty")}</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.product_id} className={`border-b border-white/5 ${r.out_of_stock ? "bg-red-500/5" : ""}`} data-testid={`reorder-row-${r.product_id}`}>
                <td className="px-4 py-3">
                  {r.name}
                  {r.out_of_stock && (
                    <span className="ml-2 text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border bg-red-500/10 text-red-400 border-red-500/30 inline-flex items-center gap-1"
                      data-testid={`reorder-out-${r.product_id}`}>
                      <AlertOctagon className="w-3 h-3" /> {t("inventory.reorder.outTag")}
                    </span>
                  )}
                </td>
                <td className={`px-4 py-3 font-mono text-right ${r.out_of_stock ? "text-red-400" : "text-amber-300"}`}>{fmtQty(r.stock, r.unit)}</td>
                <td className="px-4 py-3 font-mono text-right text-neutral-400">{fmtQty(r.min_stock, r.unit)}</td>
                <td className="px-4 py-3 font-mono text-right text-neutral-400">{fmtQty(r.target, r.unit)}</td>
                <td className="px-4 py-3 font-mono text-right text-[#8B5CF6]" data-testid={`reorder-suggested-${r.product_id}`}>+{fmtQty(r.suggested, r.unit)}</td>
                <td className="px-4 py-3 font-mono text-right">{fmt(r.restock_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Card = ({ label, value, tone }) => {
  const cls = tone === "red" ? "text-red-400" : tone === "amber" ? "text-amber-300" : "text-white";
  return (
    <div className="border border-white/10 bg-[#14122A] px-3 py-3">
      <div className="text-neutral-500 text-[0.6rem] uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-2xl font-display ${cls}`}>{value}</div>
    </div>
  );
};
