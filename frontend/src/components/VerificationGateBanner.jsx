/**
 * VerificationGateBanner — iter55.36o
 *
 * Renders a prominent CTA banner when the current user has not completed
 * ALL required verifications (email + phone + KYC). Reads the
 * `user.verification` snapshot returned by `/api/auth/me` — no extra
 * network round-trip.
 *
 * Behaviour:
 *   - Staff (admin, employee) never see the banner — the backend
 *     `verification.fully_verified` is `true` for them.
 *   - Each missing step gets its own actionable link so the operator
 *     doesn't have to guess where to click next.
 *   - Optional `blocking` prop: when true, the banner replaces the
 *     children entirely (used on ExchangeView so the submit button is
 *     invisible while the user is unverified — no way to hit the API).
 *
 * Usage:
 *   <VerificationGateBanner blocking={true}>
 *     <ExchangeForm ... />
 *   </VerificationGateBanner>
 */
import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import { ShieldAlert, Mail, Phone, IdCard, ArrowRight } from "lucide-react";

const STEP_META = {
  email: {
    label: "Verificar email",
    hint: "Confirma tu correo desde el enlace que te enviamos al registrarte.",
    icon: Mail,
    href: "/dashboard/security",
    testid: "gate-cta-email",
  },
  phone: {
    label: "Verificar teléfono",
    hint: "Un miembro del staff debe confirmar tu número. Contacta a soporte para acelerarlo.",
    icon: Phone,
    href: "/dashboard/security",
    testid: "gate-cta-phone",
  },
  kyc: {
    label: "Completar KYC",
    hint: "Sube tu documento de identidad y una selfie desde el módulo de verificación.",
    icon: IdCard,
    href: "/dashboard/kyc",
    testid: "gate-cta-kyc",
  },
};

export default function VerificationGateBanner({ children, blocking = false, action = "operar" }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const verification = user?.verification;

  // Backend hasn't returned the snapshot yet (older cached user object) or
  // staff bypass — render children normally.
  if (!verification || verification.fully_verified) {
    return children ?? null;
  }

  const missing = verification.missing || [];

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
          <div className="micro-label text-amber-400 mb-1">/ Verificación requerida</div>
          <h2 className="font-display text-2xl mb-2">
            Completa tu verificación para poder {action}
          </h2>
          <p className="text-neutral-300 text-sm">
            Por normativa AML/KYC y para proteger a los usuarios de Resilience Brothers, exigimos
            estas 3 verificaciones antes de habilitar operaciones. Solo tomará unos minutos.
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
                  <div className="text-sm font-medium text-white">{meta.label}</div>
                  <div className="text-xs text-neutral-500">{meta.hint}</div>
                </div>
                <ArrowRight className="w-4 h-4 text-neutral-500 group-hover:text-amber-400 group-hover:translate-x-0.5 transition-all flex-shrink-0" />
              </button>
            </li>
          );
        })}
      </ul>

      <div className="text-xs text-neutral-500 pt-2 border-t border-white/5">
        Una vez completes cada paso, esta pantalla desbloqueará automáticamente el formulario de
        {" "}
        {action}.
      </div>
    </div>
  );

  if (blocking) {
    return banner;
  }

  return (
    <>
      {banner}
      {children}
    </>
  );
}
