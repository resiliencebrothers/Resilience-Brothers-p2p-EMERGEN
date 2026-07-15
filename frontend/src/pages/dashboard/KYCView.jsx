import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import {
  IdCard, Upload, Check, X, Loader2, Camera, FileImage, ShieldCheck,
  AlertTriangle, Info, RefreshCw, ArrowRight,
} from "lucide-react";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";

// iter55.36s — DOC_STEPS + STATUS_LABELS now consume i18n keys resolved at
// render time (see build helpers inside the component).
const DOC_STEP_KEYS = [
  { key: "id_front", labelKey: "kyc.docStep.id_front.label", hintKey: "kyc.docStep.id_front.hint" },
  { key: "id_back",  labelKey: "kyc.docStep.id_back.label",  hintKey: "kyc.docStep.id_back.hint" },
  { key: "selfie",   labelKey: "kyc.docStep.selfie.label",   hintKey: "kyc.docStep.selfie.hint" },
];

const STATUS_LABEL_KEYS = {
  unverified:      { key: "kyc.statusLabel.unverified",       tone: "muted",  icon: Info },
  pending:         { key: "kyc.statusLabel.pending",          tone: "warn",   icon: Loader2 },
  needs_more_info: { key: "kyc.statusLabel.needs_more_info",  tone: "warn",   icon: AlertTriangle },
  verified:        { key: "kyc.statusLabel.verified",         tone: "ok",     icon: ShieldCheck },
  rejected:        { key: "kyc.statusLabel.rejected",         tone: "danger", icon: X },
};

/**
 * KYCView — client-facing wizard to submit identity documents.
 * Route: /dashboard/kyc (iter52)
 */
