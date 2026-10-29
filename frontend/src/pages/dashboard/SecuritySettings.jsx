import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { LogOut } from "lucide-react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import TwoFAStatusCard from "./security/TwoFAStatusCard";
import TwoFASetupPanel from "./security/TwoFASetupPanel";
import RecoveryCodesPanel from "./security/RecoveryCodesPanel";
import { DisableTwoFAModal, RegenerateCodesModal } from "./security/TwoFAModals";
import PasswordChangeCard from "./security/PasswordChangeCard";
import ActiveSessionsCard from "./security/ActiveSessionsCard";

export default function SecuritySettings({ embedded = false }) {
  const { t } = useTranslation();
  const { logoutAll } = useAuth();
  const [status, setStatus] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [signOutAllBusy, setSignOutAllBusy] = useState(false);
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

  const signOutEverywhere = async () => {
    if (signOutAllBusy) return;
    setSignOutAllBusy(true);
    try {
      await logoutAll();   // redirige al inicio al completarse
    } catch (e) {
      toast.error(t("security.signOutAll.error"));
      setSignOutAllBusy(false);
    }
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

  const submitPasswordSet = async () => {
    if (pwd.new.length < 8) return toast.error(t("security.password.tooShort"));
    if (pwd.new !== pwd.confirm) return toast.error(t("security.password.mismatch"));
    if (status?.enabled && pwd.totp.length !== 6) return toast.error(t("security.password.enterTotp"));
    setPwdBusy(true);
    try {
      await axios.post(
        `${API}/profile/password/set`,
        {
          new_password: pwd.new,
          totp_code: status?.enabled ? pwd.totp : undefined,
        },
        { withCredentials: true },
      );
      toast.success(t("security.password.setUpdated"));
      setPwd({ current: "", new: "", confirm: "", totp: "", show: pwd.show });
      await loadStatus();
    } catch (e) {
      const detail = e.response?.data?.detail;
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
      {!embedded && <ProfileSectionTabs />}
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
        onSetSubmit={submitPasswordSet}
      />

      <ActiveSessionsCard />

      <div className="tactile-card p-5 border border-red-500/20" data-testid="sign-out-all-card">
        <div className="flex items-start gap-3">
          <LogOut className="w-5 h-5 text-red-400 mt-0.5 shrink-0" />
          <div className="flex-1">
            <h2 className="font-display text-lg">{t("security.signOutAll.title")}</h2>
            <p className="text-neutral-500 text-sm mt-1">{t("security.signOutAll.desc")}</p>
          </div>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button
              type="button"
              data-testid="sign-out-all-btn"
              disabled={signOutAllBusy}
              className="mt-4 px-5 py-2.5 text-sm font-bold uppercase tracking-wider border border-red-500/50 text-red-300 hover:bg-red-500/10 transition-colors rounded-none disabled:opacity-50"
            >
              {signOutAllBusy ? t("security.signOutAll.working") : t("security.signOutAll.button")}
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none" data-testid="sign-out-all-dialog">
            <AlertDialogHeader>
              <AlertDialogTitle className="font-display">{t("security.signOutAll.confirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription className="text-neutral-400">
                {t("security.signOutAll.confirmBody")}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel data-testid="sign-out-all-cancel" className="rounded-none bg-transparent border-white/20 text-white hover:bg-white/5">
                {t("security.signOutAll.cancel")}
              </AlertDialogCancel>
              <AlertDialogAction
                data-testid="sign-out-all-confirm"
                onClick={signOutEverywhere}
                className="rounded-none bg-red-600 hover:bg-red-500 text-white"
              >
                {t("security.signOutAll.confirm")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}
