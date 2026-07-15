/**
 * VerificationGateBanner — iter55.36o (i18n'd in iter55.36s)
 *
 * Renders a prominent CTA banner when the current user has not completed
 * ALL required verifications (email + phone + KYC). Reads the
 * `user.verification` snapshot returned by `/api/auth/me` — no extra
 * network round-trip.
 *
 * Usage:
 *   <VerificationGateBanner blocking={true} action="createOrders">
 *     <ExchangeForm ... />
 *   </VerificationGateBanner>
 *
 * `action` is an i18n key suffix under `verificationGate.actions.*`.
 */
import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ShieldAlert, Mail, Phone, IdCard, ArrowRight } from "lucide-react";

const STEP_META = {
  email: { icon: Mail, href: "/dashboard/security", testid: "gate-cta-email" },
  phone: { icon: Phone, href: "/dashboard/security", testid: "gate-cta-phone" },
  kyc:   { icon: IdCard, href: "/dashboard/kyc", testid: "gate-cta-kyc" },
};

export default function VerificationGateBanner({ children, blocking = false, action = "operate" }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const verification = user?.verification;

  if (!verification || verification.fully_verified) return children ?? null;

  const missing = verification.missing || [];
  const actionLabel = t(`verificationGate.actions.${action}`, { defaultValue: t("verificationGate.actions.operate") });

  const banner = (
    <div
      data-testid="verification-gate-banner"
      className="tactile-card p-6 lg:p-8 border-2 border-amber-500/40 bg-amber-500/5 space-y-5"
    >
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-12 h-12 rounded-none border border-amber-500/40 bg-amber-500/10 flex items-center justify-center">
          <ShieldAlert className="w-6 h-6 text-amber-400" />
        </div>
        <div className="flex-1">
          <div className="micro-label text-amber-400 mb-1">{t("verificationGate.eyebrow")}</div>
          <h2 className="font-display text-2xl mb-2">
            {t("verificationGate.title", { action: actionLabel })}
          </h2>
          <p className="text-neutral-300 text-sm">
            {t("verificationGate.subtitle")}
          </p>
        </div>
      </div>

      <ul className="space-y-2">
        {missing.map((key) => {
          const meta = STEP_META[key];
          if (!meta) return null;
          const Icon = meta.icon;
          return (
            <li key={key}>
              <button
                type="button"
                data-testid={meta.testid}
                onClick={() => navigate(meta.href)}
                className="group w-full flex items-center gap-3 p-4 border border-white/10 hover:border-amber-400/60 hover:bg-amber-500/[0.04] transition-all text-left"
              >
                <Icon className="w-5 h-5 text-amber-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white">{t(`verificationGate.steps.${key}.label`)}</div>
                  <div className="text-xs text-neutral-500">{t(`verificationGate.steps.${key}.hint`)}</div>
                </div>
                <ArrowRight className="w-4 h-4 text-neutral-500 group-hover:text-amber-400 group-hover:translate-x-0.5 transition-all flex-shrink-0" />
              </button>
            </li>
          );
        })}
      </ul>

      <div className="text-xs text-neutral-500 pt-2 border-t border-white/5">
        {t("verificationGate.footer", { action: actionLabel })}
      </div>
    </div>
  );

  if (blocking) return banner;
  return (<>{banner}{children}</>);
}
