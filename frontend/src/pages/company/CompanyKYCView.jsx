import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  Building2, Upload, Check, X, Loader2, FileImage, FileText, ShieldCheck,
  AlertTriangle, Info, RefreshCw, ArrowRight,
} from "lucide-react";

// Verificación de cuenta Empresa: código fiscal, licencia operativa y
// dirección legal (en vez del documento de identidad personal + selfie).
// Reusa /kyc/my-status para el estado y POSTea a /kyc/company/submit.
const DOC_STEPS = [
  { key: "operating_license", labelKey: "operatingLicenseLabel", hintKey: "operatingLicenseHint" },
  { key: "legal_rep_id", labelKey: "legalRepIdLabel", hintKey: "legalRepIdHint" },
];

const STATUS_META = {
  unverified:      { tone: "muted",  icon: Info },
  pending:         { tone: "warn",   icon: Loader2 },
  needs_more_info: { tone: "warn",   icon: AlertTriangle },
  verified:        { tone: "ok",     icon: ShieldCheck },
  rejected:        { tone: "danger", icon: X },
  superseded:      { tone: "muted",  icon: Info },
};

export default function CompanyKYCView() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reverify, setReverify] = useState(false);
  const [fiscalCode, setFiscalCode] = useState("");
  const [legalAddress, setLegalAddress] = useState("");
  const [companyName, setCompanyName] = useState(user?.name || "");
  const [docs, setDocs] = useState({ operating_license: null, legal_rep_id: null });
  const fileRefs = { operating_license: useRef(), legal_rep_id: useRef() };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/kyc/my-status`, { withCredentials: true });
      setStatus(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("company.kyc.statusLoadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const handleFile = (docKey, ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { toast.error(t("company.kyc.fileTooLarge")); return; }
    const isImg = file.type.startsWith("image/");
    const isPdf = file.type === "application/pdf";
    if (!isImg && !isPdf) { toast.error(t("company.kyc.fileWrongType")); return; }
    const reader = new FileReader();
    reader.onload = () => setDocs((p) => ({ ...p, [docKey]: { data: reader.result, name: file.name, isPdf } }));
    reader.readAsDataURL(file);
  };

  const removeFile = (docKey) => {
    setDocs((p) => ({ ...p, [docKey]: null }));
    if (fileRefs[docKey].current) fileRefs[docKey].current.value = "";
  };

  const allReady = fiscalCode.trim() && legalAddress.trim()
    && docs.operating_license && docs.legal_rep_id;

  const submit = async () => {
    if (!allReady) { toast.error(t("company.kyc.completeRequired")); return; }
    setSubmitting(true);
    try {
      await axios.post(`${API}/kyc/company/submit`, {
        fiscal_code: fiscalCode.trim(),
        legal_address: legalAddress.trim(),
        company_name: companyName.trim(),
        operating_license: docs.operating_license.data,
        legal_rep_id: docs.legal_rep_id.data,
      }, { withCredentials: true });
      toast.success(t("company.kyc.submitted"));
      setDocs({ operating_license: null, legal_rep_id: null });
      setReverify(false);
      for (const k of Object.keys(fileRefs)) { if (fileRefs[k].current) fileRefs[k].current.value = ""; }
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("company.kyc.submitFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  const s = status?.status || "unverified";
  const v = status?.verification;
  // R05 — needs_more_info permite subsanar; R10 — 'superseded' (expediente
  // huérfano por un fallo de reemplazo) también puede reenviarse para recuperar.
  const canSubmit = s === "unverified" || s === "rejected"
    || s === "needs_more_info" || s === "superseded"
    || (s === "verified" && reverify);
  const cfg = STATUS_META[s] || STATUS_META.unverified;
  const StatusIcon = cfg.icon;
  const statusLabel = t(`company.kyc.status.${s}`, { defaultValue: s });
  const toneCls = {
    muted: "border-white/10 bg-black/30 text-neutral-300",
    warn: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
  }[cfg.tone];

  return (
    <div className="max-w-3xl space-y-6" data-testid="company-kyc-page">
      <header>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <Building2 className="w-7 h-7 text-[#8B5CF6]" /> {t("company.kyc.title")}
        </h1>
        <p className="text-neutral-500 text-sm mt-2">
          {t("company.kyc.subtitle")}
        </p>
      </header>

      {loading && <div className="text-neutral-500 text-sm">{t("company.kyc.loading")}</div>}

      {!loading && status && (
        <>
          <div className={`border ${toneCls} p-4 flex items-center gap-3`} data-testid="company-kyc-status-card">
            <StatusIcon className={`w-6 h-6 ${s === "pending" ? "animate-spin" : ""}`} />
            <div>
              <div className="text-sm font-semibold">{statusLabel}</div>
              {v?.created_at && (
                <div className="text-xs opacity-70">{t("company.kyc.submittedPrefix")} {v.created_at.slice(0, 16).replace("T", " ")}</div>
              )}
            </div>
          </div>

          {s === "rejected" && v?.rejection_reasons?.length > 0 && (
            <div className="border border-[#EF4444]/30 bg-[#EF4444]/5 p-4" data-testid="company-kyc-rejection">
              <div className="text-sm font-semibold text-[#FEE2E2] flex items-center gap-2 mb-2">
                <X className="w-4 h-4" /> {t("company.kyc.rejectionTitle")}
              </div>
              <ul className="text-xs text-neutral-300 space-y-1 list-disc pl-5">
                {v.rejection_reasons.map((r) => (<li key={r}>{r}</li>))}
              </ul>
              {v.review_notes && <div className="text-xs text-neutral-400 italic mt-2">{t("company.kyc.teamNote")} {v.review_notes}</div>}
            </div>
          )}

          {s === "needs_more_info" && v?.review_notes && (
            <div className="border border-blue-500/30 bg-blue-500/5 p-4" data-testid="company-kyc-more-info">
              <div className="text-sm font-semibold text-blue-200 flex items-center gap-2 mb-2">
                <Info className="w-4 h-4" /> {t("company.kyc.moreInfoTitle")}
              </div>
              <div className="text-xs text-neutral-300">{v.review_notes}</div>
            </div>
          )}

          {canSubmit && (
            <div className="space-y-4">
              {s === "verified" && reverify && (
                <div className="border border-amber-500/40 bg-amber-500/5 p-4 text-xs text-amber-200" data-testid="company-kyc-revalidation-notice">
                  {t("company.kyc.reverifyNoticePre")}<strong>{t("company.kyc.reverifyNoticeBold")}</strong>{t("company.kyc.reverifyNoticePost")}
                </div>
              )}
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">{t("company.kyc.companyName")}</label>
                  <Input
                    data-testid="company-kyc-name"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    placeholder={t("company.kyc.companyNamePlaceholder")}
                    className="bg-black/40 border-white/10 text-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">{t("company.kyc.fiscalCode")} *</label>
                  <Input
                    data-testid="company-kyc-fiscal-code"
                    value={fiscalCode}
                    onChange={(e) => setFiscalCode(e.target.value)}
                    placeholder={t("company.kyc.fiscalCodePlaceholder")}
                    className="bg-black/40 border-white/10 text-white font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wider text-neutral-500">{t("company.kyc.legalAddress")} *</label>
                <Textarea
                  data-testid="company-kyc-address"
                  value={legalAddress}
                  onChange={(e) => setLegalAddress(e.target.value)}
                  rows={2}
                  placeholder={t("company.kyc.legalAddressPlaceholder")}
                  className="bg-black/40 border-white/10 text-white"
                />
              </div>

              <h2 className="text-lg font-semibold text-white pt-2">{t("company.kyc.docsHeading")}</h2>
              {DOC_STEPS.map(({ key, labelKey, hintKey }) => {
                const label = t(`company.kyc.${labelKey}`);
                return (
                <div key={key} className="border border-white/10 bg-black/30 p-4" data-testid={`company-kyc-upload-${key}`}>
                  <div className="flex items-start gap-3">
                    <div className="flex-1 space-y-1">
                      <div className="text-sm font-semibold text-white flex items-center gap-2">
                        <FileImage className="w-4 h-4 text-[#8B5CF6]" /> {label} *
                      </div>
                      <div className="text-xs text-neutral-500">{t(`company.kyc.${hintKey}`)}</div>
                    </div>
                    {docs[key] ? (
                      <div className="flex items-center gap-2">
                        {docs[key].isPdf ? (
                          <span className="flex items-center gap-1.5 px-2 py-2 border border-white/10 bg-black/40 text-xs text-neutral-200 max-w-[10rem] truncate" title={docs[key].name}>
                            <FileText className="w-4 h-4 text-[#8B5CF6] shrink-0" /> {docs[key].name}
                          </span>
                        ) : (
                          <img src={docs[key].data} alt={label} className="w-20 h-20 object-cover border border-white/10" />
                        )}
                        <Button size="sm" variant="outline" onClick={() => removeFile(key)}
                          className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
                          data-testid={`company-kyc-remove-${key}`}>
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <label className="cursor-pointer">
                        <input ref={fileRefs[key]} type="file" accept="image/*,application/pdf"
                          onChange={(e) => handleFile(key, e)} className="hidden"
                          data-testid={`company-kyc-file-input-${key}`} />
                        <span className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs font-semibold hover:bg-[#8B5CF6]/20 transition">
                          <Upload className="w-3.5 h-3.5" /> {t("company.kyc.chooseFile")}
                        </span>
                      </label>
                    )}
                  </div>
                  {docs[key] && (
                    <div className="text-[0.65rem] text-emerald-400 mt-2 flex items-center gap-1">
                      <Check className="w-3 h-3" /> {t("company.kyc.readyToSend")}
                    </div>
                  )}
                </div>
                );
              })}

              <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
                <Button
                  data-testid="company-kyc-submit-btn"
                  onClick={submit}
                  disabled={!allReady || submitting}
                  className="bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90 disabled:opacity-40">
                  {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  {submitting ? t("company.kyc.submitting") : t("company.kyc.submitBtn")}
                  {!submitting && <ArrowRight className="w-4 h-4 ml-2" />}
                </Button>
                <p className="text-xs text-neutral-500">{t("company.kyc.responseTime")}</p>
                {s === "verified" && reverify && (
                  <Button variant="ghost" size="sm" onClick={() => { setReverify(false); removeFile("operating_license"); removeFile("legal_rep_id"); }}
                    className="text-neutral-400 hover:text-white"
                    data-testid="company-kyc-cancel-reverify-btn">
                    {t("company.kyc.cancelReverify")}
                  </Button>
                )}
              </div>
            </div>
          )}

          {(s === "pending" || (s === "verified" && !reverify)) && (
            <div className="border border-white/10 bg-black/30 p-6 text-sm text-neutral-400" data-testid="company-kyc-settled">
              {s === "pending" && t("company.kyc.settledPending")}
              {s === "verified" && t("company.kyc.settledVerified")}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={load}
                  className="border-white/10 text-neutral-300 hover:bg-white/5"
                  data-testid="company-kyc-refresh-btn">
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("company.kyc.refreshStatus")}
                </Button>
                {s === "verified" && (
                  <Button variant="outline" size="sm" onClick={() => setReverify(true)}
                    className="border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10"
                    data-testid="company-kyc-reverify-btn">
                    <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("company.kyc.reverifyBtn")}
                  </Button>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
