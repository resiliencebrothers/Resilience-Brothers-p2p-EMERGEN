import { useMemo, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { BarChart3, Award, PieChart as PieIcon, FileText, FileSpreadsheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";

/**
 * iter55.36k — Analytics dialog surfacing the operator's most-asked
 * questions in a single view:
 *   1) Which month brought the most revenue? (monthly comparison table + bar chart)
 *   2) Which currency (pair) contributes the most? (top-pair card)
 *   3) Which of the three revenue sources dominates: marketplace, exchange
 *      (P2P), or conversions? (category breakdown with % share)
 *
 * Consumes the already-computed data returned by `admin_revenue` + the
 * monthly timeseries the parent already fetches — no new backend endpoints.
 */
const fmt = (n) => (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
// iter55.36k — when a category is negative (net loss) the naive `value/total`
// share yields nonsensical percentages (e.g. 110% / -10%). Use magnitude for
// share so the three bars always sum to 100 while the sign is preserved in
// the displayed value.
const shareOfMagnitude = (v, absTotal) => (absTotal > 0 ? (Math.abs(v) / absTotal) * 100 : 0);

const CAT_META = [
  { key: "p2p_profit_usdt",         label: "Intercambio P2P",    color: "#8B5CF6" },
  { key: "marketplace_profit_usdt", label: "Marketplace",        color: "#22C55E" },
  { key: "conversion_fees_usdt",    label: "Conversiones",       color: "#EAB308" },
];

export default function RevenueAnalyticsDialog({ open, onOpenChange, data, monthly, days }) {
  const [exporting, setExporting] = useState(null); // "csv" | "pdf" | null

  const download = async (format) => {
    setExporting(format);
    try {
      const params = new URLSearchParams({ format });
      if (days && days !== "all") params.append("days", String(days));
      const r = await axios.get(
        `${API}/admin/revenue/analytics/export?${params.toString()}`,
        { responseType: "blob", withCredentials: true },
      );
      const blob = new Blob([r.data], {
        type: format === "csv" ? "text/csv" : "application/pdf",
      });
      const ext = format === "csv" ? "csv" : "pdf";
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `estadisticas-ingresos-${stamp}.${ext}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`${format.toUpperCase()} descargado.`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo generar el archivo.");
    } finally {
      setExporting(null);
    }
  };
  const catBreakdown = useMemo(() => {
    if (!data) return { rows: [], total: 0, absTotal: 0 };
    const values = CAT_META.map((c) => data[c.key] || 0);
    const total = values.reduce((sum, v) => sum + v, 0);
    const absTotal = values.reduce((sum, v) => sum + Math.abs(v), 0);
    const rows = CAT_META.map((c, i) => ({
      ...c,
      value: values[i],
      pct: shareOfMagnitude(values[i], absTotal),
      negative: values[i] < 0,
    })).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
    return { rows, total, absTotal };
  }, [data]);

  const topPair = useMemo(() => {
    if (!data?.by_pair?.length) return null;
    return data.by_pair[0];
  }, [data]);

  const topMonth = useMemo(() => {
    if (!monthly?.length) return null;
    return [...monthly].sort((a, b) => (b.total_profit_usdt || 0) - (a.total_profit_usdt || 0))[0];
  }, [monthly]);

  const chartData = useMemo(() => {
    if (!monthly?.length) return [];
    return [...monthly]
      .sort((a, b) => (a.bucket || "").localeCompare(b.bucket || ""))
      .slice(-12) // last 12 months max
      .map((r) => ({
        bucket: r.bucket,
        "Intercambio P2P":  Number((r.p2p_profit_usdt || 0).toFixed(2)),
        "Marketplace":      Number((r.marketplace_profit_usdt || 0).toFixed(2)),
        "Conversiones":     Number((r.conversion_fees_usdt || 0).toFixed(2)),
        total:              Number((r.total_profit_usdt || 0).toFixed(2)),
        orders:             r.orders || 0,
      }));
  }, [monthly]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-6xl max-h-[85vh] overflow-y-auto"
        data-testid="revenue-analytics-dialog"
      >
        <DialogHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <DialogTitle className="font-display flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-[#22C55E]" />
                Estadísticas comparativas de ingresos
              </DialogTitle>
              <DialogDescription className="text-neutral-500 text-xs mt-1">
                Comparativa mensual, categorías (marketplace / P2P / conversiones)
                y la moneda que más aporta. Los datos coinciden con el filtro de
                período activo en la vista principal.
              </DialogDescription>
            </div>
            <div className="flex gap-2 flex-shrink-0" data-testid="revenue-analytics-export-actions">
              <Button
                data-testid="export-analytics-csv"
                variant="outline"
                size="sm"
                disabled={!!exporting}
                onClick={() => download("csv")}
                className="rounded-none border-white/20 hover:bg-white/5"
                title="Descargar comparativa como CSV"
              >
                <FileSpreadsheet className="w-4 h-4 mr-1" />
                {exporting === "csv" ? "Generando…" : "CSV"}
              </Button>
              <Button
                data-testid="export-analytics-pdf"
                variant="outline"
                size="sm"
                disabled={!!exporting}
                onClick={() => download("pdf")}
                className="rounded-none border-white/20 hover:bg-white/5"
                title="Descargar reporte ejecutivo en PDF (con gráfico)"
              >
                <FileText className="w-4 h-4 mr-1" />
                {exporting === "pdf" ? "Generando…" : "PDF"}
              </Button>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-6 mt-2">
          {/* Row of "top" highlights */}
          <div className="grid sm:grid-cols-3 gap-3" data-testid="revenue-analytics-highlights">
            <HighlightCard
              icon={Award}
              label="Mejor mes"
              value={topMonth ? topMonth.bucket : "—"}
              hint={topMonth ? `${fmt(topMonth.total_profit_usdt)} USDT` : "sin datos"}
              testid="revenue-analytics-top-month"
            />
            <HighlightCard
              icon={PieIcon}
              label="Categoría líder"
              value={catBreakdown.rows[0]?.label || "—"}
              hint={catBreakdown.total > 0
                ? `${fmt(catBreakdown.rows[0]?.value)} USDT · ${catBreakdown.rows[0]?.pct.toFixed(1)}%`
                : "sin datos"}
              testid="revenue-analytics-top-category"
            />
            <HighlightCard
              icon={Award}
              label="Par con más ganancia"
              value={topPair ? topPair.pair : "—"}
              hint={topPair ? `${fmt(topPair.profit_usdt)} USDT · ${topPair.orders} órdenes` : "sin datos"}
              testid="revenue-analytics-top-pair"
            />
          </div>

          {/* Category breakdown with % — uses magnitude-share so signs (net
              loss on any category) don't produce nonsensical percentages. */}
          <div className="tactile-card p-4" data-testid="revenue-analytics-category-breakdown">
            <div className="micro-label text-neutral-500 mb-3">
              Aporte por categoría · Total neto {fmt(catBreakdown.total)} USDT
            </div>
            <div className="space-y-2">
              {catBreakdown.rows.map((c) => (
                <div key={c.key} data-testid={`category-row-${c.key}`}>
                  <div className="flex justify-between items-baseline text-sm">
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block w-2.5 h-2.5"
                        style={{ backgroundColor: c.color }}
                        aria-hidden
                      />
                      <span className="text-neutral-200">{c.label}</span>
                    </div>
                    <div className="font-mono">
                      <span className={c.negative ? "text-[#EF4444]" : "text-white"}>
                        {c.negative && "-"}{fmt(Math.abs(c.value))} USDT
                      </span>
                      <span className="ml-2 text-neutral-500 text-xs">({c.pct.toFixed(1)}%)</span>
                    </div>
                  </div>
                  <div className="h-2 bg-white/5 mt-1 relative overflow-hidden">
                    <div
                      className="h-full transition-all duration-500"
                      style={{
                        width: `${Math.min(100, c.pct)}%`,
                        backgroundColor: c.color,
                        opacity: c.negative ? 0.4 : 1,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
            {catBreakdown.rows.some((r) => r.negative) && (
              <div className="text-[0.65rem] text-neutral-500 mt-3 italic leading-relaxed">
                Los porcentajes representan la magnitud relativa de cada categoría
                sobre el total absoluto. Las barras atenuadas indican pérdida neta.
              </div>
            )}
          </div>

          {/* Bar chart per month */}
          <div className="tactile-card p-4" data-testid="revenue-analytics-chart">
            <div className="micro-label text-neutral-500 mb-3">
              Ganancias por mes (últimos {chartData.length} meses)
            </div>
            {chartData.length === 0 ? (
              <div className="text-neutral-500 text-sm py-8 text-center">Sin datos mensuales aún.</div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                  <XAxis dataKey="bucket" tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0a0a0a",
                      border: "1px solid #ffffff20",
                      borderRadius: 0,
                      color: "#fff",
                    }}
                    formatter={(v) => `${fmt(v)} USDT`}
                    cursor={{ fill: "#8B5CF610" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {CAT_META.map((c) => (
                    <Bar key={c.key} dataKey={c.label} stackId="a" fill={c.color} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Monthly comparison table */}
          <div className="tactile-card overflow-hidden" data-testid="revenue-analytics-monthly-table">
            <div className="px-4 py-3 border-b border-white/10 micro-label text-neutral-500">
              Comparativa mensual
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#0a0a0a] border-b border-white/10">
                  <tr className="text-left">
                    <th className="px-4 py-2 micro-label text-neutral-500">Mes</th>
                    <th className="px-4 py-2 micro-label text-neutral-500 text-right">P2P</th>
                    <th className="px-4 py-2 micro-label text-neutral-500 text-right">Marketplace</th>
                    <th className="px-4 py-2 micro-label text-neutral-500 text-right">Conversiones</th>
                    <th className="px-4 py-2 micro-label text-neutral-500 text-right">Total</th>
                    <th className="px-4 py-2 micro-label text-neutral-500 text-right">Órdenes</th>
                  </tr>
                </thead>
                <tbody>
                  {[...(monthly || [])]
                    .sort((a, b) => (b.bucket || "").localeCompare(a.bucket || ""))
                    .map((r) => (
                      <tr
                        key={r.bucket}
                        className="border-b border-white/5"
                        data-testid={`monthly-row-${r.bucket}`}
                      >
                        <td className="px-4 py-2 font-mono">{r.bucket}</td>
                        <td className="px-4 py-2 text-right font-mono text-[#8B5CF6]">
                          {fmt(r.p2p_profit_usdt)}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-[#22C55E]">
                          {fmt(r.marketplace_profit_usdt)}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-[#EAB308]">
                          {fmt(r.conversion_fees_usdt)}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-white font-semibold">
                          {fmt(r.total_profit_usdt)}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-neutral-400">
                          {r.orders || 0}
                        </td>
                      </tr>
                    ))}
                  {(monthly || []).length === 0 && (
                    <tr>
                      <td colSpan={6} className="text-center text-neutral-500 py-8">
                        Sin datos mensuales aún.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function HighlightCard({ icon: Icon, label, value, hint, testid }) {
  return (
    <div className="tactile-card p-3" data-testid={testid}>
      <div className="flex items-center gap-2 text-neutral-500 text-[0.65rem] uppercase tracking-widest">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="mt-1 font-display text-lg text-white truncate" title={value}>
        {value}
      </div>
      <div className="text-xs text-neutral-500 font-mono">{hint}</div>
    </div>
  );
}
