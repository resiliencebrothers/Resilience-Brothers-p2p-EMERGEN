import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { CalendarDays, TrendingUp, TrendingDown, Wallet, Globe, FileDown, PackageCheck } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// iter230 — cierre diario de la tienda física: ventas, compras y ganancia
// en CUP efectivo para cuadrar la caja al cerrar (+ línea aparte web USDT).
export default function InventoryCloseTab() {
  const { t } = useTranslation();
  const [date, setDate] = useState(todayLocal());
  const [data, setData] = useState(null);
  const [downloading, setDownloading] = useState(false);

  const downloadPdf = async () => {
    setDownloading(true);
    try {
      const r = await axios.get(`${API}/admin/inventory/daily-close.pdf`, {
        params: { date }, responseType: "blob", withCredentials: true,
      });
      const url = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cierre_tienda_${date}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("inventory.close.pdfDone"));
    } catch {
      toast.error(t("inventory.close.pdfError"));
    } finally { setDownloading(false); }
  };

  const load = useCallback(() => {
    axios.get(`${API}/admin/inventory/daily-close`, { params: { date }, withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null));
  }, [date]);
  useEffect(() => { load(); }, [load]);

  if (!data) return <p className="text-neutral-500 text-sm py-8 text-center" data-testid="close-loading">…</p>;
  const { fisica, web } = data;
  const recogidas = data.recogidas || { num: 0, unidades: 0, total_usdt: 0, detalle: [] };
  const cur = data.store_currency;
  const empty = fisica.num_ventas === 0 && fisica.num_compras === 0 && web.num_ventas === 0 && recogidas.num === 0;

  const kpi = (testid, Icon, label, value, sub, color) => (
    <div className="tactile-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 micro-label text-neutral-500"><Icon className="w-3.5 h-3.5" /> {label}</div>
      <p className={`font-display text-2xl mt-1 ${color || "text-white"}`}>{value}</p>
      <p className="text-[0.65rem] text-neutral-500">{sub}</p>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="inventory-close-tab">
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <Label className="micro-label text-neutral-500 flex items-center gap-1"><CalendarDays className="w-3.5 h-3.5" /> {t("inventory.close.dateLabel")}</Label>
          <Input data-testid="close-date-input" type="date" value={date} max={todayLocal()}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono h-10 w-[180px]" />
        </div>
        <p className="text-xs text-neutral-500 pb-2">{t("inventory.close.hint")}</p>
        <Button data-testid="close-pdf-btn" onClick={downloadPdf} disabled={downloading}
          variant="outline" size="sm" className="rounded-none border-white/10 text-xs mb-1 ml-auto">
          <FileDown className="w-3.5 h-3.5 mr-1" /> {downloading ? "…" : t("inventory.close.downloadPdf")}
        </Button>
      </div>

      {empty ? (
        <div className="tactile-card p-10 text-center text-neutral-500 text-sm" data-testid="close-empty">
          {t("inventory.close.empty")}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {kpi("close-kpi-ventas", TrendingUp, t("inventory.close.sales"),
              `${fmt(fisica.ventas)} ${cur}`,
              t("inventory.close.salesSub", { units: fisica.unidades_vendidas, count: fisica.num_ventas }),
              "text-emerald-400")}
            {kpi("close-kpi-compras", TrendingDown, t("inventory.close.purchases"),
              `${fmt(fisica.compras)} ${cur}`,
              t("inventory.close.purchasesSub", { units: fisica.unidades_compradas, count: fisica.num_compras }),
              "text-amber-400")}
            {kpi("close-kpi-ganancia", TrendingUp, t("inventory.close.profit"),
              `${fmt(fisica.ganancia)} ${cur}`, t("inventory.close.profitSub"),
              fisica.ganancia >= 0 ? "text-emerald-400" : "text-red-400")}
            {kpi("close-kpi-caja", Wallet, t("inventory.close.netCash"),
              `${fisica.caja_neta >= 0 ? "+" : ""}${fmt(fisica.caja_neta)} ${cur}`,
              t("inventory.close.netCashSub"),
              fisica.caja_neta >= 0 ? "text-emerald-400" : "text-red-400")}
          </div>

          <div className="tactile-card p-4 flex items-center gap-4 flex-wrap" data-testid="close-web-line">
            <div className="flex items-center gap-2 micro-label text-neutral-500"><Globe className="w-3.5 h-3.5" /> {t("inventory.close.webSales")}</div>
            <p className="font-display text-lg text-[#8B5CF6]">{fmt(web.ventas_usdt)} USDT</p>
            <p className="text-xs text-neutral-500 font-mono">≈ {fmt(web.ventas_store)} {cur} · {t("inventory.close.webSub", { units: web.unidades, count: web.num_ventas })}</p>
          </div>

          <div className="tactile-card p-4" data-testid="close-pickups-section">
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2 micro-label text-neutral-500"><PackageCheck className="w-3.5 h-3.5" /> {t("inventory.close.pickupsTitle")}</div>
              <p className="font-display text-lg text-[#8B5CF6]">{recogidas.unidades} ud.</p>
              <p className="text-xs text-neutral-500 font-mono">
                {t("inventory.close.pickupsSub", { count: recogidas.num })} · {fmt(recogidas.total_usdt)} USDT
              </p>
            </div>
            {recogidas.detalle.length > 0 && (
              <table className="w-full text-sm mt-3">
                <thead>
                  <tr className="text-left micro-label text-neutral-500 border-b border-white/10">
                    <th className="py-1.5">{t("inventory.close.pickupClient")}</th>
                    <th>{t("inventory.control.product")}</th>
                    <th className="text-right">{t("inventory.close.units")}</th>
                    <th className="text-right">USDT</th>
                  </tr>
                </thead>
                <tbody>
                  {recogidas.detalle.map((p) => (
                    <tr key={p.id} className="border-b border-white/5" data-testid={`close-pickup-row-${p.id}`}>
                      <td className="py-1.5">{p.user_name}</td>
                      <td className="text-neutral-400">{p.product_name}{p.store_name ? <span className="text-[0.6rem] text-neutral-600"> · {p.store_name}</span> : null}</td>
                      <td className="text-right font-mono">{p.quantity}</td>
                      <td className="text-right font-mono text-[#8B5CF6]">{fmt(p.total_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {data.productos.length > 0 && (
            <div className="tactile-card p-4" data-testid="close-products-table">
              <p className="micro-label text-neutral-500 mb-2">{t("inventory.close.soldTitle")}</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left micro-label text-neutral-500 border-b border-white/10">
                    <th className="py-1.5">{t("inventory.control.product")}</th>
                    <th className="text-right">{t("inventory.close.units")}</th>
                    <th className="text-right">{t("inventory.close.totalCol", { cur })}</th>
                    <th className="text-right">{t("inventory.close.profitCol")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.productos.map((p) => (
                    <tr key={p.product_id} className="border-b border-white/5" data-testid={`close-product-row-${p.product_id}`}>
                      <td className="py-1.5">{p.name}</td>
                      <td className="text-right font-mono">
                        {p.unidades + p.unidades_web}
                        {p.unidades_web > 0 && <span className="text-[0.6rem] text-[#8B5CF6] ml-1">({p.unidades_web} web)</span>}
                      </td>
                      <td className="text-right font-mono">{fmt(p.total)}</td>
                      <td className={`text-right font-mono ${p.ganancia >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(p.ganancia)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {data.compras_detalle.length > 0 && (
            <div className="tactile-card p-4" data-testid="close-purchases-table">
              <p className="micro-label text-neutral-500 mb-2">{t("inventory.close.boughtTitle")}</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left micro-label text-neutral-500 border-b border-white/10">
                    <th className="py-1.5">{t("inventory.control.product")}</th>
                    <th className="text-right">{t("inventory.close.units")}</th>
                    <th className="text-right">{t("inventory.close.totalCol", { cur })}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.compras_detalle.map((p) => (
                    <tr key={p.product_id} className="border-b border-white/5" data-testid={`close-purchase-row-${p.product_id}`}>
                      <td className="py-1.5">{p.name}</td>
                      <td className="text-right font-mono">{p.unidades}</td>
                      <td className="text-right font-mono text-amber-400">{fmt(p.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
