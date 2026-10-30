import { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Turnstile } from "@marsidev/react-turnstile";
import { getTheme } from "@/lib/theme";
import { toast } from "sonner";
import {
  Building2, Upload, Check, X, FileText, FileImage, Send, Loader2, ShieldCheck, Mail, Search,
} from "lucide-react";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+[1-9]\d{7,14}$/;

// Documentos del KYB Empresa. El código fiscal ya se pide como texto, por eso
// no se solicita un "certificado fiscal" aparte. Las etiquetas/pistas se
// resuelven por i18n en el render (claves company.signup.*).
const DOC_STEPS = [
  { key: "operating_license", labelKey: "operatingLicenseLabel", hintKey: "operatingLicenseHint" },
  { key: "legal_rep_id", labelKey: "legalRepIdLabel", hintKey: "legalRepIdHint" },
];

const EMPTY = {
  company_name: "", account_email: "", password: "", password_confirm: "",
  company_phone: "", tax_id: "", address: "",
};

/**
 * Alta de cuenta Empresa en UN solo paso (pública, sin sesión). Captura datos +
 * los 2 documentos del KYB y los envía a `/company-signup`. La cuenta se crea y
 * activa cuando el equipo aprueba la solicitud y el usuario verifica su correo.
 */
export default function CompanySignupDialog({ open, onClose, prefill = null, resubmitToken = null, rejectionReason = "" }) {
  const { t, i18n } = useTranslation();
  const langQS = (i18n.language || "es").split("-")[0];
  const isResubmit = !!resubmitToken;
  const initialForm = useMemo(() => ({
    ...EMPTY,
    company_name: prefill?.company_name || "",
    account_email: prefill?.account_email || "",
    company_phone: prefill?.company_phone || "",
    tax_id: prefill?.tax_id || "",
    address: prefill?.address || "",
  }), [prefill]);
  const [form, setForm] = useState(initialForm);
  const [docs, setDocs] = useState({ operating_license: null, legal_rep_id: null });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [trackToken, setTrackToken] = useState("");
  const fileRefs = { operating_license: useRef(), legal_rep_id: useRef() };

  const [captchaCfg, setCaptchaCfg] = useState(null);
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaKey, setCaptchaKey] = useState(0);

  useEffect(() => {
    if (!open || captchaCfg !== null) return;
    axios.get(`${API}/captcha/config`)
      .then((r) => setCaptchaCfg(r.data))
      .catch(() => setCaptchaCfg({ enabled: false }));
  }, [open, captchaCfg]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const reset = () => {
    setForm(initialForm);
    setDocs({ operating_license: null, legal_rep_id: null });
    setDone(false);
    setTrackToken("");
    setSubmitting(false);
    setCaptchaToken("");
    setCaptchaKey((k) => k + 1);
    for (const k of Object.keys(fileRefs)) { if (fileRefs[k].current) fileRefs[k].current.value = ""; }
  };

  const handleClose = () => { onClose?.(); setTimeout(reset, 200); };

  const handleFile = (docKey, ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { toast.error(t("company.signup.fileTooLarge")); return; }
    const isImg = file.type.startsWith("image/");
    const isPdf = file.type === "application/pdf";
    if (!isImg && !isPdf) { toast.error(t("company.signup.fileWrongType")); return; }
    const reader = new FileReader();
    reader.onload = () => setDocs((p) => ({ ...p, [docKey]: { data: reader.result, name: file.name, isPdf } }));
    reader.readAsDataURL(file);
  };

  const removeFile = (docKey) => {
    setDocs((p) => ({ ...p, [docKey]: null }));
    if (fileRefs[docKey].current) fileRefs[docKey].current.value = "";
  };

  const errors = useMemo(() => {
    const e = {};
    if (form.company_name.trim().length < 2) e.company_name = true;
    if (!EMAIL_RE.test(form.account_email.trim())) e.account_email = true;
    if (form.password.length < 8) e.password = true;
    if (form.password_confirm !== form.password || !form.password_confirm) e.password_confirm = true;
    if (!PHONE_RE.test(form.company_phone.trim())) e.company_phone = true;
    if (form.tax_id.trim().length < 3) e.tax_id = true;
    if (form.address.trim().length < 5) e.address = true;
    if (!docs.operating_license) e.operating_license = true;
    if (!docs.legal_rep_id) e.legal_rep_id = true;
    return e;
  }, [form, docs]);

  const captchaMissing = captchaCfg?.enforced && !captchaToken;
  const canSubmit = Object.keys(errors).length === 0 && !submitting && !captchaMissing;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const base = isResubmit ? `${API}/company-signup/resubmit/${resubmitToken}` : `${API}/company-signup`;
      const url = `${base}?lang=${langQS}`;
      const r = await axios.post(url, {
        company_name: form.company_name.trim(),
        account_email: form.account_email.trim().toLowerCase(),
        password: form.password,
        password_confirm: form.password_confirm,
        company_phone: form.company_phone.trim(),
        tax_id: form.tax_id.trim(),
        address: form.address.trim(),
        operating_license: docs.operating_license.data,
        legal_rep_id: docs.legal_rep_id.data,
        ...(captchaCfg?.enabled && captchaToken ? { captcha_token: captchaToken } : {}),
      });
      setTrackToken(r.data?.status_token || "");
      setDone(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("company.signup.submitFailed"));
      setCaptchaToken("");
      setCaptchaKey((k) => k + 1);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent
        data-testid="company-signup-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-lg max-h-[88vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Building2 className="w-5 h-5 text-[#8B5CF6]" /> {isResubmit ? t("company.signup.titleResubmit") : t("company.signup.titleNew")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {isResubmit ? t("company.signup.descResubmit") : t("company.signup.descNew")}
          </DialogDescription>
        </DialogHeader>

        {isResubmit && rejectionReason && !done && (
          <div className="border border-[#EF4444]/40 bg-[#EF4444]/5 p-3" data-testid="company-resubmit-reason">
            <div className="micro-label text-[#EF4444] mb-1 flex items-center gap-1.5">
              <X className="w-3.5 h-3.5" /> {t("company.signup.resubmitReasonLabel")}
            </div>
            <p className="text-sm text-neutral-200 whitespace-pre-line">{rejectionReason}</p>
          </div>
        )}

        {done ? (
          <div className="py-6 text-center space-y-4" data-testid="company-signup-success">
            <ShieldCheck className="w-12 h-12 text-emerald-400 mx-auto" />
            <div className="text-lg font-semibold">{isResubmit ? t("company.signup.successTitleResubmit") : t("company.signup.successTitleNew")}</div>
            <p className="text-sm text-neutral-400 leading-relaxed flex items-start gap-2 text-left">
              <Mail className="w-4 h-4 mt-0.5 shrink-0 text-[#8B5CF6]" />
              <span>
                {t("company.signup.successBodyPre")}
                <strong className="text-neutral-200 break-all">{form.account_email || t("company.signup.successEmailFallback")}</strong>
                {t("company.signup.successBodyPost")}
              </span>
            </p>
            <Button
              data-testid="company-signup-done-btn"
              onClick={handleClose}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold"
            >
              {t("company.signup.successDoneBtn")}
            </Button>
            <div className="pt-1">
              {trackToken ? (
                <a href={`/empresa/seguimiento/${trackToken}`} data-testid="company-signup-track-link"
                  className="inline-flex items-center gap-1.5 text-xs text-[#8B5CF6] hover:underline">
                  <Search className="w-3.5 h-3.5" /> {t("company.signup.trackLinkWithToken")}
                </a>
              ) : (
                <a href="/empresa/seguimiento" data-testid="company-signup-track-link"
                  className="text-xs text-[#8B5CF6] hover:underline">
                  {t("company.signup.trackLinkNoToken")}
                </a>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3 mt-1">
            <Field id="cs-name" testid="company-signup-name"
              label={t("company.signup.companyName")} value={form.company_name} onChange={set("company_name")}
              placeholder={t("company.signup.companyNamePlaceholder")} />

            <div className="border-t border-white/5 pt-3">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("company.signup.credentialsSection")}</div>
              <Field id="cs-email" testid="company-signup-email" type="email"
                label={t("company.signup.email")} value={form.account_email} onChange={set("account_email")}
                placeholder={t("company.signup.emailPlaceholder")} disabled={isResubmit}
                hint={isResubmit ? t("company.signup.emailResubmitHint") : undefined} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
                <Field id="cs-pass" testid="company-signup-password" type="password"
                  label={t("company.signup.password")} value={form.password} onChange={set("password")}
                  autoComplete="new-password" />
                <Field id="cs-pass2" testid="company-signup-password-confirm" type="password"
                  label={t("company.signup.passwordConfirm")} value={form.password_confirm} onChange={set("password_confirm")}
                  autoComplete="new-password"
                  invalid={!!form.password_confirm && form.password_confirm !== form.password} />
              </div>
              {!!form.password_confirm && form.password_confirm !== form.password && (
                <div className="text-[0.65rem] text-[#EF4444] mt-1" data-testid="company-signup-password-mismatch">
                  {t("company.signup.passwordMismatch")}
                </div>
              )}
            </div>

            <div className="border-t border-white/5 pt-3">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("company.signup.companyDataSection")}</div>
              <Field id="cs-phone" testid="company-signup-phone" type="tel"
                label={t("company.signup.phone")} hint={t("company.signup.phoneHint")}
                value={form.company_phone} onChange={set("company_phone")} placeholder={t("company.signup.phonePlaceholder")} />
              <div className="mt-3">
                <Field id="cs-tax" testid="company-signup-taxid"
                  label={t("company.signup.taxId")} value={form.tax_id} onChange={set("tax_id")}
                  placeholder={t("company.signup.taxIdPlaceholder")} />
              </div>
              <div className="mt-3">
                <Label htmlFor="cs-address" className="micro-label text-neutral-500">{t("company.signup.address")}</Label>
                <textarea id="cs-address" data-testid="company-signup-address"
                  value={form.address} onChange={set("address")} maxLength={400} rows={2}
                  placeholder={t("company.signup.addressPlaceholder")}
                  className="w-full mt-1 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#8B5CF6]/50 focus:outline-none resize-y" />
              </div>
            </div>

            <div className="border-t border-white/5 pt-3">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("company.signup.docsSection")}</div>
              {DOC_STEPS.map(({ key, labelKey, hintKey }) => {
                const label = t(`company.signup.${labelKey}`);
                return (
                <div key={key} className="border border-white/10 bg-black/30 p-3 mb-2" data-testid={`company-signup-upload-${key}`}>
                  <div className="flex items-start gap-3">
                    <div className="flex-1 space-y-1">
                      <div className="text-sm font-semibold text-white flex items-center gap-2">
                        <FileImage className="w-4 h-4 text-[#8B5CF6]" /> {label} *
                      </div>
                      <div className="text-xs text-neutral-500">{t(`company.signup.${hintKey}`)}</div>
                    </div>
                    {docs[key] ? (
                      <div className="flex items-center gap-2">
                        {docs[key].isPdf ? (
                          <span className="flex items-center gap-1.5 px-2 py-2 border border-white/10 bg-black/40 text-xs text-neutral-200 max-w-[8rem] truncate" title={docs[key].name}>
                            <FileText className="w-4 h-4 text-[#8B5CF6] shrink-0" /> {docs[key].name}
                          </span>
                        ) : (
                          <img src={docs[key].data} alt={label} className="w-16 h-16 object-cover border border-white/10" />
                        )}
                        <Button size="sm" variant="outline" onClick={() => removeFile(key)}
                          className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
                          data-testid={`company-signup-remove-${key}`}>
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <label className="cursor-pointer">
                        <input ref={fileRefs[key]} type="file" accept="image/*,application/pdf"
                          onChange={(e) => handleFile(key, e)} className="hidden"
                          data-testid={`company-signup-file-${key}`} />
                        <span className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs font-semibold hover:bg-[#8B5CF6]/20 transition">
                          <Upload className="w-3.5 h-3.5" /> {t("company.signup.chooseFile")}
                        </span>
                      </label>
                    )}
                  </div>
                  {docs[key] && (
                    <div className="text-[0.65rem] text-emerald-400 mt-2 flex items-center gap-1">
                      <Check className="w-3 h-3" /> {t("company.signup.readyToSend")}
                    </div>
                  )}
                </div>
                );
              })}
            </div>

            {captchaCfg?.enabled && (
              <div className="flex justify-center" data-testid="company-signup-captcha">
                <Turnstile
                  key={captchaKey}
                  siteKey={captchaCfg.site_key}
                  options={{ theme: getTheme() === "light" ? "light" : "dark", language: langQS }}
                  onSuccess={(tk) => setCaptchaToken(tk)}
                  onExpire={() => setCaptchaToken("")}
                  onError={() => setCaptchaToken("")}
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
              <Button variant="ghost" onClick={handleClose} data-testid="company-signup-cancel"
                className="rounded-none text-neutral-400 hover:text-white">
                {t("company.signup.cancel")}
              </Button>
              <Button onClick={submit} disabled={!canSubmit} data-testid="company-signup-submit"
                className="rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold disabled:opacity-40">
                {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                {submitting ? t("company.signup.submitting") : t("company.signup.submit")}
              </Button>
            </div>
            <p className="text-xs text-neutral-500 text-center">{t("company.signup.responseTime")}</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Field({ id, testid, label, hint, value, onChange, placeholder, type = "text", autoComplete, invalid, disabled }) {
  return (
    <div>
      <Label htmlFor={id} className="micro-label text-neutral-500">{label}</Label>
      <Input id={id} data-testid={testid} type={type} value={value} onChange={onChange}
        placeholder={placeholder} autoComplete={autoComplete} disabled={disabled}
        className={`rounded-none bg-black/40 text-white h-10 mt-1 ${invalid ? "border-[#EF4444]/60" : "border-white/10"} ${disabled ? "opacity-70 cursor-not-allowed" : ""}`} />
      {hint && <div className="text-[0.65rem] text-neutral-500 mt-1">{hint}</div>}
    </div>
  );
}
