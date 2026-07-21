import { useTranslation } from "react-i18next";
import { ShieldAlert, Users } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function UsersSection({ platform }) {
  const { t } = useTranslation();
  return (
    <Section title={t("admin.health.usersTitle")}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          testid="health-users-total"
          icon={Users}
          label={t("admin.health.total")}
          value={platform.users_total}
        />
        <StatCard
          testid="health-users-active"
          icon={Users}
          label={t("admin.health.active")}
          value={platform.users_active}
          tone="ok"
        />
        <StatCard
          testid="health-users-review"
          icon={Users}
          label={t("admin.health.underReview")}
          value={platform.users_under_review}
          tone={platform.users_under_review > 0 ? "warn" : "default"}
        />
        <StatCard
          testid="health-users-blocked"
          icon={ShieldAlert}
          label={t("admin.health.blocked")}
          value={platform.users_blocked}
          tone={platform.users_blocked > 0 ? "danger" : "default"}
        />
      </div>
    </Section>
  );
}