export default function KYCView() {
  const { t } = useTranslation();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [docs, setDocs] = useState({ id_front: null, id_back: null, selfie: null });
  const [submitting, setSubmitting] = useState(false);
  const fileRefs = { id_front: useRef(), id_back: useRef(), selfie: useRef() };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/kyc/my-status`, { withCredentials: true });
      setStatus(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar tu estado de verificación");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleFile = (docKey, ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      toast.error("Archivo muy grande (máximo 8 MB).");
      return;
    }
    if (!file.type.startsWith("image/")) {
      toast.error("Solo se aceptan imágenes (JPG, PNG).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setDocs((prev) => ({ ...prev, [docKey]: reader.result }));
    };
    reader.readAsDataURL(file);
  };

  const removeFile = (docKey) => {
    setDocs((prev) => ({ ...prev, [docKey]: null }));
    if (fileRefs[docKey].current) fileRefs[docKey].current.value = "";
  };

  const allReady = docs.id_front && docs.id_back && docs.selfie;

  const submit = async () => {
    if (!allReady) {
      toast.error("Sube los 3 documentos antes de enviar.");
      return;
    }
    setSubmitting(true);
    try {
      await axios.post(
        `${API}/kyc/submit`,
        { id_front: docs.id_front, id_back: docs.id_back, selfie: docs.selfie },
        { withCredentials: true },
      );
      toast.success(t("kyc.successToast"));
      setDocs({ id_front: null, id_back: null, selfie: null });
      for (const k of Object.keys(fileRefs)) {
        if (fileRefs[k].current) fileRefs[k].current.value = "";
      }
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("kyc.submitErrorFallback"));
    } finally {
      setSubmitting(false);
    }
  };

  const s = status?.status || "unverified";
  const v = status?.verification;
  const canSubmit = s === "unverified" || s === "rejected";

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="client-kyc-page">
      <ProfileSectionTabs />
      <header>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <IdCard className="w-7 h-7 text-[#8B5CF6]" /> {t("kyc.titleFull")}
        </h1>
        <p className="text-neutral-500 text-sm mt-2">
          {t("kyc.subtitle")}
        </p>
      </header>

      {loading && <div className="text-neutral-500 text-sm">{t("kyc.loading")}</div>}

      {!loading && status && (
        <>
          <StatusCard status={s} verification={v} />

          {s === "rejected" && v?.rejection_reasons?.length > 0 && (
            <div className="border border-[#EF4444]/30 bg-[#EF4444]/5 p-4">
              <div className="text-sm font-semibold text-[#FEE2E2] flex items-center gap-2 mb-2">
                <X className="w-4 h-4" /> {t("kyc.rejectionReasonsTitle")}
              </div>
              <ul className="text-xs text-neutral-300 space-y-1 list-disc pl-5">
                {v.rejection_reasons.map((r) => (<li key={r}>{r}</li>))}
              </ul>
              {v.review_notes && (
                <div className="text-xs text-neutral-400 italic mt-2">{t("kyc.teamNote")}: {v.review_notes}</div>
              )}
              <div className="text-xs text-neutral-300 mt-3">
                {t("kyc.canResubmit")}
              </div>
            </div>
          )}

          {s === "needs_more_info" && v?.review_notes && (
            <div className="border border-blue-500/30 bg-blue-500/5 p-4">
              <div className="text-sm font-semibold text-blue-200 flex items-center gap-2 mb-2">
                <Info className="w-4 h-4" /> {t("kyc.needsMoreInfoTitle")}
              </div>
              <div className="text-xs text-neutral-300">{v.review_notes}</div>
              <div className="text-xs text-neutral-400 mt-2">
                {t("kyc.contactSupport")}
              </div>
            </div>
          )}

          {canSubmit && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-white">{t("kyc.uploadHeading")}</h2>
              {DOC_STEP_KEYS.map(({ key, labelKey, hintKey }) => (
                <DocUploadRow
                  key={key}
                  docKey={key}
                  label={t(labelKey)}
                  hint={t(hintKey)}
                  preview={docs[key]}
                  fileRef={fileRefs[key]}
                  onSelect={handleFile}
                  onRemove={removeFile}
                />
              ))}

              <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
                <Button
                  data-testid="kyc-submit-btn"
                  onClick={submit}
                  disabled={!allReady || submitting}
                  className="bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90 disabled:opacity-40"
                >
                  {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  {submitting ? t("kyc.submittingBtn") : t("kyc.submitBtn")}
                  {!submitting && <ArrowRight className="w-4 h-4 ml-2" />}
                </Button>
                <p className="text-xs text-neutral-500">
                  {t("kyc.responseTime")}
                </p>
              </div>
            </div>
          )}

          {(s === "pending" || s === "verified") && (
            <div className="border border-white/10 bg-black/30 p-6 text-sm text-neutral-400">
              {s === "pending" && t("kyc.pendingMessage")}
              {s === "verified" && t("kyc.verifiedMessage")}
              <div className="mt-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={load}
                  className="border-white/10 text-neutral-300 hover:bg-white/5"
                  data-testid="kyc-refresh-btn"
                >
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("kyc.refreshStatus")}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatusCard({ status, verification }) {
  const { t } = useTranslation();
  const cfg = STATUS_LABEL_KEYS[status] || STATUS_LABEL_KEYS.unverified;
  const Icon = cfg.icon;
  const toneClasses = {
    muted: "border-white/10 bg-black/30 text-neutral-300",
    warn: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
  }[cfg.tone];

  return (
    <div className={`border ${toneClasses} p-4 flex items-center gap-3`} data-testid="kyc-status-card">
      <Icon className={`w-6 h-6 ${status === "pending" ? "animate-spin" : ""}`} />
      <div>
        <div className="text-sm font-semibold">{t(cfg.key)}</div>
        {verification?.created_at && (
          <div className="text-xs opacity-70">{t("kyc.submittedAt")}: {verification.created_at.slice(0, 16).replace("T", " ")}</div>
        )}
      </div>
    </div>
  );
}

function DocUploadRow({ docKey, label, hint, preview, fileRef, onSelect, onRemove }) {
  return (
    <div className="border border-white/10 bg-black/30 p-4" data-testid={`kyc-upload-${docKey}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-1">
          <div className="text-sm font-semibold text-white flex items-center gap-2">
            {docKey === "selfie" ? <Camera className="w-4 h-4 text-[#8B5CF6]" /> : <FileImage className="w-4 h-4 text-[#8B5CF6]" />}
            {label}
          </div>
          <div className="text-xs text-neutral-500">{hint}</div>
        </div>
        {preview ? (
          <div className="flex items-center gap-2">
            <img src={preview} alt={label} className="w-20 h-20 object-cover border border-white/10" />
            <Button
              size="sm"
              variant="outline"
              onClick={() => onRemove(docKey)}
              className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
              data-testid={`kyc-remove-${docKey}`}
            >
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        ) : (
          <label className="cursor-pointer">
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={(e) => onSelect(docKey, e)}
              className="hidden"
              data-testid={`kyc-file-input-${docKey}`}
            />
            <span className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs font-semibold hover:bg-[#8B5CF6]/20 transition">
              <Upload className="w-3.5 h-3.5" /> Elegir archivo
            </span>
          </label>
        )}
      </div>
      {preview && (
        <div className="text-[0.65rem] text-emerald-400 mt-2 flex items-center gap-1">
          <Check className="w-3 h-3" /> Listo para enviar
        </div>
      )}
    </div>
  );
}
