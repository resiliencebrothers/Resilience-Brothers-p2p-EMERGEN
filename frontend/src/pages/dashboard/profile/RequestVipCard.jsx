import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Crown, Clock, XCircle, CheckCircle2 } from "lucide-react";
import RequestVipDialog from "./RequestVipDialog";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * iter109 — "Programa VIP" card in Mi Perfil.
 *
 * Only visible for role="normal" clients. Shows:
 *   - no request yet          → CTA to open the dialog
 *   - pending                 → info banner (yellow)
 *   - rejected (cooldown)     → red banner + admin_note + retry-in-N-days
 *   - rejected (elapsed)      → red banner + CTA to submit again
 *
 * Refreshes on the SSE events `vip_request_created` and
 * `vip_request_updated` so the client sees state changes without reload.
 */
export default function RequestVipCard({ userRole }) {
  const { t } = useTranslation();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/vip/requests/me`, { withCredentials: true });
      setState(r.data);
    } catch {
      setState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (userRole === "normal") refresh();
    else setLoading(false);
  }, [userRole, refresh]);

  // Live push if the client is currently on the profile page when the
  // admin approves/rejects — state flips without a manual refresh.
  useLiveEvent(userRole === "normal" ? "vip_request_updated" : null, refresh);
  useLiveEvent(userRole === "normal" ? "vip_request_approved" : null, refresh);
  useLiveEvent(userRole === "normal" ? "vip_request_rejected" : null, refresh);

  if (userRole !== "normal") return null;
  if (loading) return null;

  const req = state?.request;
  const cooldownDays = state?.cooldown_days_left || 0;
  const canSubmit = !!state?.can_submit;

  return (
    <section
      className="tactile-card p-6 space-y-3"
      data-testid="profile-vip-request-card"
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
        <div className="flex items-center gap-2">
          <Crown className="w-4 h-4 text-amber-400" />
          <span className="micro-label text-neutral-500">
            {t("vipRequest.sectionTitle")}
          </span>
        </div>
        {req?.status && (
          <StatusBadge status={req.status} />
        )}
      </div>

      {!req && (
        <>
          <p className="text-xs text-neutral-400 leading-relaxed">
            {t("vipRequest.emptyBody")}
          </p>
          <Button
            onClick={() => setDialogOpen(true)}
            data-testid="open-vip-request-dialog"
            className="rounded-none bg-amber-500 hover:bg-amber-400 text-black font-semibold h-9 px-4 text-xs uppercase tracking-wider"
          >
            <Crown className="w-4 h-4 mr-2" />
            {t("vipRequest.ctaFirstTime")}
          </Button>
        </>
      )}

      {req?.status === "pending" && (
        <div className="border border-amber-500/30 bg-amber-500/5 px-4 py-3 flex items-start gap-3">
          <Clock className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div className="text-xs text-neutral-300 leading-relaxed">
            <div className="text-amber-300 font-semibold mb-1">
              {t("vipRequest.pendingTitle")}
            </div>
            <div>
              {t("vipRequest.pendingBody", {
                date: new Date(req.created_at).toLocaleDateString(),
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
                {t("vipRequest.rejectedTitle")}
              </div>
              {req.admin_note ? (
                <div className="italic text-neutral-400">&ldquo;{req.admin_note}&rdquo;</div>
              ) : (
                <div className="text-neutral-500">{t("vipRequest.rejectedNoNote")}</div>
              )}
              {cooldownDays > 0 && (
                <div className="mt-2 text-amber-400" data-testid="vip-cooldown-notice">
                  {t("vipRequest.cooldownRemaining", { days: cooldownDays })}
                </div>
              )}
            </div>
          </div>
          {canSubmit && (
            <Button
              onClick={() => setDialogOpen(true)}
              data-testid="open-vip-request-dialog"
              className="rounded-none bg-amber-500 hover:bg-amber-400 text-black font-semibold h-9 px-4 text-xs uppercase tracking-wider"
            >
              {t("vipRequest.ctaRetry")}
            </Button>
          )}
        </>
      )}

      {req?.status === "approved" && (
        <div className="border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
          <div className="text-xs text-neutral-300 leading-relaxed">
            {t("vipRequest.approvedBody")}
          </div>
        </div>
      )}

      <RequestVipDialog
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
    pending:  "bg-amber-500/10 text-amber-400 border-amber-500/30",
    approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  };
  const cls = map[status] || map.pending;
  return (
    <span
      data-testid={`vip-request-status-${status}`}
      className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 font-mono ${cls}`}
    >
      {t(`vipRequest.status.${status}`)}
    </span>
  );
}
