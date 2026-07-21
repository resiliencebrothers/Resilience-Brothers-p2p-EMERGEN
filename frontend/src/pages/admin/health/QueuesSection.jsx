import { useTranslation } from "react-i18next";
import { Inbox, ShieldAlert, ShieldCheck, Users } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function QueuesSection({ queues }) {
  const { t } = useTranslation();
  return (
    <Section title={t("admin.health.queues")}>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard
          testid="health-queue-orders"
          icon={Inbox}
          label={t("admin.health.pendingOrders")}
          value={queues.pending_orders}
          tone={queues.pending_orders > 10 ? "warn" : "default"}
        />
        <StatCard
          testid="health-queue-double"
          icon={ShieldAlert}
          label={t("admin.health.doubleApproval")}
          value={queues.pending_double_approval}
          tone={queues.pending_double_approval > 0 ? "warn" : "default"}
        />
        <StatCard
          testid="health-queue-withdrawals"
          icon={Inbox}
          label={t("admin.health.pendingWithdrawals")}
          value={queues.pending_withdrawals}
          tone={queues.pending_withdrawals > 5 ? "warn" : "default"}
        />
        <StatCard
          testid="health-queue-phone"
          icon={Users}
          label={t("admin.health.verifyPhone")}
          value={queues.pending_phone_verifications}
          tone={queues.pending_phone_verifications > 0 ? "warn" : "default"}
        />
        <StatCard
          testid="health-blocklist"
          icon={ShieldCheck}
          label={t("admin.health.blocked")}
          value={queues.blocked_contacts}
          sub={t("admin.health.antiScamList")}
        />
      </div>
    </Section>
  );
}
