import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { BarChart3, Clock, AlertTriangle, Banknote } from "lucide-react";

// Mejora #8 (Fase C) — métricas operativas de mensajería: tiempos de
// asignación/aceptación/entrega, % de incidencias, trabajos sin rendir y
// costo neto por servicio, con filtros de fecha y mensajero.

function daysAgo(n) {
  const d = new Date(Date.now() - n * 86400000);
  return d.toISOString().slice(0, 10);
}

function MetricCard({ label, value, suffix, accent = "", testid }) {
  return (
    <div className="tactile-card px-4 py-3" data-testid={testid}>
      <div className="micro-label text-neutral-500">{label}</div>
      <div className={`font-display text-xl ${accent}`}>
        {value ?? "—"}{value != null && suffix ? <span className="text-xs text-neutral-400"> {suffix}</span> : null}
      </div>
    </div>
  );
}

export default function DeliveryMetricsTab() {
  const { t } = useTranslation();
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(daysAgo(0));
  const [courierId, setCourierId] = useState("all");
  const [couriers, setCouriers] = useState([]);
  const [data, setData] = useState(null);

  useEffect(() => {
    axios.get(`${API}/admin/couriers`, { withCredentials: true })
      .then((r) => setCouriers(r.data)).catch(() => setCouriers([]));
  }, []);

  const load = useCallback(() => {
    const params = { date_from: from, date_to: to };
    if (courierId !== "all") params.courier_id = courierId;
    axios.get(`${API}/admin/deliveries/metrics`, { params, withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null));
  }, [from, to, courierId]);

  useEffect(() => { load(); }, [load]);

  const m = data;
  return (
    <div className="space-y-5" data-testid="delivery-metrics-tab">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("admin.deliveries.metricsFrom")}</div>
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            data-testid="metrics-date-from"
            className="bg-[#0a0a0a] border border-white/10 text-white text-sm px-3 h-10 rounded-none [color-scheme:dark]"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("admin.deliveries.metricsTo")}</div>
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            data-testid="metrics-date-to"
            className="bg-[#0a0a0a] border border-white/10 text-white text-sm px-3 h-10 rounded-none [color-scheme:dark]"
          />
        </div>
        <div className="min-w-[200px]">
          <div className="micro-label text-neutral-500 mb-1">{t("admin.deliveries.metricsCourier")}</div>
          <Select value={courierId} onValueChange={setCourierId}>
            <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="metrics-courier-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white">
              <SelectItem value="all">{t("admin.deliveries.metricsAllCouriers")}</SelectItem>
              {couriers.map((c) => (
                <SelectItem key={c.user_id} value={c.user_id}>
                  {c.name || c.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!m ? (
        <p className="text-neutral-500 text-center py-8" data-testid="metrics-loading">…</p>
      ) : (
        <>
          <div>
            <div className="micro-label text-[#A78BFA] mb-2 flex items-center gap-1.5">
              <BarChart3 className="w-3.5 h-3.5" /> {t("admin.deliveries.metricsVolume")}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricCard label={t("admin.deliveries.metricsTotal")} value={m.total} testid="metric-total" />
              <MetricCard label={t("admin.deliveries.metricsConfirmed")} value={m.confirmed} accent="text-[#22C55E]" testid="metric-confirmed" />
              <MetricCard label={t("admin.deliveries.metricsCancelled")} value={m.cancelled} accent="text-[#EF4444]" testid="metric-cancelled" />
              <MetricCard label={t("admin.deliveries.metricsUnsettled")} value={m.unsettled_count} accent={m.unsettled_count > 0 ? "text-amber-300" : ""} testid="metric-unsettled" />
            </div>
          </div>

          <div>
            <div className="micro-label text-[#A78BFA] mb-2 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" /> {t("admin.deliveries.metricsTimes")}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <MetricCard label={t("admin.deliveries.metricsAvgAccept")} value={m.avg_accept_min} suffix="min" testid="metric-avg-accept" />
              <MetricCard label={t("admin.deliveries.metricsAvgDeliver")} value={m.avg_deliver_min} suffix="min" testid="metric-avg-deliver" />
              <MetricCard label={t("admin.deliveries.metricsAvgTotal")} value={m.avg_total_min} suffix="min" testid="metric-avg-total" />
            </div>
          </div>

          <div>
            <div className="micro-label text-[#A78BFA] mb-2 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> {t("admin.deliveries.metricsIncidentsTitle")}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <MetricCard label={t("admin.deliveries.metricsIncidents")} value={m.incidents_count} accent={m.incidents_count > 0 ? "text-amber-300" : ""} testid="metric-incidents" />
              <MetricCard label={t("admin.deliveries.metricsIncidentsPct")} value={m.incidents_pct} suffix="%" accent={m.incidents_pct > 0 ? "text-amber-300" : ""} testid="metric-incidents-pct" />
              <MetricCard label={t("admin.deliveries.metricsSyncPending")} value={m.sync_pending_count} accent={m.sync_pending_count > 0 ? "text-amber-300" : ""} testid="metric-sync-pending" />
            </div>
          </div>

          <div>
            <div className="micro-label text-[#A78BFA] mb-2 flex items-center gap-1.5">
              <Banknote className="w-3.5 h-3.5" /> {t("admin.deliveries.metricsCostTitle")}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricCard label={t("admin.deliveries.metricsFees")} value={m.fees_usdt} suffix="USDT" testid="metric-fees" />
              <MetricCard label={t("admin.deliveries.metricsCourierPaid")} value={m.courier_paid_usdt} suffix="USDT" accent="text-[#22C55E]" testid="metric-courier-paid" />
              <MetricCard label={t("admin.deliveries.metricsPlatformNet")} value={m.platform_net_usdt} suffix="USDT" accent="text-[#8B5CF6]" testid="metric-platform-net" />
              <MetricCard label={t("admin.deliveries.metricsAvgFee")} value={m.avg_fee_usdt} suffix="USDT" testid="metric-avg-fee" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
