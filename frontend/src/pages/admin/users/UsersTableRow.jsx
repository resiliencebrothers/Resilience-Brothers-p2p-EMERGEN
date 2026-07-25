/**
 * iter100 — Extracted from AdminUsers.jsx.
 * A single row of the users table: identity, email verification badge/CTA,
 * role badge and per-user action buttons (Stats + Functions dialog).
 *
 * iter106 — Adds a KYC status badge column for `normal`/`vip` clients.
 * Falls back to "not_started" so anything unknown renders as neutral.
 */
import { useTranslation } from "react-i18next";
import { BarChart3, Settings2 } from "lucide-react";
import CopyableText from "@/components/CopyableText";
import { KYC_META } from "../user-stats/userStatsMeta";

const ROLE_BADGE_CLASSES = {
  admin:    "border-[#8B5CF6]/50 bg-[#8B5CF6]/10 text-[#8B5CF6]",
  employee: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400",
  vip:      "border-amber-500/40 bg-amber-500/5 text-amber-400",
  normal:   "border-white/10 bg-white/5 text-neutral-300",
};

const KYC_BADGE_TONE = {
  verified:        "border-emerald-500/40 bg-emerald-500/5 text-emerald-400",
  approved:        "border-emerald-500/40 bg-emerald-500/5 text-emerald-400",
  pending:         "border-amber-500/40 bg-amber-500/5 text-amber-400",
  needs_more_info: "border-amber-500/40 bg-amber-500/5 text-amber-400",
  rejected:        "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]",
  not_started:     "border-white/10 bg-white/5 text-neutral-400",
};

export default function UsersTableRow({
  user, roleLabel,
  onVerifyEmail, onOpenStats, onOpenFunctions,
}) {
  const { t } = useTranslation();
  const badgeClass = ROLE_BADGE_CLASSES[user.role] || ROLE_BADGE_CLASSES.normal;
  const needsEmailVerify = user.auth_provider === "password" && user.email_verified === false;
  const canShowStats = user.role === "vip" || user.role === "normal";

  // iter106 — KYC only applies to client roles; admins/staff show "—".
  const kycStatus = user.effective_kyc_status || user.kyc_status || "not_started";
  const kycMeta = KYC_META[kycStatus] || KYC_META.not_started;
  const kycTone = KYC_BADGE_TONE[kycStatus] || KYC_BADGE_TONE.not_started;
  const KycIcon = kycMeta.icon;
  return (
    <tr key={user.user_id} className="border-b border-white/5">
      <td className="px-4 py-3 flex items-center gap-2">
        {user.picture && <img src={user.picture} alt="" className="w-7 h-7 rounded-full" />}
        <span>{user.name}</span>
      </td>
      <td
        className="px-4 py-3 text-xs text-neutral-400 whitespace-nowrap align-middle"
        data-testid={`user-id-cell-${user.user_id}`}
      >
        <CopyableText
          value={user.user_id}
          testid={`user-id-copy-${user.user_id}`}
          toastMessage={t("admin.users.userIdCopied")}
          label={t("admin.users.copyUserId")}
          className="text-xs"
        />
      </td>
      <td className="px-4 py-3 text-neutral-400">
        <div className="flex items-center gap-2 flex-wrap">
          <span>{user.email}</span>
          {needsEmailVerify && (
            <>
              <span
                data-testid={`email-unverified-${user.user_id}`}
                className="text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"
                title={t("admin.users.notVerifiedTitle")}
              >
                {t("admin.users.notVerified")}
              </span>
              <button
                type="button"
                data-testid={`verify-email-btn-${user.user_id}`}
                onClick={() => onVerifyEmail(user.user_id, user.email)}
                className="text-[0.65rem] uppercase tracking-widest text-[#8B5CF6] hover:text-[#A78BFA] underline underline-offset-4"
                title={t("admin.users.verifyTitle")}
              >
                {t("admin.users.verify")}
              </button>
            </>
          )}
        </div>
      </td>
      <td className="px-4 py-3" data-testid={`role-cell-${user.user_id}`}>
        <span
          data-testid={`role-badge-${user.user_id}`}
          className={`text-[0.65rem] uppercase tracking-widest px-2 py-1 border font-mono ${badgeClass}`}
        >
          {roleLabel}
        </span>
      </td>
      <td className="px-4 py-3" data-testid={`kyc-cell-${user.user_id}`}>
        {canShowStats ? (
          <span
            data-testid={`kyc-badge-${user.user_id}`}
            title={kycMeta.label}
            className={`inline-flex items-center gap-1 text-[0.65rem] uppercase tracking-widest px-2 py-1 border font-mono ${kycTone}`}
          >
            {KycIcon && <KycIcon className="w-3 h-3" />}
            {kycMeta.label}
          </span>
        ) : (
          <span className="text-xs text-neutral-600">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-neutral-500">
        {new Date(user.created_at).toLocaleDateString()}
      </td>
      <td className="px-4 py-3 sticky right-0 bg-[#1A1730] z-10 shadow-[-8px_0_12px_-4px_rgba(0,0,0,0.6)]">
        <div className="flex items-center gap-2">
          {canShowStats && (
            <button
              type="button"
              onClick={() => onOpenStats(user.user_id)}
              className="flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 hover:border-[#8B5CF6] hover:bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs uppercase tracking-widest transition-all"
              title={t("admin.users.statsTitle")}
              data-testid={`user-stats-btn-${user.user_id}`}
            >
              <BarChart3 className="w-3.5 h-3.5" />
              {t("admin.users.stats")}
            </button>
          )}
          <button
            type="button"
            onClick={() => onOpenFunctions(user)}
            className="flex items-center gap-1.5 px-3 py-2 border border-emerald-500/40 hover:border-emerald-500 hover:bg-emerald-500/10 text-emerald-400 text-xs uppercase tracking-widest transition-all"
            title={t("admin.users.functionsTitle")}
            data-testid={`user-perms-btn-${user.user_id}`}
          >
            <Settings2 className="w-3.5 h-3.5" />
            {t("admin.users.functions")}
          </button>
        </div>
      </td>
    </tr>
  );
}
