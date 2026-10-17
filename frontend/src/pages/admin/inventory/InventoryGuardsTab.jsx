import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { ShieldAlert, RefreshCw, AlertTriangle } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
const shortDate = (s) => (s ? String(s).slice(0, 10) : "—");

function Kpi({ label, value, tone = "", testid }) {
  return (
    <div className="tactile-card px-5 py-4" data-testid={testid}>
      <div className="micro-label text-neutral-500 mb-1">{label}</div>
      <div className={`font-display text-2xl ${tone}`}>{value}</div>
    </div>
  );
}

export default function InventoryGuardsTab() {
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/admin/inventory/guard-stats`, { withCredentials: true })
      .then((r) => setStats(r.data)).catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const openDetail = (pid) => {
    setDetail({ loading: true, product_id: pid });
    setDetailLoading(true);
    axios.get(`${API}/admin/inventory/guard-detail/${pid}`, { withCredentials: true })
      .then((r) => setDetail(r.data)).catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  };

  const m = stats?.abort_metrics || {};
  const rows = stats?.top || [];

  return (
    <div className="space-y-6" data-testid="inventory-guards">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-xs text-neutral-500 max-w-2xl">{t("inventory.guards.hint")}</p>
        <Button variant="outline" size="sm" data-testid="guards-refresh-btn"
          onClick={load} disabled={loading}
          className="rounded-none border-white/10 text-xs">
          <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />
          {t("inventory.guards.refresh")}
        </Button>
      </div>

      {/* Métricas de abortos / bloqueos tardíos */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi testid="guards-kpi-aborted-dispatch"
          label={t("inventory.guards.abortedDispatch")}
          value={fmt(m.aborted_dispatch)} tone="text-amber-300" />
        <Kpi testid="guards-kpi-aborted-pickup"
          label={t("inventory.guards.abortedPickup")}
          value={fmt(m.aborted_pickup)} tone="text-amber-300" />
        <Kpi testid="guards-kpi-blocked-dispatch"
          label={t("inventory.guards.blockedDispatch")}
          value={fmt(m.blocked_late_dispatch)} tone="text-red-400" />
        <Kpi testid="guards-kpi-blocked-pickup"
          label={t("inventory.guards.blockedPickup")}
          value={fmt(m.blocked_late_pickup)} tone="text-red-400" />
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi testid="guards-kpi-products"
          label={t("inventory.guards.productsWithGuards")}
          value={fmt(stats?.products_with_guards)} />
        <Kpi testid="guards-kpi-total-entries"
          label={t("inventory.guards.totalEntries")}
          value={fmt(stats?.total_guard_entries)} />
        <Kpi testid="guards-kpi-max-size"
          label={t("inventory.guards.maxSize")}
          value={fmt(stats?.max_size)} tone="text-[#8B5CF6]" />
        <Kpi testid="guards-kpi-over-threshold"
          label={t("inventory.guards.overThreshold", { threshold: fmt(stats?.threshold) })}
          value={fmt(stats?.over_threshold_count)}
          tone={stats?.over_threshold_count ? "text-red-400" : ""} />
      </div>

      {/* Ranking de productos con más candados */}
      <div>
        <h3 className="font-display text-lg mb-1 flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-[#8B5CF6]" />
          {t("inventory.guards.rankingTitle")}
        </h3>
        <p className="text-xs text-neutral-500 mb-3">{t("inventory.guards.rankingHint")}</p>
        <div className="tactile-card overflow-auto max-h-[55vh]" data-testid="guards-ranking-table">
          <table className="w-full text-sm min-w-[640px]">
            <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.guards.colProduct")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.guards.colCompany")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.guards.colSize")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.guards.colAction")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan="4" className="text-center text-neutral-500 py-8">
                  {t("inventory.guards.empty")}
                </td></tr>
              )}
              {rows.map((p) => (
                <tr key={p.id}
                  className={`border-b border-white/5 ${p.size >= (stats?.threshold || Infinity) ? "bg-red-500/5" : ""}`}
                  data-testid={`guards-row-${p.id}`}>
                  <td className="px-4 py-3">{p.name || p.id}</td>
                  <td className="px-4 py-3 font-mono text-xs text-neutral-400">{p.company_id}</td>
                  <td className="px-4 py-3 font-mono text-right text-[#8B5CF6]">
                    {fmt(p.size)}
                    {p.size >= (stats?.threshold || Infinity) && (
                      <AlertTriangle className="inline w-3.5 h-3.5 ml-1 text-red-400" />
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="outline" size="sm" data-testid={`guards-detail-btn-${p.id}`}
                      onClick={() => openDetail(p.id)}
                      className="rounded-none border-white/10 text-xs">
                      {t("inventory.guards.viewDetail")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal de detalle por producto */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-3xl"
          data-testid="guards-detail-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">
              {t("inventory.guards.detailTitle", { name: detail?.name || detail?.product_id || "" })}
            </DialogTitle>
          </DialogHeader>
          {detailLoading && (
            <div className="text-sm text-neutral-500 py-6 text-center">{t("inventory.guards.loading")}</div>
          )}
          {detail && !detailLoading && (
            <div className="space-y-3">
              <div className="text-xs text-neutral-400" data-testid="guards-detail-summary">
                {t("inventory.guards.detailSummary", {
                  total: fmt(detail.total_guards), shown: fmt(detail.shown),
                })}
              </div>
              <div className="overflow-auto max-h-[55vh] border border-white/10">
                <table className="w-full text-xs min-w-[620px]">
                  <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left">
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dOp")}</th>
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dType")}</th>
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dResult")}</th>
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dBlocked")}</th>
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dDone")}</th>
                      <th className="px-3 py-2 micro-label text-neutral-500">{t("inventory.guards.dPrunable")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.entries || []).map((e) => (
                      <tr key={e.op_id} className="border-b border-white/5" data-testid={`guards-detail-row-${e.op_id}`}>
                        <td className="px-3 py-2 font-mono text-neutral-400 truncate max-w-[180px]" title={e.op_id}>{e.op_id}</td>
                        <td className="px-3 py-2">{e.op_type || "—"}</td>
                        <td className="px-3 py-2">
                          <span className={e.result === "burned" ? "text-amber-300" : "text-neutral-300"}>
                            {e.result || e.status || "—"}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          {e.blocked_late
                            ? <span className="text-red-400">{t("inventory.guards.yes")} ({fmt(e.block_attempts)})</span>
                            : <span className="text-neutral-600">{t("inventory.guards.no")}</span>}
                        </td>
                        <td className="px-3 py-2 font-mono text-neutral-400">{shortDate(e.done_at)}</td>
                        <td className="px-3 py-2">
                          {e.prunable
                            ? <span className="text-emerald-400">{t("inventory.guards.yes")}</span>
                            : <span className="text-neutral-600">{t("inventory.guards.no")}</span>}
                        </td>
                      </tr>
                    ))}
                    {(detail.entries || []).length === 0 && (
                      <tr><td colSpan="6" className="text-center text-neutral-500 py-6">{t("inventory.guards.empty")}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="text-[0.65rem] text-neutral-500">{t("inventory.guards.detailFoot")}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
