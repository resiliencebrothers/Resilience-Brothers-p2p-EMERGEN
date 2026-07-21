import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import TwoFAStatusCard from "./security/TwoFAStatusCard";
import TwoFASetupPanel from "./security/TwoFASetupPanel";
import RecoveryCodesPanel from "./security/RecoveryCodesPanel";
import { DisableTwoFAModal, RegenerateCodesModal } from "./security/TwoFAModals";
import PasswordChangeCard from "./security/PasswordChangeCard";

export default function SecuritySettings() {
  const { t } = useTranslation();
  const [status, setStatus] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupData, setSetupData] = useState(null); // { qr_data_url, secret, provisioning_uri }
  const [verifyCode, setVerifyCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState(null); // shown once after activation
  const [disableModal, setDisableModal] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [regenModal, setRegenModal] = useState(false);
  const [regenCode, setRegenCode] = useState("");

  // iter55.30 — password change state (grouped)
  const [pwd, setPwd] = useState({
    current: "", new: "", confirm: "", totp: "", show: false,
  });
  const [pwdBusy, setPwdBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const [statusRes, profileRes] = await Promise.all([
        axios.get(`${API}/me/2fa/status`, { withCredentials: true }),
        axios.get(`${API}/profile/me`, { withCredentials: true }),
      ]);
      setStatus(statusRes.data);
      setProfile(profileRes.data);
    } catch (e) {
      toast.error(t("security.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  const startSetup = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/setup`, {}, { withCredentials: true });
      setSetupData(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("security.setupError"));
    } finally {
      setBusy(false);
    }
  };

  const verifySetup = async () => {
    if (verifyCode.length !== 6) return toast.error(t("security.enterSixDigits"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/verify-setup`, { code: verifyCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setSetupData(null);
      setVerifyCode("");
      toast.success(t("security.activated"));
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const disable2FA = async () => {
    if (!disableCode) return toast.error(t("security.enterCurrentTotp"));
    setBusy(true);
    try {
      await axios.post(`${API}/me/2fa/disable`, { code: disableCode }, { withCredentials: true });
      toast.success(t("security.disabled"));
      setDisableModal(false); setDisableCode("");
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const regenerateCodes = async () => {
    if (!regenCode) return toast.error(t("security.enterCurrentTotp"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/regenerate-recovery-codes`, { code: regenCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setRegenModal(false); setRegenCode("");
      toast.success(t("security.codesRegenerated"));
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const copyText = (text) => {
    navigator.clipboard.writeText(text);
    toast.success(t("security.copied"));
  };

  const submitPasswordChange = async () => {
    if (pwd.new.length < 8) return toast.error(t("security.password.tooShort"));
    if (pwd.new !== pwd.confirm) return toast.error(t("security.password.mismatch"));
    if (pwd.current === pwd.new) return toast.error(t("security.password.mustDiffer"));
    if (status?.enabled && pwd.totp.length !== 6) return toast.error(t("security.password.enterTotp"));
    setPwdBusy(true);
    try {
      const r = await axios.post(
        `${API}/profile/password/change`,
        {
          current_password: pwd.current,
          new_password: pwd.new,
          totp_code: status?.enabled ? pwd.totp : undefined,
        },
        { withCredentials: true },
      );
      const revoked = r.data?.other_sessions_revoked || 0;
      toast.success(
        revoked > 0
          ? t("security.password.updatedWithSessions", { count: revoked })
          : t("security.password.updated"),
      );
      setPwd({ current: "", new: "", confirm: "", totp: "", show: pwd.show });
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail && typeof detail === "object") {
        if (detail.code === "TOTP_SETUP_REQUIRED") {
          toast.error(t("security.password.setupRequired"));
          return;
        }
        if (detail.code === "TOTP_INVALID" || detail.code === "TOTP_CODE_REQUIRED") {
          toast.error(detail.message || t("security.password.totpInvalid"));
          return;
        }
      }
      const msg = typeof detail === "string"
        ? detail
        : (detail?.message || t("security.password.updateError"));
      toast.error(msg);
    } finally {
      setPwdBusy(false);
    }
  };

  if (loading) return <div className="text-neutral-500">{t("security.loading")}</div>;

  return (
    <div data-testid="security-settings" className="space-y-6 max-w-2xl">
      <ProfileSectionTabs />
      <div>
        <h1 className="font-display text-3xl">{t("security.title")}</h1>
        <p className="text-neutral-500 text-sm mt-1">{t("security.subtitle")}</p>
      </div>

      <TwoFAStatusCard
        status={status}
        busy={busy}
        hasSetupData={!!setupData}
        onStartSetup={startSetup}
        onRegen={() => setRegenModal(true)}
        onDisable={() => setDisableModal(true)}
      />

      {setupData && (
        <TwoFASetupPanel
          setupData={setupData}
          verifyCode={verifyCode}
          onVerifyCodeChange={setVerifyCode}
          onVerify={verifySetup}
          busy={busy}
          onCopy={copyText}
        />
      )}

      {recoveryCodes && (
        <RecoveryCodesPanel
          recoveryCodes={recoveryCodes}
          onCopy={copyText}
          onAcknowledged={() => setRecoveryCodes(null)}
        />
      )}

      <DisableTwoFAModal
        open={disableModal}
        onOpenChange={setDisableModal}
        code={disableCode}
        onCodeChange={setDisableCode}
        onConfirm={disable2FA}
        busy={busy}
      />

      <RegenerateCodesModal
        open={regenModal}
        onOpenChange={setRegenModal}
        code={regenCode}
        onCodeChange={setRegenCode}
        onConfirm={regenerateCodes}
        busy={busy}
      />

      <PasswordChangeCard
        profile={profile}
        status={status}
        pwd={pwd}
        setPwd={setPwd}
        busy={pwdBusy}
        onSubmit={submitPasswordChange}
      />
    </div>
  );
}
