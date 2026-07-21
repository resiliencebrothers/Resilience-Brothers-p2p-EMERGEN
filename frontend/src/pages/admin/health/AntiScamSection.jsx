import { useTranslation } from "react-i18next";
import { AlertTriangle, Clock, ShieldCheck, ShieldX } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function AntiScamSection({ antiScam }) {
  const { t } = useTranslation();
  if (!antiScam || antiScam.error) return null;

  const oldestTone = (() => {
    if (antiScam.oldest_pending_hours == null) return "default";
    if (antiScam.oldest_pending_hours > 48) return "danger";
    if (antiScam.oldest_pending_hours > 24) return "warn";
    return "default";
  })();

  return (
    <Section title={t("admin.health.antiScamTitle")}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          testid="health-antiscam-queue"
          icon={ShieldX}
          label={t("admin.health.underReviewNow")}
          value={antiScam.users_under_review}
          sub={t("admin.health.phoneVerifyQueue")}
          tone={antiScam.users_under_review > 5 ? "warn" : "default"}
        />
        <StatCard
          testid="health-antiscam-avg-hours"
          icon={Clock}
          label={t("admin.health.avgResolution")}
          value={antiScam.avg_resolution_hours == null ? "—" : `${antiScam.avg_resolution_hours} h`}
          sub={
            antiScam.avg_resolution_hours == null
              ? t("admin.health.noResolvedYet")
              : t("admin.health.resolvedCases", { n: antiScam.resolved_count })
          }
          tone={antiScam.avg_resolution_hours != null && antiScam.avg_resolution_hours > 24 ? "warn" : "default"}
        />
        <StatCard
          testid="health-antiscam-oldest"
          icon={AlertTriangle}
          label={t("admin.health.oldestTicket")}
          value={antiScam.oldest_pending_hours == null ? "—" : `${antiScam.oldest_pending_hours} h`}
          sub={t("admin.health.waiting")}
          tone={oldestTone}
        />
        <StatCard
          testid="health-antiscam-resolved"
          icon={ShieldCheck}
          label={t("admin.health.resolvedHistoric")}
          value={antiScam.resolved_count}
          sub={t("admin.health.contributesAvg")}
          tone="ok"
        />
      </div>
    </Section>
  );
}
