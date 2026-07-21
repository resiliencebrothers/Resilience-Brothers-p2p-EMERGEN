import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  User, Mail, Phone, AlertTriangle, Check, X, Info,
  CheckCircle2, XCircle,
} from "lucide-react";

/**
 * One row of the KYC review queue. Shows the client's declared identity,
 * risk score, risk signals + inline approve / more info / reject buttons.
 */
export default function KYCVerificationRow({
  v, idx, focused, inBatch, onSelect, onToggleBatch, onAction,
}) {
  const { t } = useTranslation();
  const statusStyle = {
    pending: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5",
    needs_more_info: "border-blue-500/40 bg-blue-500/5",
    verified: "border-emerald-500/40 bg-emerald-500/5",
    rejected: "border-neutral-500/30 bg-neutral-500/5",
  }[v.status];
  const riskColor =
    v.risk_score >= 60 ? "text-[#EF4444]" :
    v.risk_score >= 30 ? "text-[#8B5CF6]" :
                         "text-emerald-400";
  const isActionable = v.status === "pending" || v.status === "needs_more_info";
  const focusRing = focused ? "ring-2 ring-[#8B5CF6] ring-offset-2 ring-offset-black" : "";

  return (
    <div
      data-kyc-row
      className={`border ${statusStyle} ${focusRing} p-4 cursor-pointer transition-shadow`}
      data-testid={`kyc-row-${v.id}`}
      onClick={onSelect}
    >
      <div className="flex flex-col md:flex-row md:items-start gap-3">
        {isActionable && (
          <Checkbox
            data-testid={`kyc-batch-checkbox-${v.id}`}
            checked={inBatch}
            onCheckedChange={onToggleBatch}
            onClick={(e) => e.stopPropagation()}
            className="mt-1"
          />
        )}

        <div className="flex-1 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-white flex items-center gap-1.5">
              <User className="w-4 h-4 text-neutral-500" /> {v.user_name}
            </div>
            <span className={`text-xs font-mono ${riskColor}`}>
              {t("admin.kycAdmin.rowRisk", { score: v.risk_score })}
            </span>
            {v.risk_flags?.length > 0 && (
              <span className="text-[0.65rem] text-amber-300 uppercase">
                <AlertTriangle className="inline w-3 h-3 mr-0.5" />
                {t("admin.kycAdmin.rowSignals", { n: v.risk_flags.length })}
              </span>
            )}
            {focused && (
              <span className="ml-auto text-[0.65rem] text-[#8B5CF6] uppercase tracking-wider">
                {t("admin.kycAdmin.rowFocused", { n: idx + 1 })}
              </span>
            )}
          </div>

          <div className="flex flex-wrap gap-3 text-xs text-neutral-400">
            <span className="flex items-center gap-1"><Mail className="w-3 h-3" /> {v.user_email}</span>
            <span className="flex items-center gap-1"><Phone className="w-3 h-3" /> {v.user_phone || "—"}</span>
            <span className="text-neutral-500">
              {t("admin.kycAdmin.rowSent", { ts: v.created_at?.slice(0, 16).replace("T", " ") })}
            </span>
          </div>

          {v.risk_flags?.length > 0 && (
            <ul className="text-[0.7rem] text-amber-200/80 mt-1 space-y-0.5">
              {v.risk_flags.slice(0, 3).map((f) => (
                <li key={f.code}>• {f.message}</li>
              ))}
            </ul>
          )}

          {v.status === "rejected" && v.rejection_reasons?.length > 0 && (
            <div className="text-[0.7rem] text-neutral-400">
              {t("admin.kycAdmin.rowRejectedReasons", {
                list: v.rejection_reasons.join(" · "),
              })}
            </div>
          )}

          {v.review_notes && (
            <div className="text-[0.7rem] text-neutral-400 italic">
              {t("admin.kycAdmin.rowNote", { text: v.review_notes })}
            </div>
          )}
        </div>

        {isActionable && (
          <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
            <Button
              data-testid={`kyc-approve-btn-${v.id}`}
              size="sm"
              onClick={() => onAction(v, "approve")}
              className="bg-emerald-500 text-black hover:bg-emerald-500/90 h-8"
            >
              <Check className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowApprove")}
            </Button>
            <Button
              data-testid={`kyc-more-info-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "more_info")}
              className="border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-8"
            >
              <Info className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowMoreInfo")}
            </Button>
            <Button
              data-testid={`kyc-reject-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "reject")}
              className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
            >
              <X className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowReject")}
            </Button>
          </div>
        )}
        {v.status === "verified" && (
          <div className="text-emerald-400 text-xs font-semibold flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4" /> {t("admin.kycAdmin.rowVerified")}
          </div>
        )}
        {v.status === "rejected" && (
          <div className="text-[#EF4444] text-xs font-semibold flex items-center gap-1">
            <XCircle className="w-4 h-4" /> {t("admin.kycAdmin.rowRejected")}
          </div>
        )}
      </div>
    </div>
  );
}
