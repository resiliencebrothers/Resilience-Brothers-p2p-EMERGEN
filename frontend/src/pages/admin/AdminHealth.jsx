import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import AlertsSection from "./health/AlertsSection";
import ExternalServicesSection from "./health/ExternalServicesSection";
import ThroughputSection from "./health/ThroughputSection";
import QueuesSection from "./health/QueuesSection";
import UsersSection from "./health/UsersSection";
import AntiScamSection from "./health/AntiScamSection";
import NegativeMarginTable from "./health/NegativeMarginTable";

export default function AdminHealth() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/health/summary`, { withCredentials: true });
      setData(r.data);
      setRefreshedAt(new Date());
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  if (loading && !data) {
    return (
      <div data-testid="admin-health-loading" className="text-neutral-400">
        {t("admin.health.loading")}
      </div>
    );
  }
  if (!data) return null;

  return (
    <div data-testid="admin-health-page" className="space-y-10 max-w-7xl">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-white">{t("admin.health.title")}</h1>
          <p className="text-sm text-neutral-400 mt-1">{t("admin.health.subtitle")}</p>
        </div>
        <div className="flex items-center gap-3">
          {refreshedAt && (
            <span className="text-xs text-neutral-500">
              {t("admin.health.updated", { ts: refreshedAt.toLocaleTimeString() })}
            </span>
          )}
          <Button
            data-testid="admin-health-refresh"
            onClick={load}
            disabled={loading}
            variant="outline"
            className="border-white/10 hover:bg-white/5"
          >
            {loading ? "..." : t("admin.health.reload")}
          </Button>
        </div>
      </div>

      <AlertsSection defensiveMode={data.defensive_mode} negativeMargin={data.negative_margin} />
      <ExternalServicesSection sentry={data.sentry} storage={data.storage} defensiveMode={data.defensive_mode} />
      <ThroughputSection throughput={data.throughput} platform={data.platform} />
      <QueuesSection queues={data.queues} />
      <UsersSection platform={data.platform} />
      <AntiScamSection antiScam={data.anti_scam} />
      <NegativeMarginTable negativeMargin={data.negative_margin} />

      <p className="text-xs text-neutral-600 text-right">
        {t("admin.health.snapshotGenerated", { ts: new Date(data.generated_at).toLocaleString() })}
      </p>
    </div>
  );
}
