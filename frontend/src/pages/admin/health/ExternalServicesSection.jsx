import { useTranslation } from "react-i18next";
import { Bug, CloudCheck, CloudOff, ExternalLink, ShieldAlert, ShieldCheck } from "lucide-react";
import { StatCard, Section } from "./HealthPrimitives";

export default function ExternalServicesSection({ sentry, storage, defensiveMode }) {
  const { t } = useTranslation();
  return (
    <Section title={t("admin.health.externalServices")}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <StatCard
          testid="health-sentry"
          icon={Bug}
          label={t("admin.health.sentryLabel")}
          value={sentry.enabled ? t("admin.health.sentryOn") : t("admin.health.sentryOff")}
          sub={
            sentry.enabled
              ? t("admin.health.sentrySubOn", { n: sentry.local_errors_recent, env: sentry.environment })
              : t("admin.health.sentrySubOff")
          }
          tone={sentry.enabled ? "ok" : "default"}
          action={
            sentry.enabled && (
              <a
                href={sentry.deep_link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-[#8B5CF6] hover:underline inline-flex items-center gap-1"
                data-testid="health-open-sentry"
              >
                {t("admin.health.openSentry")} <ExternalLink className="w-3 h-3" />
              </a>
            )
          }
        />
        <StatCard
          testid="health-storage"
          icon={storage.enabled ? CloudCheck : CloudOff}
          label={t("admin.health.storageLabel")}
          value={storage.enabled ? storage.provider.toUpperCase() : t("admin.health.storageOff")}
          sub={
            storage.enabled
              ? t("admin.health.storageSubOn", {
                  n: storage.object_count,
                  gb: storage.size_gb,
                  cost: storage.monthly_cost_usd,
                })
              : t("admin.health.storageSubOff")
          }
          tone={storage.enabled ? "ok" : "default"}
        />
        <StatCard
          testid="health-defensive-card"
          icon={defensiveMode.enabled ? ShieldAlert : ShieldCheck}
          label={t("admin.health.defensiveLabel")}
          value={defensiveMode.enabled ? t("admin.health.sentryOn") : t("admin.health.sentryOff")}
          sub={
            defensiveMode.enabled
              ? t("admin.health.defensiveSubOn", { ts: defensiveMode.enabled_at?.slice(0, 19) || "—" })
              : t("admin.health.defensiveSubOff")
          }
          tone={defensiveMode.enabled ? "danger" : "ok"}
        />
      </div>
      {storage.enabled && storage.by_folder?.length > 0 && (
        <div className="border border-white/5 p-4 mt-4" data-testid="health-storage-folders">
          <div className="text-xs uppercase tracking-wider text-neutral-400 mb-3">
            {t("admin.health.byFolder")}
          </div>
          <div className="space-y-2">
            {storage.by_folder.map((f) => (
              <div key={f.folder} className="flex items-center justify-between text-sm">
                <span className="text-neutral-300 font-mono">{f.folder}/</span>
                <span className="text-neutral-500">
                  {f.count} {t("admin.health.filesUnit")} · {f.size_mb} MB
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}
