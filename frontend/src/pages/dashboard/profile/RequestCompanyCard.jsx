import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Building2, Clock, XCircle, CheckCircle2 } from "lucide-react";
import RequestCompanyDialog from "./RequestCompanyDialog";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * Programa Empresas — tarjeta en "Mi Perfil".
 *
 * Visible para clientes (role="normal" o "vip"). A diferencia de VIP, la
 * aprobación NO cambia el rol de esta cuenta: crea una cuenta Empresa NUEVA
 * e independiente con credenciales propias. Estados:
 *   - sin solicitud            → CTA para abrir el diálogo
 *   - pending                  → banner informativo
 *   - rejected (cooldown)      → banner + nota del admin + reintento en N días
 *   - approved                 → banner verde + email de la cuenta nueva
 */
export default function RequestCompanyCard({ userRole }) {
  const { t } = useTranslation();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  const eligible = userRole === "normal" || userRole === "vip";

  const refresh = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/company-requests/me`, { withCredentials: true });
      setState(r.data);
    } catch {
      setState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (eligible) refresh();
    else setLoading(false);
  }, [eligible, refresh]);

  useLiveEvent(eligible ? "company_request_approved" : null, refresh);
  useLiveEvent(eligible ? "company_request_rejected" : null, refresh);

  if (!eligible) return null;
  if (loading) return null;

  const req = state?.request;
  const cooldownDays = state?.cooldown_days_left || 0;
  const canSubmit = !!state?.can_submit;

  return (
    <section
      className="tactile-card p-6 space-y-3"
      data-testid="profile-company-request-card"
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
        <div className="flex items-center gap-2">
          <Building2 className="w-4 h-4 text-[#8B5CF6]" />
          <span className="micro-label text-neutral-500">
            {t("companyRequest.sectionTitle")}
          </span>
        </div>
        {req?.status && <StatusBadge status={req.status} />}
      </div>

      {!req && (
        <>
          <p className="text-xs text-neutral-400 leading-relaxed">
            {t("companyRequest.emptyBody")}
          </p>
          <Button
            onClick={() => setDialogOpen(true)}
            data-testid="open-company-request-dialog"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold h-9 px-4 text-xs uppercase tracking-wider"
          >
            <Building2 className="w-4 h-4 mr-2" />
            {t("companyRequest.ctaFirstTime")}
          </Button>
        </>
      )}

      {req?.status === "pending" && (
        <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 px-4 py-3 flex items-start gap-3">
          <Clock className="w-4 h-4 text-[#8B5CF6] mt-0.5 shrink-0" />
          <div className="text-xs text-neutral-300 leading-relaxed">
            <div className="text-[#A78BFA] font-semibold mb-1">
              {t("companyRequest.pendingTitle")}
            </div>
            <div>
              {t("companyRequest.pendingBody", {
                company: req.company_name,
                email: req.account_email,
              })}
            </div>
          </div>
        </div>
      )}

      {req?.status === "rejected" && (
        <>
          <div className="border border-[#EF4444]/30 bg-[#EF4444]/5 px-4 py-3 flex items-start gap-3">
            <XCircle className="w-4 h-4 text-[#EF4444] mt-0.5 shrink-0" />
            <div className="text-xs text-neutral-300 leading-relaxed flex-1">
              <div className="text-[#EF4444] font-semibold mb-1">
                {t("companyRequest.rejectedTitle")}
              </div>
              {req.admin_note ? (
                <div className="italic text-neutral-400">&ldquo;{req.admin_note}&rdquo;</div>
              ) : (
                <div className="text-neutral-500">{t("companyRequest.rejectedNoNote")}</div>
              )}
              {cooldownDays > 0 && (
                <div className="mt-2 text-amber-400" data-testid="company-cooldown-notice">
                  {t("companyRequest.cooldownRemaining", { days: cooldownDays })}
                </div>
              )}
            </div>
          </div>
          {canSubmit && (
            <Button
              onClick={() => setDialogOpen(true)}
              data-testid="open-company-request-dialog"
              className="rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold h-9 px-4 text-xs uppercase tracking-wider"
            >
              {t("companyRequest.ctaRetry")}
            </Button>
          )}
        </>
      )}

      {req?.status === "approved" && (
        <div className="border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
          <div className="text-xs text-neutral-300 leading-relaxed">
            {t("companyRequest.approvedBody", { email: req.account_email })}
          </div>
        </div>
      )}

      <RequestCompanyDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSubmitted={refresh}
      />
    </section>
  );
}


function StatusBadge({ status }) {
  const { t } = useTranslation();
  const map = {
    pending:  "bg-[#8B5CF6]/10 text-[#A78BFA] border-[#8B5CF6]/30",
    approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  };
  const cls = map[status] || map.pending;
  return (
    <span
      data-testid={`company-request-status-${status}`}
      className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 font-mono ${cls}`}
    >
      {t(`companyRequest.status.${status}`)}
    </span>
  );
}
