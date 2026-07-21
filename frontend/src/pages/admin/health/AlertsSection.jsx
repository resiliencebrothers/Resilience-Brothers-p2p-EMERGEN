import { useTranslation } from "react-i18next";
import { AlertTriangle, ExternalLink, ShieldAlert } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function AlertsSection({ defensiveMode, negativeMargin }) {
  const { t } = useTranslation();
  if (!defensiveMode.enabled && negativeMargin.count === 0) return null;
  return (
    <Section title={t("admin.health.activeAlerts")}>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {defensiveMode.enabled && (
          <StatCard
            testid="health-defensive-on"
            icon={ShieldAlert}
            label={t("admin.health.defensiveOn")}
            value={t("admin.health.defensiveOnValue")}
            sub={t("admin.health.defensiveOnSub", {
              email: defensiveMode.enabled_by_email || "—",
              reason: defensiveMode.reason || t("admin.health.noReason"),
            })}
            tone="danger"
          />
        )}
        {negativeMargin.count > 0 && (
          <StatCard
            testid="health-negative-margin"
            icon={AlertTriangle}
            label={t("admin.health.negativeMargin")}
            value={negativeMargin.count}
            sub={t("admin.health.negativeMarginSub", {
              pair: negativeMargin.items[0]?.pair || "—",
              amount: negativeMargin.items[0]?.loss_amount?.toLocaleString() || "0",
              code: negativeMargin.items[0]?.loss_currency || "",
            })}
            tone="warn"
            action={
              <a
                href="/admin/orders"
                className="text-xs text-[#8B5CF6] hover:underline inline-flex items-center gap-1"
                data-testid="health-go-to-orders"
              >
                {t("admin.health.reviewOrders")} <ExternalLink className="w-3 h-3" />
              </a>
            }
          />
        )}
      </div>
    </Section>
  );
}
