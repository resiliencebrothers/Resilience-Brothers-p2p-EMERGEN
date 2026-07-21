import { useTranslation } from "react-i18next";
import { Activity, Database, TrendingUp } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function ThroughputSection({ throughput, platform }) {
  const { t } = useTranslation();
  const peakHour = (throughput.hourly_24h || []).reduce(
    (best, cur) => (cur.count > best.count ? cur : best),
    { hour: "—", count: 0 },
  );
  return (
    <Section title={t("admin.health.throughput")}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          testid="health-orders-1h"
          icon={Activity}
          label={t("admin.health.lastHour")}
          value={throughput.orders_last_1h}
          sub={t("admin.health.newOrders")}
        />
        <StatCard
          testid="health-orders-24h"
          icon={TrendingUp}
          label={t("admin.health.last24h")}
          value={throughput.orders_last_24h}
          sub={t("admin.health.peak", { hour: peakHour.hour, n: peakHour.count })}
        />
        <StatCard
          testid="health-orders-7d"
          icon={Activity}
          label={t("admin.health.last7d")}
          value={throughput.orders_last_7d}
          sub={t("admin.health.newOrders")}
        />
        <StatCard
          testid="health-orders-total"
          icon={Database}
          label={t("admin.health.totalHistoric")}
          value={platform.orders_total.toLocaleString()}
          sub={t("admin.health.approvedRejected", { a: platform.orders_approved, r: platform.orders_rejected })}
        />
      </div>
    </Section>
  );
}
