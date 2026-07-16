import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import CopyableText from "@/components/CopyableText";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import {
  User, Mail, Phone, Globe, ShieldCheck, IdCard, Clock, CheckCircle2,
  AlertTriangle, Pencil, Fingerprint,
} from "lucide-react";


/**
 * iter55.20 — Client "Mi Perfil".
 *
 * Central page grouping personal data, verification (KYC) and security (2FA)
 * so the client can review + update every piece of info they registered with:
 *  · Name / registration date (read-only)
 *  · Email → dual-notification change (code to new + alert to old)
 *  · Phone → 2FA-guarded change with admin approval
 *  · Country → free, but resets KYC to pending if was approved
 *  · Verification (link to /dashboard/kyc)
 *  · Security (link to /dashboard/security)
 */
export default function ProfileView() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t } = useTranslation();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [emailDialog, setEmailDialog] = useState(false);
  const [phoneDialog, setPhoneDialog] = useState(false);
  const [countryDialog, setCountryDialog] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/profile/me`, { withCredentials: true });
      setProfile(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("profile.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  if (loading || !profile) {
    return (
      <div className="p-8 text-neutral-500 text-sm" data-testid="profile-loading">
        {t("profile.loading")}
      </div>
    );
  }

  const kycBadge = KYC_BADGE[profile.kyc_status] || KYC_BADGE.not_started;

  return (
    <div className="space-y-6" data-testid="profile-view">
      <ProfileSectionTabs />
      <div>
        <h1 className="font-display text-3xl">{t("profile.title")}</h1>
        <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
          {t("profile.headerBody")}
        </p>
      </div>

      {/* --- Personal data card --- */}
      <section className="tactile-card p-6 space-y-4" data-testid="profile-personal">
        <div className="flex items-center gap-2 border-b border-white/5 pb-3">
          <User className="w-4 h-4 text-[#8B5CF6]" />
          <span className="micro-label text-neutral-500">{t("profile.sectionPersonal")}</span>
        </div>
        <PersonalRow icon={User} label={t("profile.fieldName")} value={profile.name || t("profile.fieldDash")} readOnly />
        <UserIdRow userId={profile.user_id} />
        <PersonalRow icon={Mail} label={t("profile.fieldEmail")} value={profile.email}
                     onEdit={() => setEmailDialog(true)}
                     pending={profile.pending_email_change ? t("profile.pendingEmailChange") : null}
                     testid="profile-email-row" />
        <PersonalRow icon={Phone} label={t("profile.fieldPhone")}
                     value={profile.phone || t("profile.fieldPhoneNone")}
                     verified={profile.phone_verified}
                     onEdit={() => setPhoneDialog(true)}
                     pending={profile.pending_phone_change ? t("profile.pendingPhoneChange") : null}
                     testid="profile-phone-row" />
        <PersonalRow icon={Globe} label={t("profile.fieldCountry")} value={profile.country || t("profile.fieldDash")}
                     onEdit={() => setCountryDialog(true)}
                     testid="profile-country-row" />
        <PersonalRow icon={Clock} label={t("profile.fieldCreated")}
                     value={new Date(profile.created_at).toLocaleDateString()}
                     readOnly />
      </section>

      {/* --- KYC card --- */}
      <section className="tactile-card p-6 space-y-3" data-testid="profile-kyc">
        <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
          <div className="flex items-center gap-2">
            <IdCard className="w-4 h-4 text-[#8B5CF6]" />
            <span className="micro-label text-neutral-500">{t("profile.sectionVerification")}</span>
          </div>
          <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 ${kycBadge.className}`}>
            {t(kycBadge.labelKey)}
          </span>
        </div>
        <p className="text-xs text-neutral-400 leading-relaxed">
          {t("profile.kycHelperBody")}
        </p>
        <Button
          onClick={() => navigate("/dashboard/kyc")}
          data-testid="profile-open-kyc"
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-9 px-4 font-mono text-xs uppercase tracking-wider"
        >
          {t("profile.openKyc")}
        </Button>
      </section>

      {/* --- Security card --- */}
      <section className="tactile-card p-6 space-y-3" data-testid="profile-security">
        <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#8B5CF6]" />
            <span className="micro-label text-neutral-500">{t("profile.sectionSecurity")}</span>
          </div>
          <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 ${
            profile.twofa_enabled
              ? "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30"
              : "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30"
          }`}>
            {profile.twofa_enabled ? t("profile.twofaOn") : t("profile.twofaOff")}
          </span>
        </div>
        <p className="text-xs text-neutral-400 leading-relaxed">
          {t("profile.securityHelperBody")}
        </p>
        <Button
          onClick={() => navigate("/dashboard/security")}
          data-testid="profile-open-security"
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-9 px-4 font-mono text-xs uppercase tracking-wider"
        >
          {t("profile.openSecurity")}
        </Button>
      </section>

      {/* --- Change dialogs --- */}
      <EmailChangeDialog
        open={emailDialog}
        onClose={() => { setEmailDialog(false); load(); }}
        currentEmail={profile.email}
        navigate={navigate}
      />
      <PhoneChangeDialog
        open={phoneDialog}
        onClose={() => { setPhoneDialog(false); load(); }}
        currentPhone={profile.phone}
        pending={profile.pending_phone_change}
        navigate={navigate}
      />
      <CountryChangeDialog
        open={countryDialog}
        onClose={() => { setCountryDialog(false); load(); }}
        currentCountry={profile.country}
        kycStatus={profile.kyc_status}
      />
    </div>
  );
}


const KYC_BADGE = {
  not_started: { labelKey: "profile.kycStatus.not_started", className: "bg-neutral-500/10 text-neutral-400 border-neutral-500/30" },
  pending: { labelKey: "profile.kycStatus.pending", className: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30" },
  needs_more_info: { labelKey: "profile.kycStatus.needs_more_info", className: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" },
  verified: { labelKey: "profile.kycStatus.verified", className: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30" },
  rejected: { labelKey: "profile.kycStatus.rejected", className: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30" },
};


function UserIdRow({ userId }) {
  const { t } = useTranslation();
  if (!userId) return null;
  return (
    <div
      className="flex items-center justify-between gap-4 py-2 border-t border-white/5"
      data-testid="profile-user-id-row"
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <Fingerprint className="w-4 h-4 text-neutral-500 flex-shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-[0.65rem] uppercase tracking-widest text-neutral-500">
            User ID
          </div>
          <div className="text-sm text-white mt-0.5">
            <CopyableText
              value={userId}
              testid="profile-user-id-copy"
              toastMessage={t("profile.userIdCopied")}
              label={t("profile.copyUserId")}
            />
          </div>
          <div className="text-[0.65rem] text-neutral-500 mt-1 leading-relaxed max-w-md">
            {t("profile.userIdShareHint")}
          </div>
        </div>
      </div>
    </div>
  );
}


function PersonalRow({ icon: Icon, label, value, onEdit, readOnly, verified, pending, testid }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-4 py-2" data-testid={testid}>
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <Icon className="w-4 h-4 text-neutral-500 flex-shrink-0" />
        <div className="min-w-0">
          <div className="text-[0.65rem] uppercase tracking-widest text-neutral-500">{label}</div>
          <div className="text-sm text-white font-mono truncate flex items-center gap-2">
            <span className="truncate">{value}</span>
            {verified && <CheckCircle2 className="w-3.5 h-3.5 text-[#22C55E] flex-shrink-0" />}
          </div>
          {pending && (
            <div className="text-[0.65rem] text-[#8B5CF6] mt-0.5 flex items-center gap-1">
              <AlertTriangle className="w-2.5 h-2.5" /> {pending}
            </div>
          )}
        </div>
      </div>
      {!readOnly && onEdit && (
        <button
          type="button"
          onClick={onEdit}
          data-testid={`${testid}-edit`}
          className="flex-shrink-0 text-[0.65rem] uppercase tracking-widest text-[#8B5CF6] hover:text-[#A78BFA] border border-[#8B5CF6]/40 hover:border-[#8B5CF6] px-3 py-1.5 flex items-center gap-1"
        >
          <Pencil className="w-3 h-3" /> {t("profile.changeButton")}
        </button>
      )}
    </div>
  );
}


// ============================================================
// Email change dialog — 2-step: request code + confirm code
// ============================================================
function EmailChangeDialog({ open, onClose, currentEmail, navigate }) {
  const { t } = useTranslation();
  const [step, setStep] = useState(1);
  const [newEmail, setNewEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [maskedTarget, setMaskedTarget] = useState("");

  useEffect(() => {
    if (open) { setStep(1); setNewEmail(""); setCode(""); setTotpCode(""); setMaskedTarget(""); }
  }, [open]);

  const requestCode = async () => {
    if (!newEmail || !newEmail.includes("@")) return toast.error(t("profile.email.invalidEmail"));
    if (!totpCode || totpCode.length < 6) return toast.error(t("profile.email.enterTotp"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/profile/email/request-change`, {
        new_email: newEmail.trim().toLowerCase(),
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      setMaskedTarget(r.data.sent_to_masked || "");
      setStep(2);
      toast.success(t("profile.email.codeSent"));
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || t("profile.email.requestError"));
      }
    } finally { setBusy(false); }
  };

  const confirmCode = async () => {
    if (!code || code.length !== 6) return toast.error(t("profile.email.enter6Digits"));
    setBusy(true);
    try {
      await axios.post(`${API}/profile/email/confirm-change`, {
        code: code.trim(),
      }, { withCredentials: true });
      toast.success(t("profile.email.updated"));
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("profile.email.wrongCode"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="email-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">{t("profile.email.dialogTitle")}</DialogTitle>
        </DialogHeader>
        {step === 1 ? (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              {t("profile.email.helperBody", { email: currentEmail })}
            </p>
            <div>
              <Label className="micro-label text-neutral-500">{t("profile.email.newEmailLabel")}</Label>
              <Input value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
                     data-testid="email-change-new-input"
                     placeholder={t("profile.email.newEmailPlaceholder")}
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("profile.email.totpLabel")}</Label>
              <Input value={totpCode} onChange={(e) => setTotpCode(e.target.value)}
                     data-testid="email-change-totp-input"
                     placeholder={t("profile.email.totpPlaceholder")}
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <Button onClick={requestCode} disabled={busy}
                    data-testid="email-change-send-btn"
                    className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
              {busy ? t("profile.email.sending") : t("profile.email.sendCode")}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              <Trans
                i18nKey="profile.email.step2Body"
                values={{ target: maskedTarget }}
                components={{ 1: <strong className="text-white font-mono" /> }}
              />
            </p>
            <div>
              <Label className="micro-label text-neutral-500">{t("profile.email.codeLabel")}</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                     maxLength={6} inputMode="numeric" pattern="[0-9]{6}"
                     data-testid="email-change-code-input"
                     placeholder={t("profile.email.codePlaceholder")}
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono text-center text-xl tracking-widest" />
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setStep(1)} disabled={busy}
                      className="flex-1 rounded-none bg-transparent border border-white/15 text-white h-11 font-mono uppercase tracking-wider">
                {t("profile.email.back")}
              </Button>
              <Button onClick={confirmCode} disabled={busy}
                      data-testid="email-change-confirm-btn"
                      className="flex-1 rounded-none bg-[#22C55E] hover:bg-[#22C55E]/90 text-black h-11 font-mono uppercase tracking-wider">
                {busy ? t("profile.email.confirmingCode") : t("profile.email.confirm")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


// ============================================================
// Phone change dialog — sends to admin review queue
// ============================================================
function PhoneChangeDialog({ open, onClose, currentPhone, pending, navigate }) {
  const { t } = useTranslation();
  const [newPhone, setNewPhone] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) { setNewPhone(""); setTotpCode(""); }
  }, [open]);

  const submit = async () => {
    if (!newPhone || newPhone.length < 6) return toast.error(t("profile.phone.invalidPhone"));
    if (!totpCode || totpCode.length < 6) return toast.error(t("profile.phone.enterTotp"));
    setBusy(true);
    try {
      await axios.post(`${API}/profile/phone/request-change`, {
        new_phone: newPhone.trim(),
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      toast.success(t("profile.phone.requestSent"));
      onClose();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || t("profile.phone.requestError"));
      }
    } finally { setBusy(false); }
  };

  const cancelPending = async () => {
    setBusy(true);
    try {
      await axios.delete(`${API}/profile/phone/pending`, { withCredentials: true });
      toast.success(t("profile.phone.requestCancelled"));
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("profile.phone.cancelError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="phone-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">{t("profile.phone.dialogTitle")}</DialogTitle>
        </DialogHeader>
        {pending ? (
          <div className="space-y-3">
            <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-4">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("profile.phone.pendingRequestLabel")}</div>
              <div className="text-xs text-neutral-400">
                <Trans
                  i18nKey="profile.phone.pendingRequestBody"
                  values={{ phone: pending.new_phone_masked }}
                  components={{ 1: <strong className="text-white font-mono" /> }}
                />
              </div>
            </div>
            <Button onClick={cancelPending} disabled={busy}
                    data-testid="phone-cancel-pending-btn"
                    className="w-full rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-11 font-mono uppercase tracking-wider">
              {t("profile.phone.cancelPending")}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              <Trans
                i18nKey="profile.phone.currentLabelBody"
                values={{ phone: currentPhone || t("profile.phone.currentNotRegistered") }}
                components={{ 1: <strong className="text-white font-mono" /> }}
              />
            </p>
            <div>
              <Label className="micro-label text-neutral-500">{t("profile.phone.newPhoneLabel")}</Label>
              <Input value={newPhone} onChange={(e) => setNewPhone(e.target.value)}
                     data-testid="phone-change-new-input"
                     placeholder={t("profile.phone.newPhonePlaceholder")}
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("profile.phone.totpLabel")}</Label>
              <Input value={totpCode} onChange={(e) => setTotpCode(e.target.value)}
                     data-testid="phone-change-totp-input"
                     placeholder={t("profile.phone.totpPlaceholder")}
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <Button onClick={submit} disabled={busy}
                    data-testid="phone-change-submit-btn"
                    className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
              {busy ? t("profile.phone.sending") : t("profile.phone.requestChange")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


// ============================================================
// Country change dialog — frictionless + KYC awareness
// ============================================================
function CountryChangeDialog({ open, onClose, currentCountry, kycStatus }) {
  const { t } = useTranslation();
  const [newCountry, setNewCountry] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setNewCountry(""); }, [open]);

  const submit = async () => {
    if (!newCountry || newCountry.trim().length < 2) return toast.error(t("profile.country.invalidCountry"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/profile/country/change`, {
        new_country: newCountry.trim(),
      }, { withCredentials: true });
      if (r.data.kyc_reset) {
        toast.warning(t("profile.country.resetsKyc"));
      } else {
        toast.success(t("profile.country.updated"));
      }
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("profile.country.changeError"));
    } finally { setBusy(false); }
  };

  const willResetKyc = kycStatus === "verified";

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="country-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">{t("profile.country.dialogTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-xs text-neutral-400 leading-relaxed">
            <Trans
              i18nKey="profile.country.currentLabelBody"
              values={{ country: currentCountry || "—" }}
              components={{ 1: <strong className="text-white font-mono" /> }}
            />
          </p>
          {willResetKyc && (
            <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-3">
              <div className="micro-label text-[#8B5CF6] mb-1 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> {t("profile.country.willResetKycTitle")}
              </div>
              <p className="text-[0.7rem] text-neutral-400 leading-relaxed">
                <Trans
                  i18nKey="profile.country.willResetKycBody"
                  components={{ 1: <strong className="text-white" /> }}
                />
              </p>
            </div>
          )}
          <div>
            <Label className="micro-label text-neutral-500">{t("profile.country.newCountryLabel")}</Label>
            <Input value={newCountry} onChange={(e) => setNewCountry(e.target.value)}
                   data-testid="country-change-new-input"
                   placeholder={t("profile.country.placeholder")}
                   className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11" />
          </div>
          <Button onClick={submit} disabled={busy}
                  data-testid="country-change-submit-btn"
                  className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
            {busy ? t("profile.country.saving") : t("profile.country.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
