/**
 * iter84 — SecurityAuditPanels
 *
 * The 4 SummaryCards + 5 audit Panel sections (staff sessions, new-IP
 * logins, rate-limited IPs, origin violations, login bursts). Renders
 * everything derived from the `/admin/security/audit` payload.
 *
 * Pure presentational — takes the `data` shape from useSecurityAudit
 * plus the `revoking` flag and `onRevokeSessions` callback.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Users, MapPin, Ban, AlertOctagon, Wifi, LogOut } from "lucide-react";
import {
  SummaryCard, Panel, Empty, TableSimple,
} from "./SecurityUiPrimitives";

export default function SecurityAuditPanels({ data, revoking, onRevokeSessions }) {
  const { t } = useTranslation();
  const HEADERS_NEW_IP = [t("admin.common.date"), t("admin.common.user"), "Rol", "IP", "User-Agent"];
  const HEADERS_RATE_LIMITED = ["IP", "Hits", "Último", "Endpoints"];
  const HEADERS_ORIGIN_VIOLATIONS = [t("admin.common.date"), "Origin", "IP", "Método", "Path"];
  const HEADERS_LOGIN_BURSTS = ["Identifier", "Fallos", "Último intento"];

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard
          icon={Users}
          label={t("admin.security.activeSessions")}
          value={data.active_sessions.total}
          hint={Object.entries(data.active_sessions.by_role).map(([r, n]) => `${r}: ${n}`).join(" · ")}
          testId="security-sessions-total"
        />
        <SummaryCard
          icon={MapPin}
          label={t("admin.security.adminsNewIp")}
          value={data.admin_new_ip_logins.length}
          hint={t("admin.security.adminsNewIpHint")}
          tone={data.admin_new_ip_logins.length > 0 ? "warn" : "default"}
          testId="security-new-ip-count"
        />
        <SummaryCard
          icon={Ban}
          label={t("admin.security.ratelimitIps")}
          value={data.top_rate_limited_ips.reduce((s, r) => s + r.hits, 0)}
          hint={t("admin.security.ratelimitDistinct", { n: data.top_rate_limited_ips.length })}
          tone={data.top_rate_limited_ips.length > 0 ? "warn" : "default"}
          testId="security-rate-limit-count"
        />
        <SummaryCard
          icon={AlertOctagon}
          label={t("admin.security.originBlocked")}
          value={data.recent_origin_violations.length}
          hint={t("admin.security.originHint")}
          tone={data.recent_origin_violations.length > 0 ? "danger" : "default"}
          testId="security-origin-block-count"
        />
      </div>

      <Panel
        icon={Wifi}
        title={t("admin.security.staffSessions")}
        subtitle={t("admin.security.staffSessionsDesc")}
      >
        {data.active_sessions.staff_active.length === 0
          && <Empty text={t("admin.security.noStaffSessions")} />}
        <ul className="space-y-2">
          {data.active_sessions.staff_active.map((s) => (
            <li
              key={s.user_id + s.created_at}
              className="flex flex-wrap items-center justify-between gap-2 border border-white/5 bg-black/30 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="text-sm text-white font-semibold truncate">{s.email || s.user_id}</div>
                <div className="text-[0.65rem] text-neutral-500">
                  <span className="text-[#8B5CF6] uppercase font-bold">{s.role}</span>
                  {" · "}{t("admin.security.createdAt")} {s.created_at?.slice(0, 16).replace("T", " ")}
                  {" · "}{t("admin.security.expiresAt")} {s.expires_at?.slice(0, 16).replace("T", " ")}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                data-testid={`revoke-sessions-btn-${s.user_id}`}
                onClick={() => onRevokeSessions(s.user_id, s.email)}
                disabled={revoking === s.user_id}
                className="bg-[#EF4444]/10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/20"
              >
                <LogOut className="w-3.5 h-3.5 mr-1" /> {t("admin.security.revoke")}
              </Button>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel
        icon={MapPin}
        title={t("admin.security.newIpLogins")}
        subtitle={t("admin.security.newIpDesc")}
      >
        {data.admin_new_ip_logins.length === 0
          && <Empty text={t("admin.security.noNewIpLogins")} />}
        <TableSimple
          headers={HEADERS_NEW_IP}
          rows={data.admin_new_ip_logins.map((e) => [
            e.created_at?.slice(0, 16).replace("T", " "),
            e.user_email || "-",
            e.extra?.role || "-",
            e.ip,
            (e.user_agent || "-").slice(0, 60),
          ])}
        />
      </Panel>

      <Panel
        icon={Ban}
        title={t("admin.security.topRateLimited")}
        subtitle={t("admin.security.topRateLimitedDesc")}
      >
        {data.top_rate_limited_ips.length === 0
          && <Empty text={t("admin.security.noRateLimited")} />}
        <TableSimple
          headers={HEADERS_RATE_LIMITED}
          rows={data.top_rate_limited_ips.map((r) => [
            r.ip,
            r.hits,
            r.last_seen?.slice(0, 16).replace("T", " "),
            r.top_paths.slice(0, 3).join(", "),
          ])}
        />
      </Panel>

      <Panel
        icon={AlertOctagon}
        title={t("admin.security.originViolations")}
        subtitle={t("admin.security.originViolationsDesc")}
      >
        {data.recent_origin_violations.length === 0
          && <Empty text={t("admin.security.noOriginViolations")} />}
        <TableSimple
          headers={HEADERS_ORIGIN_VIOLATIONS}
          rows={data.recent_origin_violations.map((e) => [
            e.created_at?.slice(0, 16).replace("T", " "),
            e.origin || "-",
            e.ip,
            e.method,
            e.path,
          ])}
        />
      </Panel>

      <Panel
        icon={AlertOctagon}
        title={t("admin.security.loginBursts")}
        subtitle={t("admin.security.loginBurstsDesc")}
      >
        {data.recent_login_bursts.length === 0
          && <Empty text={t("admin.security.noLoginBursts")} />}
        <TableSimple
          headers={HEADERS_LOGIN_BURSTS}
          rows={data.recent_login_bursts.map((r) => [
            r.identifier,
            r.failed_attempts,
            r.last_seen?.slice(0, 16).replace("T", " "),
          ])}
        />
      </Panel>
    </>
  );
}
