import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import {
  CheckCircle2, XCircle, Info, User, Mail, Phone, AlertTriangle, Loader2,
} from "lucide-react";

const REJECT_REASON_KEYS = [
  "blurry", "expired", "selfie_mismatch", "manipulated",
  "name_mismatch", "invalid_country", "incomplete",
];

/**
 * Approve / reject / more-info dialog. Side-by-side layout: declared
 * profile vs uploaded documents. Reject shows a required checklist of
 * pre-canned reasons; more-info requires a text explanation.
 */
export default function KYCActionDialog({
  selected, action, notes, onNotesChange,
  reasons, onToggleReason,
  saving, onClose, onSubmit,
}) {
  const { t } = useTranslation();
  const REJECT_REASONS = REJECT_REASON_KEYS.map((k) => ({
    key: k,
    label: t(`admin.kycAdmin.reject_reasons.${k}`),
  }));

  return (
    <Dialog open={!!selected} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="bg-neutral-950 border-white/10 max-w-4xl max-h-[90vh] overflow-y-auto"
        data-testid="kyc-action-dialog"
      >
        {selected && (
          <>
            <DialogHeader>
              <DialogTitle className="text-white flex items-center gap-2">
                {action === "approve" && <><CheckCircle2 className="w-5 h-5 text-emerald-400" /> {t("admin.kycAdmin.actionApprove")}</>}
                {action === "reject" && <><XCircle className="w-5 h-5 text-[#EF4444]" /> {t("admin.kycAdmin.actionReject")}</>}
                {action === "more_info" && <><Info className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.kycAdmin.actionMoreInfo")}</>}
              </DialogTitle>
              <DialogDescription className="text-neutral-500">
                {t("admin.kycAdmin.actionDesc")}
              </DialogDescription>
            </DialogHeader>

            <div className="grid md:grid-cols-2 gap-4">
              <div
                className="border border-white/10 bg-black/40 p-4 space-y-2.5"
                data-testid="kyc-declared-panel"
              >
                <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-2">
                  {t("admin.kycAdmin.declaredPanel")}
                </div>
                <ProfileField label={t("admin.kycAdmin.fFullName")} value={selected.user_name} icon={User} />
                <ProfileField label={t("admin.kycAdmin.fEmail")} value={selected.user_email} icon={Mail} />
                <ProfileField label={t("admin.kycAdmin.fPhone")} value={selected.user_phone || "—"} icon={Phone} />
                <ProfileField
                  label={t("admin.kycAdmin.fRiskAuto")}
                  value={`${selected.risk_score}/100`}
                  tone={selected.risk_score >= 60 ? "danger" : selected.risk_score >= 30 ? "warn" : "ok"}
                />
                <ProfileField
                  label={t("admin.kycAdmin.fSubmittedAt")}
                  value={selected.created_at?.slice(0, 16).replace("T", " ")}
                />
                {selected.submit_ip && (
                  <ProfileField label={t("admin.kycAdmin.fSubmitIp")} value={selected.submit_ip} mono />
                )}
                {selected.risk_flags?.length > 0 && (
                  <div className="border border-amber-500/30 bg-amber-500/5 p-2 mt-3 space-y-1">
                    <div className="text-[0.65rem] font-semibold text-amber-300 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5" /> {t("admin.kycAdmin.riskSignals")}
                    </div>
                    {selected.risk_flags.map((f) => (
                      <div key={f.code} className="text-[0.7rem] text-amber-200">
                        • [{f.severity}] {f.message}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div
                className="border border-white/10 bg-black/40 p-4 space-y-2"
                data-testid="kyc-documents-panel"
              >
                <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-1">
                  {t("admin.kycAdmin.documentsPanel", { n: selected.documents?.length || 0 })}
                </div>
                {selected.documents?.map((d) => (
                  <div key={d.doc_type} className="space-y-1">
                    <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">
                      {d.doc_type.replace("_", " ")}
                    </div>
                    <a href={d.ref} target="_blank" rel="noreferrer" className="block">
                      <img
                        src={d.ref}
                        alt={d.doc_type}
                        className="w-full h-40 object-contain bg-neutral-900 border border-white/10 hover:border-[#8B5CF6]/60 transition"
                        data-testid={`kyc-doc-${d.doc_type}`}
                      />
                    </a>
                  </div>
                ))}
              </div>
            </div>

            {action === "reject" && (
              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wider text-neutral-500">
                  {t("admin.kycAdmin.reasonsLabel")}
                </label>
                {REJECT_REASONS.map((r) => (
                  <label
                    key={r.key}
                    className="flex items-center gap-2 text-sm text-neutral-200 cursor-pointer"
                  >
                    <Checkbox
                      data-testid={`kyc-reject-reason-${r.key}`}
                      checked={reasons.includes(r.label)}
                      onCheckedChange={() => onToggleReason(r.label)}
                    />
                    {r.label}
                  </label>
                ))}
              </div>
            )}

            <div>
              <label className="text-xs uppercase tracking-wider text-neutral-500">
                {action === "more_info" ? t("admin.kycAdmin.notesMoreInfo") : t("admin.kycAdmin.notesInternal")}
              </label>
              <Textarea
                data-testid="kyc-action-notes"
                value={notes}
                onChange={(e) => onNotesChange(e.target.value)}
                rows={3}
                placeholder={action === "more_info" ? t("admin.kycAdmin.notesMoreInfoPh") : ""}
                className="bg-black/40 border-white/10 text-white text-sm mt-1"
              />
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={onClose}
                className="border-white/10 text-neutral-300 hover:bg-white/5"
              >
                {t("admin.common.cancel")}
              </Button>
              <Button
                data-testid="kyc-action-submit"
                onClick={onSubmit}
                disabled={saving}
                className={
                  action === "approve" ? "bg-emerald-500 text-black hover:bg-emerald-500/90" :
                  action === "reject"  ? "bg-[#EF4444] text-white hover:bg-[#EF4444]/90" :
                                         "bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90"
                }
              >
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {t("admin.kycAdmin.confirm")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ProfileField({ label, value, icon: Icon, tone, mono }) {
  const toneCls =
    tone === "danger" ? "text-[#EF4444]" :
    tone === "warn"   ? "text-amber-300"  :
    tone === "ok"     ? "text-emerald-400" : "text-white";
  return (
    <div className="flex items-start gap-2">
      {Icon && <Icon className="w-3.5 h-3.5 text-neutral-500 mt-0.5 flex-shrink-0" />}
      <div className="min-w-0 flex-1">
        <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500">{label}</div>
        <div className={`text-sm ${mono ? "font-mono" : ""} ${toneCls} break-words`}>
          {value || <span className="text-neutral-600 italic">—</span>}
        </div>
      </div>
    </div>
  );
}
