import { Clock, CheckCircle2, XCircle, ShieldAlert, User, Info } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Six-card horizontal funnel (Total → Pending → High-Risk → More info →
 * Verified → Rejected). Pure presentational component — accepts the funnel
 * shape returned by /api/admin/kyc/funnel.
 */
export default function KYCFunnelCards({ funnel }) {
  const { t } = useTranslation();
  if (!funnel) return null;
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
      <FunnelCard label={t("admin.kycAdmin.funnelTotal")} value={funnel.total_users} icon={User} tone="neutral" testid="funnel-total" />
      <FunnelCard label={t("admin.kycAdmin.funnelPending")} value={funnel.pending} icon={Clock} tone="warn" testid="funnel-pending" />
      <FunnelCard label={t("admin.kycAdmin.funnelHighRisk")} value={funnel.high_risk_pending} icon={ShieldAlert} tone="danger" testid="funnel-high-risk" />
      <FunnelCard label={t("admin.kycAdmin.funnelMoreInfo")} value={funnel.needs_more_info} icon={Info} tone="neutral" testid="funnel-more-info" />
      <FunnelCard label={t("admin.kycAdmin.funnelVerified")} value={funnel.verified} icon={CheckCircle2} tone="ok" testid="funnel-verified" />
      <FunnelCard label={t("admin.kycAdmin.funnelRejected")} value={funnel.rejected} icon={XCircle} tone="muted" testid="funnel-rejected" />
    </div>
  );
}

function FunnelCard({ label, value, icon: Icon, tone, testid }) {
  const toneClasses = {
    neutral: "border-white/10 bg-black/30 text-white",
    warn: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    muted: "border-white/5 bg-black/20 text-neutral-400",
  };
  return (
    <div className={`border ${toneClasses[tone]} p-3`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[0.65rem] uppercase tracking-wider opacity-70">{label}</span>
        <Icon className="w-4 h-4 opacity-60" />
      </div>
      <div className="text-2xl font-bold">{value ?? 0}</div>
    </div>
  );
}
