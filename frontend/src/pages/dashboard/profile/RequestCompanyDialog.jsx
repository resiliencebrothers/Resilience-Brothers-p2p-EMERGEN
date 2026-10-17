import { useState, useMemo } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Building2, Send } from "lucide-react";

/**
 * Programa Empresas — diálogo para solicitar el alta de una cuenta Empresa
 * NUEVA e independiente. Al aprobarse, Resilience crea una cuenta separada
 * (email + contraseña propios) con rol empresa (under_review).
 */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+[1-9]\d{7,14}$/;

export default function RequestCompanyDialog({ open, onClose, onSubmitted }) {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    company_name: "", account_email: "", password: "", password_confirm: "",
    company_phone: "", tax_id: "", address: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const reset = () => setForm({
    company_name: "", account_email: "", password: "", password_confirm: "",
    company_phone: "", tax_id: "", address: "",
  });

  const errors = useMemo(() => {
    const e = {};
    if (form.company_name.trim().length < 2) e.company_name = true;
    if (!EMAIL_RE.test(form.account_email.trim())) e.account_email = true;
    if (form.password.length < 8) e.password = true;
    if (form.password_confirm !== form.password || !form.password_confirm) e.password_confirm = true;
    if (!PHONE_RE.test(form.company_phone.trim())) e.company_phone = true;
    if (form.tax_id.trim().length < 3) e.tax_id = true;
    if (form.address.trim().length < 5) e.address = true;
    return e;
  }, [form]);

  const canSubmit = Object.keys(errors).length === 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await axios.post(
        `${API}/company-requests`,
        {
          company_name: form.company_name.trim(),
          account_email: form.account_email.trim().toLowerCase(),
          password: form.password,
          password_confirm: form.password_confirm,
          company_phone: form.company_phone.trim(),
          tax_id: form.tax_id.trim(),
          address: form.address.trim(),
        },
        { withCredentials: true },
      );
      toast.success(t("companyRequest.dialog.successToast"));
      reset();
      onSubmitted?.();
      onClose?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("companyRequest.dialog.errorToast"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="request-company-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-lg max-h-[88vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Building2 className="w-5 h-5 text-[#8B5CF6]" />
            {t("companyRequest.dialog.title")}
          </DialogTitle>
        </DialogHeader>

        <p className="text-xs text-neutral-400 leading-relaxed">
          {t("companyRequest.dialog.body")}
        </p>

        <div className="space-y-3 mt-2">
          <Field
            id="co-req-name" testid="company-request-name"
            label={t("companyRequest.dialog.companyNameLabel")}
            value={form.company_name} onChange={set("company_name")}
            placeholder={t("companyRequest.dialog.companyNamePlaceholder")}
          />

          <div className="border-t border-white/5 pt-3">
            <div className="micro-label text-[#8B5CF6] mb-2">
              {t("companyRequest.dialog.credentialsSection")}
            </div>
            <Field
              id="co-req-email" testid="company-request-email" type="email"
              label={t("companyRequest.dialog.accountEmailLabel")}
              hint={t("companyRequest.dialog.accountEmailHint")}
              value={form.account_email} onChange={set("account_email")}
              placeholder="empresa@correo.com"
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
              <Field
                id="co-req-pass" testid="company-request-password" type="password"
                label={t("companyRequest.dialog.passwordLabel")}
                value={form.password} onChange={set("password")}
                autoComplete="new-password"
              />
              <Field
                id="co-req-pass2" testid="company-request-password-confirm" type="password"
                label={t("companyRequest.dialog.passwordConfirmLabel")}
                value={form.password_confirm} onChange={set("password_confirm")}
                autoComplete="new-password"
                invalid={!!form.password_confirm && form.password_confirm !== form.password}
              />
            </div>
            {!!form.password_confirm && form.password_confirm !== form.password && (
              <div className="text-[0.65rem] text-[#EF4444] mt-1" data-testid="company-password-mismatch">
                {t("companyRequest.dialog.passwordMismatch")}
              </div>
            )}
          </div>

          <div className="border-t border-white/5 pt-3">
            <div className="micro-label text-[#8B5CF6] mb-2">
              {t("companyRequest.dialog.businessSection")}
            </div>
            <Field
              id="co-req-phone" testid="company-request-phone" type="tel"
              label={t("companyRequest.dialog.phoneLabel")}
              hint={t("companyRequest.dialog.phoneHint")}
              value={form.company_phone} onChange={set("company_phone")}
              placeholder="+5350123456"
            />
            <div className="mt-3">
              <Field
                id="co-req-tax" testid="company-request-taxid"
                label={t("companyRequest.dialog.taxIdLabel")}
                value={form.tax_id} onChange={set("tax_id")}
                placeholder={t("companyRequest.dialog.taxIdPlaceholder")}
              />
            </div>
            <div className="mt-3">
              <Label htmlFor="co-req-address" className="micro-label text-neutral-500">
                {t("companyRequest.dialog.addressLabel")}
              </Label>
              <textarea
                id="co-req-address"
                data-testid="company-request-address"
                value={form.address}
                onChange={set("address")}
                maxLength={400}
                rows={2}
                placeholder={t("companyRequest.dialog.addressPlaceholder")}
                className="w-full mt-1 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#8B5CF6]/50 focus:outline-none resize-y"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-4">
          <Button
            variant="ghost"
            onClick={onClose}
            data-testid="company-request-cancel"
            className="rounded-none text-neutral-400 hover:text-white"
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={!canSubmit}
            data-testid="company-request-submit"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold disabled:opacity-40"
          >
            <Send className="w-4 h-4 mr-2" />
            {t("companyRequest.dialog.submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function Field({ id, testid, label, hint, value, onChange, placeholder, type = "text", autoComplete, invalid }) {
  return (
    <div>
      <Label htmlFor={id} className="micro-label text-neutral-500">{label}</Label>
      <Input
        id={id}
        data-testid={testid}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className={`rounded-none bg-black/40 text-white h-10 mt-1 ${invalid ? "border-[#EF4444]/60" : "border-white/10"}`}
      />
      {hint && <div className="text-[0.65rem] text-neutral-500 mt-1">{hint}</div>}
    </div>
  );
}
