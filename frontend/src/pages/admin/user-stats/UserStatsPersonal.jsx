import { IdCard, Mail, Phone, ShieldCheck, User as UserIcon } from "lucide-react";
import { KYC_META, ROLE_LABELS, fmtDate } from "./userStatsMeta";

export default function UserStatsPersonal({ user, kyc }) {
  const kycMeta = KYC_META[kyc?.status || "not_started"] || KYC_META.not_started;
  const KycIcon = kycMeta.icon;
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="user-stats-personal">
      <div className="tactile-card p-5 lg:col-span-2">
        <div className="micro-label text-neutral-500 mb-3">Datos personales</div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <PersonalField
            icon={Mail}
            label="Email"
            value={user.email}
            truncate
            verified={user.email_verified}
            unverifiedLabel="⧗ No verificado"
          />
          <PersonalField
            icon={Phone}
            label="Teléfono"
            value={user.phone || "— sin registrar —"}
            mono
            truncate
            verified={user.phone ? user.phone_verified : null}
            unverifiedLabel="⧗ Pendiente"
          />
          <PersonalField
            icon={ShieldCheck}
            label="Autenticación 2FA"
            renderValue={() =>
              user.twofa_enabled ? (
                <span className="text-emerald-400 text-xs">✓ Activada</span>
              ) : (
                <span className="text-amber-400 text-xs">⧗ Desactivada</span>
              )
            }
          />
          <PersonalField
            icon={UserIcon}
            label="Rol"
            value={ROLE_LABELS[user.role] || user.role}
          />
        </div>
      </div>
      <div className="tactile-card p-5" data-testid="user-stats-kyc">
        <div className="micro-label text-neutral-500 mb-3 flex items-center gap-2">
          <IdCard className="w-3.5 h-3.5" /> Verificación KYC
        </div>
        <div className={`flex items-center gap-2 ${kycMeta.cls}`}>
          <KycIcon className="w-5 h-5" />
          <span className="font-display text-xl">{kycMeta.label}</span>
        </div>
        {kyc?.submitted_at && (
          <div className="text-xs text-neutral-500 mt-3">Enviado: {fmtDate(kyc.submitted_at)}</div>
        )}
        {kyc?.reviewed_at && (
          <div className="text-xs text-neutral-500 mt-1">Revisado: {fmtDate(kyc.reviewed_at)}</div>
        )}
        {kyc?.reviewer_notes && (
          <div className="text-xs text-neutral-400 mt-2 border-l-2 border-white/10 pl-2 italic">
            {kyc.reviewer_notes}
          </div>
        )}
      </div>
    </div>
  );
}

function PersonalField({ icon: Icon, label, value, mono, truncate, verified, unverifiedLabel, renderValue }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="w-4 h-4 text-neutral-500 shrink-0" />
      <div className={truncate ? "min-w-0 flex-1" : ""}>
        <div className="text-xs text-neutral-500">{label}</div>
        {renderValue ? (
          <div>{renderValue()}</div>
        ) : (
          <div className={`${mono ? "font-mono " : ""}${truncate ? "truncate" : ""}`}>{value}</div>
        )}
        {verified === true && <div className="text-[0.65rem] text-emerald-400 mt-0.5">✓ Verificado</div>}
        {verified === false && <div className="text-[0.65rem] text-amber-400 mt-0.5">{unverifiedLabel}</div>}
      </div>
    </div>
  );
}
