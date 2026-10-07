import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { CalendarDays, TrendingUp, TrendingDown, Wallet, Globe, FileDown, PackageCheck, ClipboardCheck, AlertTriangle, PackageMinus, Lock } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// iter230 — cierre diario de la tienda física: ventas, compras y ganancia
// en CUP efectivo para cuadrar la caja al cerrar (+ línea aparte web USDT).
export default function InventoryCloseTab() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [date, setDate] = useState(todayLocal());
  const [data, setData] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadingSheet, setDownloadingSheet] = useState(false);
  // iter320 (IPV) — revisión del cierre: alertas + firma (responsable/revisor/folio).
  const [review, setReview] = useState(null);
  const emptySign = { responsable: "", revisado_por: "", folio: "", note: "" };
  const [sign, setSign] = useState(emptySign);
  const [savingClose, setSavingClose] = useState(false);
  // iter343 (H11/IPV-R04) — modo "corrección": permite crear una nueva revisión
  // trazable (nueva versión del acta) incluso sobre un cierre ya FINAL.
  const [correcting, setCorrecting] = useState(false);

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

  // iter321 (IPV Fase 2) — acta de conteo físico firmable del día (PDF).
  const downloadCountSheet = async () => {
    setDownloadingSheet(true);
    try {
      const r = await axios.get(`${API}/admin/inventory/count-sheet.pdf`, {
        params: { date }, responseType: "blob", withCredentials: true,
      });
      const url = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `acta_conteo_${date}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("inventory.close.countSheetDone"));
    } catch {
      toast.error(t("inventory.close.countSheetError"));
    } finally { setDownloadingSheet(false); }
  };

  const load = useCallback(() => {
    axios.get(`${API}/admin/inventory/daily-close`, { params: { date }, withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null));
    // iter320 (IPV) — revisión del cierre (alertas + salidas + cierre guardado).
    axios.get(`${API}/admin/inventory/close-review`, { params: { date }, withCredentials: true })
      .then((r) => setReview(r.data)).catch(() => setReview(null));
  }, [date]);
  useEffect(() => { load(); }, [load]);

  // iter336 (IPV-R04) — si el día tiene un cierre PENDIENTE (guardado sin
  // revisor), precarga el formulario para que el admin pueda completarlo y
  // finalizarlo desde la pantalla (no solo por API).
  useEffect(() => {
    const c = review?.close;
    if (c && !(c.resultado === "cuadra" && (c.revisado_por || "").trim())) {
      setSign({
        responsable: c.responsable || "",
        revisado_por: c.revisado_por || "",
        folio: c.folio || "",
        note: c.note || "",
      });
    }
  }, [review?.close?.close_date, review?.close?.resultado, review?.close?.snapshot_version]);

  const saveReview = async () => {
    if (!sign.responsable.trim()) return toast.error(t("inventory.close.respRequired"));
    setSavingClose(true);
    try {
      await axios.post(`${API}/admin/inventory/close-review`, {
        date,
        responsable: sign.responsable.trim(),
        revisado_por: sign.revisado_por.trim(),
        folio: sign.folio.trim(),
        note: sign.note.trim(),
      }, { withCredentials: true });
      toast.success(correcting ? t("inventory.close.correctionSaved") : t("inventory.close.reviewSaved"));
      setSign(emptySign);
      setCorrecting(false);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("inventory.close.reviewError")); }
    finally { setSavingClose(false); }
  };

  if (!data) return <p className="text-neutral-500 text-sm py-8 text-center" data-testid="close-loading">…</p>;
  const { fisica, web } = data;
  const recogidas = data.recogidas || { num: 0, unidades: 0, total_usdt: 0, detalle: [] };
  const cur = data.store_currency;
  const empty = fisica.num_ventas === 0 && fisica.num_compras === 0 && web.num_ventas === 0 && recogidas.num === 0;

  // iter336 (IPV-R04) — distingue el RESULTADO NUMÉRICO del inventario
  // (review.resultado_sugerido) del ESTADO DE REVISIÓN del cierre guardado
  // (review.close.resultado). Un cierre solo es FINAL (solo lectura) si quedó
  // 'cuadra' Y con revisor; si no, sigue PENDIENTE y se puede completar.
  const closeDoc = review?.close || null;
  const closeFinal = !!closeDoc && closeDoc.resultado === "cuadra" && (closeDoc.revisado_por || "").trim();
  const closePending = !!closeDoc && !closeFinal;
  const closeStateLabel = (r) => r === "cuadra" ? t("inventory.close.stateRevisado")
    : r === "descuadra" ? t("inventory.close.resDescuadra") : t("inventory.close.resPendiente");
  const closeStateCls = (r) => r === "cuadra" ? "text-emerald-400 border-emerald-500/30"
    : r === "descuadra" ? "text-amber-300 border-amber-500/30" : "text-sky-300 border-sky-500/30";

  const kpi = (testid, Icon, label, value, sub, color) => (
    <div className="tactile-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 micro-label text-neutral-500"><Icon className="w-3.5 h-3.5" /> {label}</div>
      <p className={`font-display text-2xl mt-1 ${color || "text-white"}`}>{value}</p>
      <p className="text-[0.65rem] text-neutral-500">{sub}</p>
    </div>
  );

  const doneBlock = closeDoc ? (
    <div className="border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-1" data-testid="close-review-done">
      <div className="flex items-center gap-2 mb-1">
        <span className="micro-label text-neutral-500">{t("inventory.close.closeState")}:</span>
        <span data-testid="close-state-badge"
          className={`text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border ${closeStateCls(closeDoc.resultado)}`}>
          {closeStateLabel(closeDoc.resultado)}
        </span>
      </div>
      <p className="text-sm"><span className="text-neutral-500">{t("inventory.close.responsable")}:</span> {closeDoc.responsable || "—"}</p>
      <p className="text-sm"><span className="text-neutral-500">{t("inventory.close.revisadoPor")}:</span> {closeDoc.revisado_por || "—"}</p>
      <p className="text-sm"><span className="text-neutral-500">{t("inventory.close.folio")}:</span> {closeDoc.folio || "—"}</p>
      {closeDoc.note && (
        <p className="text-sm"><span className="text-neutral-500">{t("inventory.close.obs")}:</span> {closeDoc.note}</p>
      )}
      {closeDoc.value_cup != null && (
        <div className="mt-2 pt-2 border-t border-emerald-500/20" data-testid="close-frozen-acta">
          <p className="micro-label text-neutral-500 flex items-center gap-1 mb-1">
            <Lock className="w-3 h-3 text-emerald-400" />
            {t("inventory.close.actaTitle", { v: closeDoc.snapshot_version || 1 })}
          </p>
          <p className="text-sm font-mono">
            <span className="text-[#8B5CF6]">{fmt(closeDoc.value_cup)} {cur}</span>
            {closeDoc.value_usdt != null && (
              <span className="text-sky-300"> · ≈ {fmt(closeDoc.value_usdt)} USDT</span>
            )}
          </p>
          <p className="text-[0.65rem] text-neutral-500">
            {t("inventory.close.actaRate", { rate: fmt(closeDoc.fx_rate_vip) })}
          </p>
        </div>
      )}
      <p className="text-[0.65rem] text-neutral-500 pt-1">
        {t("inventory.close.closedBy", { email: closeDoc.closed_by_email || "—" })}
        {closeDoc.closed_at ? ` · ${new Date(closeDoc.closed_at).toLocaleString()}` : ""}
      </p>
    </div>
  ) : null;

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
        <Button data-testid="close-count-sheet-btn" onClick={downloadCountSheet} disabled={downloadingSheet}
          variant="outline" size="sm" className="rounded-none border-white/10 text-xs mb-1">
          <ClipboardCheck className="w-3.5 h-3.5 mr-1" /> {downloadingSheet ? "…" : t("inventory.close.countSheetPdf")}
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

      {review && (
        <div className="tactile-card p-4 space-y-4" data-testid="close-review-section">
          <div className="flex items-center gap-2 flex-wrap">
            <ClipboardCheck className="w-4 h-4 text-[#8B5CF6]" />
            <h3 className="font-display text-base">{t("inventory.close.ipvTitle")}</h3>
            <div className="ml-auto flex items-center gap-2 flex-wrap">
              <span
                data-testid="close-review-result"
                className={`text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border whitespace-nowrap ${
                  review.resultado_sugerido === "cuadra"
                    ? "text-emerald-400 border-emerald-500/30"
                    : review.resultado_sugerido === "pendiente"
                    ? "text-sky-300 border-sky-500/30"
                    : "text-amber-300 border-amber-500/30"
                }`}
              >
                {t("inventory.close.numericResult")}: {
                  review.resultado_sugerido === "cuadra"
                    ? t("inventory.close.resCuadra")
                    : review.resultado_sugerido === "pendiente"
                    ? t("inventory.close.resPendiente")
                    : t("inventory.close.resDescuadra")}
              </span>
              {/* H11 — estado de REVISIÓN guardado, distinto del resultado numérico:
                  un inventario que "cuadra" puede seguir con la revisión PENDIENTE. */}
              <span
                data-testid="close-review-state-badge"
                className={`text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border whitespace-nowrap ${
                  closeDoc ? closeStateCls(closeDoc.resultado) : "text-neutral-500 border-white/10"
                }`}
              >
                {t("inventory.close.reviewState")}: {
                  !closeDoc ? t("inventory.close.stateSinRevisar") : closeStateLabel(closeDoc.resultado)}
              </span>
            </div>
          </div>
          <p className="text-[0.65rem] text-neutral-500">{t("inventory.close.ipvHint")}</p>

          <div>
            <p className="micro-label text-neutral-500 mb-2 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-300" /> {t("inventory.close.alertsTitle")}
            </p>
            <div className="grid grid-cols-3 gap-3">
              <div className="border border-white/10 p-3" data-testid="close-alert-sin-conteo">
                <p className="font-display text-2xl text-amber-300">{review.alerts.sin_conteo}</p>
                <p className="text-[0.65rem] text-neutral-500">{t("inventory.close.alSinConteo")}</p>
              </div>
              <div className="border border-white/10 p-3" data-testid="close-alert-diferencias">
                <p className="font-display text-2xl text-red-400">{review.alerts.diferencias}</p>
                <p className="text-[0.65rem] text-neutral-500">{t("inventory.close.alDiferencias")}</p>
              </div>
              <div className="border border-white/10 p-3" data-testid="close-alert-salidas">
                <p className="font-display text-2xl text-orange-400">{review.alerts.salidas_sin_documento}</p>
                <p className="text-[0.65rem] text-neutral-500">{t("inventory.close.alSalidasSinDoc")}</p>
              </div>
            </div>
            <p className="text-[0.65rem] text-neutral-500 mt-2" data-testid="close-counted-summary">
              {t("inventory.close.countedSummary", { counted: review.productos_contados, active: review.productos_activos })}
            </p>
          </div>

          <div>
            <p className="micro-label text-neutral-500 mb-2 flex items-center gap-1">
              <PackageMinus className="w-3 h-3 text-orange-400" /> {t("inventory.close.salidasTitle")}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                ["merma", "salMerma", "text-orange-400"],
                ["consumo", "salConsumo", "text-cyan-300"],
                ["otra_salida", "salOtra", "text-rose-300"],
              ].map(([key, label, color]) => {
                const s = review.salidas[key] || { unidades: 0, valor_costo: 0, num: 0 };
                return (
                  <div key={key} className="border border-white/10 p-3" data-testid={`close-salida-${key}`}>
                    <p className={`text-xs uppercase tracking-wider ${color}`}>{t(`inventory.close.${label}`)}</p>
                    <p className="font-mono text-sm mt-1">
                      {t("inventory.close.salLine", { units: s.unidades, cost: fmt(s.valor_costo), cur })}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {closeFinal && !correcting ? (
            <div className="space-y-3">
              {doneBlock}
              {isAdmin && (
                <Button data-testid="close-create-correction" variant="outline" size="sm"
                  onClick={() => {
                    setSign({
                      responsable: closeDoc.responsable || "",
                      revisado_por: closeDoc.revisado_por || "",
                      folio: closeDoc.folio || "",
                      note: closeDoc.note || "",
                    });
                    setCorrecting(true);
                  }}
                  className="rounded-none border-white/10 text-xs">
                  <ClipboardCheck className="w-3.5 h-3.5 mr-1" /> {t("inventory.close.createCorrection")}
                </Button>
              )}
            </div>
          ) : isAdmin ? (
            <div className="space-y-3">
              {correcting ? (
                <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-3" data-testid="close-correction-banner">
                  <p className="text-sm text-[#A78BFA] flex items-center gap-2">
                    <ClipboardCheck className="w-4 h-4" /> {t("inventory.close.correctionTitle")}
                    {closeDoc && (
                      <span data-testid="close-correction-prev-version"
                        className="ml-auto text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border border-white/10 text-neutral-400">
                        v{closeDoc.snapshot_version || 1}
                      </span>
                    )}
                  </p>
                  <p className="text-[0.65rem] text-neutral-400 mt-1">{t("inventory.close.correctionHint")}</p>
                </div>
              ) : closePending && (
                <div className="border border-sky-500/20 bg-sky-500/5 p-3" data-testid="close-pending-banner">
                  <p className="text-sm text-sky-300 flex items-center gap-2">
                    <ClipboardCheck className="w-4 h-4" /> {t("inventory.close.pendingTitle")}
                    <span data-testid="close-pending-state"
                      className={`ml-auto text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${closeStateCls(closeDoc.resultado)}`}>
                      {closeStateLabel(closeDoc.resultado)}
                    </span>
                  </p>
                  <p className="text-[0.65rem] text-neutral-400 mt-1">{t("inventory.close.pendingHint")}</p>
                </div>
              )}
              <div className="border border-white/10 p-4 space-y-3" data-testid="close-review-form">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <Label className="micro-label text-neutral-500">{t("inventory.close.responsable")}</Label>
                    <Input data-testid="close-responsable" value={sign.responsable}
                      onChange={(e) => setSign({ ...sign, responsable: e.target.value })}
                      className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  </div>
                  <div>
                    <Label className="micro-label text-neutral-500">{t("inventory.close.revisadoPor")}</Label>
                    <Input data-testid="close-revisado-por" value={sign.revisado_por}
                      onChange={(e) => setSign({ ...sign, revisado_por: e.target.value })}
                      className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  </div>
                  <div>
                    <Label className="micro-label text-neutral-500">{t("inventory.close.folio")}</Label>
                    <Input data-testid="close-folio" value={sign.folio}
                      onChange={(e) => setSign({ ...sign, folio: e.target.value })}
                      className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  </div>
                  <div>
                    <Label className="micro-label text-neutral-500">{t("inventory.close.obs")}</Label>
                    <Input data-testid="close-note" value={sign.note}
                      onChange={(e) => setSign({ ...sign, note: e.target.value })}
                      className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button data-testid="close-review-save" onClick={saveReview} disabled={savingClose}
                    className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10">
                    <ClipboardCheck className="w-4 h-4 mr-1" /> {savingClose ? "…" : (correcting ? t("inventory.close.correctionBtn") : closePending ? t("inventory.close.completeBtn") : t("inventory.close.reviewBtn"))}
                  </Button>
                  {correcting && (
                    <Button data-testid="close-cancel-correction" variant="outline" size="sm"
                      onClick={() => { setCorrecting(false); setSign(emptySign); }}
                      className="rounded-none border-white/10 text-xs h-10">
                      {t("inventory.close.cancelCorrection")}
                    </Button>
                  )}
                </div>
                <p className="text-[0.65rem] text-neutral-500" data-testid="close-no-close">
                  {correcting ? t("inventory.close.correctionHint") : closePending ? t("inventory.close.completeHint") : t("inventory.close.noClose")}
                </p>
              </div>
            </div>
          ) : closeDoc ? (
            doneBlock
          ) : (
            <p className="text-xs text-neutral-500" data-testid="close-review-admin-only">{t("inventory.close.adminOnly")}</p>
          )}
        </div>
      )}
    </div>
  );
}
