import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, Database, ExternalLink, ServerCog,
  ShieldAlert, ShieldCheck, TrendingUp, Users, Inbox, Bug,
  CloudOff, CloudCheck, Clock, ShieldX,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const StatCard = ({ icon: Icon, label, value, sub, tone = "default", testid, action }) => {
  const toneClass = {
    default: "border-white/10",
    danger: "border-red-500/40 bg-red-500/5",
    warn: "border-amber-500/40 bg-amber-500/5",
    ok: "border-emerald-500/30 bg-emerald-500/5",
  }[tone];
  return (
    <div data-testid={testid} className={`p-5 border ${toneClass} space-y-1`}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-neutral-400">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="font-display text-3xl text-white">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
};

const Section = ({ title, children, action }) => (
  <section className="space-y-4">
    <div className="flex items-end justify-between">
      <h2 className="font-display text-lg text-[#8B5CF6]">{title}</h2>
      {action}
    </div>
    {children}
  </section>
);

export default function AdminHealth() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState(null);

  const load = async () => {
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
  };
  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  if (loading && !data) {
    return (
      <div data-testid="admin-health-loading" className="text-neutral-400">
        {t("admin.health.loading")}
      </div>
    );
  }
  if (!data) return null;

  const s = data;
  const peakHour = (s.throughput.hourly_24h || []).reduce(
    (best, cur) => (cur.count > best.count ? cur : best),
    { hour: "—", count: 0 },
  );

  return (
    <div data-testid="admin-health-page" className="space-y-10 max-w-7xl">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-white">{t("admin.health.title")}</h1>
          <p className="text-sm text-neutral-400 mt-1">
            {t("admin.health.subtitle")}
          </p>
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

      {(s.defensive_mode.enabled || s.negative_margin.count > 0) && (
        <Section title={t("admin.health.activeAlerts")}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {s.defensive_mode.enabled && (
              <StatCard
                testid="health-defensive-on"
                icon={ShieldAlert}
                label={t("admin.health.defensiveOn")}
                value={t("admin.health.defensiveOnValue")}
                sub={t("admin.health.defensiveOnSub", {
                  email: s.defensive_mode.enabled_by_email || "—",
                  reason: s.defensive_mode.reason || t("admin.health.noReason"),
                })}
                tone="danger"
              />
            )}
            {s.negative_margin.count > 0 && (
              <StatCard
                testid="health-negative-margin"
                icon={AlertTriangle}
                label={t("admin.health.negativeMargin")}
                value={s.negative_margin.count}
                sub={t("admin.health.negativeMarginSub", {
                  pair: s.negative_margin.items[0]?.pair || "—",
                  amount: s.negative_margin.items[0]?.loss_amount?.toLocaleString() || "0",
                  code: s.negative_margin.items[0]?.loss_currency || "",
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
      )}

      <Section title={t("admin.health.externalServices")}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <StatCard
            testid="health-sentry"
            icon={Bug}
            label={t("admin.health.sentryLabel")}
            value={s.sentry.enabled ? t("admin.health.sentryOn") : t("admin.health.sentryOff")}
            sub={
              s.sentry.enabled
                ? t("admin.health.sentrySubOn", { n: s.sentry.local_errors_recent, env: s.sentry.environment })
                : t("admin.health.sentrySubOff")
            }
            tone={s.sentry.enabled ? "ok" : "default"}
            action={
              s.sentry.enabled && (
                <a
                  href={s.sentry.deep_link}
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
            icon={s.storage.enabled ? CloudCheck : CloudOff}
            label={t("admin.health.storageLabel")}
            value={s.storage.enabled ? s.storage.provider.toUpperCase() : t("admin.health.storageOff")}
            sub={
              s.storage.enabled
                ? t("admin.health.storageSubOn", {
                    n: s.storage.object_count,
                    gb: s.storage.size_gb,
                    cost: s.storage.monthly_cost_usd,
                  })
                : t("admin.health.storageSubOff")
            }
            tone={s.storage.enabled ? "ok" : "default"}
          />
          <StatCard
            testid="health-defensive-card"
            icon={s.defensive_mode.enabled ? ShieldAlert : ShieldCheck}
            label={t("admin.health.defensiveLabel")}
            value={s.defensive_mode.enabled ? t("admin.health.sentryOn") : t("admin.health.sentryOff")}
            sub={
              s.defensive_mode.enabled
                ? t("admin.health.defensiveSubOn", { ts: s.defensive_mode.enabled_at?.slice(0, 19) || "—" })
                : t("admin.health.defensiveSubOff")
            }
            tone={s.defensive_mode.enabled ? "danger" : "ok"}
          />
        </div>
        {s.storage.enabled && s.storage.by_folder?.length > 0 && (
          <div className="border border-white/5 p-4 mt-4" data-testid="health-storage-folders">
            <div className="text-xs uppercase tracking-wider text-neutral-400 mb-3">
              {t("admin.health.byFolder")}
            </div>
            <div className="space-y-2">
              {s.storage.by_folder.map((f) => (
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

      <Section title={t("admin.health.throughput")}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            testid="health-orders-1h"
            icon={Activity}
            label={t("admin.health.lastHour")}
            value={s.throughput.orders_last_1h}
            sub={t("admin.health.newOrders")}
          />
          <StatCard
            testid="health-orders-24h"
            icon={TrendingUp}
            label={t("admin.health.last24h")}
            value={s.throughput.orders_last_24h}
            sub={t("admin.health.peak", { hour: peakHour.hour, n: peakHour.count })}
          />
          <StatCard
            testid="health-orders-7d"
            icon={Activity}
            label={t("admin.health.last7d")}
            value={s.throughput.orders_last_7d}
            sub={t("admin.health.newOrders")}
          />
          <StatCard
            testid="health-orders-total"
            icon={Database}
            label={t("admin.health.totalHistoric")}
            value={s.platform.orders_total.toLocaleString()}
            sub={t("admin.health.approvedRejected", { a: s.platform.orders_approved, r: s.platform.orders_rejected })}
          />
        </div>
      </Section>

      <Section title={t("admin.health.queues")}>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard
            testid="health-queue-orders"
            icon={Inbox}
            label={t("admin.health.pendingOrders")}
            value={s.queues.pending_orders}
            tone={s.queues.pending_orders > 10 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-double"
            icon={ShieldAlert}
            label={t("admin.health.doubleApproval")}
            value={s.queues.pending_double_approval}
            tone={s.queues.pending_double_approval > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-withdrawals"
            icon={Inbox}
            label={t("admin.health.pendingWithdrawals")}
            value={s.queues.pending_withdrawals}
            tone={s.queues.pending_withdrawals > 5 ? "warn" : "default"}
          />
          <StatCard
            testid="health-queue-phone"
            icon={Users}
            label={t("admin.health.verifyPhone")}
            value={s.queues.pending_phone_verifications}
            tone={s.queues.pending_phone_verifications > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-blocklist"
            icon={ShieldCheck}
            label={t("admin.health.blocked")}
            value={s.queues.blocked_contacts}
            sub={t("admin.health.antiScamList")}
          />
        </div>
      </Section>

      <Section title={t("admin.health.usersTitle")}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            testid="health-users-total"
            icon={Users}
            label={t("admin.health.total")}
            value={s.platform.users_total}
          />
          <StatCard
            testid="health-users-active"
            icon={Users}
            label={t("admin.health.active")}
            value={s.platform.users_active}
            tone="ok"
          />
          <StatCard
            testid="health-users-review"
            icon={Users}
            label={t("admin.health.underReview")}
            value={s.platform.users_under_review}
            tone={s.platform.users_under_review > 0 ? "warn" : "default"}
          />
          <StatCard
            testid="health-users-blocked"
            icon={ShieldAlert}
            label={t("admin.health.blocked")}
            value={s.platform.users_blocked}
            tone={s.platform.users_blocked > 0 ? "danger" : "default"}
          />
        </div>
      </Section>

      {s.anti_scam && !s.anti_scam.error && (
        <Section title={t("admin.health.antiScamTitle")}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard
              testid="health-antiscam-queue"
              icon={ShieldX}
              label={t("admin.health.underReviewNow")}
              value={s.anti_scam.users_under_review}
              sub={t("admin.health.phoneVerifyQueue")}
              tone={s.anti_scam.users_under_review > 5 ? "warn" : "default"}
            />
            <StatCard
              testid="health-antiscam-avg-hours"
              icon={Clock}
              label={t("admin.health.avgResolution")}
              value={
                s.anti_scam.avg_resolution_hours == null
                  ? "—"
                  : `${s.anti_scam.avg_resolution_hours} h`
              }
              sub={
                s.anti_scam.avg_resolution_hours == null
                  ? t("admin.health.noResolvedYet")
                  : t("admin.health.resolvedCases", { n: s.anti_scam.resolved_count })
              }
              tone={
                s.anti_scam.avg_resolution_hours != null
                && s.anti_scam.avg_resolution_hours > 24
                  ? "warn"
                  : "default"
              }
            />
            <StatCard
              testid="health-antiscam-oldest"
              icon={AlertTriangle}
              label={t("admin.health.oldestTicket")}
              value={
                s.anti_scam.oldest_pending_hours == null
                  ? "—"
                  : `${s.anti_scam.oldest_pending_hours} h`
              }
              sub={t("admin.health.waiting")}
              tone={
                s.anti_scam.oldest_pending_hours != null
                && s.anti_scam.oldest_pending_hours > 48
                  ? "danger"
                  : s.anti_scam.oldest_pending_hours != null
                    && s.anti_scam.oldest_pending_hours > 24
                    ? "warn"
                    : "default"
              }
            />
            <StatCard
              testid="health-antiscam-resolved"
              icon={ShieldCheck}
              label={t("admin.health.resolvedHistoric")}
              value={s.anti_scam.resolved_count}
              sub={t("admin.health.contributesAvg")}
              tone="ok"
            />
          </div>
        </Section>
      )}

      {s.negative_margin.count > 0 && (
        <Section title={t("admin.health.negativeMarginTable", { n: s.negative_margin.count })}>
          <div className="border border-white/10 overflow-x-auto">
            <table className="w-full text-sm" data-testid="health-margin-table">
              <thead className="bg-white/5 text-xs uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="text-left p-3">{t("admin.health.colId")}</th>
                  <th className="text-left p-3">{t("admin.health.colClient")}</th>
                  <th className="text-left p-3">{t("admin.health.colPair")}</th>
                  <th className="text-right p-3">{t("admin.health.colLoss")}</th>
                  <th className="text-right p-3">{t("admin.health.colLossPct")}</th>
                  <th className="text-left p-3">{t("admin.health.colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {s.negative_margin.items.map((it) => (
                  <tr key={it.id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="p-3 text-neutral-500 font-mono text-xs">{it.id.slice(0, 8)}</td>
                    <td className="p-3 text-neutral-300">{it.user_name}</td>
                    <td className="p-3 font-mono text-xs">{it.pair}</td>
                    <td className="p-3 text-right text-red-400 font-medium">
                      {it.loss_amount.toLocaleString()} {it.loss_currency}
                    </td>
                    <td className="p-3 text-right text-red-400">{it.loss_pct}%</td>
                    <td className="p-3 text-neutral-500 text-xs">{it.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {s.negative_margin.count > 20 && (
            <p className="text-xs text-neutral-500">
              {t("admin.health.showingFirst", { n: s.negative_margin.count })}
            </p>
          )}
        </Section>
      )}

      <p className="text-xs text-neutral-600 text-right">
        {t("admin.health.snapshotGenerated", { ts: new Date(s.generated_at).toLocaleString() })}
      </p>
    </div>
  );
}
